# -*- coding: utf-8 -*-
"""개발용: 이 PC 의 실제 HWPX 중 서로 다른 것들을 골라 _out/corpus.txt 에 적는다(저장소에는 올리지 않는 경로 목록)."""
import glob
import os
import sys

base = os.path.expanduser('~')
pats = ['Desktop/*.hwpx', 'Desktop/*/*.hwpx', 'Desktop/*/*/*.hwpx', 'Documents/GOE메신저/Message 받은 파일/*.hwpx',
        'Documents/RAS 패스포트 배포자료/*.hwpx', 'Documents/카카오톡 받은 파일/*.hwpx',
        'Documents/rasnew/.tmp/hwpx-peek/*.hwpx']
cands = []
for p in pats:
    cands += glob.glob(os.path.join(base, p))
cands = [c.replace(chr(92), '/') for c in cands]
seen, out = set(), []
for c in sorted(cands):
    key = os.path.basename(c)[:14]
    if key in seen:
        continue
    seen.add(key)
    out.append(c)
out = [c for c in out if '지방보조금 결정서' not in c or '/01.' in c]
dst = os.path.join(os.path.dirname(os.path.dirname(os.path.abspath(__file__))), '_out', 'corpus.txt')
os.makedirs(os.path.dirname(dst), exist_ok=True)
open(dst, 'w', encoding='utf-8').write('\n'.join(out))
print(len(out))
for x in out:
    print(os.path.basename(x), os.path.getsize(x) // 1024, 'KB')
