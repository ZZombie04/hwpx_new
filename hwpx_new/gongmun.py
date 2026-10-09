# -*- coding: utf-8 -*-
"""공문(기안문·시행문) 만들기 — 내용 명세(JSON) 하나로, 어떤 AI 가 써도 같은 모양이 나오게.

기관 공문 서식(머리 표 + 결재란이 든 HWPX)을 받아
  - 머리 표(수신·제목 칸)와 결재란(시행 번호 등)은 서식에서 그대로 복제해 글만 바꾸고,
  - 본문은 공문 번호 체계(1. → 가. → 1) → 가))와 표·QR 을 정해진 모양으로 새로 짠다.
AI 는 글(내용)만 쓰고, 들여쓰기·글꼴·표 모양·붙임/끝 표기·발신 명의·수신자 줄은 이 모듈이 정한다.

명세 예(전체 문법은 FORMAT.md 의 '공문 명세', 예시는 examples/gongmun_spec.json):
{
  "template": "기관_공문서식.hwpx",
  "receiver": "수신자 참조",                     # 머리 표 '수신' 칸
  "title": "○○ 대회 참가 신청 안내",             # 머리 표 '제목' 칸
  "body": [
    "1. 관련: ○○과-1234(2026. 4. 6.)",
    "2. ○○ 대회를 다음과 같이 운영하오니 기한 내에 신청하여 주시기 바랍니다.",
    "가. 대회 개요",
    {"table": {"rows": [["일시", "2026. 11. 21.(토)"], ["장소", "○○ 체육관"]], "label_col": true}},
    "※ 세부 일정은 바뀔 수 있습니다.",
    "3. 문의: ○○과(☎ 000-0000)"
  ],
  "attachments": ["대회 운영 계획 1부"],          # 없으면 마지막 문장 뒤에 '끝.'
  "sender": "○○교육지원청교육장",                 # 시행문(학교 발송)만. 내부결재는 생략
  "receivers": ["가나초등학교장", "다라초등학교장"],  # '수신자 참조'일 때 수신자 줄
  "approval": {"시행": "○○과-○○○○(2026. 10. ○○.)"}  # 결재란 칸 글 바꾸기(칸 이름: 새 글), 또는 {"replace": {옛: 새}}
}
"""
from __future__ import annotations

import json
import os
import re
import tempfile

from lxml import etree

from .compose import Composer, HP, HH
from . import compose as C

LEVELS = [  # (정규식, 단계)
    (re.compile(r'^\d{1,2}\.\s'), 1),
    (re.compile(r'^[가-하]\.\s'), 2),
    (re.compile(r'^\d{1,2}\)\s'), 3),
    (re.compile(r'^[가-하]\)\s'), 4),
]
NOTE = re.compile(r'^※')


def _txt(el):
    return ''.join(''.join(t.itertext()) for t in el.iter(HP + 't'))


def _font_of(head, p, default=('굴림체', 12.0)):
    """서식 본문 문단의 글꼴·크기(한글 글꼴 이름, pt)."""
    run = p.find(HP + 'run') if p is not None else None
    if run is None:
        return default
    cp = next((c for c in head.iter(HH + 'charPr') if c.get('id') == run.get('charPrIDRef')), None)
    if cp is None:
        return default
    fr = cp.find(HH + 'fontRef')
    fid = fr.get('hangul') if fr is not None else '0'
    face = default[0]
    for ff in head.iter(HH + 'fontface'):
        if ff.get('lang') == 'HANGUL':
            for f in ff.findall(HH + 'font'):
                if f.get('id') == fid:
                    face = f.get('face')
    return face, int(cp.get('height', '1200')) / 100


