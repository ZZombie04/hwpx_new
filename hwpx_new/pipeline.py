# -*- coding: utf-8 -*-
"""한 번에 끝내는 파이프라인: 서식 분석 → 조립 → PDF 변환 → 조판 점검 → 자동 보정 → 미리보기."""
from __future__ import annotations

import os
import re
import shutil
import tempfile

from .builder import Builder
from .mdparse import load_content
from .package import Package
from . import pdf as pdfmod
from . import qa as qamod
from .validate import validate


def safe_name(s):
    s = re.sub(r'[\\/:*?"<>|\r\n]+', ' ', s).strip()
    return s[:80] or '결과물'


def build_once(template, specs, breaks, compact, out_hwpx, title, base_dir=None):
    b = Builder(template, base_dir=base_dir)
    specs2 = []
    for i, s in enumerate(specs):
        s = dict(s)
        if i in breaks:
            s['page_break'] = True
        specs2.append(s)
    els, probes = b.build(specs2, compact=compact)
    # probes 의 i 는 specs2 인덱스와 동일
    b.write(els, out_hwpx, title=title, preview_text=title)
    return b, probes


WEEK = '월화수목금토일'
DATE_RE = re.compile(r'(\d{4})\.\s*(\d{1,2})\.\s*(\d{1,2})\.?\s*\(([월화수목금토일])\)')


def lint_content(specs):
    """내용 점검: 날짜-요일 불일치, 빈 표 칸, 지나치게 많은 열 등."""
    import datetime
    warns = []

    def texts(s):
        out = []
        for k in ('text', 'title'):
            if isinstance(s.get(k), str):
                out.append(s[k])
        out += [x for x in s.get('lines', []) if isinstance(x, str)]
        for r in (s.get('rows') or []) + ([s['header']] if s.get('header') else []):
            rows = r if r and isinstance(r[0], list) else [r]
            for row in rows:
                for c in row:
                    out.append(c.get('text', '') if isinstance(c, dict) else (c if isinstance(c, str) else ''))
        return out

    for i, s in enumerate(specs):
        for t in texts(s):
            for m in DATE_RE.finditer(t.replace(chr(10), ' ')):
                y, mo, d, w = int(m.group(1)), int(m.group(2)), int(m.group(3)), m.group(4)
                try:
                    real = WEEK[datetime.date(y, mo, d).weekday()]
                except ValueError:
                    warns.append(f'존재하지 않는 날짜: {m.group(0)}')
                    continue
                if real != w:
                    warns.append(f'요일 불일치: {m.group(0)} → 실제 {y}. {mo}. {d}.은 {real}요일')
        if s.get('type') == 'table':
            hdr = s.get('header') or []
            ncol = len(hdr[0]) if hdr and isinstance(hdr[0], list) else len(hdr)
            if ncol >= 8:
                warns.append(f'표(블록 {i + 1})의 열이 {ncol}개로 많아 글자가 좁게 나올 수 있습니다.')
            carry = [0] * max(ncol, 1)   # 위 행의 rowspan 이 차지한 칸 수
            for r in s.get('rows') or []:
                used = sum(1 for x in carry if x > 0)
                carry = [max(0, x - 1) for x in carry]
                span = sum(int(c.get('colspan', 1)) if isinstance(c, dict) else 1 for c in r)
                rs_cells = [c for c in r if isinstance(c, dict) and int(c.get('rowspan', 1)) > 1]
                for c in rs_cells:
                    for k in range(min(int(c.get('colspan', 1)), len(carry))):
                        carry[k] = max(carry[k], int(c['rowspan']) - 1)
                if ncol and span + used != ncol:
                    warns.append(f'표(블록 {i + 1})의 한 행 칸 수({len(r)})가 머리글({ncol})과 다릅니다: {str(r)[:40]}')
                    break
    return warns


