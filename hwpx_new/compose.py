# -*- coding: utf-8 -*-
"""정돈 조판(compose): 서식의 표지·대제목 같은 디자인 요소는 그대로 쓰고, 본문은 하나의 일관된 체계로 새로 짠다.

`build`(서식 재현)는 서식 원본의 문단·글자 모양을 블록마다 복제한다. 서식이 산만하면 결과도 산만해진다.
`compose` 는 계획서·안내문을 **처음부터 구조화**할 때 쓴다.

  Ⅰ(대제목) → ■ 소제목(HY헤드라인M 15pt) → ❍ 항목(휴먼명조 14pt) → - 세부(13pt) → · 보충(12pt) / ※ 참고(12pt)

- 단계마다 글꼴·크기·굵기·들여쓰기·줄간격을 하나로 고정한다(내어쓰기로 둘째 줄이 기호 뒤 글자에 맞음).
- 글자색은 검정. 꼭 지켜야 할 기한·필수 사항만 `^^강조^^`(진한 빨강), 낱말 굵게는 `**굵게**`.
- 표는 머리행 연한 남색, 왼쪽 항목 열 연회색, 위·아래 바깥선 굵게, 좌우 바깥선 없음으로 통일한다.
- 서식 블록을 복제할 때(표지, 양식)는 `recolor_black()`·`refill()` 로 원본의 파랑 글씨·분홍 칸 등을 문서 색 체계로 바꾼다.

한글(실측)에서 확인한 사실
- 문단 속성 breakNonLatinWord 는 이름과 반대로 동작한다: KEEP_WORD = 한글을 **글자** 단위로 줄나눔, BREAK_WORD = **어절** 단위.
  본문은 글자 단위(양쪽 정렬이 고르게), 제목·표 칸은 어절 단위(낱말이 중간에서 끊기지 않게)로 둔다.
- 표 칸의 높이는 한글이 내용에 맞춰 늘린다. 행 높이는 '한 줄' 높이(또는 기재 칸이면 min_row)만 주면 된다.
  글자 수로 줄 수를 넉넉히 어림하면 오히려 칸이 헐렁하게 커진다.
- 쪽 번호 다시 시작(newNum)이 든 서식 블록을 여러 번 복제하면 쪽 번호가 매번 1로 돌아간다(복제 시 첫 번째만 남긴다).
"""
from __future__ import annotations

import copy
import os
import re

from lxml import etree

from .images import MM, fit_size, pic_run, prepare_image, register_images, next_image_index
from .package import Package

HP_NS = 'http://www.hancom.co.kr/hwpml/2011/paragraph'
HH_NS = 'http://www.hancom.co.kr/hwpml/2011/head'
HC_NS = 'http://www.hancom.co.kr/hwpml/2011/core'
HP = '{%s}' % HP_NS
HH = '{%s}' % HH_NS
HC = '{%s}' % HC_NS
NSDECL = f'xmlns:hp="{HP_NS}" xmlns:hh="{HH_NS}" xmlns:hc="{HC_NS}"'
LANGS = ('HANGUL', 'LATIN', 'HANJA', 'JAPANESE', 'OTHER', 'SYMBOL', 'USER')

ACCENT = '#C00000'      # 꼭 지켜야 할 기한·필수 사항
HEAD_FILL = '#DCE6F2'   # 표 머리행
LABEL_FILL = '#F2F2F2'  # 표 왼쪽 항목 열
BOX_FILL = '#F4F7FB'    # 안내 박스
NAVY = '#1F3864'
LINE_THIN = ('SOLID', '0.12 mm', '#8C8C8C')
LINE_THICK = ('SOLID', '0.4 mm', NAVY)
LINE_HEAD = ('SOLID', '0.25 mm', NAVY)
LINE_NONE = ('NONE', '0.1 mm', '#000000')

BODY_FONT = '휴먼명조'
HEAD_FONT = 'HY헤드라인M'


def esc(s):
    return s.replace('&', '&amp;').replace('<', '&lt;').replace('>', '&gt;')


def dwidth(s):
    return sum(1.0 if ord(c) > 0x2E7F else 0.55 for c in s)


