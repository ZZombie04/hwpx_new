# -*- coding: utf-8 -*-
"""서식(HWPX) 분석: 문서를 '역할이 있는 블록'(표지·소제목·표·박스·글머리…)의 나열로 해석하고,
같은 모양의 블록끼리 '서식 종류(class)'로 묶는다."""
from __future__ import annotations

import re
import unicodedata
from collections import Counter
from dataclasses import dataclass, field

from .package import HH, HP, NS, Head, Package

ROMAN = 'ⅠⅡⅢⅣⅤⅥⅦⅧⅨⅩⅪⅫⅰⅱⅲⅳⅴⅵⅶⅷⅸⅹ'
HEADING_RE = re.compile(r'^\s*([%s]+|\d{1,2}|[가-힣]|[IVX]+)\s*[\.\)]\s*\S' % ROMAN)
NUMBERED_RE = re.compile(r'^\s*(\d{1,2}\s*[\.\)]|[가-힣]\s*[\.\)]|\(\d{1,2}\)|\([가-힣]\)|[①-⑳㉮-㉻⑴-⒇])\s*\S')
BULLET_CHARS = '○●□■◦◎◆◇▶▷▪▫•ㆍ·※-–—*◈▣❍❏❖➢➔✓☞'


def _symbol_char(ch: str) -> bool:
    o = ord(ch)
    if 0xE000 <= o <= 0xF8FF:          # 한글 글머리표(사용자 정의 영역)
        return True
    if 0x3131 <= o <= 0x318E:          # 한글 자모: 'ㅇ' 'ㅁ' 같은 글머리
        return True
    return unicodedata.category(ch)[0] in 'SP'


def bullet_marker(s: str) -> str:
    """문단 앞머리의 글머리 기호(앞뒤 공백 포함). 없으면 ''."""
    t = s.lstrip()
    lead = s[:len(s) - len(t)]
    if not t:
        return ''
    if 0xE000 <= ord(t[0]) <= 0xF8FF:
        m = re.match(r'^(\S)(\s*)', t)
        return lead + m.group(0)
    m = re.match(r'^(\S{1,2})(\s+)', t)
    if m and len(t) > len(m.group(0)) and all(_symbol_char(c) for c in m.group(1)):
        return lead + m.group(0)
    return ''


def is_bullet_start(s: str) -> bool:
    return bool(bullet_marker(s))


def ptext(p) -> str:
    """문단 자체(중첩 표 제외)의 텍스트."""
    out = []
    for run in p.findall(HP + 'run'):
        for t in run.findall(HP + 't'):
            out.append(''.join(t.itertext()))
    return ''.join(out)


def cell_paragraphs(tc):
    sub = tc.find(HP + 'subList')
    return sub.findall(HP + 'p') if sub is not None else []


def cell_text(tc) -> str:
    return '\n'.join(ptext(p) for p in cell_paragraphs(tc))


@dataclass
class Block:
    idx: int
    el: object
    role: str = 'paragraph'
    text: str = ''
    info: dict = field(default_factory=dict)
    cls: str = ''


@dataclass
class Blueprint:
    path: str
    pkg: Package
    head: Head
    root: object
    blocks: list
    page: dict
    section_count: int
    classes: dict = field(default_factory=dict)
    body_size: int = 1000
    cover_end: int = 0            # 표지로 본 블록은 0 ≤ idx < cover_end
    styles: object = None


def table_of(p):
    """최상위 문단 안의 표(직접 자식 run 안). 없으면 None."""
    for run in p.findall(HP + 'run'):
        t = run.find(HP + 'tbl')
        if t is not None:
            return t
    return None


def table_grid(tbl, head: Head):
    cells = []
    for tr in tbl.findall(HP + 'tr'):
        for tc in tr.findall(HP + 'tc'):
            addr = tc.find(HP + 'cellAddr')
            span = tc.find(HP + 'cellSpan')
            sz = tc.find(HP + 'cellSz')
            ps = cell_paragraphs(tc)
            first = ps[0] if ps else None
            char = None
            if first is not None:
                r = first.find(HP + 'run')
                char = r.get('charPrIDRef') if r is not None else None
            cells.append({
                'el': tc,
                'r': int(addr.get('rowAddr')), 'c': int(addr.get('colAddr')),
                'rs': int(span.get('rowSpan')), 'cs': int(span.get('colSpan')),
                'w': int(sz.get('width')), 'h': int(sz.get('height')),
                'bf': tc.get('borderFillIDRef'),
                'text': cell_text(tc),
                'para_pr': first.get('paraPrIDRef') if first is not None else None,
                'style': first.get('styleIDRef') if first is not None else '0',
                'char': char,
                'filled': head.has_fill(tc.get('borderFillIDRef')),
            })
    return cells


