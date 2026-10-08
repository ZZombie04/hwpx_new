# -*- coding: utf-8 -*-
"""사용자가 한글에서 손본 HWPX 를 '손본 그대로' 두고 필요한 곳만 고친다.

원칙: 다시 만들지 않는다. 원본 블록을 하나도 빠짐없이 복제(자간·빈 줄·직접 맞춘 내어쓰기·글자색 유지)하고,
글로 찾은 위치에만 문단·표를 끼우거나 바꾼다. 찾는 글이 정확히 한 곳에 있지 않으면 멈추고 후보를 알려 준다.

1) 이름·날짜만 바꾸기(바이트 보존): replace_text_zip(src, out, [(옛, 새), ...])
   - 본문·미리보기 글·문서 제목에서만 문자열을 바꾸고 나머지 ZIP 항목은 그대로 둔다.
2) 위치를 찾아 고치기: patch(src, ops, out, style='plan'|'gongmun')
   ops 예(examples/patch_ops.json):
   [
     {"op": "replace_text", "find": "참가비 없음", "to": "참가비 1만원"},            # 글자 모양 유지, 기본 1곳(count/all)
     {"op": "replace_block", "find": "표창장 수여 계획 없음", "blocks": [{"b1": "우수 지도교사 표창 수여"}]},
     {"op": "insert_after", "find": "■ 운영 원칙", "blocks": [{"b1": "새 항목"}]},
     {"op": "insert_before", "find": "Ⅳ 사제동행", "blocks": [{"h2": "표창"}, {"table": {...}}]},
     {"op": "delete_block", "find": "옛 문장"},
     {"op": "page_break", "find": "Ⅹ 행정 사항", "on": true}
   ]
   blocks 문법은 spec.py(정돈 조판 명세)와 같다. 공문이면 style='gongmun' 에 blocks 를 공문 줄("가. …")·{"table"} 로.
"""
from __future__ import annotations

import json
import os
import re
import zipfile

from lxml import etree

from .compose import Composer, HP

TEXT_ENTRIES = ('Contents/section', 'Preview/PrvText.txt', 'Contents/content.hpf')


def _norm(s):
    return re.sub(r'\s+', '', s or '')


def block_text(el):
    return ''.join(''.join(t.itertext()) for t in el.iter(HP + 't'))


def strings(el):
    """글자 덩어리: t.text 와 t 안 요소(묶음 빈칸 등)의 tail."""
    for t in el.iter(HP + 't'):
        yield t, 'text'
        for ch in t:
            yield ch, 'tail'


def replace_in(el, a, b):
    n = 0
    for obj, attr in strings(el):
        v = getattr(obj, attr)
        if v and a in v:
            n += v.count(a)
            setattr(obj, attr, v.replace(a, b))
    return n


# ---------------------------------------------------------------- 1) 바이트 보존 문자열 바꾸기
def replace_text_zip(src, out, pairs):
    """본문·미리보기·제목의 문자열만 바꾸고 나머지 ZIP 항목은 그대로. 돌려줌: {옛 글: 바꾼 횟수}."""
    hits = {a: 0 for a, _ in pairs}
    tmp = out + '.tmp'
    with zipfile.ZipFile(src) as zin, zipfile.ZipFile(tmp, 'w') as zout:
        for info in zin.infolist():
            data = zin.read(info.filename)
            if not info.is_dir() and info.filename.startswith(TEXT_ENTRIES):
                s = data.decode('utf-8')
                for a, b in pairs:
                    if a in s:
                        hits[a] += s.count(a) if info.filename.startswith('Contents/section') else 0
                        s = s.replace(a, b)
                data = s.encode('utf-8')
            zi = zipfile.ZipInfo(info.filename, date_time=info.date_time)
            zi.compress_type, zi.external_attr, zi.create_system = info.compress_type, info.external_attr, info.create_system
            zout.writestr(zi, data)
    os.replace(tmp, out)
    return hits


def saved_by_hancom(path):
    """한글에서 다시 저장한 파일인지(ZIP 항목 시각이 1980-01-01 이면 한글 저장)."""
    with zipfile.ZipFile(path) as z:
        return all(i.date_time[:3] == (1980, 1, 1) for i in z.infolist()[:3])


def _paras(path):
    with zipfile.ZipFile(path) as z:
        out = []
        for n in sorted(x for x in z.namelist() if x.startswith('Contents/section')):
            for p in etree.fromstring(z.read(n)).iter(HP + 'p'):
                t = ''.join(''.join(x.itertext()) for r in p.findall(HP + 'run') for x in r.findall(HP + 't')).strip()
                if t:
                    out.append(t)
        return out