def make_report(template, content, out_dir, name=None, engine=None, autofix=True, max_rounds=6,
                previews=True, dpi=70, base_dir=None):
    """content: 파일 경로 | JSON 문자열 | Markdown 문자열.  반환: dict(결과 요약)."""
    specs, meta = load_content(content)
    if base_dir is None:
        base_dir = os.path.dirname(os.path.abspath(content)) if len(content) < 500 and os.path.exists(content) else os.getcwd()
    if not specs:
        raise ValueError('내용(블록)이 비어 있습니다.')
    title = next((s.get('text') for s in specs if s.get('type') == 'title'), None)
    lint = lint_content(specs)
    name = safe_name(name or meta.get('name') or title or '결과물')
    os.makedirs(out_dir, exist_ok=True)
    final_hwpx = os.path.join(out_dir, name + '.hwpx')
    final_pdf = os.path.join(out_dir, name + '.pdf')
    work = tempfile.mkdtemp(prefix='hwpx_new_')
    log = []
    try:
        user_breaks = {i for i, s in enumerate(specs) if s.get('page_break')}
        state = (frozenset(), 0)
        seen = set()
        best = None
        eng = None
        rounds = 0
        while True:
            rounds += 1
            breaks, compact = state
            seen.add(state)
            tmp_h = os.path.join(work, f'r{rounds}.hwpx')
            tmp_p = os.path.join(work, f'r{rounds}.pdf')
            builder, probes = build_once(template, specs, set(breaks), compact, tmp_h, title or name, base_dir)
            eng, elog = pdfmod.convert(tmp_h, tmp_p, prefer=engine)
            if eng is None:
                log += elog
                best = {'state': state, 'hwpx': tmp_h, 'pdf': None, 'qa': None, 'score': 0,
                        'warnings': builder.warnings}
                break
            log += elog
            q = qamod.inspect(tmp_p, probes)
            score = sum({'blank_page': 5, 'orphan_heading': 3, 'split_table': 4, 'widow_last_page': 2, 'short_page': 2}.get(i['kind'], 1)
                        for i in q['issues']) * 100 + q['n_pages']
            cand = {'state': state, 'hwpx': tmp_h, 'pdf': tmp_p, 'qa': q, 'score': score,
                    'warnings': builder.warnings}
            if best is None or score < best['score']:
                best = cand
            if not q['issues'] or not autofix or rounds >= max_rounds:
                break
            # ---- 자동 보정 결정
            nb, nc = set(breaks), compact
            changed = False
            for iss in q['issues']:
                if iss['kind'] == 'orphan_heading' and iss['spec'] not in nb:
                    top = iss['spec']
                    while top > 0 and (specs[top - 1].get('type') == 'heading' or specs[top - 1].get('qa') == 'heading'):
                        top -= 1                      # 소제목 바로 아래 소제목/머리 문단까지 함께 다음 쪽으로
                    nb.add(top)
                    if iss['spec'] + 1 not in user_breaks:
                        nb.discard(iss['spec'] + 1)   # 소제목과 붙은 표는 같이 넘어가므로 중복 쪽 나눔 제거
                    changed = True
                elif iss['kind'] == 'split_table' and iss['spec'] not in nb:
                    i = iss['spec']
                    top = i
                    while top > 0 and (specs[top - 1].get('type') == 'heading' or specs[top - 1].get('qa') == 'heading'):
                        top -= 1
                    if top < i:
                        # 소제목 묶음째 넘긴다. 이미 소제목이 쪽 맨 위라면(표가 한 쪽보다 큼) 더 할 수 있는 것이 없다
                        if top not in nb:
                            nb.add(top)
                            changed = True
                    else:
                        nb.add(i)
                        changed = True
                elif iss['kind'] == 'blank_page':
                    # 빈 쪽을 만든 자동 쪽나눔부터 해제
                    for s_ in sorted(nb - user_breaks):
                        nb.discard(s_)
                        changed = True
                        break
                    else:
                        if nc < 2:
                            nc += 1
                            changed = True
                elif iss['kind'] in ('widow_last_page', 'short_page') and nc < 2:
                    nc += 1
                    changed = True
            ns = (frozenset(nb), nc)
            if not changed or ns in seen:
                break
            state = ns
        shutil.copyfile(best['hwpx'], final_hwpx)
        struct = validate(final_hwpx)
        pdf_out = None
        prev_files = []
        q = best['qa']
        if best['pdf']:
            shutil.copyfile(best['pdf'], final_pdf)
            pdf_out = final_pdf
            if previews:
                import pymupdf
                pdir = os.path.join(out_dir, name + '_미리보기')
                os.makedirs(pdir, exist_ok=True)
                for old_png in os.listdir(pdir):
                    if old_png.startswith('page_') and old_png.endswith('.png'):
                        os.remove(os.path.join(pdir, old_png))
                d = pymupdf.open(final_pdf)
                for i, pg in enumerate(d):
                    f = os.path.join(pdir, f'page_{i + 1}.png')
                    pg.get_pixmap(dpi=dpi).save(f)
                    prev_files.append(f)
                # 한글 파일 미리보기 이미지 갱신
                try:
                    pk = Package(final_hwpx)
                    if 'Preview/PrvImage.png' in pk.files:
                        pk.files['Preview/PrvImage.png'] = d[0].get_pixmap(dpi=50).tobytes('png')
                        pk.save(final_hwpx)
                except Exception:  # noqa
                    pass
        remaining = q['issues'] if q else []
        return {
            'hwpx': final_hwpx, 'pdf': pdf_out, 'previews': prev_files,
            'engine': eng, 'pages': q['n_pages'] if q else None,
            'rounds': rounds, 'auto_page_breaks': sorted(best['state'][0] - user_breaks),
            'compact_level': best['state'][1],
            'remaining_issues': [qamod.describe(i) for i in remaining],
            'warnings': lint + best['warnings'] + ['구조 검증: ' + e for e in struct], 'log': log,
            'approximate_pdf': eng == 'html',
        }
    finally:
        shutil.rmtree(work, ignore_errors=True)


def summarize(res) -> str:
    L = []
    L.append(f'HWPX: {res["hwpx"]}')
    if res['pdf']:
        L.append(f'PDF : {res["pdf"]}  ({res["pages"]}쪽, 변환 엔진: {res["engine"]})')
    else:
        L.append('PDF : 만들지 못했습니다 → ' + ' / '.join(res['log']))
    if res['approximate_pdf']:
        L.append('※ 한글·LibreOffice 가 없어 내장 렌더러로 만든 PDF 입니다. 실제 한글에서의 쪽 배치와 조금 다를 수 있습니다.')
    if res['auto_page_breaks']:
        L.append(f'자동 보정: 쪽 나눔 {len(res["auto_page_breaks"])}곳 추가, 압축 단계 {res["compact_level"]}, {res["rounds"]}회 반복')
    if res['remaining_issues']:
        L.append('남은 조판 문제: ' + '; '.join(res['remaining_issues']))
    elif res['pdf']:
        L.append('조판 점검: 문제 없음')
    if res['pdf'] and res['log']:
        L.append('참고: ' + ' / '.join(res['log']))
    for w in res['warnings']:
        L.append('경고: ' + w)
    if res['previews']:
        L.append('미리보기 이미지: ' + os.path.dirname(res['previews'][0]))
    return '\n'.join(L)
