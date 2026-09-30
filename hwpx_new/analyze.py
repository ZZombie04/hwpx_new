# -*- coding: utf-8 -*-
"""서식(HWPX) 분석: 문서를 '역할이 있는 블록'(표지·소제목·표·박스·글머리…)의 나열로 해석한다."""
from __future__ import annotations

import re
from dataclasses import dataclass, field

from .package import HH, HP, NS, Head, Package

HEADING_RE = re.compile(r'^\s*([ⅠⅡⅢⅣⅤⅥⅦⅧⅨⅩⅰⅱⅲⅳⅴⅵⅶⅷⅸⅹ]+|\d{1,2}|[가-힣]|[IVX]+)\s*[\.\)]\s*\S')
NUMBERED_RE = re.compile(r'^\s*(\d{1,2}\s*[\.\)]|[가-힣]\s*[\.\)]|\(\d{1,2}\)|[①-⑳])\s*\S')
BULLET_CHARS = '○●□■◦◎◆◇▶▷▪▫•ㆍ·※-–—*◈▣❍❏❖➢➔✓☞'


def is_bullet_start(s: str) -> bool:
    s = s.lstrip()
    if not s:
        return False
    ch = s[0]
    if '' <= ch <= '':
        return True
    return ch in BULLET_CHARS and len(s) > 1 and s[1] in '  	'


def bullet_marker(s: str) -> str:
    m = re.match(r'^(\s*(?:[%s]|[-])\s*)' % re.escape(BULLET_CHARS), s)
    return m.group(1) if m else ''


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


@dataclass
class Blueprint:
    path: str
    pkg: Package
    head: Head
    root: object
    blocks: list
    page: dict
    section_count: int


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


def analyze(path: str) -> Blueprint:
    pkg = Package(path)
    head = pkg.header()
    root = pkg.section_root(0)
    blocks = []
    for i, p in enumerate(root.findall(HP + 'p')):
        b = Block(idx=i, el=p)
        b.text = ptext(p)
        b.info['para_pr'] = p.get('paraPrIDRef')
        b.info['style'] = p.get('styleIDRef')
        b.info['has_sec'] = p.find('.//' + HP + 'secPr') is not None
        b.info['font'] = max_font(p, head)
        tbl = table_of(p)
        if tbl is not None:
            cells = table_grid(tbl, head)
            rows = int(tbl.get('rowCnt'))
            cols = int(tbl.get('colCnt'))
            b.info.update(tbl=tbl, cells=cells, rows=rows, cols=cols)
            texts = [c['text'] for c in cells if c['text'].strip()]
            b.text = ' | '.join(t.replace('\n', ' / ') for t in texts)
            nonempty = len(texts)
            fills = [c for c in cells if c['filled']]
            if cols == 1 and rows <= 2 and nonempty <= 1 and texts and len(texts[0]) < 60:
                b.role = 'heading'
            elif cols == 1 and rows == 1:
                b.role = 'box'
            else:
                b.role = 'table'
            b.info['fills'] = len(fills)
        else:
            t = b.text.strip()
            para = head.para.get(b.info['para_pr'], {})
            OBJ = ('pic', 'rect', 'line', 'ellipse', 'arc', 'polygon', 'curve', 'container', 'ole', 'equation',
                   'textart', 'video', 'chart', 'connectLine')
            has_obj = any(ch.tag.split('}')[1] in OBJ for run in p.findall(HP + 'run') for ch in run)
            if not t and has_obj:
                b.role = 'image'
            elif not t:
                b.role = 'blank'
            elif is_bullet_start(b.text):
                b.role = 'bullet'
                b.info['marker'] = bullet_marker(b.text)
            elif NUMBERED_RE.match(b.text) and not (
                    HEADING_RE.match(b.text) and b.info['font'] >= 1500 and len(t) < 40):
                b.role = 'numbered'
            elif HEADING_RE.match(b.text) and len(t) < 40 and b.info['font'] >= 1400:
                b.role = 'heading_text'
            else:
                b.role = 'paragraph'
            b.info['align'] = para.get('align')
            b.info['left'] = para.get('left', 0)
            b.info['intent'] = para.get('intent', 0)
        blocks.append(b)

    # ---- 표지(제목) 판정: 앞쪽 3블록 중 처음으로 글이 있고 번호 머리말이 아닌 블록
    for b in blocks[:4]:
        if b.role == 'blank' or not b.text.strip():
            continue
        if HEADING_RE.match(b.text.split(' | ')[0]) and b.info['font'] < 2000 and b.role in ('heading', 'heading_text'):
            break
        if b.role in ('table', 'heading', 'box', 'heading_text', 'paragraph'):
            if b.role == 'paragraph' and b.info['font'] < 1400 and not b.info['has_sec']:
                break
            b.role = 'title'
        break

    # ---- 부제(표지 아래 짧은 오른쪽·가운데 정렬 문단)
    seen_title = False
    for b in blocks[:8]:
        if b.role == 'title':
            seen_title = True
            continue
        if seen_title and b.role == 'paragraph' and len(b.text.strip()) < 45 \
                and b.info.get('align') in ('RIGHT', 'CENTER'):
            b.role = 'subtitle'
            break
        if b.role in ('heading', 'table', 'bullet', 'box'):
            break

    return Blueprint(path=path, pkg=pkg, head=head, root=root, blocks=blocks,
                     page=page_info(root), section_count=len(pkg.section_names()))


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