class Composer:
    # 문단 체계: 이름 → (글꼴, 크기pt, 굵게, 정렬, 왼쪽여백, 내어쓰기, 앞간격, 뒤간격, 줄간격%, 다음 문단과 함께)
    STYLES = {
        'h2': (HEAD_FONT, 15, False, 'JUSTIFY', 0, 2300, 900, 300, 160, True),         # ■
        'b1': (BODY_FONT, 14, False, 'JUSTIFY', 1200, 2100, 300, 0, 160, False),       # ❍
        'b1h': (BODY_FONT, 14, False, 'JUSTIFY', 1200, 2100, 300, 0, 160, True),       # ❍ 묶음 제목(다음 줄과 함께)
        'b2': (BODY_FONT, 13, False, 'JUSTIFY', 3300, 1300, 100, 0, 160, False),       # -
        'b3': (BODY_FONT, 12, False, 'JUSTIFY', 4600, 1300, 0, 0, 155, False),         # ·
        'note': (BODY_FONT, 12, False, 'JUSTIFY', 3300, 1800, 100, 0, 150, False),     # ※ (- 단계)
        'note1': (BODY_FONT, 12, False, 'JUSTIFY', 1200, 1800, 100, 0, 150, False),    # ※ (❍ 단계)
        'p': (BODY_FONT, 14, False, 'JUSTIFY', 0, 0, 200, 0, 160, False),
        'pc': (BODY_FONT, 14, False, 'CENTER', 0, 0, 200, 0, 160, False),
        'blank': (BODY_FONT, 8, False, 'JUSTIFY', 0, 0, 0, 0, 100, False),
        'tcap': (BODY_FONT, 11, False, 'RIGHT', 0, 0, 100, 100, 130, True),            # 표 위 단위 표시
        'cap': (BODY_FONT, 11, False, 'CENTER', 0, 0, 100, 200, 130, False),           # 그림 설명
        'boxt': (HEAD_FONT, 13, False, 'LEFT', 0, 0, 0, 200, 150, False),              # 박스 제목
        'bx1': (BODY_FONT, 13, False, 'JUSTIFY', 300, 1950, 100, 0, 155, False),       # 박스 안 ❍
        'bx2': (BODY_FONT, 12, False, 'JUSTIFY', 2250, 1200, 0, 0, 150, False),        # 박스 안 -
        'cell': (BODY_FONT, 12, False, 'CENTER', 0, 0, 0, 0, 135, False),
        'cellL': (BODY_FONT, 12, False, 'LEFT', 0, 0, 0, 0, 135, False),
        'cellLh': (BODY_FONT, 12, False, 'LEFT', 0, 1200, 0, 0, 135, False),           # 칸 안 '- ' 내어쓰기
        'cellS': (BODY_FONT, 11, False, 'CENTER', 0, 0, 0, 0, 130, False),
        'cellSL': (BODY_FONT, 11, False, 'LEFT', 0, 1100, 0, 0, 130, False),
        'title': (HEAD_FONT, 22, False, 'CENTER', 0, 0, 600, 900, 140, True),          # 서식·계약서 제목
        'title2': (HEAD_FONT, 16, False, 'CENTER', 0, 0, 0, 400, 140, True),           # 부제
        'label': (BODY_FONT, 11, True, 'LEFT', 0, 0, 0, 200, 130, True),               # [서식1]
        'clause': (BODY_FONT, 13, False, 'JUSTIFY', 0, 0, 500, 0, 160, False),         # 제1조(…)
        'clause2': (BODY_FONT, 13, False, 'JUSTIFY', 650, 1300, 100, 0, 160, False),   # ② …
        'clause3': (BODY_FONT, 13, False, 'JUSTIFY', 1950, 1300, 0, 0, 160, False),    # 1. …
        'sign': (BODY_FONT, 14, False, 'CENTER', 0, 0, 300, 300, 160, False),
        'signR': (BODY_FONT, 14, False, 'RIGHT', 0, 0, 200, 200, 160, False),
        'body': (BODY_FONT, 14, False, 'JUSTIFY', 0, 0, 200, 200, 170, False),        # 서식 안내 문장
        'lineq': (BODY_FONT, 14, False, 'JUSTIFY', 1200, 0, 0, 0, 220, False),        # 빈칸 기재 줄
    }
    # 어절 단위로 줄을 나눌 문단(제목·표 칸 등). 나머지 본문은 글자 단위(양쪽 정렬이 고르게).
    WORD_WRAP = {'h2', 'boxt', 'tcap', 'cap', 'cell', 'cellL', 'cellLh', 'cellS', 'cellSL', 'pc', 'title', 'title2',
                 'label', 'sign', 'signR'}

    def __init__(self, template, heading_block=None):
        """template: 서식 HWPX. heading_block: 대제목(Ⅰ)으로 복제할 서식 블록 번호(없으면 자체 디자인으로 그림)."""
        self.pkg = Package(template)
        self.head = etree.fromstring(self.pkg.files['Contents/header.xml'])
        self.sec_name = self.pkg.section_names()[0]
        self.sec = etree.fromstring(self.pkg.files[self.sec_name])
        self.tops = [e for e in self.sec if e.tag == HP + 'p']
        self.heading_block = heading_block
        self.out = []
        self._char_cache = {}
        self._para_cache = {}
        self._fill_cache = {}
        self._tid = 1900000000
        self._z = 100
        self._next_page = False
        self._font_idx = {ff.get('lang'): {f.get('face'): f.get('id') for f in ff.findall(HH + 'font')}
                          for ff in self.head.iter(HH + 'fontface')}
        c0 = next(self.head.iter(HH + 'charPr'))
        self._char_bf = c0.get('borderFillIDRef', '2')
        p0 = next(self.head.iter(HH + 'paraPr'))
        b0 = p0.find(HH + 'border')
        self._para_bf = b0.get('borderFillIDRef', '2') if b0 is not None else '2'
        self._images = []
        self._img_idx = next_image_index(self.pkg)
        self._uid = 0
        self.text_width = self._text_width()

    # ------------------------------------------------------------ 쪽 정보
    def _text_width(self):
        pp = self.sec.find('.//' + HP + 'pagePr')
        if pp is None:
            return 48190
        mg = pp.find(HP + 'margin')
        w = int(pp.get('width', '59528'))
        if mg is not None:
            w -= int(mg.get('left', '0')) + int(mg.get('right', '0')) + int(mg.get('gutter', '0'))
        return w

    # ------------------------------------------------------------ header: 글꼴·글자·문단·테두리
    def font_ref(self, face):
        refs = {}
        for lang in LANGS:
            m = self._font_idx.setdefault(lang, {})
            if face not in m:
                ff = next((f for f in self.head.iter(HH + 'fontface') if f.get('lang') == lang), None)
                if ff is None:
                    refs[lang] = '0'
                    continue
                src = next((f for f in self.head.iter(HH + 'font') if f.get('face') == face), None)
                if src is None:            # 서식에 없는 글꼴: 같은 언어의 첫 글꼴 정의를 본떠 새로 등록
                    src = ff.find(HH + 'font')
                new = copy.deepcopy(src)
                new.set('face', face)
                new.set('id', str(len(ff.findall(HH + 'font'))))
                ff.append(new)
                ff.set('fontCnt', str(len(ff.findall(HH + 'font'))))
                m[face] = new.get('id')
            refs[lang] = m[face]
        return refs

    def _box(self, tag):
        return next(self.head.iter(HH + tag))

    @staticmethod
    def _next_id(box, tag):
        return str(max(int(c.get('id')) for c in box.findall(HH + tag)) + 1)

    def char(self, face, size, bold=False, color='#000000', underline=False):
        key = (face, size, bold, color, underline)
        if key in self._char_cache:
            return self._char_cache[key]
        box = self._box('charProperties')
        nid = self._next_id(box, 'charPr')
        r = self.font_ref(face)
        fr = ' '.join(f'{lang.lower()}="{r[lang]}"' for lang in LANGS)
        xml = (f'<hh:charPr {NSDECL} id="{nid}" height="{int(size * 100)}" textColor="{color}" shadeColor="none" '
               f'useFontSpace="0" useKerning="0" symMark="NONE" borderFillIDRef="{self._char_bf}"><hh:fontRef {fr}/>'
               '<hh:ratio hangul="100" latin="100" hanja="100" japanese="100" other="100" symbol="100" user="100"/>'
               '<hh:spacing hangul="0" latin="0" hanja="0" japanese="0" other="0" symbol="0" user="0"/>'
               '<hh:relSz hangul="100" latin="100" hanja="100" japanese="100" other="100" symbol="100" user="100"/>'
               '<hh:offset hangul="0" latin="0" hanja="0" japanese="0" other="0" symbol="0" user="0"/>'
               + ('<hh:bold/>' if bold else '') +
               f'<hh:underline type="{"BOTTOM" if underline else "NONE"}" shape="SOLID" color="{color}"/>'
               '<hh:strikeout shape="NONE" color="#000000"/><hh:outline type="NONE"/>'
               '<hh:shadow type="NONE" color="#C0C0C0" offsetX="10" offsetY="10"/></hh:charPr>')
        box.append(etree.fromstring(xml))
        box.set('itemCnt', str(len(box.findall(HH + 'charPr'))))
        self._char_cache[key] = nid
        return nid

    def para(self, align='JUSTIFY', left=0, hang=0, prev=0, nxt=0, line=160, keep_next=False, word_wrap=False):
        key = (align, left, hang, prev, nxt, line, keep_next, word_wrap)
        if key in self._para_cache:
            return self._para_cache[key]
        box = self._box('paraProperties')
        nid = self._next_id(box, 'paraPr')

        def margin(f):
            return (f'<hh:margin><hc:intent value="{-hang * f}" unit="HWPUNIT"/><hc:left value="{left * f}" unit="HWPUNIT"/>'
                    f'<hc:right value="0" unit="HWPUNIT"/><hc:prev value="{prev * f}" unit="HWPUNIT"/>'
                    f'<hc:next value="{nxt * f}" unit="HWPUNIT"/></hh:margin>'
                    f'<hh:lineSpacing type="PERCENT" value="{line}" unit="HWPUNIT"/>')
        # 한글 실측: KEEP_WORD = 글자 단위, BREAK_WORD = 어절 단위 줄나눔
        brk = 'BREAK_WORD' if word_wrap else 'KEEP_WORD'
        xml = (f'<hh:paraPr {NSDECL} id="{nid}" tabPrIDRef="0" condense="0" fontLineHeight="0" snapToGrid="0" '
               f'suppressLineNumbers="0" checked="0"><hh:align horizontal="{align}" vertical="BASELINE"/>'
               '<hh:heading type="NONE" idRef="0" level="0"/>'
               f'<hh:breakSetting breakLatinWord="KEEP_WORD" breakNonLatinWord="{brk}" widowOrphan="1" '
               f'keepWithNext="{1 if keep_next else 0}" keepLines="0" pageBreakBefore="0" lineWrap="BREAK"/>'
               '<hh:autoSpacing eAsianEng="0" eAsianNum="0"/>'
               '<hp:switch><hp:case hp:required-namespace="http://www.hancom.co.kr/hwpml/2016/HwpUnitChar">'
               + margin(1) + '</hp:case><hp:default>' + margin(2) + '</hp:default></hp:switch>'
               f'<hh:border borderFillIDRef="{self._para_bf}" offsetLeft="0" offsetRight="0" offsetTop="0" offsetBottom="0" '
               'connect="0" ignoreMargin="0"/></hh:paraPr>')
        box.append(etree.fromstring(xml))
        box.set('itemCnt', str(len(box.findall(HH + 'paraPr'))))
        self._para_cache[key] = nid
        return nid

    def fill(self, fill=None, left=LINE_THIN, right=LINE_THIN, top=LINE_THIN, bottom=LINE_THIN):
        key = (fill, left, right, top, bottom)
        if key in self._fill_cache:
            return self._fill_cache[key]
        box = self._box('borderFills')
        nid = self._next_id(box, 'borderFill')

        def side(tag, s):
            return f'<hh:{tag} type="{s[0]}" width="{s[1]}" color="{s[2]}"/>'
        brush = (f'<hc:fillBrush><hc:winBrush faceColor="{fill}" hatchColor="#999999" alpha="0"/></hc:fillBrush>'
                 if fill else '')
        xml = (f'<hh:borderFill {NSDECL} id="{nid}" threeD="0" shadow="0" centerLine="NONE" breakCellSeparateLine="0">'
               '<hh:slash type="NONE" Crooked="0" isCounter="0"/><hh:backSlash type="NONE" Crooked="0" isCounter="0"/>'
               + side('leftBorder', left) + side('rightBorder', right) + side('topBorder', top) + side('bottomBorder', bottom)
               + '<hh:diagonal type="SOLID" width="0.1 mm" color="#000000"/>' + brush + '</hh:borderFill>')
        box.append(etree.fromstring(xml))
        box.set('itemCnt', str(len(box.findall(HH + 'borderFill'))))
        self._fill_cache[key] = nid
        return nid

    def style_ids(self, name, size=None):
        face, sz, b, align, left, hang, prev, nxt, line, kn = self.STYLES[name]
        cid = self.char(face, size or sz, b)
        pid = self.para(align, left, hang, prev, nxt, line, kn, word_wrap=name in self.WORD_WRAP)
        return pid, cid

    # ------------------------------------------------------------ 문단
    def _runs(self, text, name, size=None, bold=None, color='#000000'):
        """**굵게**, ^^강조색^^ 표시를 글자 덩어리로."""
        face, sz, b = self.STYLES[name][:3]
        b = b if bold is None else bold
        out = []
        for part in re.split(r'(\*\*.+?\*\*|\^\^.+?\^\^)', text):
            if not part:
                continue
            if part.startswith('**') and part.endswith('**'):
                out.append((part[2:-2], self.char(face, size or sz, True, color)))
            elif part.startswith('^^') and part.endswith('^^'):
                out.append((part[2:-2], self.char(face, size or sz, True, ACCENT)))
            else:
                out.append((part, self.char(face, size or sz, b, color)))
        return out

    LEAD = re.compile(r'^(■|❍|※|·|-|\d{1,2}\.|[가-하]\.|[①-⑳]) ')

    def _p_xml(self, pid, runs, hanging=False):
        """hanging: 내어쓰기 문단이면 줄머리 기호 뒤 빈칸을 묶음 빈칸으로(표 머리칸 등 좁은 칸에는 쓰지 않음 —
        '③ 크로스홉' 같은 글이 한 낱말로 묶여 글자 중간에서 끊긴다)."""
        xml = f'<hp:p id="2147483648" paraPrIDRef="{pid}" styleIDRef="0" pageBreak="0" columnBreak="0" merged="0">'
        for i, (t, cid) in enumerate(runs):
            m = self.LEAD.match(t) if (i == 0 and hanging) else None
            if m:
                # 한글 실측: 양쪽 정렬은 보통 빈칸을 늘려 기호 뒤 글자가 둘째 줄(내어쓰기)보다 1~2pt 밀린다.
                # 묶음 빈칸(nbSpace)은 늘어나지 않고 폭도 보통 빈칸과 같아 첫 줄과 둘째 줄 글자가 정확히 맞는다.
                body = esc(m.group(1)) + '<hp:nbSpace/>' + esc(t[m.end():])
            else:
                body = esc(t)
            xml += f'<hp:run charPrIDRef="{cid}"><hp:t>{body}</hp:t></hp:run>'
        return xml + '</hp:p>'

    def make_p(self, text, name, size=None, para_id=None, color='#000000'):
        pid = para_id or self.style_ids(name, size=size)[0]
        runs = self._runs(text, name, size, color=color) if text else [('', self.char(*self.STYLES[name][:2]))]
        return etree.fromstring(self._p_xml(pid, runs, self.STYLES[name][5] > 0).replace('<hp:p ', f'<hp:p {NSDECL} ', 1))

    def _add(self, el):
        if self._next_page:
            el.set('pageBreak', '1')
            self._next_page = False
        self.out.append(el)
        return el

    def page(self):
        """다음 블록을 새 쪽에서 시작."""
        self._next_page = True

    def p(self, text, name='p', size=None, color='#000000'):
        """문단 하나. color 는 제목·표어처럼 디자인상 꼭 필요한 곳에만(본문은 검정)."""
        return self._add(self.make_p(text, name, size, color=color))

    def h2(self, text):
        return self.p('■ ' + text, 'h2')

    def b1(self, text):
        return self.p('❍ ' + text, 'b1')

    def b1h(self, text):
        """❍ 묶음 제목(굵게, 다음 줄과 같은 쪽에)."""
        return self.p('❍ **' + text + '**', 'b1h')

    def b2(self, text):
        return self.p('- ' + text, 'b2')

    def b3(self, text):
        return self.p('· ' + text, 'b3')

    def note(self, text, level=2):
        return self.p('※ ' + text, 'note' if level == 2 else 'note1')

    def blank(self):
        return self.p('', 'blank')

    # ------------------------------------------------------------ 서식 블록 복제
    @staticmethod
    def _strip_ls(el):
        for ls in list(el.iter(HP + 'linesegarray')):
            ls.getparent().remove(ls)

    @staticmethod
    def _ptext(p):
        return ''.join(t.text or '' for r in p.findall(HP + 'run') for t in r.findall(HP + 't'))

    @staticmethod
    def set_text(p, new):
        """문단 글을 new 로(글이 있는 첫 덩어리의 모양을 쓰고 나머지 덩어리는 비움)."""
        ts = [t for r in p.findall(HP + 'run') for t in r.findall(HP + 't')]
        main = next((t for t in ts if (t.text or '').strip()), ts[0] if ts else None)
        for t in ts:
            if t is main:
                for ch in list(t):
                    t.remove(ch)
                t.text = new
            elif not len(t):
                t.text = ''

    def clone(self, lo, hi=None, replace=None):
        """서식의 lo..hi 블록을 그대로 복제(replace: {옛글: 새글}, 글자 모양 유지). 복제한 요소 목록을 돌려준다."""
        hi = lo if hi is None else hi
        els = [copy.deepcopy(self.tops[i]) for i in range(lo, hi + 1)]
        for el in els:
            self._strip_ls(el)
            if replace:
                for t in el.iter(HP + 't'):
                    if t.text:
                        s = t.text
                        for a, b in replace.items():
                            s = s.replace(a, b)
                        t.text = s
            if el.find('.//' + HP + 'tbl') is not None:
                for tbl in el.iter(HP + 'tbl'):
                    tbl.set('id', str(self._new_id()))
            self._add(el)
        return els

    def section_start(self):
        """표지 없이 시작하는 문서: 서식에서 쪽 설정(secPr)이 든 첫 블록의 설정만 남긴 빈 문단."""
        src = next((e for e in self.tops if e.find('.//' + HP + 'secPr') is not None), self.tops[0])
        el = copy.deepcopy(src)
        self._strip_ls(el)
        for run in el.findall(HP + 'run'):
            for ch in list(run):
                if ch.tag.split('}')[1] not in ('secPr', 'ctrl'):
                    run.remove(ch)
            for ctrl in list(run.findall(HP + 'ctrl')):     # 단 설정·쪽 번호만 남김
                if ctrl.find(HP + 'colPr') is None and ctrl.find(HP + 'pageNum') is None:
                    run.remove(ctrl)
        for p in list(el.iter(HP + 'p')):
            if p is not el:
                p.getparent().remove(p)
        return self._add(el)

    def recolor_black(self, el):
        """복제한 블록의 글자색(검정·흰색 외)을 검정으로 — 서식의 색을 무조건 따르지 않는다."""
        ids = {c.get('id'): c for c in self.head.iter(HH + 'charPr')}
        box = self._box('charProperties')
        for r in el.iter(HP + 'run'):
            c = ids.get(r.get('charPrIDRef'))
            if c is None or c.get('textColor', '#000000').upper() in ('#000000', '#FFFFFF'):
                continue
            key = ('black', r.get('charPrIDRef'))
            if key not in self._char_cache:
                new = copy.deepcopy(c)
                new.set('id', self._next_id(box, 'charPr'))
                new.set('textColor', '#000000')
                box.append(new)
                box.set('itemCnt', str(len(box.findall(HH + 'charPr'))))
                ids[new.get('id')] = new
                self._char_cache[key] = new.get('id')
            r.set('charPrIDRef', self._char_cache[key])

    def refill(self, els, mapping):
        """복제한 표 칸의 채우기 색을 문서 색 체계로 바꾼다. mapping: {옛 색(대문자): 새 색}"""
        box = self._box('borderFills')
        bfs = {b.get('id'): b for b in box.findall(HH + 'borderFill')}
        for el in els:
            for tc in el.iter(HP + 'tc'):
                bid = tc.get('borderFillIDRef')
                src = bfs.get(bid)
                wb = src.find('.//' + HC + 'winBrush') if src is not None else None
                old = (wb.get('faceColor') or '').upper() if wb is not None else ''
                if old not in mapping:
                    continue
                key = ('refill', bid)
                if key not in self._fill_cache:
                    new = copy.deepcopy(src)
                    new.set('id', self._next_id(box, 'borderFill'))
                    new.find('.//' + HC + 'winBrush').set('faceColor', mapping[old])
                    box.append(new)
                    box.set('itemCnt', str(len(box.findall(HH + 'borderFill'))))
                    bfs[new.get('id')] = new
                    self._fill_cache[key] = new.get('id')
                tc.set('borderFillIDRef', self._fill_cache[key])

    def wordwrap(self, els, align=None):
        """복제한 블록 문단을 어절 단위 줄나눔으로(표지 제목이 '과/업지시서'처럼 끊기지 않게).
        align('LEFT' 등)을 주면 양쪽 정렬 문단의 정렬도 바꾼다(어절 단위 + 양쪽 정렬은 낱말 사이가 크게 벌어짐)."""
        box = self._box('paraProperties')
        ids = {c.get('id'): c for c in box.findall(HH + 'paraPr')}
        for el in els:
            for p in el.iter(HP + 'p'):
                pid = p.get('paraPrIDRef')
                key = ('ww', pid, align)
                if key not in self._para_cache:
                    src = ids.get(pid)
                    if src is None:
                        continue
                    new = copy.deepcopy(src)
                    new.set('id', self._next_id(box, 'paraPr'))
                    bs = new.find(HH + 'breakSetting')
                    if bs is not None:
                        bs.set('breakNonLatinWord', 'BREAK_WORD')
                    al = new.find(HH + 'align')
                    if align and al is not None and al.get('horizontal') in ('JUSTIFY', 'DISTRIBUTE'):
                        al.set('horizontal', align)
                    box.append(new)
                    box.set('itemCnt', str(len(box.findall(HH + 'paraPr'))))
                    ids[new.get('id')] = new
                    self._para_cache[key] = new.get('id')
                p.set('paraPrIDRef', self._para_cache[key])

    def strip_lead(self, els):
        """복제한 블록의 앞쪽 공백을 지운다(가운데 정렬 제목이 밀리지 않게)."""
        for el in els:
            for p in el.iter(HP + 'p'):
                for t in [t for r in p.findall(HP + 'run') for t in r.findall(HP + 't')]:
                    if t.text and not t.text.strip() and not len(t):
                        t.text = ''
                    elif t.text:
                        t.text = t.text.lstrip()
                        break

    def cover(self, lo, hi, replace, wrap=()):
        """표지 블록 복제 + 제목 칸 정리(앞 공백 제거·어절 단위 줄나눔). wrap: 정리할 블록의 상대 번호."""
        els = self.clone(lo, hi, replace=replace)
        targets = [els[i] for i in wrap if i < len(els)]
        self.strip_lead(targets)
        self.wordwrap(targets, align='LEFT')
        return els

    # ------------------------------------------------------------ 대제목(Ⅰ)
    def h1(self, num, title, page=False):
        if page:
            self.page()
        if self.heading_block is not None:
            el = copy.deepcopy(self.tops[self.heading_block])
            self._strip_ls(el)
            tbl = el.find('.//' + HP + 'tbl')
            cells = tbl.findall('.//' + HP + 'tc')
            self.set_text(cells[0].find('.//' + HP + 'p'), num)
            self.set_text(cells[-1].find('.//' + HP + 'p'), ' ' + title)
            w_num = sum(int(c.find(HP + 'cellSz').get('width')) for c in cells[:-1])
            w_title = int(cells[-1].find(HP + 'cellSz').get('width'))
            need = int(dwidth(title) * 1800 + 1600)
            w_title = max(w_title, min(need, self.text_width - w_num))
            cells[-1].find(HP + 'cellSz').set('width', str(w_title))
            tbl.find(HP + 'sz').set('width', str(w_num + w_title))
            tbl.set('id', str(self._new_id()))
            el.set('paraPrIDRef', self.para('LEFT', 0, 0, 600, 300, 130, True, True))
            return self._add(el)
        # 자체 디자인: [번호(남색 칸, 흰 글씨)] + [제목(아래 굵은 선)]
        w_num = 2800
        w_title = min(int(dwidth(title) * 1800 + 2400), self.text_width - w_num)
        bf_num = self.fill(NAVY, LINE_NONE, LINE_NONE, LINE_NONE, LINE_NONE)
        bf_title = self.fill(None, LINE_NONE, LINE_NONE, LINE_NONE, LINE_THICK)
        pid = self.para('CENTER', 0, 0, 0, 0, 100, False, True)
        pid_t = self.para('LEFT', 0, 0, 0, 0, 100, False, True)
        c_num = self.char(HEAD_FONT, 16, False, '#FFFFFF')
        c_title = self.char(HEAD_FONT, 16, False, '#000000')
        h = 2900

        def tc(col, w, bf, p_id, c_id, text):
            return (f'<hp:tc name="" header="0" hasMargin="0" protect="0" editable="0" dirty="0" borderFillIDRef="{bf}">'
                    '<hp:subList id="" textDirection="HORIZONTAL" lineWrap="BREAK" vertAlign="CENTER" linkListIDRef="0" '
                    'linkListNextIDRef="0" textWidth="0" textHeight="0" hasTextRef="0" hasNumRef="0">'
                    + self._p_xml(p_id, [(text, c_id)]) + '</hp:subList>'
                    f'<hp:cellAddr colAddr="{col}" rowAddr="0"/><hp:cellSpan colSpan="1" rowSpan="1"/>'
                    f'<hp:cellSz width="{w}" height="{h}"/><hp:cellMargin left="300" right="300" top="100" bottom="100"/></hp:tc>')
        self._z += 1
        tbl = (f'<hp:tbl id="{self._new_id()}" zOrder="{self._z}" numberingType="TABLE" textWrap="TOP_AND_BOTTOM" '
               'textFlow="BOTH_SIDES" lock="0" dropcapstyle="None" pageBreak="NONE" repeatHeader="0" rowCnt="1" colCnt="2" '
               'cellSpacing="0" borderFillIDRef="2" noAdjust="0">'
               f'<hp:sz width="{w_num + w_title}" widthRelTo="ABSOLUTE" height="{h}" heightRelTo="ABSOLUTE" protect="0"/>'
               '<hp:pos treatAsChar="1" affectLSpacing="0" flowWithText="1" allowOverlap="0" holdAnchorAndSO="0" '
               'vertRelTo="PARA" horzRelTo="PARA" vertAlign="TOP" horzAlign="LEFT" vertOffset="0" horzOffset="0"/>'
               '<hp:outMargin left="0" right="0" top="0" bottom="0"/><hp:inMargin left="300" right="300" top="100" bottom="100"/>'
               '<hp:tr>' + tc(0, w_num, bf_num, pid, c_num, num) + tc(1, w_title, bf_title, pid_t, c_title, ' ' + title)
               + '</hp:tr></hp:tbl>')
        return self._wrap_tbl(tbl, self.para('LEFT', 0, 0, 600, 300, 130, True, True))

    def _new_id(self):
        self._tid += 7
        return self._tid

    def _wrap_tbl(self, tbl_xml, pid=None):
        pid = pid or self.para('CENTER', 0, 0, 200, 200, 100, False)
        cid = self.char(BODY_FONT, 10)
        p = etree.fromstring(f'<hp:p {NSDECL} id="2147483648" paraPrIDRef="{pid}" styleIDRef="0" pageBreak="0" '
                             f'columnBreak="0" merged="0"><hp:run charPrIDRef="{cid}">{tbl_xml}<hp:t/></hp:run></hp:p>')
        return self._add(p)

    # ------------------------------------------------------------ 그림
    def _pic(self, path, w_mm, max_h_mm=120):
        data, ext, wpx, hpx = prepare_image(path, max_px=2400)
        bin_id = f'image{self._img_idx}'
        self._img_idx += 1
        self._images.append((bin_id, ext, data))
        w, h = fit_size(wpx, hpx, int(w_mm * MM), int(max_h_mm * MM))
        self._uid += 1
        return pic_run(self.char(BODY_FONT, 10), bin_id, w, h, wpx, hpx, inline=True, uid=self._uid + 500,
                       name=os.path.basename(path))

    def image(self, path, width_mm=150, max_h_mm=120, caption=None, keep_next=False):
        """그림 한 장(가운데). caption 이 있으면 아래에 설명 줄. keep_next: 뒤따르는 표·문단과 같은 쪽에 둠."""
        pid = self.para('CENTER', 0, 0, 200, 100, 100, bool(caption) or keep_next, True)
        p = etree.fromstring(f'<hp:p {NSDECL} id="2147483648" paraPrIDRef="{pid}" styleIDRef="0" pageBreak="0" '
                             'columnBreak="0" merged="0"/>')
        p.append(self._pic(path, width_mm, max_h_mm))
        self._add(p)
        if caption:
            self.p(caption, 'cap')
        return p

    # ------------------------------------------------------------ 표
    def table(self, widths, rows, head=1, label_col=False, aligns=None, size='n', split=None, total=None,
              fills=None, min_row=0, accent_cells=(), pad=200):
        """rows: 칸 = 글 또는 {'t':글, 'cs':n, 'rs':n, 'a':'l|c|r', 'b':True, 'fill':색, 'img':그림경로, 'w_mm':폭}.
        칸 안 줄바꿈은 '\\n', 줄 앞 '- '·'※ '·'❍ '는 내어쓰기. label_col: 첫 열을 항목 열(연회색·굵게)로."""
        total = total or self.text_width
        widths = [int(w) for w in widths]
        s = sum(widths)
        if s != total:
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
                    raise ValueError(f'표 {r}행 칸 수 초과: {row}')
                spec = cell if isinstance(cell, dict) else {'t': cell}
                cs, rs = spec.get('cs', 1), spec.get('rs', 1)
                for rr in range(r, r + rs):
                    for cc in range(c, c + cs):
                        occ[rr][cc] = (r, c)
                placed.append((r, c, cs, rs, spec))
                c += cs
            if any(x is None for x in occ[r]):
                raise ValueError(f'표 {r}행 칸 수 부족: {row}')
        small = size == 's'
        fsz = 11 if small else 12
        row_h = [0] * nrow
        tcs = {}
        for (r, c, cs, rs, spec) in placed:
            w = sum(widths[c:c + cs])
            is_head = r < head
            is_label = label_col and c == 0 and not is_head
            fill = spec.get('fill') or (HEAD_FILL if is_head else (LABEL_FILL if is_label else None))
            if fills and (r, c) in fills:
                fill = fills[(r, c)]
            left = LINE_NONE if c == 0 else LINE_THIN
            right = LINE_NONE if c + cs == ncol else LINE_THIN
            top = LINE_THICK if r == 0 else LINE_THIN
            bottom = LINE_THICK if r + rs == nrow else (LINE_HEAD if (is_head and r + rs == head) else LINE_THIN)
            bf = self.fill(fill, left, right, top, bottom)
            a = spec.get('a') or (aligns[c] if aligns and not is_head else 'c')
            bold = spec.get('b', is_head or is_label)
            ps = ''
            img_h = 0
            if spec.get('img'):
                pid = self.para('CENTER', 0, 0, 0, 0, 100, False, True)
                run = self._pic(spec['img'], spec.get('w_mm', w / MM - 4), spec.get('max_h_mm', 60))
                img_h = int(run.find(HP + 'pic').find(HP + 'sz').get('height'))
                ps += (f'<hp:p id="2147483648" paraPrIDRef="{pid}" styleIDRef="0" pageBreak="0" columnBreak="0" merged="0">'
                       + etree.tostring(run, encoding='unicode') + '</hp:p>')
            lines = str(spec.get('t', '')).split('\n') if (spec.get('t') or not spec.get('img')) else []
            for ln in lines:
                if a == 'l':
                    hanging = ln.startswith(('- ', '· ', '※ ', '❍ '))
                    name = ('cellSL' if small else 'cellLh') if hanging else ('cellSL' if small else 'cellL')
                elif a == 'r':
                    name = 'cellS' if small else 'cell'
                else:
                    name = 'cellS' if small else 'cell'
                pid = self.style_ids(name)[0]
                if a == 'r':
                    pid = self.para('RIGHT', 0, 0, 0, 0, self.STYLES[name][8], False, True)
                color = spec.get('color') or (ACCENT if spec.get('accent') or (r, c) in accent_cells else '#000000')
                runs = self._runs(ln, name, size=spec.get('size'), bold=bold, color=color)
                ps += self._p_xml(pid, runs, self.STYLES[name][5] > 0)
            h = int(max(1, len(lines)) * fsz * 100 * 1.3 + 2 * pad) + img_h
            row_h[r] = max(row_h[r], h // rs if rs > 1 else h, min_row if r >= head else 0)
            tcs[(r, c)] = (cs, rs, w, bf, ps, spec.get('va', 'CENTER'))
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
        if split is None:
            split = nrow > 9
        # 한글 실측: '글자처럼 취급'(treatAsChar=1) 표는 쪽을 넘어 나뉘지 않고 통째로 다음 쪽으로 밀린다.
        # 나뉘어야 하는 긴 표는 본문과 함께 흐르는 '떠 있는' 표(treatAsChar=0, 위아래 배치)로 둔다.
        as_char = '0' if split else '1'
        self._z += 1
        tbl = (f'<hp:tbl id="{self._new_id()}" zOrder="{self._z}" numberingType="TABLE" textWrap="TOP_AND_BOTTOM" '
               f'textFlow="BOTH_SIDES" lock="0" dropcapstyle="None" pageBreak="{"CELL" if split else "NONE"}" '
               f'repeatHeader="{1 if head else 0}" rowCnt="{nrow}" colCnt="{ncol}" cellSpacing="0" borderFillIDRef="2" '
               'noAdjust="0">'
               f'<hp:sz width="{total}" widthRelTo="ABSOLUTE" height="{sum(row_h)}" heightRelTo="ABSOLUTE" protect="0"/>'
               f'<hp:pos treatAsChar="{as_char}" affectLSpacing="0" flowWithText="1" allowOverlap="0" holdAnchorAndSO="0" '
               'vertRelTo="PARA" horzRelTo="COLUMN" vertAlign="TOP" horzAlign="LEFT" vertOffset="0" horzOffset="0"/>'
               f'<hp:outMargin left="0" right="0" top="0" bottom="0"/><hp:inMargin left="510" right="510" top="{pad}" bottom="{pad}"/>'
               + xml_rows + '</hp:tbl>')
        return self._wrap_tbl(tbl)

    def box(self, lines, title=None, fill=BOX_FILL):
        """안내 박스: lines = [('bx1'|'bx2'|'body'|'sign'|'signR', 글)]"""
        total = self.text_width
        ps = ''
        for name, text in ([('boxt', title)] if title else []) + list(lines):
            pid = self.style_ids(name)[0]
            ps += self._p_xml(pid, self._runs(text, name), self.STYLES[name][5] > 0)
        edge = ('SOLID', '0.3 mm', NAVY)
        bf = self.fill(fill, edge, edge, edge, edge)
        h = 2000
        self._z += 1
        tbl = (f'<hp:tbl id="{self._new_id()}" zOrder="{self._z}" numberingType="TABLE" textWrap="TOP_AND_BOTTOM" '
               'textFlow="BOTH_SIDES" lock="0" dropcapstyle="None" pageBreak="CELL" repeatHeader="0" rowCnt="1" colCnt="1" '
               'cellSpacing="0" borderFillIDRef="2" noAdjust="0">'
               f'<hp:sz width="{total}" widthRelTo="ABSOLUTE" height="{h}" heightRelTo="ABSOLUTE" protect="0"/>'
               '<hp:pos treatAsChar="1" affectLSpacing="0" flowWithText="1" allowOverlap="0" holdAnchorAndSO="0" '
               'vertRelTo="PARA" horzRelTo="PARA" vertAlign="TOP" horzAlign="LEFT" vertOffset="0" horzOffset="0"/>'
               '<hp:outMargin left="0" right="0" top="0" bottom="0"/><hp:inMargin left="850" right="850" top="560" bottom="560"/>'
               f'<hp:tr><hp:tc name="" header="0" hasMargin="1" protect="0" editable="0" dirty="0" borderFillIDRef="{bf}">'
               '<hp:subList id="" textDirection="HORIZONTAL" lineWrap="BREAK" vertAlign="TOP" linkListIDRef="0" '
               f'linkListNextIDRef="0" textWidth="0" textHeight="0" hasTextRef="0" hasNumRef="0">{ps}</hp:subList>'
               '<hp:cellAddr colAddr="0" rowAddr="0"/><hp:cellSpan colSpan="1" rowSpan="1"/>'
               f'<hp:cellSz width="{total}" height="{h}"/><hp:cellMargin left="850" right="850" top="560" bottom="560"/>'
               '</hp:tc></hp:tr></hp:tbl>')
        return self._wrap_tbl(tbl, self.para('CENTER', 0, 0, 300, 300, 100, False))

    # ------------------------------------------------------------ 저장
    def save(self, out, title=None):
        pkg = self.pkg
        for ch in list(self.sec):
            self.sec.remove(ch)
        for e in self.out:
            self.sec.append(e)
        pkg.set_xml(self.sec_name, self.sec)
        register_images(pkg, self._images)
        if 'settings.xml' in pkg.files:     # 서식에 저장된 '모아찍기' 인쇄 설정 초기화
            st = pkg.files['settings.xml'].decode('utf-8', 'ignore')
            st = re.sub(r'(name="PrintMethod" type="short">)\d+(<)', r'\g<1>0\g<2>', st)
            pkg.files['settings.xml'] = st.encode('utf-8')
        self.head.set('secCnt', '1')        # 첫 구역만 남기므로 구역 수를 맞춤(안 맞으면 한글이 열지 못함)
        pkg.set_xml('Contents/header.xml', self.head)
        opf = '{http://www.idpf.org/2007/opf/}'
        if 'Contents/content.hpf' in pkg.files:
            hpf = etree.fromstring(pkg.files['Contents/content.hpf'])
            for name in pkg.section_names()[1:]:
                for it in list(hpf.iter(opf + 'item')):
                    if it.get('href') == name:
                        iid = it.get('id')
                        it.getparent().remove(it)
                        for ir in list(hpf.iter(opf + 'itemref')):
                            if ir.get('idref') == iid:
                                ir.getparent().remove(ir)
                pkg.files.pop(name, None)
            if title:
                for t in hpf.iter('{http://purl.org/dc/elements/1.1/}title'):
                    t.text = title
            pkg.files['Contents/content.hpf'] = etree.tostring(hpf, xml_declaration=True, encoding='UTF-8',
                                                                 standalone=True)
        if 'Preview/PrvText.txt' in pkg.files:
            pkg.files['Preview/PrvText.txt'] = (title or '').encode('utf-8')
        d = os.path.dirname(os.path.abspath(out))
        os.makedirs(d, exist_ok=True)
        pkg.save(out)
        return out