def max_font(el, head: Head) -> int:
    best = 0
    for run in el.iter(HP + 'run'):
        cid = run.get('charPrIDRef')
        if cid is not None and any(True for _ in run.iter(HP + 't')):
            best = max(best, head.size(cid))
    return best


def page_info(root) -> dict:
    pp = root.find('.//' + HP + 'pagePr')
    if pp is None:
        return {'width': 59528, 'height': 84188, 'left': 5669, 'right': 5669, 'top': 4252, 'bottom': 4252,
                'text_width': 48190}
    m = pp.find(HP + 'margin')
    w, h = int(pp.get('width')), int(pp.get('height'))
    l, r = int(m.get('left')), int(m.get('right'))
    return {'width': w, 'height': h, 'left': l, 'right': r, 'top': int(m.get('top')),
            'bottom': int(m.get('bottom')), 'text_width': w - l - r}


# ---------------------------------------------------------------- 보조 판정
OBJ_TAGS = ('pic', 'rect', 'line', 'ellipse', 'arc', 'polygon', 'curve', 'container', 'ole', 'equation',
            'textart', 'video', 'chart', 'connectLine')


def _has_obj(p) -> bool:
    return any(ch.tag.split('}')[1] in OBJ_TAGS for run in p.findall(HP + 'run') for ch in run)


def first_char_id(p):
    """문단에서 글이 있는 첫 run 의 글자 서식 번호."""
    for r in p.findall(HP + 'run'):
        if any(''.join(t.itertext()).strip() for t in r.findall(HP + 't')):
            return r.get('charPrIDRef')
    r = p.find(HP + 'run')
    return r.get('charPrIDRef') if r is not None else None


def body_char_id(p):
    """문단에서 글자가 가장 많은 덩어리(본문)의 글자 서식 번호."""
    best, bn = None, -1
    for r in p.findall(HP + 'run'):
        n = sum(len(''.join(t.itertext()).strip()) for t in r.findall(HP + 't'))
        if n > bn:
            best, bn = r.get('charPrIDRef'), n
    return best


def text_runs(p) -> int:
    return sum(1 for r in p.findall(HP + 'run') if any(''.join(t.itertext()).strip() for t in r.findall(HP + 't')))


def _body_size(root, head: Head) -> int:
    cnt = Counter()
    for p in root.findall(HP + 'p'):
        if table_of(p) is not None:
            continue
        for r in p.findall(HP + 'run'):
            n = sum(len(''.join(t.itertext()).strip()) for t in r.findall(HP + 't'))
            if n:
                cnt[head.size(r.get('charPrIDRef'))] += n
    if not cnt:
        # 글 대부분이 표 안에 있는 문서: 표 안 글자로 판단
        for p in root.iter(HP + 'p'):
            for r in p.findall(HP + 'run'):
                n = sum(len(''.join(t.itertext()).strip()) for t in r.findall(HP + 't'))
                if n:
                    cnt[head.size(r.get('charPrIDRef'))] += n
    return cnt.most_common(1)[0][0] if cnt else 1000


def _is_bold(head_root_cache, head: Head, cid) -> bool:
    return bool(head.char.get(str(cid), {}).get('bold'))


def heading_class(text: str) -> str:
    """소제목 번호 종류: roman(Ⅰ.) · num(1.) · hangul(가.) · symbol(■ ◆ …) · plain."""
    t = (text or '').strip()
    if re.match(r'^[%s]+\s*[\.\)]?(\s|$)' % ROMAN, t):
        return 'roman'
    if re.match(r'^\d{1,2}\s*[\.\)]', t):
        return 'num'
    if re.match(r'^[가-힣]\s*[\.\)]', t):
        return 'hangul'
    if bullet_marker(t):
        return 'symbol'
    return 'plain'