def blueprint_markdown(bp: Blueprint) -> str:
    """AI 가 읽고 '이 서식이 어떤 문서인지' 파악할 수 있는 요약."""
    L = []
    pg = bp.page
    L.append(f'# 서식 분석: {bp.path}')
    L.append('')
    L.append(f'- 용지: {pg["width"] / 283.46:.0f}×{pg["height"] / 283.46:.0f}mm, 본문 폭 {pg["text_width"]} HWPUNIT, '
             f'여백 좌{pg["left"]} 우{pg["right"]} 상{pg["top"]} 하{pg["bottom"]}')
    L.append(f'- 구역(섹션) 수: {bp.section_count}' + (' (첫 구역만 사용)' if bp.section_count > 1 else ''))
    roles = {}
    for b in bp.blocks:
        roles[b.role] = roles.get(b.role, 0) + 1
    L.append('- 블록 구성: ' + ', '.join(f'{ROLE_KO.get(k, k)} {v}' for k, v in roles.items()))
    heads = [b for b in bp.blocks if b.role in ('heading', 'heading_text')]
    if heads:
        L.append('- 문서 뼈대(소제목): ' + ' → '.join(b.text.split(' | ')[0] for b in heads))
    L.append('')
    L.append('## 블록 목록 (위에서 아래 순서)')
    L.append('')
    for b in bp.blocks:
        if b.role == 'blank':
            continue
        head = f'[{b.idx:02d}] **{ROLE_KO.get(b.role, b.role)}**'
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
            if b.role == 'title':
                fields = [ptext(p) for p in b.el.iter(HP + 'p') if ptext(p).strip()]
                if len(fields) > 1:
                    L.append(f'    - 글 칸 {len(fields)}개(fields 로 순서대로 교체 가능): ' + ' | '.join(f[:14] for f in fields))
    return '\n'.join(L)


def scaffold_markdown(bp: Blueprint) -> str:
    """서식 뼈대를 그대로 따르는 Markdown 초안(내용은 ‘…’). AI 가 이 골격을 새 문서 내용으로 바꿔 쓴다."""
    L = []
    for b in bp.blocks:
        r = b.role
        if r == 'title':
            L.append(f'# {b.text.split(" | ")[0] if b.text else "제목"}')
        elif r == 'subtitle':
            L.append(f'@subtitle {b.text.strip()}')
        elif r in ('heading', 'heading_text'):
            L.append('')
            L.append(f'## {b.text.split(" | ")[0]}')
        elif r == 'table' and b.info['cols'] > 12:
            L.append('')
            L.append(f'<!-- [{b.idx}]번 블록: 격자형 표(열 {b.info["cols"]}개). 글만 바꾸려면 JSON 블록 {{"type":"clone","from":{b.idx},"texts":[...]}} 사용 -->')
            L.append('')
        elif r == 'table':
            prev = _cell_preview(b.info['cells'], b.info['cols'])
            hdr = prev[0]
            L.append('')
            if _has_span(b.info['cells']):
                L.append('<!-- 병합 셀이 있는 표: 같은 모양이 필요하면 JSON 블록(header 를 목록의 목록, colspan/rowspan)으로 작성 -->')
            L.append('| ' + ' | '.join(hdr) + ' |')
            L.append('|' + '|'.join([':-:'] * len(hdr)) + '|')
            for row in prev[1:4]:
                L.append('| ' + ' | '.join(row) + ' |')
            if len(prev) > 4:
                L.append('| … |' + ' |' * (len(hdr) - 1))
            L.append('')
        elif r == 'box':
            L.append('')
            L.append(':::box')
            for ln in b.text.split(' | ')[0].split(' / '):
                L.append(ln)
            L.append(':::')
            L.append('')
        elif r == 'bullet':
            L.append('- ' + b.text.strip().lstrip(BULLET_CHARS + ''.join(chr(c) for c in range(0xf000, 0xf100))).strip())
        elif r == 'numbered':
            L.append(b.text.strip())
        elif r == 'paragraph':
            L.append(b.text.strip())
    return '\n'.join(L).strip() + '\n'


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
