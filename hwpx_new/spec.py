# -*- coding: utf-8 -*-
"""정돈 조판 명세(JSON) — 파이썬 없이 Composer 로 계획서·안내문을 짠다(어떤 AI 가 써도 같은 모양).

명세 예(examples/compose_spec.json):
{
  "template": "서식.hwpx",
  "heading_block": 25,                                  # 대제목(Ⅰ) 표 블록 번호(없으면 자체 디자인)
  "cover": {"from": 0, "to": 24, "replace": {"옛 제목": "새 제목"}, "wrap": [1, 22]},   # 없으면 표지 없이 시작
  "title": "문서 제목",
  "blocks": [
    {"h1": "Ⅰ 추진 개요"}, {"h2": "목적"}, {"b1": "항목"}, {"b2": "세부"}, {"note": "참고", "level": 1},
    {"table": {"rows": [["구분", "내용"], ["기간", "2026. 11. 21.(토)"]], "label_col": true}},
    {"box": {"title": "학교에서 할 일", "lines": ["❍ ^^신청 마감: 10. 30.(금)^^", "- 세부"]}},
    {"image": {"path": "그림.png", "width_mm": 150}}, {"page": true},
    {"clone": {"from": 190, "to": 192, "replace": {"2025": "2026"}, "recolor": true}}
  ]
}
글 안에서 **굵게**, ^^강조(진한 빨강)^^ 를 쓸 수 있다. 표 칸은 글 또는 {"t","cs","rs","a","b","fill","img","qr"}.
"""
from __future__ import annotations

import os

from .compose import Composer

BLOCK_KEYS = ('h1', 'h2', 'b1', 'b1h', 'b2', 'b3', 'note', 'p', 'table', 'box', 'image', 'page', 'blank', 'clone')


def _path(base, p):
    return p if os.path.isabs(p) else os.path.join(base, p)


def _table_rows(rows):
    from .gongmun import make_qr
    out = []
    for r in rows:
        row = []
        for c in r:
            if isinstance(c, dict) and c.get('qr'):
                mm = c.get('size_mm', 25)
                c = {**{k: v for k, v in c.items() if k not in ('qr', 'caption', 'size_mm')},
                     'img': make_qr(c['qr']), 'w_mm': mm, 'max_h_mm': mm, 't': c.get('caption', 'QR 바로가기'),
                     'fill': c.get('fill', '#FFFFFF'), 'b': False, 'a': 'c'}
            row.append(c)
        out.append(row)
    return out


def render_block(d, blk, base='.'):
    """명세 블록 하나를 문서에 더한다. 돌려줌: 더한 요소 목록."""
    n0 = len(d.out)
    if 'h1' in blk:
        v = blk['h1']
        num, title = (v if isinstance(v, (list, tuple)) else v.split(' ', 1))
        d.h1(num, title, page=blk.get('page', False))
    elif 'h2' in blk:
        d.h2(blk['h2'])
    elif 'b1h' in blk:
        d.b1h(blk['b1h'])
    elif 'b1' in blk:
        d.b1(blk['b1'])
    elif 'b2' in blk:
        d.b2(blk['b2'])
    elif 'b3' in blk:
        d.b3(blk['b3'])
    elif 'note' in blk:
        d.note(blk['note'], level=blk.get('level', 2))
    elif 'p' in blk:
        d.p(blk['p'], blk.get('style', 'p'))
    elif 'table' in blk:
        t = dict(blk['table'])
        rows = _table_rows(t.pop('rows'))
        ncol = max(sum(c.get('cs', 1) if isinstance(c, dict) else 1 for c in r) for r in rows)
        widths = t.pop('widths', None) or ([9500] + [10000] * (ncol - 1) if t.get('label_col') and ncol > 1 else [1] * ncol)
        if 'aligns' not in t:
            t['aligns'] = ['c'] + ['l'] * (ncol - 1)
        d.table(widths, rows, **t)
    elif 'box' in blk:
        b = blk['box']
        lines = [(('bx2' if ln.startswith('- ') else 'bx1'), ln) if isinstance(ln, str) else tuple(ln) for ln in b['lines']]
        d.box(lines, title=b.get('title'))
    elif 'image' in blk:
        im = blk['image']
        d.image(_path(base, im['path']), im.get('width_mm', 150), im.get('max_h_mm', 120), im.get('caption'),
                im.get('keep_next', False))
    elif 'page' in blk:
        d.page()
    elif 'blank' in blk:
        d.blank()
    elif 'clone' in blk:
        c = blk['clone']
        els = d.clone(c['from'], c.get('to'), replace=c.get('replace'))
        if c.get('recolor'):
            for el in els:
                d.recolor_black(el)
    else:
        raise ValueError(f'알 수 없는 블록: {blk} (쓸 수 있는 키: {", ".join(BLOCK_KEYS)})')
    return d.out[n0:]


def build(spec, out):
    """명세(dict·JSON 문자열·JSON 파일) → HWPX."""
    from .gongmun import load_spec
    spec, base = load_spec(spec)
    d = Composer(_path(base, spec['template']), heading_block=spec.get('heading_block'))
    cov = spec.get('cover')
    if cov:
        d.cover(cov['from'], cov['to'], cov.get('replace') or {}, wrap=tuple(cov.get('wrap') or ()))
    else:
        d.section_start()
    for blk in spec.get('blocks') or []:
        render_block(d, blk, base)
    d.save(out, title=spec.get('title'))
    return out
