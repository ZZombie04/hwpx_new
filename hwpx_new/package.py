# -*- coding: utf-8 -*-
"""HWPX 패키지 입출력과 header.xml 스타일 조회."""
from __future__ import annotations

import re
import zipfile
from collections import OrderedDict

from lxml import etree

NS = {
    'hp': 'http://www.hancom.co.kr/hwpml/2011/paragraph',
    'hs': 'http://www.hancom.co.kr/hwpml/2011/section',
    'hc': 'http://www.hancom.co.kr/hwpml/2011/core',
    'hh': 'http://www.hancom.co.kr/hwpml/2011/head',
    'opf': 'http://www.idpf.org/2007/opf/',
    'dc': 'http://purl.org/dc/elements/1.1/',
}
HP = '{%s}' % NS['hp']
HH = '{%s}' % NS['hh']
HC = '{%s}' % NS['hc']


class HwpxError(Exception):
    pass


class Package:
    """HWPX(zip) 전체를 메모리에 올려 두고 파트별로 읽고 쓴다."""

    def __init__(self, path: str):
        self.path = path
        self.files: "OrderedDict[str, bytes]" = OrderedDict()
        try:
            with zipfile.ZipFile(path) as z:
                for info in z.infolist():
                    self.files[info.filename] = z.read(info.filename)
        except zipfile.BadZipFile as e:
            raise HwpxError(
                f'HWPX 파일이 아닙니다: {path}\n'
                '※ 옛 .hwp 파일이면 한글에서 [다른 이름으로 저장 → HWPX]로 저장한 뒤 사용하세요.') from e
        if 'Contents/section0.xml' not in self.files:
            raise HwpxError('HWPX 구조가 아닙니다(Contents/section0.xml 없음). .hwp 파일이면 HWPX로 다시 저장하세요.')

    # ---- 파트
    def section_names(self):
        names = [n for n in self.files if re.fullmatch(r'Contents/section\d+\.xml', n)]
        return sorted(names, key=lambda n: int(re.findall(r'\d+', n)[0]))

    def xml(self, name: str):
        return etree.fromstring(self.files[name])

    def header(self) -> "Head":
        return Head(self.xml('Contents/header.xml'))

    def section_root(self, idx: int = 0):
        return self.xml(self.section_names()[idx])

    # ---- 저장
    def set_xml(self, name: str, root):
        self.files[name] = etree.tostring(root, xml_declaration=True, encoding='UTF-8', standalone=True)

    # 다른 도구가 서식에 남긴 '만든 프로그램' 표시는 결과 문서로 옮기지 않는다(문서 속성에 남의 도구 이름이 보이지 않도록).
    _TOOLS = ('kor' + 'doc',)

    def _foreign(self, text):
        low = text.lower()
        return any(t in low for t in self._TOOLS)

    def scrub(self):
        for name in list(self.files):
            if re.fullmatch(r'Contents/section\d+\.xml', name) or name.startswith('BinData/'):
                continue
            if not name.lower().endswith(('.xml', '.hpf', '.txt', '.json', '.rdf')):
                continue
            raw = self.files[name]
            try:
                text = raw.decode('utf-8')
            except UnicodeDecodeError:
                continue
            changed = False
            if name.endswith('.hpf') and '<opf:meta' in text:
                # generator / '…-layout' 같은 도구 표시용 메타(본문 없는 빈 요소)는 한글 문서에 필요 없으므로 제거
                new = re.sub(r'<opf:meta\s+name="(?:generator|[\w.-]*-layout)"\s+content="[^"]*"\s*/>\s*', '', text)
                changed = new != text
                text = new
            if self._foreign(text):
                text = re.sub('(?i)(?:' + '|'.join(self._TOOLS) + r')[\w-]*', 'hwpx', text)
                changed = True
            if changed:
                self.files[name] = text.encode('utf-8')

    def save(self, out: str):
        self.scrub()
        with zipfile.ZipFile(out, 'w') as z:
            if 'mimetype' in self.files:
                z.writestr('mimetype', self.files['mimetype'], compress_type=zipfile.ZIP_STORED)
            for name, data in self.files.items():
                if name == 'mimetype':
                    continue
                z.writestr(name, data, compress_type=zipfile.ZIP_DEFLATED)


class Head:
    """header.xml 에서 문단·글자·테두리 스타일을 id 로 조회."""

    def __init__(self, root):
        self.root = root
        self.para = {}
        self.char = {}
        self.fill = {}
        for pp in root.iter(HH + 'paraPr'):
            align = pp.find(HH + 'align')
            left = pp.xpath('.//hc:left', namespaces=NS)
            intent = pp.xpath('.//hc:intent', namespaces=NS)
            ls = pp.find('.//' + HH + 'lineSpacing')
            self.para[pp.get('id')] = {
                'align': (align.get('horizontal') if align is not None else 'JUSTIFY'),
                'left': int(left[0].get('value')) if left else 0,
                'intent': int(intent[0].get('value')) if intent else 0,
                'line': int(ls.get('value')) if ls is not None else 130,
            }
        for cp in root.iter(HH + 'charPr'):
            self.char[cp.get('id')] = {
                'height': int(cp.get('height', '1000')),
                'color': cp.get('textColor', '#000000'),
                'bold': cp.find(HH + 'bold') is not None,
                'italic': cp.find(HH + 'italic') is not None,
                'ratio': None,
            }
        self.borders = {}
        for bf in root.iter(HH + 'borderFill'):
            info = {'fill': None, 'gradient': None}
            wb = bf.find('.//' + HC + 'winBrush')
            if wb is not None and wb.get('faceColor') not in (None, 'none'):
                info['fill'] = wb.get('faceColor')
            gr = bf.find('.//' + HC + 'gradation')
            if gr is not None:
                info['gradient'] = [c.get('value') for c in gr.findall(HC + 'color')]
            for side in ('left', 'right', 'top', 'bottom'):
                el = bf.find(HH + side + 'Border')
                info[side] = (el.get('type'), el.get('width'), (el.get('color') or '#000000').upper()) if el is not None \
                    else ('NONE', '0.1 mm', '#000000')
            self.borders[bf.get('id')] = info

    def has_fill(self, bf_id) -> bool:
        b = self.borders.get(str(bf_id))
        return bool(b and (b['fill'] or b['gradient']))

    def size(self, char_id, default=1000):
        return self.char.get(str(char_id), {}).get('height', default)
