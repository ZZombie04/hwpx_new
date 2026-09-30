# -*- coding: utf-8 -*-
"""코퍼스 전체의 차이를 (항목, 원본값→결과값) 별로 세어 많은 순으로 보여 준다."""
import os, sys, re
from collections import Counter
sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
import roundtrip
root = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
lst = [l.strip() for l in open(os.path.join(root, '_out', 'corpus.txt'), encoding='utf-8') if l.strip()]
mode = sys.argv[1] if len(sys.argv) > 1 else 'md'
cnt = Counter()
ex = {}
for n, path in enumerate(lst):
    try:
        r = roundtrip.run_one(path, os.path.join(root, '_out', 'rt', f'{n:02d}'), with_class=(mode == 'cls'), md=(mode == 'md'))
    except Exception as e:
        print('ERR', n, e); continue
    for i, d in r['details']:
        for p, x, y in d:
            fld = re.sub(r'#\d+\.', '', p)
            fld = re.sub(r'cell\(\d+, \d+\)\.', 'cell.', fld)
            fld = re.sub(r'\.p\d+\.', '.p.', fld)
            fld = re.sub(r'run\d+', 'run', fld)
            key = (fld, str(x)[:60], str(y)[:60])
            cnt[key] += 1
            ex.setdefault(key, (n, i))
for (fld, x, y), c in cnt.most_common(40):
    print(f'{c:5}  {fld:<28} {x}  →  {y}    (예: 문서{ex[(fld,x,y)][0]} 블록{ex[(fld,x,y)][1]})')