def _classify_table(b: Block, head: Block, body_size: int):
    cells = b.info['cells']
    rows, cols = b.info['rows'], b.info['cols']
    texts = [c['text'].strip() for c in cells if c['text'].strip()]
    nonempty = len(texts)
    total = sum(len(t) for t in texts)
    has_pic = any(True for _ in b.el.iter(HP + 'pic'))
    has_nested = len(b.el.findall('.//' + HP + 'tbl')) > 1
    b.info['has_pic'] = has_pic
    if has_nested or has_pic:
        return 'table'
    if cols == 1 and rows <= 2 and nonempty <= 1 and texts and len(texts[0]) < 60:
        return 'heading'
    if cols == 1 and rows == 1:
        return 'box'
    if rows <= 2 and 2 <= cols <= 5 and nonempty <= 3 and total < 60:
        # 'Ⅰ | 운영 개요' 처럼 번호 칸 + 제목 칸으로 된 소제목 줄
        first = texts[0] if texts else ''
        numbered_first = len(first) <= 3 and not first.isdigit() or bool(HEADING_RE.match(first + '. x')) or len(first) <= 2
        one_row_fill = any(c['filled'] for c in cells)
        if rows == 1 and (numbered_first or nonempty == 1) and one_row_fill:
            return 'heading'
    return 'table'


def _classify_paragraph(b: Block, styles, body_size: int):
    t = b.text.strip()
    p = b.el
    para = styles.para.get(b.info['para_pr'], {})
    size = b.info['font']
    has_obj = _has_obj(p)
    if not t and has_obj:
        return 'image'
    if not t:
        return 'blank'
    mk = bullet_marker(b.text)
    if mk:
        b.info['marker'] = mk
        return 'bullet'
    auto = para.get('heading', 'NONE')
    if auto in ('BULLET', 'NUMBER', 'OUTLINE'):
        b.info['marker'] = ''
        b.info['auto_list'] = auto
        return 'bullet'
    short = len(t) < 50
    endsdot = t.endswith(('.', '다', '함', '음', '임', '됨'))
    first_cid = first_char_id(p)
    bold = bool(styles.char.get(str(first_cid), {}).get('bold'))
    if NUMBERED_RE.match(b.text):
        if HEADING_RE.match(b.text) and size >= max(1500, body_size + 100) and short:
            return 'heading_text'
        return 'numbered'
    if HEADING_RE.match(b.text) and short and size >= 1400 and size >= body_size:
        return 'heading_text'
    if short and not endsdot and size >= body_size + 200 and (bold or size >= body_size + 400):
        return 'heading_text'
    return 'paragraph'


def _char_look(st, cid):
    c = st.char.get(str(cid), {})
    return (c.get('size'), c.get('color'), c.get('bold'), c.get('italic'), c.get('under'), c.get('face'))


def _para_look(st, pid):
    p = st.para.get(str(pid), {})
    return (p.get('align') if p.get('align') != 'LEFT' else 'JUSTIFY', round(p.get('left', 0) / 200), round(p.get('intent', 0) / 200),
            p.get('ls_type'), round((p.get('ls') or 0) / 5), round(p.get('prev', 0) / 100), round(p.get('next', 0) / 100),
            p.get('heading'))


def _border_look(st, bid):
    b = st.border.get(str(bid))
    if not b:
        return None
    return (b['fill'], b['left'], b['right'], b['top'], b['bottom'])


def _signature(b: Block, st):
    """같은 '모양'의 블록을 같은 종류로 묶기 위한 지문(스타일 번호가 달라도 모양이 같으면 같은 것)."""
    if b.info.get('tbl') is not None:
        cells = b.info['cells']

        def row_sig(r):
            return tuple((c['c'], _border_look(st, c['bf']), _char_look(st, c['char']), _para_look(st, c['para_pr']))
                         for c in sorted(cells, key=lambda x: x['c']) if c['r'] == r)
        tw = sum(c['w'] for c in cells if c['r'] == 0) or 1
        ratios = tuple(round(100.0 * c['w'] / tw / 5) for c in sorted(cells, key=lambda x: x['c']) if c['r'] == 0)
        return ('t', b.role, b.info['cols'], row_sig(0), row_sig(1), b.info.get('pos_inline'), ratios)
    return (b.role, _para_look(st, b.info['para_pr']), b.info['style'], _char_look(st, b.info.get('first_char')),
            _char_look(st, b.info.get('body_char')), b.info.get('marker', '').strip())


PREFIX = {'title': 'C', 'subtitle': 'S', 'heading': 'H', 'heading_text': 'G', 'bullet': 'B', 'numbered': 'N',
          'paragraph': 'P', 'table': 'T', 'box': 'X', 'image': 'I', 'blank': 'Z'}


