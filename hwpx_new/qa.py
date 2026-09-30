# -*- coding: utf-8 -*-
"""PDF 조판 점검: 빈 쪽, 소제목만 쪽 끝에 남음, 표가 쪽 사이에서 잘림, 마지막 쪽 토막 등을 찾는다."""
from __future__ import annotations

import re


def _norm(s):
    return re.sub(r'\s+', '', s or '')


def inspect(pdf, probes):
    import pymupdf
    doc = pymupdf.open(pdf)
    pages = []
    for pi, page in enumerate(doc):
        blocks = page.get_text('blocks')
        lines = [b for b in blocks if b[4].strip()]
        body = [b for b in lines if not re.fullmatch(r'\s*[-–]?\s*\d+\s*[-–]?\s*', b[4])]
        H = page.rect.height
        pages.append({
            'index': pi + 1,
            'n_lines': sum(len([x for x in b[4].split('\n') if x.strip()]) for b in body),
            'fill': max([b[3] for b in body], default=0) / H,
            'figure': len(page.get_images()) > 0 or len(page.get_drawings()) > 30,
            'text': page.get_text(),
        })
    # 프로브 위치(순서대로 앞으로만 검색)
    found = {}
    cur_page, cur_y = 0, -1
    for pr in probes:
        locs = []
        first_page = None
        for t in pr['texts']:
            hit = None
            # 한 블록의 첫 글은 앞으로 제한 없이, 같은 블록의 나머지(표의 다음 행 등)는 첫 글이 있는 쪽과 바로 다음 쪽 안에서만 찾는다
            last = len(doc) if first_page is None else min(len(doc), first_page + 2)
            for pi in range(cur_page, last):
                rects = doc[pi].search_for(t[:14]) or doc[pi].search_for(t[:8])
                rects = [r for r in rects if not (pi == cur_page and r.y0 < cur_y - 3)]
                if rects:
                    r = min(rects, key=lambda r: (r.y0, r.x0))
                    hit = (pi, r.y0, r.y1)
                    break
            locs.append(hit)
            if hit:
                cur_page, cur_y = hit[0], hit[1]
                if first_page is None:
                    first_page = hit[0]
        found[pr['i']] = locs
    issues = []
    for p in pages:
        if p['n_lines'] == 0:
            issues.append({'kind': 'blank_page', 'page': p['index']})
    for k, pr in enumerate(probes):
        locs = [l for l in found.get(pr['i'], []) if l]
        typ = pr['type']
        if typ == 'table' and len(locs) >= 2 and locs[0][0] != locs[-1][0]:
            pgs = [l[0] for l in locs]
            # 쪽 사이에서 잘려도 양쪽에 2행 이상 남으면 자연스러운 분할(머리글 반복)로 본다
            if min(pgs.count(pgs[0]), pgs.count(pgs[-1])) < 2 or len(set(pgs)) > 2:
                issues.append({'kind': 'split_table', 'spec': pr['i'], 'page': locs[0][0] + 1})
        if typ == 'heading' and locs and k + 1 < len(probes):
            nxt = [l for l in found.get(probes[k + 1]['i'], []) if l]
            if nxt and nxt[0][0] > locs[0][0]:
                issues.append({'kind': 'orphan_heading', 'spec': pr['i'], 'page': locs[0][0] + 1})
    for p in pages[1:-1]:
        if 0 < p['n_lines'] <= 3 and not p.get('figure'):
            issues.append({'kind': 'short_page', 'page': p['index'], 'lines': p['n_lines']})
    if len(pages) > 1 and pages[-1]['n_lines'] > 0 and (pages[-1]['n_lines'] <= 3 or pages[-1]['fill'] < 0.16):
        issues.append({'kind': 'widow_last_page', 'page': len(pages), 'lines': pages[-1]['n_lines']})
    return {'n_pages': len(pages), 'pages': pages, 'issues': issues, 'probe_pages': {
        i: [(l[0] + 1) if l else None for l in v] for i, v in found.items()}}


ISSUE_KO = {
    'blank_page': '빈 쪽이 있음', 'orphan_heading': '소제목이 쪽 끝에 홀로 남음',
    'split_table': '표가 쪽 사이에서 잘림', 'widow_last_page': '마지막 쪽에 내용이 몇 줄만 남음',
    'short_page': '쪽에 내용이 몇 줄만 있음(앞 쪽에서 넘친 줄)',
}


def describe(issue):
    s = ISSUE_KO.get(issue['kind'], issue['kind'])
    return f'{issue["page"]}쪽: {s}'