class Gongmun(Composer):
    """공문 본문 조판: 1.(0칸) → 가.(1칸) → 1)(2칸) → 가)(3칸). 표·※ 는 바로 위 단계보다 한 칸 더 들여 놓는다."""
    LEAD = re.compile(r'^(※|\d{1,2}\.|[가-하]\.|\d{1,2}\)|[가-하]\)) ')

    def __init__(self, template, font=None, size=None):
        super().__init__(template)
        self.cover_i, self.approval_i = self._find_blocks()
        body_p = next((e for e in self.tops[self.cover_i + 1:self.approval_i] if _txt(e).strip()), None)
        f, s = _font_of(self.head, body_p)
        self.font, self.size = font or f, float(size or s)
        u = int(self.size * 100)            # 한 칸(본문 글자 1자) 폭 HWPUNIT
        self.unit = u
        F, S = self.font, self.size
        cs = max(S - 1, 9)
        st = {k: ((F,) + v[1:] if v[0] in (C.BODY_FONT, C.HEAD_FONT) else v) for k, v in Composer.STYLES.items()}
        # 단계 n: 왼쪽 여백 (n-1)칸, 내어쓰기 = 번호 폭('1. '·'1) ' 1.5칸, '가. '·'가) ' 2칸)
        for n, hang in ((1, 1.5), (2, 2), (3, 1.5), (4, 2)):
            st[f'g{n}'] = (F, S, False, 'JUSTIFY', u * (n - 1), int(u * hang), 240 if n == 1 else 60, 0, 160, False)
            st[f'g{n}k'] = st[f'g{n}'][:9] + (True,)        # 뒤따르는 표와 같은 쪽에
        for n in (1, 2, 3, 4):                                # ※ 참고(표 아래 등)
            st[f'gn{n}'] = (F, cs, False, 'JUSTIFY', u * n, int(cs * 150), 80, 0, 150, False)
        st.update({
            'gp': (F, S, False, 'JUSTIFY', 0, 0, 240, 0, 160, False),
            'att': (F, S, False, 'LEFT', 0, 0, 500, 0, 160, False),
            'att2': (F, S, False, 'LEFT', u * 3, 0, 0, 0, 160, False),       # '붙임  ' 폭만큼
            'sig': (F, S + 6, True, 'CENTER', 0, 0, 900, 600, 130, False),
            'rcv': (F, cs, False, 'LEFT', 0, int(cs * 100 * 4), 0, 0, 150, False),   # '수신자  ' 폭만큼
            'cell': (F, cs, False, 'CENTER', 0, 0, 0, 0, 140, False),
            'cellL': (F, cs, False, 'LEFT', 0, 0, 0, 0, 145, False),
            'cellLh': (F, cs, False, 'LEFT', 0, int(cs * 100), 0, 0, 145, False),
            'cellS': (F, cs - 1, False, 'CENTER', 0, 0, 0, 0, 135, False),
            'cellSL': (F, cs - 1, False, 'LEFT', 0, int((cs - 1) * 100), 0, 0, 135, False),
        })
        self.STYLES = st
        self.WORD_WRAP = Composer.WORD_WRAP | {'sig', 'att', 'att2', 'rcv'}
        self.level = 1

    # ------------------------------------------------------------ 서식 블록 찾기
    def _find_blocks(self):
        tbl = [i for i, e in enumerate(self.tops) if e.find('.//' + HP + 'tbl') is not None]
        cover = next((i for i in tbl if '수신' in _txt(self.tops[i]) and '제목' in _txt(self.tops[i])), None)
        appr = next((i for i in reversed(tbl) if '시행' in _txt(self.tops[i]) or '협조자' in _txt(self.tops[i])), None)
        if cover is None:
            raise ValueError('공문 서식에서 머리 표(수신·제목 칸)를 찾지 못했습니다.')
        if appr is None or appr <= cover:
            raise ValueError('공문 서식에서 결재란(시행·협조자 칸이 든 표)을 찾지 못했습니다.')
        return cover, appr

    def set_cell_after(self, el, label, text):
        """표에서 글이 label 인 칸 바로 다음 칸의 글을 text 로(글자 모양 유지). 찾으면 True."""
        tcs = list(el.iter(HP + 'tc'))
        key = label.replace(' ', '')
        for i, tc in enumerate(tcs):
            if _txt(tc).replace(' ', '') == key and i + 1 < len(tcs):
                p = next(tcs[i + 1].iter(HP + 'p'))
                if list(p.iter(HP + 't')):
                    self.set_text(p, text)
                else:                                   # 빈 칸: 이름 칸의 글자 모양으로 덩어리를 만든다
                    src = next(tc.iter(HP + 'run'), None)
                    run = p.find(HP + 'run')
                    if run is None:
                        run = etree.SubElement(p, HP + 'run')
                    run.set('charPrIDRef', src.get('charPrIDRef') if src is not None else '0')
                    etree.SubElement(run, HP + 't').text = text
                return True
        return False

    # ------------------------------------------------------------ 본문
    def line(self, text, keep=False):
        if NOTE.match(text):
            return self.p(text, f'gn{min(self.level, 4)}')
        for rx, n in LEVELS:
            if rx.match(text):
                self.level = n
                return self.p(text, f'g{n}' + ('k' if keep else ''))
        return self.p(text, 'gp')

    def gtable(self, spec):
        rows = spec['rows']
        ncol = max(sum(c.get('cs', 1) if isinstance(c, dict) else 1 for c in r) for r in rows)
        widths = spec.get('widths') or ([7600] + [10000] * (ncol - 1) if spec.get('label_col') and ncol > 1 else [1] * ncol)
        rows = [[self._qr_cell(c) if isinstance(c, dict) and c.get('qr') else c for c in r] for r in rows]
        indent = self.unit * spec.get('indent', self.level)
        p = self.table(widths, rows, head=spec.get('head', 0 if spec.get('label_col') else 1),
                       label_col=spec.get('label_col', False), aligns=spec.get('aligns') or (['c'] + ['l'] * (ncol - 1)),
                       size=spec.get('size', 'n'), split=spec.get('split'), total=self.text_width - indent)
        p.set('paraPrIDRef', self.para('LEFT', indent, 0, 100, 200, 100, False, True))
        return p

    def _qr_cell(self, c):
        mm = c.get('size_mm', 21)
        out = {k: v for k, v in c.items() if k not in ('qr', 'caption', 'size_mm')}
        out.update({'img': make_qr(c['qr']), 'w_mm': mm, 'max_h_mm': mm, 't': c.get('caption', 'QR 바로가기'),
                    'fill': c.get('fill', '#FFFFFF'), 'b': False, 'size': c.get('size', 9), 'a': 'c'})
        return out