def analyze(path: str) -> Blueprint:
    pkg = Package(path)
    head = pkg.header()
    root = pkg.section_root(0)
    from .styleprint import Styles
    styles = Styles(head.root)
    body = _body_size(root, head)
    blocks = []
    for i, p in enumerate(root.findall(HP + 'p')):
        b = Block(idx=i, el=p)
        b.text = ptext(p)
        b.info['para_pr'] = p.get('paraPrIDRef')
        b.info['style'] = p.get('styleIDRef')
        b.info['has_sec'] = p.find('.//' + HP + 'secPr') is not None
        b.info['font'] = max_font(p, head)
        b.info['first_char'] = first_char_id(p)
        b.info['body_char'] = body_char_id(p)
        b.info['nruns'] = text_runs(p)
        tbl = table_of(p)
        if tbl is not None:
            cells = table_grid(tbl, head)
            rows = int(tbl.get('rowCnt'))
            cols = int(tbl.get('colCnt'))
            pos = tbl.find(HP + 'pos')
            b.info.update(tbl=tbl, cells=cells, rows=rows, cols=cols,
                          pos_inline=(pos.get('treatAsChar') if pos is not None else None))
            texts = [c['text'] for c in cells if c['text'].strip()]
            b.text = ' | '.join(t.replace('\n', ' / ') for t in texts)
            b.info['fills'] = len([c for c in cells if c['filled']])
            b.role = _classify_table(b, head, body)
        else:
            b.role = _classify_paragraph(b, styles, body)
            para = head.para.get(b.info['para_pr'], {})
            b.info['align'] = para.get('align')
            b.info['left'] = para.get('left', 0)
            b.info['intent'] = para.get('intent', 0)
        blocks.append(b)

    cover_end = _mark_cover(blocks, body)

    # ---- 서식 종류(class) 묶기: 같은 모양의 블록끼리
    classes = {}
    by_role_sig = {}
    for b in blocks:
        b.info['sig'] = _signature(b, styles)
        key = (b.role, b.info['sig'])
        by_role_sig.setdefault(b.role, {}).setdefault(b.info['sig'], []).append(b)
    for role, sigs in by_role_sig.items():
        order = sorted(sigs.values(), key=lambda lst: lst[0].idx)
        for n, lst in enumerate(order, 1):
            cid = f'{PREFIX.get(role, "Q")}{n}'
            for b in lst:
                b.cls = cid
            classes[cid] = {'role': role, 'blocks': [b.idx for b in lst], 'count': len(lst),
                            'cover': sum(1 for b in lst if b.idx < cover_end)}
    return Blueprint(path=path, pkg=pkg, head=head, root=root, blocks=blocks, page=page_info(root),
                     section_count=len(pkg.section_names()), classes=classes, body_size=body, cover_end=cover_end,
                     styles=styles)


def _mark_cover(blocks, body) -> int:
    """문서 맨 앞의 표지 부분(본문이 시작되기 전까지)을 찾는다. 반환: 본문 첫 블록의 번호(표지 끝)."""
    end = 0
    seen_visible = False
    for b in blocks[:30]:
        r = b.role
        stop = False
        if r in ('heading', 'bullet', 'numbered', 'box') and seen_visible:
            stop = True
        elif r == 'heading_text' and seen_visible and b.info.get('font', 0) < body + 300:
            stop = True
        elif r == 'paragraph' and len(b.text.strip()) >= 25 and b.info.get('font', 0) <= body + 100 \
                and b.info.get('align') not in ('CENTER',) and seen_visible:
            stop = True
        elif r == 'table' and seen_visible and b.info.get('rows', 0) >= 3 and b.info.get('cols', 0) >= 2 \
                and b.info.get('font', 0) <= body + 100:
            stop = True
        if stop:
            break
        if r not in ('blank', 'image'):
            seen_visible = True
        end = b.idx + 1
    # 본문 시작 전에 끝나는 빈 줄은 표지에 넣지 않는다
    while end > 0 and blocks[end - 1].role == 'blank':
        end -= 1
    for b in blocks[:end]:
        b.info['cover'] = True
    # 표지 안에서 가장 큰 글자를 가진 블록 = 제목 칸
    best = None
    for b in blocks[:end]:
        if b.role in ('blank', 'image'):
            continue
        key = (b.info.get('font', 0), len(b.text))
        if best is None or key > best[0]:
            best = (key, b)
    if best is not None and end > 0:
        best[1].info['title_slot'] = True
        best[1].role = 'title'
    return end


