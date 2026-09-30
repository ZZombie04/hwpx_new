# -*- coding: utf-8 -*-
import os, sys
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
from hwpx_new.analyze import analyze
from hwpx_new.styleprint import Styles
from hwpx_new.package import HP
bp = analyze(sys.argv[1])
st = Styles(bp.head.root)
lim = int(sys.argv[2]) if len(sys.argv) > 2 else 60
start = int(sys.argv[3]) if len(sys.argv) > 3 else 0
for b in bp.blocks[start:start + lim]:
    p = st.para.get(b.info['para_pr'], {})
    if b.role == 'blank':
        print(f'[{b.idx:3}] ·blank pp={b.info["para_pr"]} ls={p.get("ls")} prev={p.get("prev")} next={p.get("next")}')
        continue
    if b.info.get('tbl') is not None:
        fills = b.info.get('fills')
        cs = b.info['cells']
        print(f'[{b.idx:3}] {b.role:<8} TABLE {b.info["rows"]}x{b.info["cols"]} fills={fills} sz={b.info["font"]} | {b.text[:60]}')
    else:
        print(f'[{b.idx:3}] {b.role:<8} sz={b.info["font"]} al={p.get("align")} L={p.get("left")} I={p.get("intent")} ls={p.get("ls")} pv={p.get("prev")} | {b.text[:50]!r}')