def make_qr(url, out_dir=None):
    """URL → QR 그림(PNG) 경로. segno(권장) 또는 qrcode 패키지가 필요하다."""
    out_dir = out_dir or tempfile.mkdtemp(prefix='hwpx_qr_')
    path = os.path.join(out_dir, 'qr.png')
    try:
        import segno
        segno.make(url, error='q').save(path, scale=20, border=2)
        return path
    except ImportError:
        pass
    try:
        import qrcode
        qrcode.make(url).save(path)
        return path
    except ImportError:
        raise RuntimeError('QR 코드를 만들려면 segno 패키지가 필요합니다: pip install segno')


def _bu(a):
    """붙임 이름 → 'OO 1부.'"""
    a = a.strip().rstrip('.').strip()
    return a + '.' if re.search(r'\d+\s*부$', a) else a + ' 1부.'


def load_spec(spec):
    if isinstance(spec, dict):
        return spec, os.getcwd()
    if isinstance(spec, str) and spec.lstrip().startswith('{'):
        return json.loads(spec), os.getcwd()
    return json.load(open(spec, encoding='utf-8')), os.path.dirname(os.path.abspath(spec))


def build(spec, out):
    """명세(dict, JSON 문자열 또는 JSON 파일 경로) → 공문 HWPX. 돌려줌: 결과 경로."""
    spec, base = load_spec(spec)
    tpl = spec['template'] if os.path.isabs(spec['template']) else os.path.join(base, spec['template'])
    d = Gongmun(tpl, spec.get('font'), spec.get('size'))
    # 머리 표(그 앞 블록 포함)
    head = d.clone(0, d.cover_i, replace=spec.get('head_replace'))[-1]
    if spec.get('receiver') is not None and not d.set_cell_after(head, '수신', spec['receiver']):
        raise ValueError("머리 표에서 '수신' 칸을 찾지 못했습니다.")
    if spec.get('title') and not d.set_cell_after(head, '제목', spec['title']):
        raise ValueError("머리 표에서 '제목' 칸을 찾지 못했습니다.")
    # 본문
    body = list(spec.get('body') or [])
    atts = spec.get('attachments') or []
    if not atts and body and isinstance(body[-1], str) and not body[-1].rstrip().endswith('끝.'):
        body[-1] = body[-1].rstrip() + '  끝.'
    for i, item in enumerate(body):
        nxt = body[i + 1] if i + 1 < len(body) else None
        if isinstance(item, str):
            d.line(item, keep=isinstance(nxt, dict) and 'table' in nxt)
        elif 'table' in item:
            d.gtable(item['table'])
        elif item.get('page'):
            d.page()
        else:
            raise ValueError(f'알 수 없는 본문 항목: {item}')
    # 붙임
    for k, a in enumerate(atts, 1):
        if len(atts) == 1:
            d.p(f'붙임  {_bu(a)}  끝.', 'att')
        else:
            text = f'{k}. {_bu(a)}' + ('  끝.' if k == len(atts) else '')
            d.p('붙임  ' + text if k == 1 else text, 'att' if k == 1 else 'att2')
    if spec.get('sender'):
        d.p(spec['sender'], 'sig')
    rec = spec.get('receivers')
    if rec:
        d.p('수신자  ' + (', '.join(rec) if isinstance(rec, (list, tuple)) else str(rec)), 'rcv')
    # 결재란
    ap = dict(spec.get('approval') or {})
    el = d.clone(d.approval_i, replace=ap.pop('replace', None))[0]
    for label, text in ap.items():
        if not d.set_cell_after(el, label, text):
            raise ValueError(f"결재란에서 '{label}' 칸을 찾지 못했습니다.")
    d.save(out, title=spec.get('title') or '')
    return out


def check_pdf(pdf):
    """공문 조판 점검: 결재란이 홀로 마지막 쪽에 남았는지. 돌려줌: 문제 문장 목록."""
    import pymupdf
    d = pymupdf.open(pdf)
    if len(d) < 2:
        return []
    lines = []
    for b in d[-1].get_text('dict')['blocks']:
        for ln in b.get('lines', []):
            t = ''.join(s['text'] for s in ln['spans']).strip()
            if t:
                lines.append((ln['bbox'][1], ln['bbox'][3], t))
    anchors = [y0 for y0, _, t in lines if t in ('협조자', '시행')]
    if not anchors:
        return []
    top = min(anchors) - 60            # 결재란 윗부분(직위·이름 줄)은 협조자 줄 위 60pt 안에 있다
    body = [t for y0, y1, t in lines if y1 < top and not re.fullmatch(r'-?\s*\d+\s*-?', t)]
    if len(body) <= 1:
        return [f'결재란이 홀로 {len(d)}쪽에 있습니다 — 문장·표 행을 줄여 앞 쪽에 함께 들어가게 하세요.']
    return []