# ---------------------------------------------------------------- 사람이 읽는 보고서
ROLE_KO = {
    'title': '표지/제목', 'subtitle': '부제(작성 부서 등)', 'heading': '소제목(표형)', 'heading_text': '소제목(글)',
    'table': '표', 'box': '강조 박스', 'bullet': '글머리 문단', 'numbered': '번호 문단',
    'paragraph': '본문', 'blank': '빈 줄', 'image': '그림/도형 문단',
}


def _cell_preview(cells, cols, header_rows=1):
    """병합을 고려한 격자(2차원 목록). 병합으로 가려진 칸은 빈 문자열."""
    nrows = max((c['r'] + c['rs'] for c in cells), default=0)
    grid = [[''] * cols for _ in range(nrows)]
    for c in cells:
        if c['r'] < nrows and c['c'] < cols:
            grid[c['r']][c['c']] = c['text'].replace(chr(10), ' / ')
    return grid


def _has_span(cells):
    return any(c['rs'] > 1 or c['cs'] > 1 for c in cells)


def describe_class(bp: Blueprint, cid: str) -> str:
    """서식 종류 하나를 '14pt 굵게 파랑 · 가운데 · 들여쓰기 …' 로 설명."""
    from .styleprint import Styles
    st = bp.styles or Styles(bp.head.root)
    info = bp.classes[cid]
    b = bp.blocks[info['blocks'][0]]
    parts = []
    if b.info.get('tbl') is not None:
        cells = b.info['cells']
        fills = {st.border.get(str(c['bf']), {}).get('fill') for c in cells if c['filled']}
        fills.discard(None)
        parts.append(f'{b.info["rows"]}행×{b.info["cols"]}열')
        if fills:
            parts.append('머리/칸 색 ' + '·'.join(sorted(fills)[:2]))
        c0 = cells[0] if cells else None
        if c0 and c0.get('char') is not None:
            ch = st.char.get(str(c0['char']), {})
            parts.append(f'{ch.get("size", 1000) / 100:g}pt')
    else:
        ch = st.char.get(str(b.info.get('first_char')), {})
        pp = st.para.get(b.info['para_pr'], {})
        seg = f'{ch.get("size", 1000) / 100:g}pt'
        if ch.get('bold'):
            seg += ' 굵게'
        if ch.get('color') and ch['color'] not in ('#000000', '#111111'):
            seg += ' ' + ch['color']
        parts.append(seg)
        al = {'CENTER': '가운데', 'RIGHT': '오른쪽', 'LEFT': '왼쪽', 'JUSTIFY': '양쪽'}.get(pp.get('align'), '')
        if al:
            parts.append(al)
        if pp.get('left') or pp.get('intent'):
            parts.append(f'들여쓰기 {pp.get("left", 0)}/{pp.get("intent", 0)}')
        if b.role == 'bullet':
            mk = b.info.get('marker', '').strip()
            if mk:
                parts.append(f'기호 "{mk}"')
    return ' · '.join(parts)


