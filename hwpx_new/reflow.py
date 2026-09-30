# -*- coding: utf-8 -*-
"""분석한 서식의 '자기 자신' 내용을 블록(JSON·Markdown)으로 되돌린다.

- AI 가 고쳐 쓸 출발점(`hwpx-new skeleton`)으로 쓰고,
- 같은 서식으로 다시 조립해 원본과 겉모양을 비교하는 자체 점검(`hwpx-new selfcheck`)에도 쓴다.
"""
from __future__ import annotations

import json
from collections import Counter

from .analyze import Blueprint, bullet_marker, cell_paragraphs, ptext
from .package import HP


def inline_text(p, head, strip=0) -> str:
    """문단 글. 본문 글자 모양과 '굵기만' 다른 부분은 **굵게** 표시로 돌려준다(앞쪽 strip 글자는 잘라냄)."""
    segs = []
    for r in p.findall(HP + 'run'):
        for t in r.findall(HP + 't'):
            tx = ''.join(t.itertext())
            if tx:
                segs.append((tx, r.get('charPrIDRef')))
    if not segs:
        return ''
    cnt = Counter()
    for tx, c in segs:
        cnt[c] += len(tx)
    base = cnt.most_common(1)[0][0]
    bch = head.char.get(str(base), {})
    flagged = []
    for tx, c in segs:
        ch = head.char.get(str(c), {})
        bold = (not bch.get('bold')) and ch.get('bold') and ch.get('height') == bch.get('height') \
            and ch.get('color') == bch.get('color')
        flagged.append([tx, bool(bold)])
    if strip:
        i = 0
        while strip > 0 and i < len(flagged):
            n = min(strip, len(flagged[i][0]))
            flagged[i][0] = flagged[i][0][n:]
            strip -= n
            i += 1
    out, cur, curb = [], '', None
    for tx, b in flagged:
        if not tx:
            continue
        if curb is None or b == curb:
            cur += tx
            curb = b
        else:
            out.append(('**' + cur + '**') if curb else cur)
            cur, curb = tx, b
    if cur:
        out.append(('**' + cur + '**') if curb else cur)
    return ''.join(out)


def _align_letter(head, para_pr):
    a = head.para.get(para_pr, {}).get('align', 'JUSTIFY')
    return {'CENTER': 'c', 'RIGHT': 'r'}.get(a, 'l')


def table_spec(b, kit):
    cells = b.info['cells']
    cols, rows = b.info['cols'], b.info['rows']
    hdr = b.info.get('hdr_rows', 0)
    head = kit.head
    w = [0] * cols
    for c in cells:
        if c['cs'] == 1 and c['c'] < cols:
            w[c['c']] = max(w[c['c']], c['w'])
    if not all(w):
        tot = sum(c['w'] for c in cells if c['r'] == 0) or 1
        fill = tot / cols
        w = [x or fill for x in w]
    votes = [dict() for _ in range(cols)]
    by_row = {}
    for c in cells:
        by_row.setdefault(c['r'], []).append(c)
        if c['r'] >= hdr and c['cs'] == 1:
            a = _align_letter(head, c['para_pr'])
            votes[c['c']][a] = votes[c['c']].get(a, 0) + 1
    align = [max(v, key=v.get) if v else 'c' for v in votes]

    def cell_out(c):
        txt = chr(10).join(inline_text(p, kit.head) for p in cell_paragraphs(c['el']))
        d = {'text': txt}
        if c['cs'] > 1:
            d['colspan'] = c['cs']
        if c['rs'] > 1:
            d['rowspan'] = c['rs']
        if len(d) == 1:
            return txt
        return d

    grid = []
    for r in range(rows):
        row = sorted(by_row.get(r, []), key=lambda x: x['c'])
        grid.append([cell_out(c) for c in row])
    return {'type': 'table', 'header': grid[:hdr], 'rows': grid[hdr:], 'widths': [round(x) for x in w], 'align': align}


def _cover_slots(bp):
    return [p for bl in bp.blocks[:bp.cover_end] for p in bl.el.iter(HP + 'p') if ptext(p).strip()]


def _slot_size(bp, p):
    for r in p.findall(HP + 'run'):
        if any(''.join(t.itertext()).strip() for t in r.findall(HP + 't')):
            return bp.head.size(r.get('charPrIDRef'))
    return 0


def _heading_text(b):
    if b.info.get('tbl') is None:
        return b.text.strip()
    parts = [c['text'].strip() for c in sorted(b.info['cells'], key=lambda c: (c['r'], c['c'])) if c['text'].strip()]
    if len(parts) <= 1:
        return parts[0] if parts else ''
    sep = ' ' if parts[0].endswith(('.', ')')) else '. '
    return parts[0] + sep + ' '.join(parts[1:])


