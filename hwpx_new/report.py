# -*- coding: utf-8 -*-
"""장편 보고서 조판(report) — 원고(글 + 간단한 표시) 하나로 표지·요약·차례·표 차례·장 표지·표·도표·사진·참고문헌·부록까지
   완성된 HWPX(+PDF)를 만든다. 연구학교 결과보고서, 연구보고서, 논문형 보고서, 사업 결과보고서처럼 20~60쪽 문서용.

AI 는 '무엇을 쓸지'만 정한다. 모양(글꼴·크기·간격·표 테두리·번호·차례 쪽수·머리말·쪽 번호)은 이 도구가 정하므로
어떤 AI 모델이 써도 같은 품질이 나온다. 원고 문법은 REPORT.md(`hwpx-new report guide`).

자동으로 하는 일
- 장별 번호(표 Ⅳ-3·그림 Ⅴ-2·사진 Ⅳ-1, 부록 표 n), 본문 참조 {표:키}·{그림:키}·{사진:키} 를 번호로
- 숫자·사실 토큰 {{이름}} (facts JSON 또는 원고의 @set) — 숫자를 손으로 옮겨 적다 틀리는 일을 막음
- 번호·괄호 뒤 조사(표 3을→표 3을/표 2를), 굽은 따옴표, 번호 묶음 빈칸
- 차례·표 차례의 쪽 번호: 한글(또는 내장 렌더러)로 PDF 를 만들어 실제 쪽을 읽고 다시 조판(쪽수가 안 바뀔 때까지)
- 쪽을 넘긴 표의 다음 쪽 머리행 자리 보충, 쪽 끝에 제목만 걸린 표는 새 쪽으로
- @chart 데이터 → 도표 PNG(보고서 강조색), 도표는 300dpi 로 넣어 인쇄해도 글자가 또렷함

한글에서 실측한 사실(엔진에 반영)
- '글자처럼 취급' 표는 쪽을 넘어 나뉘지 않는다 → 긴 표는 떠 있는 표 + pageBreak="TABLE"(행 단위로 나눔. "CELL"은 칸 글까지 쪼갬)
- 떠 있는 표의 자리는 문서에 적힌 행 높이로 잡힌다 → 글자 폭(GLYPH)으로 줄 수를 어림해 행 높이를 적고, 다음 쪽 머리행 반복분은 빈 문단으로 보충
- 머리말은 hp:header 제어(왼쪽 글 + 오른쪽 탭), 쪽 번호는 pageNum + newNum(본문 1쪽부터, 앞부분은 로마 숫자)
"""
from __future__ import annotations

import copy
import json
import os
import re
import shutil
import time

from lxml import etree

from .compose import Composer, HP, HH, NSDECL, esc, LINE_NONE
from .images import MM
from . import textfix

HERE = os.path.dirname(os.path.abspath(__file__))
TEMPLATE = os.path.join(HERE, 'data', 'sample_template.hwpx')

THEMES = {
    'wine': '#8C1C3C', 'navy': '#1F3A5F', 'blue': '#1D4E89', 'teal': '#0F6E78', 'green': '#24684B',
    'forest': '#2E5B34', 'plum': '#5B2A6E', 'brown': '#7A4A24', 'charcoal': '#33363B', 'red': '#A3262A',
}
FONT_SETS = {
    'gothic': ('맑은 고딕', '맑은 고딕'),
    'myungjo': ('휴먼명조', 'HY헤드라인M'),
    'nanum': ('나눔고딕', '나눔고딕'),
    'batang': ('바탕', '맑은 고딕'),
}
INK = '#1E1E22'
GRAY = '#5E636B'
LIGHT = '#8E939B'
BOX_GRAY = '#F4F4F6'
ROMAN = 'Ⅰ Ⅱ Ⅲ Ⅳ Ⅴ Ⅵ Ⅶ Ⅷ Ⅸ Ⅹ'.split()


# ------------------------------------------------------------------ 색
def _rgb(h):
    h = h.strip().lstrip('#')
    return tuple(int(h[i:i + 2], 16) for i in (0, 2, 4))


def _hex(c):
    return '#%02X%02X%02X' % tuple(max(0, min(255, int(round(v)))) for v in c)


def _mix(h, w, other='#FFFFFF'):
    a, b = _rgb(h), _rgb(other)
    return _hex(tuple(x + (y - x) * w for x, y in zip(a, b)))


def theme_colors(accent):
    import colorsys
    r, g, b = [v / 255 for v in _rgb(accent)]
    hh, ll, ss = colorsys.rgb_to_hls(r, g, b)
    dark = _hex(tuple(v * 255 for v in colorsys.hls_to_rgb(hh, max(0, ll * 0.78), ss)))
    return {'accent': accent.upper(), 'dark': dark, 'pale': _mix(accent, 0.91), 'light': _mix(accent, 0.66),
            'head': _mix(accent, 0.92), 'label': _mix(accent, 0.96), 'band_text': _mix(accent, 0.86)}


def make_styles(body, head):
    """이름: (글꼴, pt, 굵게, 정렬, 왼쪽, 내어쓰기(음수=첫 줄 들여쓰기), 앞, 뒤, 줄간격%, 다음과 함께)"""
    return {
        'p': (body, 10, False, 'JUSTIFY', 0, -1000, 240, 0, 170, False),
        'pk': (body, 10, False, 'JUSTIFY', 0, -1000, 240, 0, 170, True),
        'b1': (body, 10, False, 'JUSTIFY', 400, 1000, 200, 0, 168, False),
        'b1k': (body, 10, False, 'JUSTIFY', 400, 1000, 200, 0, 168, True),
        'b2': (body, 9.5, False, 'JUSTIFY', 1400, 650, 70, 0, 163, False),
        'b3': (body, 9.5, False, 'JUSTIFY', 2100, 600, 40, 0, 160, False),
        'note': (body, 9, False, 'JUSTIFY', 400, 900, 120, 0, 150, False),
        'res': (body, 10, True, 'JUSTIFY', 400, 1150, 280, 120, 165, False),
        'resk': (body, 10, True, 'JUSTIFY', 400, 1150, 280, 120, 165, True),
        'sec': (head, 14, True, 'LEFT', 0, 0, 0, 0, 120, True),
        'sub': (head, 11.5, True, 'LEFT', 0, 0, 1000, 260, 140, True),
        'ssub': (head, 10.5, True, 'LEFT', 300, 0, 620, 160, 140, True),
        'tcap': (head, 10, True, 'LEFT', 0, 0, 720, 200, 130, True),
        'tunit': (body, 8.5, False, 'RIGHT', 0, 0, 0, 60, 120, True),
        'tnote': (body, 8.5, False, 'JUSTIFY', 0, 0, 100, 420, 140, False),
        'fcap': (head, 9.5, True, 'CENTER', 0, 0, 140, 640, 130, False),
        'pcap': (body, 8.5, False, 'CENTER', 0, 0, 30, 0, 120, False),
        'cell': (body, 9.5, False, 'CENTER', 0, 0, 0, 0, 135, False),
        'cellL': (body, 9.5, False, 'LEFT', 0, 0, 0, 0, 135, False),
        'cellLh': (body, 9.5, False, 'LEFT', 0, 750, 0, 0, 135, False),
        'cellS': (body, 9, False, 'CENTER', 0, 0, 0, 0, 130, False),
        'cellSL': (body, 9, False, 'LEFT', 0, 0, 0, 0, 130, False),
        'cellSLh': (body, 9, False, 'LEFT', 0, 700, 0, 0, 130, False),
        'cellH': (head, 9.5, True, 'CENTER', 0, 0, 0, 0, 130, False),
        'cellSH': (head, 9, True, 'CENTER', 0, 0, 0, 0, 125, False),
        'boxt': (head, 10, True, 'LEFT', 0, 0, 0, 160, 140, False),
        'bx1': (body, 9.5, False, 'JUSTIFY', 0, 900, 80, 0, 160, False),
        'bx2': (body, 9.5, False, 'JUSTIFY', 900, 560, 30, 0, 155, False),
        'bxp': (body, 9.5, False, 'JUSTIFY', 0, 0, 80, 0, 160, False),
        'vq': (body, 9.5, False, 'JUSTIFY', 0, 0, 160, 0, 158, False),
        'vby': (body, 8.5, False, 'RIGHT', 0, 0, 20, 60, 130, False),
        'kpin': (head, 19, True, 'CENTER', 0, 0, 0, 0, 115, False),
        'kpil': (head, 9, True, 'CENTER', 0, 0, 60, 0, 125, False),
        'kpis': (body, 8, False, 'CENTER', 0, 0, 20, 0, 125, False),
        'chn': (head, 30, True, 'LEFT', 0, 0, 0, 0, 100, False),
        'cht': (head, 21, True, 'LEFT', 0, 0, 60, 0, 120, False),
        'chl': (body, 9.5, False, 'LEFT', 0, 0, 160, 0, 150, False),
        'chs': (body, 9.5, False, 'JUSTIFY', 0, 950, 50, 0, 155, False),
        'toc0': (head, 10.5, True, 'LEFT', 0, 0, 200, 30, 130, True),
        'toc1': (body, 9.5, False, 'LEFT', 1100, 0, 0, 0, 130, False),
        'lot': (body, 8.5, False, 'LEFT', 0, 0, 0, 0, 124, False),
        'loth': (head, 10.5, True, 'LEFT', 0, 0, 460, 140, 130, True),
        'ftitle': (head, 16, True, 'LEFT', 0, 0, 0, 0, 120, True),
        'fsub': (head, 11.5, True, 'LEFT', 0, 0, 600, 200, 140, True),
        'ref': (body, 9, False, 'LEFT', 0, 2500, 50, 0, 140, False),
        'refh': (head, 10.5, True, 'LEFT', 0, 0, 420, 120, 140, True),
        'blank': (body, 8, False, 'JUSTIFY', 0, 0, 0, 0, 100, False),
        'hdr': (body, 8, False, 'LEFT', 0, 0, 0, 0, 100, False),
        'cv_k1': (head, 10, True, 'LEFT', 0, 0, 0, 0, 130, False),
        'cv_k2': (body, 10, False, 'LEFT', 0, 0, 40, 0, 140, False),
        'cv_sub': (head, 13, True, 'LEFT', 0, 0, 0, 120, 140, False),
        'cv_title': (head, 25, True, 'LEFT', 0, 0, 0, 0, 130, False),
        'cv_date': (head, 12.5, False, 'RIGHT', 0, 0, 0, 120, 140, False),
        'cv_org': (head, 19, True, 'RIGHT', 0, 0, 0, 0, 140, False),
        'cv_note': (body, 8, False, 'LEFT', 0, 0, 380, 0, 130, False),
    }