def diff_report(a, b):
    """두 HWPX 의 글 차이(문단 단위)와 한글 저장 여부. 사용자가 손본 곳을 찾아 보존할 때 쓴다."""
    import difflib
    pa, pb = _paras(a), _paras(b)
    lines = [f'A: {a} (문단 {len(pa)}, 한글 저장: {"예" if saved_by_hancom(a) else "아니오"})',
             f'B: {b} (문단 {len(pb)}, 한글 저장: {"예" if saved_by_hancom(b) else "아니오"})']
    d = list(difflib.unified_diff(pa, pb, 'A', 'B', lineterm='', n=0))
    lines += d[:200] if d else ['글 차이 없음(모양·자간만 다를 수 있음)']
    return '\n'.join(lines)


# ---------------------------------------------------------------- 2) 위치를 찾아 고치기
def _load_ops(ops):
    if isinstance(ops, list):
        return ops
    if isinstance(ops, str) and ops.lstrip().startswith('['):
        return json.loads(ops)
    return json.load(open(ops, encoding='utf-8'))


def _original_title(src):
    try:
        z = zipfile.ZipFile(src)
        hpf = etree.fromstring(z.read('Contents/content.hpf'))
        t = next(hpf.iter('{http://purl.org/dc/elements/1.1/}title'), None)
        return t.text if t is not None else None
    except (KeyError, etree.XMLSyntaxError, zipfile.BadZipFile):
        return None


def patch(src, ops, out, style='plan', title=None):
    """ops 를 적용한 새 HWPX 를 out 에 저장. 돌려줌: 적용 보고(문자열 목록)."""
    from .spec import render_block
    ops = _load_ops(ops)
    if style == 'gongmun':
        from .gongmun import Gongmun
        d = Gongmun(src)
    else:
        d = Composer(src)
    texts = [_norm(block_text(e)) for e in d.tops]
    before, after, replace, delete, brk = {}, {}, {}, set(), {}
    report = []

    def locate(op):
        key = _norm(op['find'])
        hits = [i for i, t in enumerate(texts) if key and key in t]
        if op.get('nth'):
            hits = hits[op['nth'] - 1:op['nth']]
        if len(hits) != 1:
            cands = '; '.join(block_text(d.tops[i])[:40] for i in hits[:5])
            raise ValueError(f"'{op['find']}' 이(가) 든 블록이 {len(hits)}개입니다(정확히 1개여야 함). 후보: {cands}")
        return hits[0]

    text_ops = []
    for op in ops:
        kind = op['op']
        if kind == 'replace_text':
            text_ops.append(op)
            continue
        i = locate(op)
        if kind == 'insert_before':
            before.setdefault(i, []).extend(op['blocks'])
        elif kind == 'insert_after':
            after.setdefault(i, []).extend(op['blocks'])
        elif kind == 'replace_block':
            replace[i] = op['blocks']
        elif kind == 'delete_block':
            delete.add(i)
        elif kind == 'page_break':
            brk[i] = op.get('on', True)
        else:
            raise ValueError(f'알 수 없는 op: {kind}')
        report.append(f"{kind}: {block_text(d.tops[i])[:30]}")

    def put(blocks):
        for b in blocks:
            if style == 'gongmun' and isinstance(b, str):
                d.line(b)
            elif style == 'gongmun' and 'table' in b:
                d.gtable(b['table'])
            else:
                render_block(d, b)

    hits = {op['find']: 0 for op in text_ops}
    for i in range(len(d.tops)):
        put(before.get(i, []))
        if i in replace:
            put(replace[i])
        elif i not in delete:
            el = d.clone(i)[0]
            if i in brk:
                el.set('pageBreak', '1' if brk[i] else '0')
            for op in text_ops:
                hits[op['find']] += replace_in(el, op['find'], op['to'])
        put(after.get(i, []))
    for op in text_ops:
        n = hits[op['find']]
        want = op.get('count', 1)
        if not op.get('all') and n != want:
            raise ValueError(f"'{op['find']}' 바꾸기: {n}곳에서 찾음(기대 {want}곳). 글자 모양이 달라 글이 나뉘었으면 더 짧게 찾거나 count/all 을 쓰세요.")
        report.append(f"replace_text: '{op['find']}' {n}곳")
    d.save(out, title=title or _original_title(src))
    return report