def has_rich_runs(p, head) -> bool:
    """굵기 말고도(색·크기·기울임·밑줄·글꼴) 글자 모양이 섞여 있는 문단인가(**굵게** 표시로는 표현 못 함)."""
    looks = []
    for r in p.findall(HP + 'run'):
        tx = ''.join(''.join(t.itertext()) for t in r.findall(HP + 't'))
        if not tx.strip() or bullet_marker(tx + 'x') == tx:
            continue
        c = head.char.get(str(r.get('charPrIDRef')), {})
        looks.append((len(tx.strip()), (c.get('height'), c.get('color'), c.get('italic'))))
    if len(looks) < 2:
        return False
    base = max(looks)[1]
    return any(lk != base for _n, lk in looks)


def is_complex_table(b) -> bool:
    cells = b.info['cells']
    nested = len(b.el.findall('.//' + HP + 'tbl')) > 1
    merged = sum(1 for c in cells if c['rs'] > 1 or c['cs'] > 1)
    return nested or b.info['cols'] > 10 or len(cells) > 120 or (merged >= 3 and len(cells) > 24)


def block_spec(bp: Blueprint, kit, b, with_class=False):
    """블록 하나 → 블록 dict(없으면 None). 표지 블록은 다루지 않는다."""
    r = b.role
    if r == 'blank':
        return None

    def tag(sp):
        if with_class and b.cls:
            sp['class'] = b.cls
        if b.el.get('pageBreak') == '1':
            sp['page_break'] = True
        return sp

    if r == 'image':
        return {'type': 'clone', 'from': b.idx}
    if b.info.get('tbl') is not None and b.info.get('has_pic'):
        return {'type': 'clone', 'from': b.idx}
    if b.info.get('tbl') is not None and r in ('table', 'box') and is_complex_table(b):
        # 양식·격자형 표는 새로 그리지 않고 통째로 복제하고 글만 바꾼다(모양 100% 유지)
        return tag({'type': 'clone', 'from': b.idx,
                    'paras': [ptext(p) for p in b.el.iter(HP + 'p') if p is not b.el and ptext(p).strip()]})
    if r in ('heading', 'heading_text'):
        return tag({'type': 'heading', 'text': _heading_text(b)})
    if r in ('bullet', 'numbered', 'paragraph') and has_rich_runs(b.el, kit.head):
        # 색·크기가 섞인 문단: 바뀐 낱말만 새로 쓰고 나머지 글자 모양은 그대로 두는 'like' 로
        return {'type': 'like', 'from': b.idx, 'text': b.text.strip() if r != 'bullet' else b.text.strip()}
    if r == 'bullet':
        mk = bullet_marker(b.text)
        txt = inline_text(b.el, kit.head, len(mk)) if mk else inline_text(b.el, kit.head)
        return tag({'type': 'bullet', 'text': txt.strip(), 'level': kit.bullet_level_of(b)})
    if r == 'numbered':
        return tag({'type': 'numbered', 'text': inline_text(b.el, kit.head).strip()})
    if r == 'paragraph':
        return tag({'type': 'paragraph', 'text': inline_text(b.el, kit.head).strip()})
    if r == 'box':
        pl = [p for p in b.el.iter(HP + 'p') if ptext(p).strip()]
        ps = [inline_text(p, kit.head) for p in pl]
        sp = {'type': 'box', 'lines': ps}
        if len(pl) >= 2 and pl[0].get('paraPrIDRef') != pl[1].get('paraPrIDRef'):
            sp = {'type': 'box', 'title': ps[0], 'lines': ps[1:]}
        return tag(sp)
    if r in ('table', 'title') and b.info.get('tbl') is not None:
        return tag(table_spec(b, kit))
    return None


def blueprint_specs(bp: Blueprint, kit=None, skip_images=True, with_class=False):
    """문서 전체를 블록 목록으로. with_class=True 면 각 블록에 서식 종류(class)를 붙여 정확히 재현되게 한다."""
    from .builder import Kit
    kit = kit or Kit(bp)
    specs = []
    cover_done = False
    for b in bp.blocks:
        if b.info.get('cover'):
            if not cover_done and b.role != 'image':
                cover_done = True
                slots = _cover_slots(bp)
                best = max(slots, key=lambda p: (_slot_size(bp, p), len(ptext(p)))) if slots else None
                specs.append({'type': 'title', 'text': ptext(best).strip() if best is not None else b.text})
            continue
        sp = block_spec(bp, kit, b, with_class)
        if sp is None:
            continue
        if sp['type'] == 'clone' and skip_images:
            continue
        specs.append(sp)
    return specs