# ------------------------------------------------------------------ 조판기
class ReportComposer(Composer):
    GLYPH = {'"': .395, '%': .836, '&': .818, "'": .232, '(': .305, ')': .305, '+': .701, ',': .219, '-': .41, '.': .219,
             '/': .396, ':': .219, ';': .219, '<': .701, '=': .701, '>': .701, '?': .46, '[': .305, ']': .305, '_': .426,
             '|': .239, '~': .701, '–': .513, '—': 1.026, '!': .289, ' ': .352, chr(0xA0): .352, '·': .5, '×': .701, '⇒': .95,
             '‘': .231, '’': .231, '“': .379, '”': .379,
             'A': .658, 'B': .584, 'C': .635, 'D': .717, 'E': .517, 'F': .499, 'G': .702, 'H': .725, 'I': .27, 'J': .36,
             'K': .59, 'L': .48, 'M': .917, 'N': .765, 'O': .773, 'P': .571, 'Q': .773, 'R': .61, 'S': .543, 'T': .534,
             'U': .703, 'V': .634, 'W': .954, 'X': .601, 'Y': .563, 'Z': .583, 'a': .52, 'b': .601, 'c': .473, 'd': .602,
             'e': .535, 'f': .316, 'g': .602, 'h': .579, 'i': .246, 'j': .246, 'k': .506, 'l': .246, 'm': .88, 'n': .578,
             'o': .599, 'p': .601, 'q': .602, 'r': .354, 's': .433, 't': .345, 'u': .578, 'v': .487, 'w': .736, 'x': .465,
             'y': .493, 'z': .462, **{d: .551 for d in '0123456789'}}
    SPLIT_MIN = 0.40
    CONDENSE = {'p', 'pk', 'b1', 'b1k', 'b2', 'b3', 'note', 'res', 'resk', 'tnote', 'bx1', 'bx2', 'bxp', 'vq', 'chs', 'chl'}
    CONDENSE_PCT = 25

    def __init__(self, template=None, accent='#8C1C3C', body_font='맑은 고딕', head_font='맑은 고딕'):
        self.STYLES = make_styles(body_font, head_font)
        self.WORD_WRAP = set(self.STYLES)          # 보고서는 모든 문단을 어절 단위로(낱말이 줄 끝에서 갈라지지 않게)
        self.BODY, self.HEAD = body_font, head_font
        self.C = theme_colors(accent)
        super().__init__(template or TEMPLATE)
        self.BODY_H = self._body_height()
        self.tabpr = self._tab('DOT', self.text_width)
        self.tabpr_plain = self._tab('NONE', self.text_width)
        c = self.C
        self.LINE_TOP = ('SOLID', '0.5 mm', c['accent'])
        self.LINE_BOT = ('SOLID', '0.35 mm', c['accent'])
        self.LINE_HD = ('SOLID', '0.2 mm', c['accent'])
        self.LINE_ROW = ('SOLID', '0.12 mm', '#CDD0D5')
        self.LINE_VER = ('SOLID', '0.12 mm', '#E1E3E7')
        self.table_log = []

    def _body_height(self):
        pp = self.sec.find('.//' + HP + 'pagePr')
        if pp is None:
            return 69000
        mg = pp.find(HP + 'margin')
        h = int(pp.get('height', '84188'))
        if mg is not None:
            h -= int(mg.get('top', '0')) + int(mg.get('bottom', '0')) + int(mg.get('header', '0')) + int(mg.get('footer', '0'))
        return max(40000, h)

    # ------------------------------------------------------------ 탭(차례 점선, 머리말 오른쪽)
    def _tab(self, leader, pos):
        tabs = self._box('tabProperties')
        tid = str(max(int(t.get('id')) for t in tabs.findall(HH + 'tabPr')) + 1)
        xml = (f'<hh:tabPr {NSDECL} id="{tid}" autoTabLeft="0" autoTabRight="0"><hp:switch>'
               f'<hp:case hp:required-namespace="http://www.hancom.co.kr/hwpml/2016/HwpUnitChar">'
               f'<hh:tabItem pos="{pos}" type="RIGHT" leader="{leader}" unit="HWPUNIT"/></hp:case>'
               f'<hp:default><hh:tabItem pos="{pos * 2}" type="RIGHT" leader="{leader}"/></hp:default></hp:switch></hh:tabPr>')
        tabs.append(etree.fromstring(xml))
        tabs.set('itemCnt', str(len(tabs.findall(HH + 'tabPr'))))
        return tid

    def para_tab(self, name, tab=None):
        pid = self.style_ids(name)[0]
        tab = tab or self.tabpr
        key = ('tab', pid, tab)
        if key not in self._para_cache:
            box = self._box('paraProperties')
            src = next(p for p in box.findall(HH + 'paraPr') if p.get('id') == pid)
            new = copy.deepcopy(src)
            new.set('id', self._next_id(box, 'paraPr'))
            new.set('tabPrIDRef', tab)
            box.append(new)
            box.set('itemCnt', str(len(box.findall(HH + 'paraPr'))))
            self._para_cache[key] = new.get('id')
        return self._para_cache[key]

    def toc_line(self, name, text, page, color=INK):
        pid = self.para_tab(name)
        face, size, bold = self.STYLES[name][:3]
        cid = self.char(face, size, bold, color)
        xml = (f'<hp:p {NSDECL} id="2147483648" paraPrIDRef="{pid}" styleIDRef="0" pageBreak="0" columnBreak="0" merged="0">'
               f'<hp:run charPrIDRef="{cid}"><hp:t>{esc(text)}<hp:tab width="4000" leader="3" type="2"/>'
               f'{esc(str(page))}</hp:t></hp:run></hp:p>')
        return self._add(etree.fromstring(xml))

    # ------------------------------------------------------------ 제어(쪽 번호·머리말)
    def ctrl(self, p, xml):
        run = p.find(HP + 'run')
        if run is None:
            run = etree.SubElement(p, HP + 'run')
            run.set('charPrIDRef', self.char(self.BODY, 10))
        run.insert(0, etree.fromstring(f'<hp:ctrl {NSDECL}>{xml}</hp:ctrl>'))

    def hide_page(self, p):
        self.ctrl(p, '<hp:pageHiding hideHeader="1" hideFooter="1" hideMasterPage="1" hideBorder="1" hideFill="1" hidePageNum="1"/>')

    def page_num(self, p, fmt='DIGIT', side='', restart=True):
        self.ctrl(p, f'<hp:pageNum pos="BOTTOM_CENTER" formatType="{fmt}" sideChar="{side}"/>')
        if restart:
            self.ctrl(p, '<hp:newNum num="1" numType="PAGE"/>')

    def header(self, p, left, right, hid=1):
        """머리말: 왼쪽 문서 이름(회색) ─ 오른쪽 장 이름(강조색)."""
        pid = self.para_tab('hdr', self.tabpr_plain)
        c1 = self.char(self.BODY, 8, False, LIGHT)
        c2 = self.char(self.HEAD, 8, True, self.C['accent'])
        xml = (f'<hp:header id="{hid}" applyPageType="BOTH"><hp:subList id="" textDirection="HORIZONTAL" lineWrap="BREAK" '
               f'vertAlign="TOP" linkListIDRef="0" linkListNextIDRef="0" textWidth="{self.text_width}" textHeight="2835" '
               f'hasTextRef="0" hasNumRef="0"><hp:p id="2147483648" paraPrIDRef="{pid}" styleIDRef="0" pageBreak="0" '
               f'columnBreak="0" merged="0"><hp:run charPrIDRef="{c1}"><hp:t>{esc(left)}<hp:tab width="4000" leader="0" type="2"/></hp:t></hp:run>'
               f'<hp:run charPrIDRef="{c2}"><hp:t>{esc(right)}</hp:t></hp:run></hp:p>'
               f'</hp:subList></hp:header>')
        self.ctrl(p, xml)

    # ------------------------------------------------------------ 상자 표 공통
    def _cell(self, col, row, w, h, bf, ps, va='CENTER', margin=(500, 300, 120, 120), cs=1, rs=1):
        l, r, t, b = margin
        return (f'<hp:tc name="" header="0" hasMargin="1" protect="0" editable="0" dirty="0" borderFillIDRef="{bf}">'
                f'<hp:subList id="" textDirection="HORIZONTAL" lineWrap="BREAK" vertAlign="{va}" linkListIDRef="0" '
                'linkListNextIDRef="0" textWidth="0" textHeight="0" hasTextRef="0" hasNumRef="0">' + ps + '</hp:subList>'
                f'<hp:cellAddr colAddr="{col}" rowAddr="{row}"/><hp:cellSpan colSpan="{cs}" rowSpan="{rs}"/>'
                f'<hp:cellSz width="{w}" height="{h}"/><hp:cellMargin left="{l}" right="{r}" top="{t}" bottom="{b}"/></hp:tc>')

    def _tbl(self, rows_xml, ncol, nrow, total, h, pid, margin=(0, 0, 0, 0)):
        l, r, t, b = margin
        self._z += 1
        tbl = (f'<hp:tbl id="{self._new_id()}" zOrder="{self._z}" numberingType="TABLE" textWrap="TOP_AND_BOTTOM" '
               'textFlow="BOTH_SIDES" lock="0" dropcapstyle="None" pageBreak="NONE" repeatHeader="0" '
               f'rowCnt="{nrow}" colCnt="{ncol}" cellSpacing="0" borderFillIDRef="2" noAdjust="0">'
               f'<hp:sz width="{total}" widthRelTo="ABSOLUTE" height="{h}" heightRelTo="ABSOLUTE" protect="0"/>'
               '<hp:pos treatAsChar="1" affectLSpacing="0" flowWithText="1" allowOverlap="0" holdAnchorAndSO="0" '
               'vertRelTo="PARA" horzRelTo="PARA" vertAlign="TOP" horzAlign="LEFT" vertOffset="0" horzOffset="0"/>'
               f'<hp:outMargin left="0" right="0" top="0" bottom="0"/><hp:inMargin left="{l}" right="{r}" top="{t}" bottom="{b}"/>'
               + rows_xml + '</hp:tbl>')
        return self._wrap_tbl(tbl, pid)

    def _ps(self, name, text, color=INK):
        pid = self.style_ids(name)[0]
        return self._p_xml(pid, self._runs(text, name, color=color), self.STYLES[name][5] > 0)

    def _pic(self, path, w_mm, max_h_mm=120, chart=False):
        """chart=True: 도표를 300dpi 팔레트 PNG 로(글자가 또렷). 사진은 기본(보이는 크기 × 200dpi JPEG)."""
        if not chart:
            return super()._pic(path, w_mm, max_h_mm)
        import io as _io
        from PIL import Image
        from .images import fit_size, image_size, pic_run
        w0, h0 = image_size(path)
        w, h = fit_size(w0, h0, int(w_mm * MM), int(max_h_mm * MM), None)
        im = Image.open(path).convert('RGB')
        tw = round(w / MM / 25.4 * 300)
        if tw < im.size[0]:
            im = im.resize((tw, round(im.size[1] * tw / im.size[0])), Image.LANCZOS)
        im = im.quantize(colors=256, method=Image.Quantize.MEDIANCUT, dither=Image.Dither.NONE)
        buf = _io.BytesIO()
        im.save(buf, 'PNG', optimize=True)
        bin_id = f'image{self._img_idx}'
        self._img_idx += 1
        self._images.append((bin_id, '.png', buf.getvalue()))
        self._uid += 1
        return pic_run(self.char(self.BODY, 10), bin_id, w, h, im.size[0], im.size[1], inline=True, uid=self._uid + 500,
                       name=os.path.basename(path))

    def _pic_p(self, path, w_mm, h_mm, chart=False):
        run = self._pic(path, w_mm, h_mm, chart=chart)
        pid = self.para('CENTER', 0, 0, 0, 0, 100, False, True)
        return (f'<hp:p id="2147483648" paraPrIDRef="{pid}" styleIDRef="0" pageBreak="0" columnBreak="0" merged="0">'
                + etree.tostring(run, encoding='unicode') + '</hp:p>'), int(run.find(HP + 'pic').find(HP + 'sz').get('height'))

    def figure(self, path, width_mm=156, max_h_mm=140, chart=False, keep_next=True):
        pid = self.para('CENTER', 0, 0, 200, 100, 100, keep_next, True)
        p = etree.fromstring(f'<hp:p {NSDECL} id="2147483648" paraPrIDRef="{pid}" styleIDRef="0" pageBreak="0" '
                             'columnBreak="0" merged="0"/>')
        p.append(self._pic(path, width_mm, max_h_mm, chart=chart))
        return self._add(p)

    # ------------------------------------------------------------ 장 표지 띠: [강조색 칸: 번호·제목·설명] [사진] + 요약 상자
    def chapter(self, roman, title, lead, photo, summary):
        self.page()
        total = self.text_width
        h = int(62 * MM)
        c = self.C
        ps_l = self._ps('chn', roman, c['light']) + self._ps('cht', title, '#FFFFFF') + self._ps('chl', lead, c['band_text'])
        bf_l = self.fill(c['accent'], LINE_NONE, LINE_NONE, LINE_NONE, LINE_NONE)
        if photo:
            from .images import image_size  # noqa: F401
            w_l = int(total * 0.58)
            w_r = total - w_l
            bf_r = self.fill(c['dark'], LINE_NONE, LINE_NONE, LINE_NONE, LINE_NONE)
            cells = self._cell(0, 0, w_l, h, bf_l, ps_l, va='CENTER', margin=(1300, 900, 700, 700))
            crop = crop_to(photo, w_r / MM, h / MM, self.work_dir)
            ps_r, _ = self._pic_p(crop, w_r / MM, h / MM)
            cells += self._cell(1, 0, w_r, h, bf_r, ps_r, va='TOP', margin=(0, 0, 0, 0))
            el = self._tbl('<hp:tr>' + cells + '</hp:tr>', 2, 1, total, h, self.para('LEFT', 0, 0, 0, 0, 100, True, True))
        else:
            el = self._tbl('<hp:tr>' + self._cell(0, 0, total, h, bf_l, ps_l, margin=(1300, 900, 700, 700)) + '</hp:tr>',
                           1, 1, total, h, self.para('LEFT', 0, 0, 0, 0, 100, True, True))
        if summary:
            bf = self.fill(BOX_GRAY, LINE_NONE, LINE_NONE, LINE_NONE, ('SOLID', '0.12 mm', '#C9CCD2'))
            ps = ''.join(self._ps('chs', '▸ ' + s) for s in summary)
            n = sum(self.wrap_lines('▸ ' + s, 'chs', total - 1800) for s in summary)
            hh = int(n * 9.5 * 100 * 1.55 + 1000)
            self._tbl('<hp:tr>' + self._cell(0, 0, total, hh, bf, ps, va='TOP', margin=(900, 900, 450, 450)) + '</hp:tr>',
                      1, 1, total, hh, self.para('LEFT', 0, 0, 0, 900, 100, False, True))
        return el

    # ------------------------------------------------------------ 절 제목: 번호(강조색)·제목 + 두 색 밑줄
    def sec_heading(self, num, title):
        total = self.text_width
        w1 = int(total * 0.17)
        pid = self.style_ids('sec')[0]
        runs = [(f'{num}. ' if num else '', self.char(self.HEAD, 14, True, self.C['accent'])), (title, self.char(self.HEAD, 14, True, INK))]
        runs = [r for r in runs if r[0]]
        ps = self._p_xml(pid, runs)
        bf0 = self.fill(None, LINE_NONE, LINE_NONE, LINE_NONE, LINE_NONE)
        bfa = self.fill(None, LINE_NONE, LINE_NONE, LINE_NONE, ('SOLID', '0.8 mm', self.C['accent']))
        bfb = self.fill(None, LINE_NONE, LINE_NONE, LINE_NONE, ('SOLID', '0.15 mm', '#B9BEC5'))
        thin = self._p_xml(self.para('LEFT', 0, 0, 0, 0, 100, False, True), [('', self.char(self.BODY, 1))])
        rows = ('<hp:tr>' + self._cell(0, 0, total, 2000, bf0, ps, va='BOTTOM', margin=(0, 0, 0, 160), cs=2) + '</hp:tr>'
                + '<hp:tr>' + self._cell(0, 1, w1, 120, bfa, thin, margin=(0, 0, 0, 0))
                + self._cell(1, 1, total - w1, 120, bfb, thin, margin=(0, 0, 0, 0)) + '</hp:tr>')
        return self._tbl(rows, 2, 2, total, 2120, self.para('LEFT', 0, 0, 1300, 420, 100, True, True))

    def sub_heading(self, num, title):
        pid = self.style_ids('sub')[0]
        runs = [(f'{num}. ' if num else '', self.char(self.HEAD, 11.5, True, self.C['accent'])), (title, self.char(self.HEAD, 11.5, True, INK))]
        runs = [r for r in runs if r[0]]
        return self._add(etree.fromstring(self._p_xml(pid, runs).replace('<hp:p ', f'<hp:p {NSDECL} ', 1)))

    def caption(self, num, title, name='tcap'):
        pid = self.style_ids(name)[0]
        face, size = self.STYLES[name][:2]
        runs = [(num, self.char(face, size, True, self.C['accent'])), ('  ' + title, self.char(face, size, True, INK))]
        return self._add(etree.fromstring(self._p_xml(pid, runs).replace('<hp:p ', f'<hp:p {NSDECL} ', 1)))

    # ------------------------------------------------------------ 상자·인용·숫자 카드
    def tbox(self, lines, title=None, tone='gray'):
        total = self.text_width
        c = self.C
        if tone in ('accent', 'wine', 'color'):
            bf = self.fill(c['pale'], LINE_NONE, LINE_NONE, ('SOLID', '0.5 mm', c['accent']), ('SOLID', '0.12 mm', c['light']))
        else:
            bf = self.fill(BOX_GRAY, LINE_NONE, LINE_NONE, ('SOLID', '0.12 mm', '#B9BEC5'), ('SOLID', '0.12 mm', '#B9BEC5'))
        ps = self._ps('boxt', title, c['accent'] if tone in ('accent', 'wine', 'color') else INK) if title else ''
        n = 1 if title else 0
        for name, text in lines:
            ps += self._ps(name, text)
            n += self.wrap_lines(text, name, total - 1800)
        hh = int(n * 9.5 * 100 * 1.62 + 1000)
        return self._tbl('<hp:tr>' + self._cell(0, 0, total, hh, bf, ps, va='TOP', margin=(900, 900, 450, 450)) + '</hp:tr>',
                         1, 1, total, hh, self.para('CENTER', 0, 0, 300, 300, 100, False, True))

    def voice(self, items, title):
        total = self.text_width
        bf = self.fill(BOX_GRAY, LINE_NONE, LINE_NONE, ('SOLID', '0.5 mm', self.C['accent']), ('SOLID', '0.12 mm', '#B9BEC5'))
        ps = self._ps('boxt', title, self.C['accent'])
        n = 1
        for q, by in items:
            ps += self._ps('vq', f'“{q}”') + (self._ps('vby', f'— {by}', GRAY) if by else '')
            n += self.wrap_lines(f'“{q}”', 'vq', total - 1800) + (1 if by else 0)
        hh = int(n * 9.5 * 100 * 1.6 + 1000)
        return self._tbl('<hp:tr>' + self._cell(0, 0, total, hh, bf, ps, va='TOP', margin=(900, 900, 450, 400)) + '</hp:tr>',
                         1, 1, total, hh, self.para('CENTER', 0, 0, 300, 300, 100, False, True))

    def kpi_grid(self, items, cols=4):
        total = self.text_width
        w = total // cols
        rows = (len(items) + cols - 1) // cols
        h = 3700
        gap = ('SOLID', '1.2 mm', '#FFFFFF')
        xml = ''
        for r in range(rows):
            xml += '<hp:tr>'
            for c in range(cols):
                i = r * cols + c
                ww = w if c < cols - 1 else total - w * (cols - 1)
                if i < len(items):
                    val, label, note = items[i]
                    bf = self.fill(self.C['pale'], gap, gap, gap, gap)
                    ps = self._ps('kpin', val, self.C['accent']) + self._ps('kpil', label, INK) + (self._ps('kpis', note, GRAY) if note else '')
                else:
                    bf = self.fill(None, gap, gap, gap, gap)
                    ps = self._ps('kpis', '')
                xml += self._cell(c, r, ww, h, bf, ps, margin=(220, 220, 260, 260))
            xml += '</hp:tr>'
        return self._tbl(xml, cols, rows, total, h * rows, self.para('CENTER', 0, 0, 240, 260, 100, False, True))

    # ------------------------------------------------------------ 본문 문단: 최소 공백
    def style_ids(self, name, size=None):
        pid, cid = super().style_ids(name, size)
        if name in self.CONDENSE:
            pid = self._condensed(pid, self.CONDENSE_PCT)
        return pid, cid

    def _condensed(self, pid, pct):
        key = ('condense', pid, pct)
        if key not in self._para_cache:
            box = self._box('paraProperties')
            src = next(p for p in box.findall(HH + 'paraPr') if p.get('id') == pid)
            new = copy.deepcopy(src)
            new.set('id', self._next_id(box, 'paraPr'))
            new.set('condense', str(pct))
            box.append(new)
            box.set('itemCnt', str(len(box.findall(HH + 'paraPr'))))
            self._para_cache[key] = new.get('id')
        return self._para_cache[key]

    def _p_xml(self, pid, runs, hanging=False):
        return super()._p_xml(pid, runs, hanging).replace('⤶', '<hp:lineBreak/>').replace(' ', '<hp:nbSpace/>')

    def _runs(self, text, name, size=None, bold=None, color=INK):
        face, sz, b = self.STYLES[name][:3]
        b = b if bold is None else bold
        out = []
        m = re.match(r'^(⇒|○|▸) ', text)
        if m:
            out.append((m.group(1) + ' ', self.char(face, size or sz, True, self.C['accent'])))
            text = text[2:]
        for part in re.split(r'(\*\*.+?\*\*|\^\^.+?\^\^)', text):
            if not part:
                continue
            if part.startswith('**') and part.endswith('**'):
                out.append((part[2:-2], self.char(face, size or sz, True, color)))
            elif part.startswith('^^') and part.endswith('^^'):
                out.append((part[2:-2], self.char(face, size or sz, True, self.C['accent'])))
            else:
                out.append((part, self.char(face, size or sz, b, color)))
        return out

    def p(self, text, name='p', size=None, color=INK):
        return self._add(self.make_p(text, name, size, color=color))

    @classmethod
    def em_width(cls, s):
        w = 0.0
        for ch in s:
            g = cls.GLYPH.get(ch)
            w += g if g is not None else (1.0 if ord(ch) >= 0x370 else 0.55)
        return w

    def wrap_lines(self, text, name, width, slack=1.0):
        st = self.STYLES[name]
        em = st[1] * 100 * slack
        left, hang = st[4], st[5]
        first = width - left - (abs(hang) if hang < 0 else 0)
        rest = width - left - (hang if hang > 0 else 0)
        t = re.sub(r'\*\*|\^\^', '', text).replace('⤶', '\n')
        total = 0
        for seg in t.split('\n'):
            lines, cap, cur = 1, first, 0.0
            for word in seg.split(' '):
                ww = self.em_width(word) * em
                need = ww if cur == 0 else cur + 0.352 * em + ww
                if need <= cap:
                    cur = need
                    continue
                if cur > 0:
                    lines += 1
                    cap = rest
                while ww > cap:
                    ww -= cap
                    lines += 1
                    cap = rest
                cur = ww
            total += lines
        return total

    # ------------------------------------------------------------ 표(열린 표: 위 강조색 선, 머리행 옅은 색, 세로선 없음)
    def table(self, widths, rows, head=1, label_col=False, aligns=None, size='n', split=None, total=None,
              fills=None, min_row=0, pad=130, grid=False, accent_cells=()):
        total = total or self.text_width
        s = float(sum(widths))
        widths = [int(w * total / s) for w in widths]
        widths[-1] += total - sum(widths)
        ncol, nrow = len(widths), len(rows)
        occ = [[None] * ncol for _ in range(nrow)]
        placed = []
        for r, row in enumerate(rows):
            c = 0
            for cell in row:
                while c < ncol and occ[r][c] is not None:
                    c += 1
                if c >= ncol:
                    raise ValueError(f'표 {r + 1}행의 칸 수가 열 수({ncol})보다 많습니다: {row}')
                spec = cell if isinstance(cell, dict) else {'t': cell}
                cs, rs = int(spec.get('cs', 1)), int(spec.get('rs', 1))
                if r + rs > nrow:
                    raise ValueError(f'표 {r + 1}행의 세로 합치기(rs={rs})가 표 아래로 넘칩니다.')
                for rr in range(r, r + rs):
                    for cc in range(c, min(ncol, c + cs)):
                        occ[rr][cc] = (r, c)
                placed.append((r, c, cs, rs, spec))
                c += cs
            if any(x is None for x in occ[r]):
                raise ValueError(f'표 {r + 1}행의 칸 수가 모자랍니다(열 {ncol}개): {row} — 위 행의 세로 합치기는 ^ 로 채우세요.')
        small = size == 's'
        base = int((9 if small else 9.5) * 100 * 1.35 + 2 * pad)
        need, tcs = {}, {}
        C = self.C
        for (r, c, cs, rs, spec) in placed:
            w = sum(widths[c:c + cs])
            is_head = r < head
            is_label = label_col and c == 0 and not is_head
            fill = spec.get('fill') or (C['head'] if is_head else (C['label'] if is_label else None))
            if fills and (r, c) in fills:
                fill = fills[(r, c)]
            vline = self.LINE_VER if (grid or is_label or (label_col and c == 1 and not is_head)) else LINE_NONE
            left = LINE_NONE if c == 0 else (self.LINE_VER if grid else (vline if label_col and c == 1 else LINE_NONE))
            right = LINE_NONE if c + cs == ncol else (self.LINE_VER if grid else (vline if is_label else LINE_NONE))
            top = self.LINE_TOP if r == 0 else self.LINE_ROW
            bottom = self.LINE_BOT if r + rs == nrow else (self.LINE_HD if (is_head and r + rs == head) else self.LINE_ROW)
            bf = self.fill(fill, left, right, top, bottom)
            a = spec.get('a') or (aligns[c] if aligns and c < len(aligns) and not is_head else 'c')
            bold = spec.get('b', (is_label and not is_head) or None)
            ps = ''
            img_h = 0
            if spec.get('img'):
                pp, img_h = self._pic_p(spec['img'], spec.get('w_mm', w / MM - 4), spec.get('max_h_mm', 60))
                ps += pp
            lines = str(spec.get('t', '')).split('\n') if (spec.get('t') or not spec.get('img')) else []
            n_lines, pitch = 0, 0
            for ln in lines:
                if a == 'l':
                    hanging = ln.startswith(('- ', '· ', '※ ', '○ '))
                    name = ('cellSLh' if small else 'cellLh') if hanging else ('cellSL' if small else 'cellL')
                else:
                    name = ('cellSH' if small else 'cellH') if is_head else ('cellS' if small else 'cell')
                pid = self.style_ids(name)[0]
                if a == 'r':
                    pid = self.para('RIGHT', 0, 0, 0, 0, self.STYLES[name][8], False, True)
                color = spec.get('color') or (C['accent'] if (spec.get('accent') or (r, c) in accent_cells)
                                              else (C['dark'] if is_head else INK))
                runs = self._runs(ln, name, size=spec.get('size'), bold=bold, color=color)
                ps += self._p_xml(pid, runs, self.STYLES[name][5] > 0)
                n_lines += self.wrap_lines(ln, name, w - 1020, 1.04 if (bold or is_head) else 1.0)
                pitch = self.STYLES[name][1] * self.STYLES[name][8]
            h = base + int(max(0, n_lines - 1) * pitch) + img_h
            need[(r, c)] = (rs, h)
            tcs[(r, c)] = (cs, rs, w, bf, ps, spec.get('va', 'CENTER'))
        row_h = [base] * nrow
        for (r, c), (rs, h) in need.items():
            if rs == 1:
                row_h[r] = max(row_h[r], h, min_row if r >= head else 0)
        for (r, c), (rs, h) in need.items():
            if rs > 1:
                lack = h - sum(row_h[r:r + rs])
                if lack > 0:
                    for rr in range(r, r + rs):
                        row_h[rr] += lack // rs + 1
        if split is None:
            split = sum(row_h) > self.BODY_H * self.SPLIT_MIN
        xml_rows = ''
        for r in range(nrow):
            xml_rows += '<hp:tr>'
            for c in range(ncol):
                if (r, c) not in tcs:
                    continue
                cs, rs, w, bf, ps, va = tcs[(r, c)]
                h = sum(row_h[r:r + rs])
                xml_rows += (f'<hp:tc name="" header="{1 if r < head else 0}" hasMargin="0" protect="0" editable="0" '
                             f'dirty="0" borderFillIDRef="{bf}"><hp:subList id="" textDirection="HORIZONTAL" '
                             f'lineWrap="BREAK" vertAlign="{va}" linkListIDRef="0" linkListNextIDRef="0" textWidth="0" '
                             f'textHeight="0" hasTextRef="0" hasNumRef="0">{ps}</hp:subList>'
                             f'<hp:cellAddr colAddr="{c}" rowAddr="{r}"/><hp:cellSpan colSpan="{cs}" rowSpan="{rs}"/>'
                             f'<hp:cellSz width="{w}" height="{h}"/>'
                             f'<hp:cellMargin left="510" right="510" top="{pad}" bottom="{pad}"/></hp:tc>')
            xml_rows += '</hp:tr>'
        as_char = '0' if split else '1'
        self._z += 1
        tbl = (f'<hp:tbl id="{self._new_id()}" zOrder="{self._z}" numberingType="TABLE" textWrap="TOP_AND_BOTTOM" '
               f'textFlow="BOTH_SIDES" lock="0" dropcapstyle="None" pageBreak="{"TABLE" if split else "NONE"}" '
               f'repeatHeader="{1 if head else 0}" rowCnt="{nrow}" colCnt="{ncol}" cellSpacing="0" borderFillIDRef="2" '
               'noAdjust="0">'
               f'<hp:sz width="{total}" widthRelTo="ABSOLUTE" height="{sum(row_h)}" heightRelTo="ABSOLUTE" protect="0"/>'
               f'<hp:pos treatAsChar="{as_char}" affectLSpacing="0" flowWithText="1" allowOverlap="0" holdAnchorAndSO="0" '
               'vertRelTo="PARA" horzRelTo="COLUMN" vertAlign="TOP" horzAlign="LEFT" vertOffset="0" horzOffset="0"/>'
               f'<hp:outMargin left="0" right="0" top="0" bottom="0"/><hp:inMargin left="510" right="510" top="{pad}" bottom="{pad}"/>'
               + xml_rows + '</hp:tbl>')
        self.last_table = dict(rows=row_h, split=split)
        self.table_log.append(dict(rows=list(row_h), split=split, widths=list(widths), size=size))
        after = getattr(self, 'table_after', 200)
        keep = getattr(self, 'table_keep', False)
        self.table_after, self.table_keep = 200, False
        return self._wrap_tbl(tbl, self.para('CENTER', 0, 0, 160, after, 100, keep))

    def spacer(self, prev):
        pid = self.para('LEFT', 0, 0, int(prev), 0, 100, False)
        cid = self.char(self.BODY, 1)
        el = etree.fromstring(f'<hp:p {NSDECL} id="2147483648" paraPrIDRef="{pid}" styleIDRef="0" pageBreak="0" '
                              f'columnBreak="0" merged="0"><hp:run charPrIDRef="{cid}"><hp:t/></hp:run></hp:p>')
        return self._add(el)

    # ------------------------------------------------------------ 사진 1~4장(가는 테두리, 사진마다 짧은 설명)
    def photo_row(self, items, max_h_mm=None):
        n = len(items)
        total = self.text_width
        widths = [total // n] * n
        widths[-1] += total - sum(widths)
        max_h_mm = max_h_mm or (50 if n >= 3 else (62 if n == 2 else 90))
        edge = ('SOLID', '0.12 mm', '#C9CCD2')
        pid_cap = self.style_ids('pcap')[0]
        pics = [self._pic_p(path, widths[c] / MM - 5, max_h_mm) for c, (path, cap) in enumerate(items)]
        if n == 1:          # 한 장이면 틀을 사진 폭에 맞춰 가운데에(넓은 빈 틀 안에 작은 사진이 떠 있지 않게)
            m = re.search(r':curSz width="(\d+)"', pics[0][0])
            if m:
                total = min(total, int(m.group(1)) + 540)
                widths = [total]
        h = max(ph for _, ph in pics) + 1300
        cells = ''
        for c, ((path, cap), (pp, _)) in enumerate(zip(items, pics)):
            bf = self.fill(None, edge if c == 0 else LINE_NONE, edge, edge, edge)
            ps = pp + (self._p_xml(pid_cap, self._runs(cap, 'pcap', color=GRAY)) if cap else '')
            cells += (f'<hp:tc name="" header="0" hasMargin="0" protect="0" editable="0" dirty="0" borderFillIDRef="{bf}">'
                      '<hp:subList id="" textDirection="HORIZONTAL" lineWrap="BREAK" vertAlign="TOP" linkListIDRef="0" '
                      f'linkListNextIDRef="0" textWidth="0" textHeight="0" hasTextRef="0" hasNumRef="0">{ps}</hp:subList>'
                      f'<hp:cellAddr colAddr="{c}" rowAddr="0"/><hp:cellSpan colSpan="1" rowSpan="1"/>'
                      f'<hp:cellSz width="{widths[c]}" height="{h}"/>'
                      '<hp:cellMargin left="250" right="250" top="250" bottom="150"/></hp:tc>')
        self._z += 1
        tbl = (f'<hp:tbl id="{self._new_id()}" zOrder="{self._z}" numberingType="TABLE" textWrap="TOP_AND_BOTTOM" '
               'textFlow="BOTH_SIDES" lock="0" dropcapstyle="None" pageBreak="NONE" repeatHeader="0" rowCnt="1" '
               f'colCnt="{n}" cellSpacing="0" borderFillIDRef="2" noAdjust="0">'
               f'<hp:sz width="{total}" widthRelTo="ABSOLUTE" height="{h}" heightRelTo="ABSOLUTE" protect="0"/>'
               '<hp:pos treatAsChar="1" affectLSpacing="0" flowWithText="1" allowOverlap="0" holdAnchorAndSO="0" '
               'vertRelTo="PARA" horzRelTo="PARA" vertAlign="TOP" horzAlign="LEFT" vertOffset="0" horzOffset="0"/>'
               '<hp:outMargin left="0" right="0" top="0" bottom="0"/><hp:inMargin left="0" right="0" top="0" bottom="0"/>'
               f'<hp:tr>{cells}</hp:tr></hp:tbl>')
        return self._wrap_tbl(tbl, self.para('CENTER', 0, 0, 260, 0, 100, True))


def crop_to(path, w_mm, h_mm, work_dir):
    """사진을 칸 비율에 맞게 가운데를 잘라 작업 폴더에 저장."""
    from PIL import Image, ImageOps
    im = ImageOps.exif_transpose(Image.open(path)).convert('RGB')
    r = w_mm / h_mm
    W, H = im.size
    if W / H > r:
        nw = int(H * r)
        box = ((W - nw) // 2, 0, (W - nw) // 2 + nw, H)
    else:
        nh = int(W / r)
        box = (0, (H - nh) // 2, W, (H - nh) // 2 + nh)
    os.makedirs(work_dir, exist_ok=True)
    out = os.path.join(work_dir, f'_crop_{os.path.splitext(os.path.basename(path))[0]}_{int(w_mm)}x{int(h_mm)}.jpg')
    im.crop(box).save(out, quality=90)
    return out


# ================================================================ 원고 읽기
def parse_cells(line):
    parts = [c.strip() for c in line.strip().strip('|').split('|')]
    out = []
    for c in parts:
        if c in ('<', '^'):
            continue
        m = re.match(r'^\{(?!\{)([^}]*)\}\s*(.*)$', c)
        spec = {}
        if m:
            for kv in m.group(1).split(','):
                kv = kv.strip()
                if not kv:
                    continue
                if '=' in kv:
                    k, v = kv.split('=', 1)
                    spec[k.strip()] = int(v) if v.strip().isdigit() else v.strip()
                else:
                    spec[kv] = True
            c = m.group(2)
        spec['t'] = c.replace('<br>', '\n')
        out.append(spec if len(spec) > 1 else c.replace('<br>', '\n'))
    return out


def opts(s):
    d = {}
    for part in s:
        part = part.strip()
        if not part:
            continue
        if '=' in part:
            k, v = part.split('=', 1)
            d[k.strip()] = v.strip()
        else:
            d[part] = True
    return d


class Manuscript:
    def __init__(self):
        self.config = {}
        self.front, self.body, self.appx = [], [], []
        self.sets = {}
        self.stats = []          # '@stats …' 줄(조판할 때 자료 파일에서 계산)
        self.stat_log = []
        self.stat_errors = []    # (줄, 오류) — 빌드는 계속하고 점검에서 '오류'로 알린다
        self.warnings = []       # 원고 문법 실수를 도구가 고친 기록(점검에서 '주의')
        self.base = '.'
        self.sources = []


def _front_matter(text):
    """맨 위 --- … --- 사이의 '키: 값' 줄(같은 키 여러 번 가능: info)."""
    cfg, info = {}, []
    lines = text.split('\n')
    if not lines or lines[0].strip() != '---':
        return cfg, text
    end = next((i for i in range(1, len(lines)) if lines[i].strip() == '---'), None)
    if end is None:
        return cfg, text
    for ln in lines[1:end]:
        if not ln.strip() or ln.strip().startswith('#'):
            continue
        if ':' not in ln:
            continue
        k, v = ln.split(':', 1)
        k, v = k.strip(), v.strip()
        if k == 'info':
            info.append(v)
        elif k == 'facts':
            cfg.setdefault('facts', []).append(v)
        else:
            cfg[k] = v
    if info:
        cfg['info'] = info
    return cfg, '\n'.join(lines[end + 1:])


KNOWN = {'ch', 'appx', 'refs', 'refh', 'sec', 'sub', 'ssub', 'table', 'tnote', 'fig', 'chart', 'photos', 'box', 'voice',
         'kpi', 'r', 'page', 'pagebreak', 'blank', 'ftitle', 'fsub', 'toc', 'lot'}
_STARTERS = {'@' + k for k in KNOWN} | {'@front', '@body', '@appendix', '@set', '@stats'}


def read_blocks(text, ms, start='body'):
    """원고 글 → 블록 목록(@front/@body/@appendix 로 나뉨). 블록 = (명령, 인자들[, 줄들]).

    가벼운 모델이 자주 내는 실수는 멈추지 않고 고친 뒤 ms.warnings 에 남긴다:
    @end 빠짐(다음 표시 앞에서 닫음), 모르는 표시(글 문단으로)."""
    target = {'front': ms.front, 'body': ms.body, 'appendix': ms.appx}
    cur = target[start]
    lines = text.replace('\r\n', '\n').split('\n')
    i = 0
    para = []

    def flush():
        if para:
            cur.append(('p', ' '.join(s.strip() for s in para)))
            para.clear()
    while i < len(lines):
        s = lines[i].strip()
        if s.startswith('//') or (s.startswith('<!--') and s.endswith('-->')):
            i += 1
            continue
        if not s:
            flush()
            i += 1
            continue
        if s.startswith('@'):
            flush()
            cmd, _, rest = s.partition(' ')
            cmd = cmd.lower()
            if cmd in ('@front', '@body', '@appendix'):
                cur = target[cmd[1:]]
                i += 1
                continue
            if cmd == '@set':
                k, _, v = rest.partition('=')
                ms.sets[k.strip()] = v.strip()
                i += 1
                continue
            if cmd == '@stats':
                ms.stats.append(rest.strip())
                i += 1
                continue
            args = [a.strip() for a in rest.split('|')] if rest else []
            if cmd == '@table':
                rows = []
                i += 1
                while i < len(lines) and lines[i].strip().startswith('|'):
                    rows.append(parse_cells(lines[i]))
                    i += 1
                cur.append(('table', args, rows))
                continue
            if cmd in ('@box', '@voice', '@kpi', '@chart'):
                body = []
                i += 1
                closed = False
                while i < len(lines):
                    t = lines[i].strip()
                    if t.lower() == '@end':
                        closed = True
                        break
                    if t.startswith('@') and t.split(' ', 1)[0].lower() in _STARTERS:
                        break
                    if t and not t.startswith('//'):
                        body.append(t)
                    i += 1
                if closed:
                    i += 1
                else:
                    ms.warnings.append(f'{cmd} {args[0] if args else ""} 에 @end 가 없어 '
                                       f'{"다음 표시 앞" if i < len(lines) else "원고 끝"}에서 닫았습니다(@end 를 넣어 주세요).')
                cur.append((cmd[1:], args, body))
                continue
            if cmd == '@end':
                ms.warnings.append('짝이 없는 @end 를 무시했습니다.')
                i += 1
                continue
            if cmd[1:] not in KNOWN:
                ms.warnings.append(f'모르는 표시 "{cmd}" 를 글 문단으로 넣었습니다(문법: hwpx-new report guide).')
                cur.append(('p', s[1:] if len(s) > 1 else s))
                i += 1
                continue
            cur.append((cmd[1:], args))
            i += 1
            continue
        if re.match(r'^(○|-|·|※|⇒) ', s):
            flush()
            cur.append(('k', s))
            i += 1
            continue
        para.append(s)
        i += 1
    flush()


def _flatten(d, prefix=''):
    out = {}
    for k, v in (d or {}).items():
        key = f'{prefix}{k}'
        if isinstance(v, dict):
            out.update(_flatten(v, key + '.'))
        else:
            out[key] = v if isinstance(v, str) else (json.dumps(v, ensure_ascii=False) if isinstance(v, (list, tuple)) else str(v))
    return out


def read_manuscript(path):
    """원고 경로(단일 .txt/.md, 또는 report.json·report.txt 가 든 폴더) → Manuscript."""
    ms = Manuscript()
    if os.path.isdir(path):
        for cand in ('report.json', 'report.txt', 'report.md', '원고.txt', '원고.md'):
            if os.path.exists(os.path.join(path, cand)):
                path = os.path.join(path, cand)
                break
        else:
            raise FileNotFoundError(f'원고 폴더에 report.json 또는 report.txt 가 없습니다: {path}')
    ms.base = os.path.dirname(os.path.abspath(path))
    if path.lower().endswith('.json'):
        cfg = json.load(open(path, encoding='utf-8-sig'))
        files = cfg.pop('files', {})
        ms.config = cfg
        if cfg.get('base'):
            ms.base = cfg['base'] if os.path.isabs(cfg['base']) else os.path.join(ms.base, cfg['base'])
        for part, key in (('front', 'front'), ('body', 'body'), ('appendix', 'appendix')):
            for f in files.get(key, []):
                fp = f if os.path.isabs(f) else os.path.join(ms.base, f)
                ms.sources.append(fp)
                read_blocks(open(fp, encoding='utf-8-sig').read(), ms, start=part)
    else:
        text = open(path, encoding='utf-8-sig').read()
        cfg, rest = _front_matter(text)
        ms.config = cfg
        ms.sources.append(path)
        read_blocks(rest, ms, start='body' if '@front' not in rest else 'front')
    facts = ms.config.get('facts') or []
    if isinstance(facts, str):
        facts = [facts]
    ms.facts = {}
    for f in facts:
        fp = f if os.path.isabs(f) else os.path.join(ms.base, f)
        d = json.load(open(fp, encoding='utf-8-sig'))
        if isinstance(d, dict) and set(d) >= {'T'} and isinstance(d['T'], dict):
            d = d['T']
        ms.facts.update(_flatten(d))
    if ms.stats:
        from .stats import run_line
        for line in ms.stats:
            try:
                toks, summary = run_line(line, ms.base)
            except Exception as e:  # noqa
                ms.stat_errors.append((line, str(e)))
                continue
            ms.facts.update(toks)
            ms.stat_log.append((line, summary, sorted(toks)))
    ms.facts.update(ms.sets)
    return ms


# ================================================================ 조립
class Builder:
    def __init__(self, ms, pages=None, splits=None, breaks=None, work_dir='.'):
        self.ms = ms
        cfg = ms.config
        self.cfg = cfg
        self.T = dict(ms.facts)
        self.pages = pages or {}
        self.splits = splits or {}
        self.breaks = set(breaks or [])
        self.work_dir = work_dir
        self.float_tables = []
        self.refs = {}
        self.caps = []
        self.missing = set()
        self.warn = set()
        self.title = _plain_title(cfg.get('title', '보고서'))
        self.org = cfg.get('org', '')
        self.header_left = cfg.get('header') or (f'{self.title}  ·  {self.org}' if self.org else self.title)
        for k, t in (('_body', 'pages.body'), ('_refs', 'pages.refs'), ('_total', 'pages.total')):
            if self.pages.get(k):
                self.T[t] = str(self.pages[k])
        self.accent = resolve_accent(cfg)
        self.fonts = resolve_fonts(cfg)
        self.chart_paths = {}
        self._number_captions()

    # ------------------------------------------------------------ 번호
    def _number_captions(self):
        ch = None
        cnt = {}
        na = {'표': 0, '그림': 0}
        any_ch = any(b[0] == 'ch' for b in self.ms.body)
        flat_cnt = {'표': 0, '그림': 0, '사진': 0}
        for part, blocks in (('body', self.ms.body), ('appx', self.ms.appx)):
            for b in blocks:
                if b[0] == 'ch':
                    ch = b[1][0]
                    cnt = {'표': 0, '그림': 0, '사진': 0}
                kind = {'table': '표', 'fig': '그림', 'chart': '그림', 'photos': '사진'}.get(b[0])
                if not kind or not (len(b) > 1 and b[1] and b[1][0]):
                    continue
                key = b[1][0]
                if part == 'appx':
                    if kind == '사진':
                        kind = '그림'
                    na[kind] += 1
                    lab = f'부록 {kind} {na[kind]}'
                    group = '부록' + kind
                elif any_ch and ch:
                    cnt[kind] += 1
                    lab = f'{kind} {ch}-{cnt[kind]}'
                    group = kind
                else:
                    flat_cnt[kind] += 1
                    lab = f'{kind} {flat_cnt[kind]}'
                    group = kind
                title = b[1][1] if len(b[1]) > 1 else ''
                if b[0] == 'fig':
                    title = b[1][3] if len(b[1]) > 3 else (b[1][1] if len(b[1]) > 1 else '')
                rk = f"{'그림' if kind == '그림' else kind}:{key}"
                if rk in self.refs:
                    raise ValueError(f'같은 이름(키)이 두 번 쓰였습니다: {rk}')
                self.refs[rk] = lab
                self.caps.append((group, lab, title, 'cap:' + key))

    # ------------------------------------------------------------ 글 치환
    def sub(self, text, polish=True):
        def tok(m):
            k = m.group(1).strip()
            if k not in self.T:
                self.missing.add(k)
                return '??' + k + '??'
            return str(self.T[k])
        text = re.sub(r'\{\{([^}]+)\}\}', tok, str(text))

        def ref(m):
            k = m.group(1) + ':' + m.group(2).strip()
            if k not in self.refs:
                self.missing.add(k)
                return '??' + k + '??'
            return self.refs[k].replace(' ', ' ')
        text = re.sub(r'\{(표|그림|사진):([^}]+)\}', ref, text)
        return textfix.polish(text) if polish else text

    def page_of(self, key):
        return self.pages.get(key, '00')

    # ------------------------------------------------------------ 블록 그리기
    def render(self, d, blocks, part):
        for bi, b in enumerate(blocks):
            kind = b[0]
            nb = blocks[bi + 1] if bi + 1 < len(blocks) else None
            nxt = nb[0] if nb else None
            if kind == 'ch':
                a = b[1] + [''] * (5 - len(b[1]))
                roman, title, lead, photo = a[0], self.sub(a[1]), self.sub(a[2]), a[3]
                summary = [self.sub(x.strip()) for x in a[4].split(';')] if a[4] else None
                photo = self._path(photo) if photo else None
                if photo and not os.path.exists(photo):
                    self.missing.add('사진 파일:' + a[3])
                    photo = None
                el = d.chapter(roman, title, lead, photo, summary)
                if part == 'body' and not getattr(self, '_numbered', False):
                    d.page_num(el, 'DIGIT', '', restart=True)
                    self._numbered = True
                d.header(el, self.header_left, f'{roman}. {title}', hid=self._hid())
            elif kind == 'appx':
                if not (len(b[1]) > 1 and b[1][1] == 'same'):
                    d.page()
                el = d.p(self.sub(b[1][0]), 'ftitle', color=d.C['dark'])
                if not getattr(self, '_appx_hdr', False):
                    d.header(el, self.header_left, '부록', hid=self._hid())
                    self._appx_hdr = True
            elif kind == 'refs':
                d.page()
                el = d.p('참고문헌', 'ftitle', color=d.C['dark'])
                d.header(el, self.header_left, '참고문헌', hid=self._hid())
            elif kind == 'refh':
                d.p(self.sub(b[1][0]), 'refh', color=d.C['accent'])
            elif kind == 'sec':
                num, title = (b[1] + [''])[:2] if len(b[1]) > 1 else ('', b[1][0])
                d.sec_heading(num, self.sub(title))
            elif kind == 'sub':
                num, title = (b[1] + [''])[:2] if len(b[1]) > 1 else ('', b[1][0])
                d.sub_heading(num, self.sub(title))
            elif kind == 'ssub':
                num, title = (b[1] + [''])[:2] if len(b[1]) > 1 else ('', b[1][0])
                d.p(f'{num} {self.sub(title)}'.strip(), 'ssub', color=d.C['dark'])
            elif kind == 'p':
                t = self.sub(b[1])
                short = d.wrap_lines(t, 'p', d.text_width) <= 2
                d.p(t, 'pk' if nxt in ('table', 'fig', 'chart', 'kpi') and short else 'p')
            elif kind == 'k':
                s = self.sub(b[1])
                lead = s[0]
                name = {'○': 'b1', '-': 'b2', '·': 'b3', '※': 'note', '⇒': 'res'}[lead]
                short = d.wrap_lines(s, name, d.text_width) <= 2
                if name in ('b1', 'res') and nxt in ('table', 'fig', 'chart', 'kpi') and short:
                    name += 'k'
                elif name == 'b1' and nb is not None and nb[0] == 'k' and nb[1].startswith('- ') and short:
                    name = 'b1k'
                d.p(s, name)
            elif kind == 'table':
                self._table(d, b[1], b[2], part, nxt)
            elif kind == 'tnote':
                d.p(self.sub(b[1][0] if b[1] else ''), 'tnote', color=GRAY)
            elif kind == 'fig':
                key, path = b[1][0], b[1][1]
                w = float(b[1][2]) if len(b[1]) > 2 and b[1][2] else 156
                cap = b[1][3] if len(b[1]) > 3 else ''
                full = self._path(path)
                if key in self.breaks:
                    d.page()
                if not os.path.exists(full):
                    self.missing.add('그림 파일:' + path)
                    d.tbox([('bxp', f'(그림 파일 없음: {path})')], tone='gray')
                else:
                    d.figure(full, width_mm=w, max_h_mm=float(b[1][4]) if len(b[1]) > 4 else 140,
                             chart=_looks_graphic(full))
                d.caption(self.refs['그림:' + key], self.sub(cap), 'fcap')
            elif kind == 'chart':
                key = b[1][0]
                cap = b[1][1] if len(b[1]) > 1 else ''
                o = opts(b[1][2:])
                path = self.chart(key, o, b[2])
                if key in self.breaks:
                    d.page()
                d.figure(path, width_mm=float(o.get('width_mm', 156)), max_h_mm=float(o.get('max_h_mm', 140)), chart=True)
                d.caption(self.refs['그림:' + key], self.sub(cap), 'fcap')
            elif kind == 'photos':
                key, cap = b[1][0], (b[1][1] if len(b[1]) > 1 else '')
                items, max_h = [], None
                for part_ in b[1][2:]:
                    if part_.startswith('h='):
                        max_h = float(part_[2:])
                        continue
                    pth, _, sc = part_.partition(';')
                    full = self._path(pth.strip())
                    if not os.path.exists(full):
                        self.missing.add('사진 파일:' + pth.strip())
                        continue
                    items.append((full, self.sub(sc.strip())))
                if key in self.breaks:
                    d.page()
                if items:
                    d.photo_row(items, max_h)
                else:
                    d.tbox([('bxp', '(사진 파일 없음: 원고의 사진 경로를 확인하세요)')], tone='gray')
                d.caption(self.refs.get('사진:' + key) or self.refs['그림:' + key], self.sub(cap), 'fcap')
            elif kind == 'box':
                title = self.sub(b[1][0]) if b[1] and b[1][0] else None
                tone = opts(b[1][1:]).get('tone', 'gray') if b[1] else 'gray'
                lines = []
                for s in b[2]:
                    s = self.sub(s)
                    if s.startswith(('○ ', '① ', '② ', '③ ', '④ ', '⑤ ', '⑥ ', '⑦ ', '⇒ ', '▸ ')):
                        lines.append(('bx1', s))
                    elif s.startswith(('- ', '· ')):
                        lines.append(('bx2', s))
                    else:
                        lines.append(('bxp', s))
                d.tbox(lines, title=title, tone=tone)
            elif kind == 'voice':
                items = []
                for s in b[2]:
                    q, _, by = s.partition('|')
                    items.append((self.sub(q.strip()), self.sub(by.strip())))
                d.voice(items, self.sub(b[1][0]) if b[1] else '목소리')
            elif kind == 'kpi':
                cols = int(opts(b[1]).get('cols', 4)) if b[1] else 4
                items = []
                for s in b[2]:
                    parts = [self.sub(x.strip()) for x in s.split('|')]
                    while len(parts) < 3:
                        parts.append('')
                    items.append(tuple(parts[:3]))
                d.kpi_grid(items, cols=cols)
            elif kind == 'r':
                d.p(self.sub(b[1][0] if len(b[1]) == 1 else ' | '.join(b[1]), polish=False), 'ref')
            elif kind in ('page', 'pagebreak'):
                d.page()
            elif kind == 'blank':
                d.p('', 'blank')
            elif kind in ('ftitle', 'fsub', 'toc', 'lot'):
                pass          # 앞부분에서 처리
            else:
                self.warn.add(f'모르는 표시 @{kind} 를 건너뛰었습니다.')

    def _hid(self):
        self._hid_n = getattr(self, '_hid_n', 2) + 1
        return self._hid_n

    def _path(self, p):
        return p if os.path.isabs(p) else os.path.join(self.ms.base, p)

    def chart(self, key, o, rows):
        from .charts import render
        spec = {k: v for k, v in o.items() if k not in ('width_mm', 'max_h_mm', 'data', 'x', 'y', 'col', 'by', 'bins',
                                                         'where', 'order', 'show_n')}
        if o.get('data'):
            spec['rows'] = self._data_rows(key, o)
        else:
            spec['rows'] = [[self.sub(x.strip(), polish=False) for x in r.split('|')] for r in rows]
        for k in ('label', 'note', 'legend', 'xlabel', 'ylabel', 'center', 'extra_label'):
            if isinstance(spec.get(k), str):
                spec[k] = self.sub(spec[k], polish=False)
        out = os.path.join(self.work_dir, 'figs', f'chart_{re.sub(r"[^0-9A-Za-z가-힣_-]", "_", key)}.png')
        if out not in self.chart_paths.values():
            render(spec, out, accent=self.accent)
        self.chart_paths[key] = out
        return out

    def _data_rows(self, key, o):
        """도표 자료를 자료 파일(CSV·XLSX)에서 바로 만든다 — 손으로 옮겨 적다 생기는 불일치를 막는다.

        x=열 | y=열[,열]          → 그대로(산점도 점, 꺾은선·막대 값)
        by=집단 | y=열[,열]        → 집단별 평균(묶음 막대: 경력별 사전·사후). order=초임,중견,원숙 / show_n=0
        col=열 | by=집단           → 집단별 비율(%)(누적 막대: 학기별 수준 분포)
        col=열 | bins=-0.5,0,0.5,1 → 도수분포(구간 끝 포함은 마지막 구간만)
        where=열=값               → 일부 행만"""
        from .stats import _isnum, column, filter_rows, freq, rd, read_table
        path = self._path(o['data'])
        if not os.path.exists(path):
            raise FileNotFoundError(f'도표 자료 파일이 없습니다: {o["data"]} (@chart {key})')
        head, rows = read_table(path)
        rows = filter_rows(head, rows, o.get('where'))

        def groups(col):
            g = [str(v).strip() for v in column(head, rows, col)]
            order = [x.strip() for x in str(o.get('order', '')).split(',') if x.strip()] or list(dict.fromkeys(x for x in g if x))
            return g, order
        if o.get('col') and o.get('by'):
            g, order = groups(o['by'])
            res = freq(column(head, rows, o['col']), g)['groups']
            cats = sorted({c for d in res.values() for c in d}, key=lambda v: (not _isnum(v), float(v) if _isnum(v) else v))
            return [[k] + [rd(res[k][c][1], 1) if c in res[k] else '0' for c in cats] for k in order if k in res]
        if o.get('col'):
            vals = [float(v) for v in column(head, rows, o['col']) if str(v).strip() and _isnum(v)]
            edges = [float(x) for x in str(o.get('bins', '')).split(',') if x.strip()]
            if len(edges) < 2:
                lo, hi = min(vals), max(vals)
                step = (hi - lo) / 5 or 1
                edges = [lo + step * i for i in range(6)]
            out = []
            for i in range(len(edges) - 1):
                a, b = edges[i], edges[i + 1]
                last = i == len(edges) - 2
                out.append([f'{_numtxt(a)}~{_numtxt(b)}', str(sum(1 for v in vals if a <= v < b or (last and v == b)))])
            return out
        ycols = [c.strip() for c in str(o.get('y', '')).split(',') if c.strip()]
        if not ycols:
            raise ValueError(f'@chart {key}: data= 를 쓰면 y=열(또는 col=열)이 필요합니다.')
        ys = [column(head, rows, c) for c in ycols]
        if o.get('by'):
            g, order = groups(o['by'])
            out = []
            for k in order:
                idx = [i for i, x in enumerate(g) if x == k]
                if not idx:
                    continue
                means = []
                for y in ys:
                    v = [float(y[i]) for i in idx if str(y[i]).strip() and _isnum(y[i])]
                    means.append(rd(sum(v) / len(v)) if v else '')
                show_n = str(o.get('show_n', '1')).lower() not in ('0', 'false', 'no')
                out.append([f'{k}(n={len(idx)})' if show_n else k] + means)
            return out
        xs = column(head, rows, o['x']) if o.get('x') else [str(i + 1) for i in range(len(rows))]
        return [[x] + [y[i] for y in ys] for i, x in enumerate(xs) if str(x).strip() and all(str(y[i]).strip() for y in ys)]

    def collect(self):
        """차례 항목: (단계, 글, 키, 찾을 글)."""
        toc = []
        for part, blocks in (('body', self.ms.body), ('appx', self.ms.appx)):
            for b in blocks:
                k = b[0]
                if k == 'ch':
                    t = self.sub(b[1][1], polish=False)
                    toc.append((0, f'{b[1][0]}. {t}', 'ch:' + b[1][0], f'{b[1][0]}{t}'))
                elif k == 'sec' and part == 'body':
                    num, title = (b[1] + [''])[:2] if len(b[1]) > 1 else ('', b[1][0])
                    t = self.sub(title, polish=False)
                    toc.append((1, f'{num}. {t}' if num else t, f'sec:{num}:{title}', f'{num}.{t}' if num else t))
                elif k == 'refs':
                    first = next((x for x in self.ms.body if x[0] in ('refh', 'r')), None)
                    needle = '참고문헌' + (self.sub(first[1][0], polish=False)[:14] if first else '')
                    toc.append((0, '참고문헌', 'refs', needle))
                elif k == 'appx':
                    t = self.sub(b[1][0], polish=False)
                    toc.append((1, t, 'appx:' + b[1][0], t))
        return toc

    def _table(self, d, args, rows, part, nxt=None):
        key = args[0] if args else ''
        cap = self.sub(args[1]) if len(args) > 1 else ''
        o = opts(args[2:])
        ncol = max(sum(int(c.get('cs', 1)) if isinstance(c, dict) else 1 for c in r) for r in rows) if rows else 1
        widths = [float(x) for x in o.get('widths', '').split(',')] if o.get('widths') else [1] * ncol
        aligns = o.get('aligns', '').split(',') if o.get('aligns') else None
        rows2 = []
        for r in rows:
            rr = []
            for c in r:
                if isinstance(c, dict):
                    c = dict(c)
                    c['t'] = self.sub(c['t'])
                    rr.append(c)
                else:
                    rr.append(self.sub(c))
            rows2.append(rr)
        num = ''
        if key:
            num = self.refs['표:' + key]
            if key in self.breaks:
                d.page()
            d.caption(num, cap)
        elif cap:
            d.p(cap, 'tcap', color=d.C['dark'])
        if o.get('unit'):
            d.p(f"({o['unit']})", 'tunit', color=GRAY)
        head = int(o.get('head', 1))
        d.table_after = 80 if nxt == 'tnote' else 420
        d.table_keep = nxt == 'tnote'
        try:
            d.table(widths, rows2, head=head, label_col=bool(o.get('label_col')), aligns=aligns,
                    size=o.get('size', 'n'), split=True if o.get('split') else None, grid=bool(o.get('grid')))
        except ValueError as e:
            n = len(widths)
            fixed = []
            for r in rows2:
                cells = [c['t'] if isinstance(c, dict) else c for c in r]
                cells = cells[:n - 1] + [' '.join(cells[n - 1:])] if len(cells) > n else cells + [''] * (n - len(cells))
                fixed.append(cells)
            self.warn.add(f'표 {num or key}: {e} → 합치기를 풀고 칸 수를 {n}개로 맞춰 조판했습니다(원고의 칸 수를 확인하세요).')
            d.table(widths, fixed, head=head, label_col=bool(o.get('label_col')), aligns=aligns,
                    size=o.get('size', 'n'), split=True if o.get('split') else None, grid=bool(o.get('grid')))
        lt = d.last_table
        if lt['split']:
            extra = sum(lt['rows'][:head]) * self.splits.get(key, 0) if key else 0
            d.spacer((300 if nxt == 'tnote' else 700) + extra)
            if key and head:
                cells = []
                for r in rows2[:head]:
                    for c in r:
                        t = c['t'] if isinstance(c, dict) else c
                        t = re.sub(r'\*\*|\^\^|\s+', '', t)
                        if t:
                            cells.append(t)
                self.float_tables.append(dict(key=key, head=cells, cap=f'{num}{cap}', height=sum(lt['rows']),
                                              allow=bool(o.get('split'))))

    # ------------------------------------------------------------ 표지·앞부분
    def cover(self, d):
        cfg = self.cfg
        el = _gap(d, 2)
        d.hide_page(el)
        total = d.text_width
        C = d.C
        if cfg.get('kicker'):
            d.p(self.sub(cfg['kicker'], polish=False), 'cv_k1', color=C['accent'])
        if cfg.get('kicker2'):
            d.p(self.sub(cfg['kicker2'], polish=False), 'cv_k2', color=GRAY)
        _gap(d, 30)
        for ln in [x.strip() for x in str(cfg.get('title', '보고서')).split('|')]:
            d.p(textfix.smart_quotes(self.sub(ln, polish=False)), 'cv_title', color=INK)
        if cfg.get('subtitle'):
            _gap(d, 8)
            d.p(textfix.smart_quotes(self.sub(cfg['subtitle'], polish=False)), 'cv_sub', color=C['accent'])
        _gap(d, 10)
        photo = cfg.get('photo')
        if photo and os.path.exists(self._path(photo)):
            h_mm = float(cfg.get('photo_height_mm', 84))
            crop = crop_to(self._path(photo), total / MM, h_mm, self.work_dir)
            pp, _ = d._pic_p(crop, total / MM, h_mm)
            bf = d.fill(None, LINE_NONE, LINE_NONE, LINE_NONE, ('SOLID', '1.2 mm', C['accent']))
            d._tbl('<hp:tr>' + d._cell(0, 0, total, int(h_mm * MM) + 200, bf, pp, va='TOP', margin=(0, 0, 0, 0)) + '</hp:tr>',
                   1, 1, total, int(h_mm * MM) + 200, d.para('CENTER', 0, 0, 0, 500, 100, False, True))
        else:
            bf = d.fill(C['accent'], LINE_NONE, LINE_NONE, LINE_NONE, LINE_NONE)
            ps = d._ps('blank', '')
            d._tbl('<hp:tr>' + d._cell(0, 0, total, 600, bf, ps, margin=(0, 0, 0, 0)) + '</hp:tr>', 1, 1, total, 600,
                   d.para('CENTER', 0, 0, 2000, 3000, 100, False, True))
        info = cfg.get('info') or []
        if isinstance(info, str):
            info = [info]
        if isinstance(info, dict):
            info = [f'{k} = {v}' for k, v in info.items()]
        rows = []
        for ln in info:
            k, _, v = ln.partition('=')
            rows.append([{'t': self.sub(k.strip(), polish=False), 'b': True}, {'t': self.sub(v.strip(), polish=False), 'a': 'l'}])
        if rows:
            d.table([2.0, 8.0], rows, head=0, label_col=True, size='s', pad=130)
        _gap(d, 34 if photo else 60)
        if cfg.get('date'):
            d.p(self.sub(cfg['date'], polish=False), 'cv_date', color=GRAY)
        if self.org:
            d.p(self.org, 'cv_org', color=C['dark'])
        if cfg.get('note'):
            d.p(self.sub(cfg['note'], polish=False), 'cv_note', color=LIGHT)

    def front(self, d):
        first = True
        blocks = self.ms.front
        has_toc = any(b[0] == 'toc' for b in blocks)
        has_lot = any(b[0] == 'lot' for b in blocks)
        for b in blocks:
            if b[0] == 'ftitle':
                d.page()
                el = d.p(self.sub(b[1][0]), 'ftitle', color=d.C['dark'])
                if first:
                    d.page_num(el, 'ROMAN_SMALL', '', restart=True)
                    first = False
            elif b[0] == 'fsub':
                d.p(self.sub(b[1][0]), 'fsub', color=d.C['accent'])
            elif b[0] == 'toc':
                first = self._toc(d, first)
            elif b[0] == 'lot':
                first = self._lot(d, first)
            else:
                self.render(d, [b], 'front')
        if not has_toc and str(self.cfg.get('toc', 'true')).lower() not in ('false', 'no', '0'):
            first = self._toc(d, first)
        if not has_lot and str(self.cfg.get('lot', 'true')).lower() not in ('false', 'no', '0') and self.caps:
            first = self._lot(d, first)

    def _toc(self, d, first):
        d.page()
        el = d.p('차  례', 'ftitle', color=d.C['dark'])
        if first:
            d.page_num(el, 'ROMAN_SMALL', '', restart=True)
        for lvl, text, key, _ in self.collect():
            if key.startswith('appx:') and not getattr(self, '_appx_line', False):
                d.toc_line('toc0', '부록', self.page_of('appx0'), color=INK)
                self._appx_line = True
            d.toc_line('toc0' if lvl == 0 else 'toc1', text, self.page_of(key), color=INK)
        return False

    def _lot(self, d, first):
        d.page()
        el = d.p('표·그림·사진 차례', 'ftitle', color=d.C['dark'])
        if first:
            d.page_num(el, 'ROMAN_SMALL', '', restart=True)
        for kind, title in (('표', '표 차례'), ('그림', '그림 차례'), ('사진', '사진 차례'), ('부록표', '부록 표 차례'),
                            ('부록그림', '부록 그림 차례')):
            items = [c for c in self.caps if c[0] == kind]
            if not items:
                continue
            d.p(title, 'loth', color=d.C['accent'])
            for _, num, cap, key in items:
                d.toc_line('lot', f'{num}  {self.sub(cap)}', self.page_of(key))
        return False

    def build(self, out_path, template=None):
        d = ReportComposer(template or self._template(), accent=self.accent, body_font=self.fonts[0], head_font=self.fonts[1])
        d.work_dir = self.work_dir
        d.section_start()
        first = d.out[-1]
        for ctrl in list(first.iter(HP + 'ctrl')):
            if ctrl.find(HP + 'pageNum') is not None:
                ctrl.getparent().remove(ctrl)
        if str(self.cfg.get('cover', 'true')).lower() not in ('false', 'no', '0'):
            self.cover(d)
        self.front(d)
        if not any(b[0] == 'ch' for b in self.ms.body):           # 장 표지 없이 쓰는 짧은 보고서: 본문 첫 블록에서 쪽 번호
            d.page()
            el = d.p('', 'blank')
            d.page_num(el, 'DIGIT', '', restart=True)
            d.header(el, self.header_left, self.title, hid=self._hid())
            self._numbered = True
        self.render(d, self.ms.body, 'body')
        self.render(d, self.ms.appx, 'appx')
        d.save(out_path, title=self.title)
        return d

    def _template(self):
        t = self.cfg.get('template')
        return self._path(t) if t else TEMPLATE


def _looks_graphic(path):
    """도표·도식처럼 색이 적은 PNG 인가(사진이면 JPEG 로 줄이고, 도표면 300dpi PNG 로 또렷하게)."""
    if os.path.splitext(path)[1].lower() != '.png':
        return False
    try:
        from PIL import Image
        im = Image.open(path).convert('RGB')
        im.thumbnail((400, 400))
        return im.getcolors(maxcolors=6000) is not None
    except Exception:  # noqa
        return False


def _plain_title(t):
    return ' '.join(x.strip() for x in str(t).split('|') if x.strip())


def _numtxt(v):
    return str(int(v)) if float(v).is_integer() else ('%.2f' % v).rstrip('0').rstrip('.')


def resolve_accent(cfg):
    a = (cfg.get('accent') or '').strip()
    if re.match(r'^#?[0-9A-Fa-f]{6}$', a):
        return '#' + a.lstrip('#').upper()
    return THEMES.get(str(cfg.get('theme', 'wine')).strip().lower(), THEMES['wine'])


def resolve_fonts(cfg):
    body, head = FONT_SETS.get(str(cfg.get('font', 'gothic')).strip().lower(), FONT_SETS['gothic'])
    return cfg.get('body_font') or body, cfg.get('head_font') or head


def _gap(d, pt):
    pid = d.para('LEFT', 0, 0, int(pt * 100), 0, 100, False)
    cid = d.char(d.BODY, 8)
    el = etree.fromstring(f'<hp:p {NSDECL} id="2147483648" paraPrIDRef="{pid}" styleIDRef="0" pageBreak="0" '
                          f'columnBreak="0" merged="0"><hp:run charPrIDRef="{cid}"><hp:t/></hp:run></hp:p>')
    return d._add(el)


# ================================================================ PDF 로 쪽 읽기 → 다시 조판
def _norm(s):
    return re.sub(r'\s+', '', s)


def read_pdf(pdf):
    import pymupdf
    doc = pymupdf.open(pdf)
    labels, texts = [], []
    for page in doc:
        h = page.rect.height
        lab = None
        for b in page.get_text('blocks'):
            if b[1] > h * 0.92:
                t = b[4].strip()
                if re.fullmatch(r'\d+', t) or re.fullmatch(r'[ivxlc]+', t):
                    lab = t
        labels.append(lab)
        texts.append(_norm(page.get_text('text')))
    return labels, texts


def map_pages(B, pdf):
    labels, texts = read_pdf(pdf)
    toc = B.collect()
    body0 = next((i for i, l in enumerate(labels) if l == '1'), None)
    if body0 is None:                       # 쪽 번호를 그리지 않는 렌더러: 첫 장 제목이 나오는 쪽을 1쪽으로
        first = next((t for lvl, _, k, t in toc if lvl == 0), None)
        body0 = next((i for i, t in enumerate(texts) if first and _norm(first) in t), 0)
        labels = [l if (l and not l.isdigit()) else (str(i - body0 + 1) if i >= body0 else None) for i, l in enumerate(labels)]
    pages = {}
    cur = body0
    for lvl, text, key, needle in toc:
        nd = _norm(needle)
        found = next((i for i in range(cur, len(texts)) if nd and nd in texts[i]), None)
        if found is None:
            pages[key] = '?'
            continue
        pages[key] = labels[found] or '?'
        cur = found
    appx_keys = [k for _, _, k, _ in toc if k.startswith('appx:')]
    pages['appx0'] = pages.get(appx_keys[0], '?') if appx_keys else '?'
    for kind, num, cap, key in B.caps:
        needle = _norm(num + B.sub(cap))[:24]
        found = next((i for i in range(body0, len(texts)) if needle in texts[i]), None)
        pages[key] = (labels[found] or '?') if found is not None else '?'
    ref_idx = next((i for i, (lvl, t, k, nd) in enumerate(toc) if k == 'refs'), None)
    ref0 = None
    if ref_idx is not None:
        nd = _norm(toc[ref_idx][3])
        ref0 = next((i for i in range(body0, len(texts)) if nd in texts[i]), None)
    appx0 = None
    if appx_keys:
        nd = _norm(next(t for _, _, k, t in toc if k == appx_keys[0]))
        appx0 = next((i for i in range(body0, len(texts)) if nd in texts[i]), None)
    end_body = ref0 if ref0 is not None else (appx0 if appx0 is not None else len(texts))
    body_pages = int(labels[end_body - 1]) if end_body and labels[end_body - 1] and labels[end_body - 1].isdigit() else 0
    refs_pages = ((appx0 if appx0 is not None else len(texts)) - ref0) if ref0 is not None else 0
    info = dict(total=len(labels), front=body0, body=body_pages, refs=refs_pages,
                appx=(len(labels) - appx0) if appx0 is not None else 0)
    pages['_body'], pages['_refs'], pages['_total'] = str(info['body']), str(info['refs']), str(info['total'])
    return pages, info


def _body_start(B, labels, texts):
    """본문 1쪽의 쪽 차례(앞부분 쪽은 표 차례 글 때문에 점검에서 뺀다)."""
    i = next((k for k, l in enumerate(labels) if l == '1'), None)
    if i is not None:
        return i
    first = next((t for lvl, _, k, t in B.collect() if lvl == 0), None)
    return next((k for k, t in enumerate(texts) if first and _norm(first) in t), 0)


def detect_splits(B, pdf):
    import pymupdf
    doc = pymupdf.open(pdf)
    labels, texts = read_pdf(pdf)
    b0 = _body_start(B, labels, texts)
    out = {}
    for pi, page in enumerate(doc):
        if pi < b0:
            continue
        top = []
        for b in page.get_text('dict')['blocks']:
            for ln in b.get('lines', []):
                if 50 < ln['bbox'][1] < 125:
                    top.append(''.join(s['text'] for s in ln['spans']))
        top = _norm(''.join(top))
        whole = _norm(page.get_text('text'))
        for ft in B.float_tables:
            if ft['head'] and all(c in top for c in ft['head']) and _norm(ft['cap']) not in whole:
                out[ft['key']] = out.get(ft['key'], 0) + 1
    return out


def detect_orphans(B, pdf):
    import pymupdf
    doc = pymupdf.open(pdf)
    labels, texts = read_pdf(pdf)
    b0 = _body_start(B, labels, texts)
    out = []
    for pi, page in enumerate(doc):
        if pi < b0:
            continue
        lines = []
        for b in page.get_text('dict')['blocks']:
            for ln in b.get('lines', []):
                lines.append((ln['bbox'][1], ln['bbox'][3], _norm(''.join(s['text'] for s in ln['spans']))))
        hl = []
        for dr in page.get_drawings():
            for it in dr['items']:
                if it[0] == 'l' and abs(it[1].y - it[2].y) < 0.5 and abs(it[2].x - it[1].x) > 30:
                    hl.append(it[1].y)
                elif it[0] == 're' and it[1].height < 2 and it[1].width > 30:
                    hl.append(it[1].y0)
        h = page.rect.height
        for ft in B.float_tables:
            cap = _norm(ft['cap'])[:14]
            for y0, y1, t in lines:
                if not t.startswith(cap) or ft['key'] in out:
                    continue
                below = sorted({round(y) for y in hl if y > y1 - 2})
                if not any(y1 - 2 < y < y1 + 40 for y in hl) or (y1 > h * 0.70 and len(below) <= 4):
                    out.append(ft['key'])
    return out


def page_gaps(pdf, threshold=0.12):
    """쪽마다 아래쪽 빈 비율(본문 영역 기준). 장 끝이 아닌 쪽의 큰 빈칸을 찾을 때 쓴다."""
    import pymupdf
    doc = pymupdf.open(pdf)
    H = doc[0].rect.height
    out = []
    for i, page in enumerate(doc):
        ys = []
        lab = None
        for b in page.get_text('blocks'):
            if b[1] > H * 0.92:
                t = b[4].strip()
                if re.fullmatch(r'\d+', t):
                    lab = t
                continue
            if b[1] < H * 0.06:
                continue
            ys.append(b[3])
        for dr in page.get_drawings():
            r = dr['rect']
            if r.y0 > H * 0.92 or r.y1 < H * 0.06:
                continue
            ys.append(r.y1)
        for img in page.get_image_info():
            ys.append(img['bbox'][3])
        bottom = max(ys) if ys else 0
        body_bottom = H * 0.905
        gap = max(0.0, (body_bottom - bottom) / (body_bottom - H * 0.07))
        out.append({'index': i + 1, 'label': lab, 'gap': round(gap, 3)})
    return out


def build_report(manuscript, out_dir, name=None, engine=None, max_passes=12, progress=None, keep_work=True):
    """원고 → HWPX + PDF. 반환 dict: hwpx, pdf, engine, info(쪽 수), passes, missing, issues(점검), work."""
    from .pdf import convert
    ms = read_manuscript(manuscript)
    title = _plain_title(ms.config.get('title', '보고서'))
    name = name or ms.config.get('name') or re.sub(r'\s+', ' ', re.sub(r'[\\/:*?"<>|‘’“”\']', '', title)).strip()[:80] or 'report'
    os.makedirs(out_dir, exist_ok=True)
    work = os.path.join(out_dir, '_작업_' + name)
    os.makedirs(work, exist_ok=True)
    state_p = os.path.join(work, 'layout_state.json')
    state = json.load(open(state_p, encoding='utf-8')) if os.path.exists(state_p) else {}
    pages, splits, breaks = state.get('pages', {}), state.get('splits', {}), state.get('breaks', [])
    log, final, used = [], None, None
    missing = set()
    B = None
    info = {}
    for k in range(1, max_passes + 1):
        B = Builder(ms, pages=pages, splits=splits, breaks=breaks, work_dir=work)
        h = os.path.join(work, f'pass{k}.hwpx')
        p = os.path.join(work, f'pass{k}.pdf')
        B.build(h)
        missing = {m for m in B.missing if not m.startswith('pages.')}
        if progress:
            progress(k, max_passes, f'{k}차 조판 → PDF')
        eng, elog = convert(h, p, prefer=engine)
        if not eng:
            log.append('PDF 변환 실패: ' + '; '.join(elog))
            final = (h, None)
            break
        used = eng
        new_pages, info = map_pages(B, p)
        found = detect_splits(B, p)
        grow = {key: c for key, c in found.items() if splits.get(key, 0) < c}
        orphans = [x for x in detect_orphans(B, p) if x not in breaks]
        hmap = {ft['key']: ft.get('height', 0) for ft in B.float_tables}
        allow = {ft['key'] for ft in B.float_tables if ft.get('allow')}
        short = [x for x in found if x not in breaks and x not in orphans and x not in allow and 0 < hmap.get(x, 0) < 0.65 * 69000]
        order = {ft['key']: i for i, ft in enumerate(B.float_tables)}
        cand = sorted(set(orphans) | set(short), key=lambda x: order.get(x, 10 ** 6))[:1]
        if cand:
            breaks = breaks + cand
        changed = {kk for kk, v in new_pages.items() if pages.get(kk) != v}
        log.append(f'{k}차: {eng}, 전체 {info.get("total")}쪽(본문 {info.get("body")}쪽), 쪽 번호 바뀜 {len(changed)}'
                   + (f', 쪽을 넘긴 표 {found}' if found else '') + (f', 새 쪽으로 {cand}' if cand else ''))
        splits.update(grow)
        pages = new_pages
        json.dump({'pages': pages, 'splits': splits, 'breaks': breaks}, open(state_p, 'w', encoding='utf-8'),
                  ensure_ascii=False, indent=1)
        final = (h, p)
        if not changed and not grow and not cand:
            break
        if eng == 'html' and k >= 3:      # 근사 렌더러는 3번이면 충분
            break
    out_h = os.path.join(out_dir, name + '.hwpx')
    out_p = os.path.join(out_dir, name + '.pdf') if final and final[1] else None
    saved_h, saved_p = _safe_copy(final[0], out_h), (_safe_copy(final[1], out_p) if out_p else None)
    res = {'hwpx': saved_h, 'pdf': saved_p, 'engine': used, 'info': info, 'log': log, 'missing': sorted(missing),
           'work': work, 'builder': B}
    try:
        from .report_check import check
        res['issues'] = check(ms, saved_p, builder=B)
    except Exception as e:  # noqa
        res['issues'] = [('주의', f'점검을 끝내지 못했습니다: {e}')]
    try:                                    # 한글이 없어도 '열리지 않을 만한' 구조 결함을 잡는다
        from .validate import validate
        res['issues'] = [('오류', f'HWPX 구조: {m}') for m in validate(saved_h)[:10]] + res['issues']
    except Exception as e:  # noqa
        res['issues'].append(('주의', f'HWPX 구조 검사를 하지 못함: {e}'))
    if not keep_work:
        shutil.rmtree(work, ignore_errors=True)
    return res


def _safe_copy(src, dst):
    """결과 파일이 한글에 열려 있어 덮어쓸 수 없으면 새 이름(_2, _3 …)으로 저장한다."""
    base, ext = os.path.splitext(dst)
    cand = dst
    for i in range(1, 30):
        try:
            shutil.copyfile(src, cand)
            return cand
        except PermissionError:
            cand = f'{base}_{i + 1}{ext}'
    raise PermissionError(f'저장할 수 없습니다(파일이 열려 있음): {dst}')


def summarize(res):
    lines = []
    lines.append(f"HWPX: {res['hwpx']}")
    lines.append(f"PDF: {res['pdf'] or '(만들지 못함)'}" + (f" — {res['engine']}" if res.get('engine') else ''))
    if res['engine'] == 'html':
        lines.append('※ 한글이 없어 내장 렌더러로 근사 PDF 를 만들었습니다. 차례 쪽수는 한글에서 열어 한 번 확인하세요.')
    i = res.get('info') or {}
    if i:
        lines.append(f"쪽: 전체 {i.get('total')} = 앞부분 {i.get('front')} + 본문 {i.get('body')} + 참고문헌 {i.get('refs')} + 부록 {i.get('appx')}")
    for x in res.get('log', []):
        lines.append('  ' + x)
    if res.get('missing'):
        lines.append('⚠ 풀지 못한 토큰·참조: ' + ', '.join(res['missing']))
    iss = res.get('issues') or []
    errs = [x for x in iss if x[0] == '오류']
    lines.append(f"점검: 오류 {len(errs)}, 주의 {sum(1 for x in iss if x[0] == '주의')}")
    for lv, msg in iss[:60]:
        lines.append(f'  [{lv}] {msg}')
    return '\n'.join(lines)
