# -*- coding: utf-8 -*-
"""스트레스 시험: 뼈대 Markdown 을 AI 가 고쳐 쓰는 것처럼 바꿔(표 행 추가, 글머리 추가, 블록 삭제, 글 교체) 조립하고,
예외 없이 끝나는지·구조 검증을 통과하는지 본다(코퍼스 전체)."""
import os
import random
import re
import sys
import tempfile
import traceback

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from hwpx_new.analyze import analyze, scaffold_markdown  # noqa: E402
from hwpx_new.builder import Builder  # noqa: E402
from hwpx_new.mdparse import parse_markdown  # noqa: E402
from hwpx_new.validate import validate  # noqa: E402

root = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
lst = [l.strip() for l in open(os.path.join(root, '_out', 'corpus.txt'), encoding='utf-8') if l.strip()]
rnd = random.Random(7)


def mutate(md):
    lines = md.split('\n')
    out = []
    i = 0
    in_fence = False
    while i < len(lines):
        ln = lines[i]
        if ln.startswith('```'):
            in_fence = not in_fence
            out.append(ln)
            i += 1
            continue
        if in_fence or ln.startswith(':::'):
            out.append(ln)
            i += 1
            continue
        if ln.startswith('|') and not re.match(r'^\|[-: |]+\|$', ln):
            # 표: 본문 행을 복제해 2행 추가
            block = []
            while i < len(lines) and lines[i].startswith('|'):
                block.append(lines[i])
                i += 1
            if len(block) >= 3:
                block += [block[-1].replace('1', '9'), block[-1]]
            out += block
            continue
        if re.match(r'^\s*- ', ln) and rnd.random() < 0.3:
            out.append(ln)
            out.append(ln.replace('- ', '- 추가된 글머리: ', 1))
            i += 1
            continue
        if rnd.random() < 0.04 and ln.strip() and not ln.startswith(('|', ':::', '```', '@clone', '{')):
            i += 1                     # 줄 삭제
            continue
        out.append(ln.replace('2026', '2027'))
        i += 1
    return '\n'.join(out)


bad = 0
for n, path in enumerate(lst):
    name = os.path.basename(path)[:40]
    try:
        d = tempfile.mkdtemp()
        b = Builder(path, base_dir=d)
        md = mutate(scaffold_markdown(b.bp))
        specs = parse_markdown(md)
        els, _ = b.build(specs)
        out = os.path.join(d, 'o.hwpx')
        b.write(els, out, title='t')
        errs = validate(out)
        if errs:
            bad += 1
            print(f'[{n}] {name}: 구조 오류 {errs[:2]}')
    except Exception as e:  # noqa
        bad += 1
        print(f'[{n}] {name}: 예외 {type(e).__name__}: {e}')
        traceback.print_exc(limit=3)
print('문서', len(lst), '문제', bad)
