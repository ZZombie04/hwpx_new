# -*- coding: utf-8 -*-
"""_out/corpus.txt 의 서식들을 모두 자체 점검하고 요약표를 출력한다."""
import os
import sys
import time
import traceback
from collections import Counter

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
import roundtrip  # noqa: E402

root = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
lst = [l.strip() for l in open(os.path.join(root, '_out', 'corpus.txt'), encoding='utf-8') if l.strip()]
args = sys.argv[1:]
use_cls = '--cls' in args
use_md = '--md' in args
only = [x for x in args if x not in ('--cls', '--md')]
tot = Counter()
rows = []
for n, path in enumerate(lst):
    name = os.path.basename(path)
    if only and not any(o in name for o in only):
        continue
    t = time.time()
    try:
        r = roundtrip.run_one(path, os.path.join(root, '_out', 'rt', f'{n:02d}'), with_class=use_cls, md=use_md)
        rows.append((n, name, r['orig_blocks'], r['matched'], r['style_bad_blocks'], r['gap_bad'], len(r['warnings']), ''))
        tot.update(r['stats'])
    except Exception as e:  # noqa
        rows.append((n, name, 0, 0, 0, 0, 0, f'{type(e).__name__}: {e}'[:90]))
        traceback.print_exc(limit=2)
print()
print(f'{"#":>2} {"문서":<44} {"블록":>4} {"대응":>4} {"모양다름":>6} {"간격다름":>6} {"경고":>4}')
for n, name, ob, m, sb, gb, w, err in rows:
    print(f'{n:>2} {name[:42]:<44} {ob:>4} {m:>4} {sb:>6} {gb:>6} {w:>4} {err}')
print('\n차이 항목 합계:', dict(tot.most_common(14)))