# ---------------------------------------------------------------- 뼈대 Markdown
def _cell_md(c):
    t = c.replace('|', '\\|').replace(chr(10), '<br>')
    return t if t.strip() else ' '


def _ncols(sp):
    hdr = sp.get('header') or []
    rows = sp.get('rows') or []
    allr = (hdr if hdr and isinstance(hdr[0], list) else [hdr]) + rows
    return max((sum(c.get('colspan', 1) if isinstance(c, dict) else 1 for c in rw) for rw in allr), default=0)


def _default_cls(kit, spec):
    """태그 없이 썼을 때 조립기가 고를 서식 종류."""
    t = spec['type']
    if t == 'bullet':
        b = kit.proto('bullet', spec.get('level', 1))
    elif t == 'numbered':
        b = kit.proto('numbered', text=spec['text'])
    elif t == 'paragraph':
        b = kit.proto('paragraph')
    elif t == 'heading':
        b = kit.proto('heading', text=spec['text'])
    elif t == 'box':
        b = kit.proto('box')
    elif t == 'table':
        b = kit.choose_table(ncols=_ncols(spec))
    else:
        return None
    return b.cls if b is not None else None


def skeleton_markdown(bp: Blueprint, kit=None) -> str:
    """서식의 내용을 '그대로 다시 만들 수 있는' Markdown 으로 돌려준다(AI 가 글만 고쳐 쓰는 출발점).
    기본 선택과 다른 모양의 블록에만 {서식종류} 표시를 붙인다."""
    from .builder import Kit
    kit = kit or Kit(bp)
    L = []
    cover_done = False
    for b in bp.blocks:
        if b.role == 'blank':
            continue
        if b.info.get('cover'):
            if cover_done or b.role == 'image':
                continue
            cover_done = True
            slots = _cover_slots(bp)
            if len(slots) <= 1:
                L.append('# ' + (ptext(slots[0]).strip() if slots else b.text))
            else:
                L.append(':::cover')
                L += [ptext(p).strip() for p in slots]
                L.append(':::')
            L.append('')
            continue
        sp = block_spec(bp, kit, b, with_class=True)
        if sp is None:
            continue
        t = sp['type']
        if t == 'like':
            L.append(f'@like {sp["from"]} | {sp["text"]}')
            continue
        if t == 'clone':
            if sp.get('paras'):
                body = {k: v for k, v in sp.items() if k not in ('class',)}
                L += ['', '```json', json.dumps(body, ensure_ascii=False, indent=1), '```', '']
            else:
                L.append(f'@clone {sp["from"]}')
            continue
        dc = _default_cls(kit, sp)
        tag = '' if (dc == sp.get('class') or not sp.get('class')) else '{%s} ' % sp['class']
        pb = ['<!-- pagebreak -->'] if sp.get('page_break') else []
        if t == 'heading':
            L += [''] + pb + ['## ' + tag + sp['text']]
        elif t == 'bullet':
            L += pb + ['  ' * (sp.get('level', 1) - 1) + '- ' + tag + sp['text']]
        elif t in ('numbered', 'paragraph'):
            L += pb + [tag + sp['text']]
        elif t == 'box':
            L += [''] + pb + [':::box ' + tag + (sp.get('title') or '')]
            L += sp['lines']
            L += [':::', '']
        elif t == 'table':
            hdr = sp.get('header') or []
            rows = sp.get('rows') or []
            spans = any(isinstance(c, dict) for rw in hdr + rows for c in rw)
            ncols = _ncols(sp)
            if spans or not hdr or ncols > 10:
                body = {k: v for k, v in sp.items() if k != 'align'}
                L += ['', '```json', json.dumps(body, ensure_ascii=False, indent=1), '```', '']
            else:
                L += ['']
                if tag:
                    L.append('<!-- class: %s -->' % sp['class'])
                L += pb
                L.append('| ' + ' | '.join(_cell_md(c) for c in hdr[0]) + ' |')
                L.append('|' + '|'.join(['---'] * ncols) + '|')
                for rw in rows:
                    L.append('| ' + ' | '.join(_cell_md(c) for c in rw) + ' |')
                L.append('')
    text = chr(10).join(L)
    while chr(10) * 3 in text:
        text = text.replace(chr(10) * 3, chr(10) * 2)
    return text.strip() + chr(10)