def blueprint_markdown(bp: Blueprint) -> str:
    """AI 가 읽고 '이 서식이 어떤 문서인지' 파악할 수 있는 요약."""
    L = []
    pg = bp.page
    L.append(f'# 서식 분석: {bp.path}')
    L.append('')
    L.append(f'- 용지: {pg["width"] / 283.46:.0f}×{pg["height"] / 283.46:.0f}mm, 본문 폭 {pg["text_width"]} HWPUNIT, '
             f'여백 좌{pg["left"]} 우{pg["right"]} 상{pg["top"]} 하{pg["bottom"]}')
    L.append(f'- 구역(섹션) 수: {bp.section_count}' + (' (본문은 첫 구역 기준 — 다른 구역의 블록은 `@clone 구역번호:블록번호` 로 복제)' if bp.section_count > 1 else ''))
    for k in range(1, bp.section_count):
        try:
            ps = bp.pkg.section_root(k).findall(HP + 'p')
            first = [ptext(p).strip()[:14] for p in ps if ptext(p).strip()][:3]
            pg = page_info(bp.pkg.section_root(k))
            L.append(f'  - 구역 {k}: 블록 {len(ps)}개, 용지 {pg["width"] / 283.46:.0f}×{pg["height"] / 283.46:.0f}mm, 앞부분 글: ' + ' | '.join(first))
        except Exception:  # noqa
            pass
    L.append(f'- 기본 글자 크기: {bp.body_size / 100:g}pt')
    roles = {}
    for b in bp.blocks:
        roles[b.role] = roles.get(b.role, 0) + 1
    L.append('- 블록 구성: ' + ', '.join(f'{ROLE_KO.get(k, k)} {v}' for k, v in roles.items()))
    heads = [b for b in bp.blocks if b.role in ('heading', 'heading_text')]
    if heads:
        L.append('- 문서 뼈대(소제목): ' + ' → '.join(b.text.split(' | ')[0] for b in heads))
    if bp.cover_end:
        slots = []
        for b in bp.blocks[:bp.cover_end]:
            for p in b.el.iter(HP + 'p'):
                t = ptext(p).strip()
                if t:
                    slots.append(t[:16])
        L.append(f'- 표지 구간: 0~{bp.cover_end - 1}번 블록. 글 칸 {len(slots)}개: ' + ' | '.join(slots))
    L.append('')
    L.append('## 서식 종류 (같은 모양끼리 묶음 — 내용에서 `{종류}` 로 골라 쓸 수 있음)')
    L.append('')
    order = sorted(bp.classes.items(), key=lambda kv: kv[1]['blocks'][0])
    order = [kv for kv in order if kv[1]['role'] != 'blank']
    shown = set(cid for cid, _ in order)
    if len(order) > 45:                      # 모양 종류가 아주 많은 문서: 자주 쓰인 것 위주로 보여 준다(나머지는 뼈대에 표시로 나옴)
        keep = sorted(order, key=lambda kv: -kv[1]['count'])[:45]
        shown = {cid for cid, _ in keep}
        L.append(f'(모양 종류가 {len(order)}가지라 자주 쓰인 45가지만 보여 줍니다. 나머지는 뼈대 Markdown 의 `{{표시}}` 로 나옵니다.)')
    for cid, info in order:
        if cid not in shown:
            continue
        b = bp.blocks[info['blocks'][0]]
        sample = b.text.split(' | ')[0].strip()[:28]
        L.append(f'- `{cid}` {ROLE_KO.get(info["role"], info["role"])} ×{info["count"]} — {describe_class(bp, cid)}'
                 + (f' — 예) {sample}' if sample else ''))
    L.append('')
    L.append('## 블록 목록 (위에서 아래 순서)')
    L.append('')
    for b in bp.blocks:
        if b.role == 'blank':
            continue
        head = f'[{b.idx:02d}] `{b.cls}` **{ROLE_KO.get(b.role, b.role)}**'
        if b.role in ('table',):
            prev = _cell_preview(b.info['cells'], b.info['cols'])
            head += f' {b.info["rows"]}행×{b.info["cols"]}열'
            if b.info['cols'] > 12:
                head += ' (격자형: clone 블록 권장)'
            L.append(head)
            for i, row in enumerate(prev[:6]):
                L.append(f'    - {"머리" if i == 0 else "행"}: ' + ' | '.join(row))
            if _has_span(b.info['cells']):
                L.append('    - (병합 셀 포함)')
            if len(prev) > 6:
                L.append(f'    - … ({len(prev) - 6}행 더)')
        else:
            t = b.text[:120] + ('…' if len(b.text) > 120 else '')
            L.append(f'{head}: {t}')
    return '\n'.join(L)


def scaffold_markdown(bp: Blueprint) -> str:
    """서식 뼈대를 그대로 따르는 Markdown 초안. AI 가 이 골격을 새 문서 내용으로 바꿔 쓴다."""
    from .reflow import skeleton_markdown
    return skeleton_markdown(bp)


def dump_document(path: str) -> str:
    """HWPX 본문을 Markdown 으로 읽어 낸다(표는 파이프 표)."""
    bp = analyze(path)
    L = []
    for b in bp.blocks:
        if b.role == 'blank':
            continue
        if b.role == 'table':
            rows = _cell_preview(b.info['cells'], b.info['cols'])
            L.append('')
            L.append('| ' + ' | '.join(rows[0]) + ' |')
            L.append('|' + '---|' * len(rows[0]))
            for row in rows[1:]:
                L.append('| ' + ' | '.join(row) + ' |')
            L.append('')
        elif b.role in ('heading', 'heading_text'):
            L.append('')
            L.append('## ' + b.text)
        elif b.role == 'title':
            L.append('# ' + b.text)
        else:
            L.append(b.text)
    return '\n'.join(L).strip() + '\n'
