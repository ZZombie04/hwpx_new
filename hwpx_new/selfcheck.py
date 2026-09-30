# -*- coding: utf-8 -*-
"""서식 재현 점검: 결과 문서(또는 서식 자신을 다시 조립한 문서)를 원본 서식과 '겉모양'으로 비교한다.

- 블록(문단·표)마다 글자 크기·색·굵기·정렬·들여쓰기·줄간격·표 테두리/칸 색을 실제 값으로 풀어 비교한다.
- `hwpx-new selfcheck 서식.hwpx` : 서식의 내용을 뼈대 Markdown 으로 뽑아 다시 조립해 보고, 얼마나 같은지 알려 준다.
"""
from __future__ import annotations

import difflib
import os
import re
import shutil
import tempfile
from collections import Counter

from .package import HP, Package
from .styleprint import Styles, block_fp, blank_height, diff_blocks


def fingerprints(path):
    pk = Package(path)
    st = Styles(pk.header().root)
    root = pk.section_root(0)
    vis, gaps = [], []
    acc = 0.0
    for p in root.findall(HP + 'p'):
        fp = block_fp(p, st)
        if fp['kind'] == 'blank':
            acc += blank_height(fp)
            continue
        if fp['kind'] == 'image':
            continue
        vis.append(fp)
        gaps.append(acc)
        acc = 0.0
    return vis, gaps


def key_of(fp):
    if fp['kind'] == 't':
        for c in fp['tbl']['cells']:
            for p in c['paras']:
                if p['text'].strip():
                    return 't:' + p['text'].strip()[:16]
        return 't:'
    return 'p:' + fp['outer']['text'].strip()[:16]


def compare(a_path, b_path):
    """a(서식) 와 b(결과)를 블록 대응시켜 겉모양 차이를 센다."""
    A, ga = fingerprints(a_path)
    B, gb = fingerprints(b_path)
    ka, kb = [key_of(x) for x in A], [key_of(x) for x in B]
    sm = difflib.SequenceMatcher(None, ka, kb, autojunk=False)
    pairs = []
    for tag, i1, i2, j1, j2 in sm.get_opcodes():
        if tag == 'equal':
            pairs += [(i1 + k, j1 + k) for k in range(i2 - i1)]
        elif tag == 'replace' and (i2 - i1) == (j2 - j1):
            pairs += [(i1 + k, j1 + k) for k in range(i2 - i1)]
    stats = Counter()
    bad_blocks = []
    gap_bad = []
    for i, j in pairs:
        d = diff_blocks(A[i], B[j], f'#{i}')
        if d:
            bad_blocks.append((i, d))
            for path, _x, _y in d:
                stats[path.split('.')[-1]] += 1
        if abs(ga[i] - gb[j]) > 3.0:
            gap_bad.append((i, round(ga[i], 1), round(gb[j], 1)))
    return {'orig_blocks': len(A), 'new_blocks': len(B), 'matched': len(pairs),
            'style_bad_blocks': len(bad_blocks), 'gap_bad': len(gap_bad), 'stats': stats,
            'details': bad_blocks, 'gap_details': gap_bad, 'A': A, 'B': B}


def run_selfcheck(template, out_dir=None, md=True, with_class=False, keep=False):
    """서식을 뼈대 Markdown(또는 종류 지정 블록)으로 풀었다가 다시 조립해 원본과 비교한다."""
    from .analyze import scaffold_markdown
    from .builder import Builder
    from .mdparse import parse_markdown
    from .reflow import blueprint_specs
    work = out_dir or tempfile.mkdtemp(prefix='hwpx_new_sc_')
    os.makedirs(work, exist_ok=True)
    orig = os.path.join(work, 'orig.hwpx')
    shutil.copyfile(template, orig)
    b = Builder(orig)
    if md:
        text = scaffold_markdown(b.bp)
        open(os.path.join(work, 'skeleton.md'), 'w', encoding='utf-8').write(text)
        specs = parse_markdown(text)
    else:
        specs = blueprint_specs(b.bp, b.kit, with_class=with_class)
    els, _probes = b.build(specs)
    rebuilt = os.path.join(work, 'rebuilt.hwpx')
    b.write(els, rebuilt, title=os.path.splitext(os.path.basename(template))[0])
    r = compare(orig, rebuilt)
    r.update(orig=orig, rebuilt=rebuilt, specs=specs, warnings=b.warnings, work=work)
    m = max(1, r['matched'])
    r['score'] = round(100.0 * (m - r['style_bad_blocks']) / m, 1)
    if not keep and out_dir is None:
        pass
    return r


FIELD_KO = {'size': '글자 크기', 'color': '글자 색', 'bold': '굵기', 'italic': '기울임', 'under': '밑줄', 'face': '글꼴',
            'align': '정렬', 'left': '왼쪽 여백', 'right': '오른쪽 여백', 'intent': '내어쓰기', 'prev': '문단 앞 간격',
            'next': '문단 뒤 간격', 'ls': '줄 간격', 'border': '표 테두리·칸 색', 'w': '표 열 너비', 'margin': '칸 안 여백',
            'span': '칸 병합', 'shape': '표 크기', 'inline': '표 배치', 'pb': '쪽 나눔', 'vertAlign': '칸 세로 정렬'}


def report(r, verbose=False):
    L = [f'서식 재현도: {r["score"]}%  (대응한 {r["matched"]}개 블록 중 {r["matched"] - r["style_bad_blocks"]}개가 원본과 같은 모양)']
    if r['stats']:
        top = ', '.join(f'{FIELD_KO.get(k.split(".")[-1], k)} {v}' for k, v in r['stats'].most_common(6))
        L.append(f'  다른 점 — {top}')
    if r['gap_bad']:
        L.append(f'  블록 사이 간격이 다른 곳 {r["gap_bad"]}곳')
    if r.get('warnings'):
        L += ['  경고: ' + w for w in r['warnings'][:5]]
    if verbose:
        for i, d in r['details'][:15]:
            L.append(f'  블록#{i} {key_of(r["A"][i])}')
            for path, x, y in d[:5]:
                L.append(f'     {path}: 원본={x} 결과={y}')
    return chr(10).join(L)
