# -*- coding: utf-8 -*-
"""HWPX 구조 검증: 한글 없이도 '열리지 않을 만한' 결함(없는 스타일 참조, 표 격자 오류 등)을 미리 잡는다."""
from __future__ import annotations

from .package import HH, HP, Package


def validate(path: str):
    """문제 목록(빈 목록이면 이상 없음)을 돌려준다."""
    errs = []
    pkg = Package(path)
    head = pkg.header()
    root = pkg.section_root(0)
    para_ids = set(head.para)
    char_ids = set(head.char)
    bf_ids = set(head.borders)
    style_ids = {s.get('id') for s in head.root.iter(HH + 'style')}
    # 개수 속성 일치
    for tag, ids in (('paraProperties', para_ids), ('charProperties', char_ids)):
        el = head.root.find('.//' + HH + tag)
        if el is not None and el.get('itemCnt') and int(el.get('itemCnt')) != len(el):
            errs.append(f'header {tag} itemCnt({el.get("itemCnt")}) 와 실제 개수({len(el)}) 불일치')
    for p in root.iter(HP + 'p'):
        pid = p.get('paraPrIDRef')
        if pid is not None and pid not in para_ids:
            errs.append(f'없는 문단 모양 참조: paraPrIDRef={pid}')
        sid = p.get('styleIDRef')
        if sid is not None and style_ids and sid not in style_ids:
            errs.append(f'없는 스타일 참조: styleIDRef={sid}')
    for r in root.iter(HP + 'run'):
        cid = r.get('charPrIDRef')
        if cid is not None and cid not in char_ids:
            errs.append(f'없는 글자 모양 참조: charPrIDRef={cid}')
    for el in root.iter():
        b = el.get('borderFillIDRef')
        if b is not None and b not in bf_ids and b != '0':
            errs.append(f'없는 테두리/배경 참조: borderFillIDRef={b}')
    hpf = pkg.files.get('Contents/content.hpf', b'').decode('utf-8', 'ignore')
    for img in root.iter('{http://www.hancom.co.kr/hwpml/2011/core}img'):
        ref = img.get('binaryItemIDRef')
        if f'id="{ref}"' not in hpf:
            errs.append(f'매니페스트에 없는 그림 참조: {ref}')
        elif not any(n.startswith(f'BinData/{ref}.') for n in pkg.files):
            errs.append(f'BinData 에 그림 파일이 없음: {ref}')
    seen = set()
    for tbl in root.iter(HP + 'tbl'):
        tid = tbl.get('id')
        if tid in seen:
            errs.append(f'표 id 중복: {tid}')
        seen.add(tid)
        rows, cols = int(tbl.get('rowCnt')), int(tbl.get('colCnt'))
        occ = {}
        trs = tbl.findall(HP + 'tr')
        own_cells = [tc for tr in trs for tc in tr.findall(HP + 'tc')]
        if len(trs) != rows:
            errs.append(f'표 rowCnt({rows}) 와 tr 개수({len(trs)}) 불일치')
        for tc in own_cells:
            a, s = tc.find(HP + 'cellAddr'), tc.find(HP + 'cellSpan')
            r0, c0 = int(a.get('rowAddr')), int(a.get('colAddr'))
            rs, cs = int(s.get('rowSpan')), int(s.get('colSpan'))
            if r0 + rs > rows or c0 + cs > cols:
                errs.append(f'표 셀이 격자를 벗어남: ({r0},{c0}) span({rs},{cs}) / {rows}x{cols}')
            for rr in range(r0, r0 + rs):
                for cc in range(c0, c0 + cs):
                    if (rr, cc) in occ:
                        errs.append(f'표 셀 겹침: ({rr},{cc})')
                    occ[(rr, cc)] = 1
            sub = tc.find(HP + 'subList')
            if sub is None or not sub.findall(HP + 'p'):
                errs.append(f'표 셀에 문단이 없음: ({r0},{c0})')
        if len(occ) != rows * cols:
            errs.append(f'표 격자가 비어 있음: 채워진 {len(occ)} / {rows * cols}')
    return errs[:20]
