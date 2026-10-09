# -*- coding: utf-8 -*-
"""조판 점검: 한글(또는 내장 렌더러)이 만든 PDF 의 글줄을 뽑아 규칙을 검사하고, 문제 위치를 표시한 쪽 그림을 남긴다.

사용:
    hwpx-new qa 결과.pdf|결과.hwpx [-o 점검폴더] [--skip 1] [--colors "#000000,#FFFFFF,#C00000"] [--strict]

검사 항목(정돈 조판 규칙)
  1. 글자색: 허용 색(검정·흰색·강조 빨강) 외의 글자(누리집 주소의 링크 색은 허용)
  2. 단계 정렬: 같은 기호·크기(■ 15pt, ❍ 14pt, - 13pt, ※ 12pt)의 줄머리 x 위치가 쪽마다 같은지
  3. 내어쓰기: 기호 문단의 둘째 줄이 첫 줄 글자 시작 위치에 맞는지
  4. 글꼴 통일: 같은 단계는 같은 글꼴인지
  5. 여백 넘침, 6. 글줄 겹침, 7. 쪽 끝에 홀로 남은 소제목, 8. 거의 빈 쪽, 9. (공문) 결재란이 홀로 남은 쪽

2.3.0 부터 검사와 표시 그림을 모두 파이썬(pymupdf + pillow)으로 한다 — Node.js·Playwright 가 없어도 같은 결과.
결과: 점검폴더/qa_result.json, qa_page_N.png(문제 쪽, 빨강=오류·주황=주의), report.html(모든 쪽 + 표시).
"""
import argparse
import html as _html
import json
import os
import re
import shutil
import sys
from collections import Counter

import pymupdf

MARKERS = ('■', '❍', '- ', '· ', '※')
LINK = re.compile(r'https?://|www\.')
LINK_COLORS = ('#0000FF', '#0563C1')


def extract(pdf, out_dir, dpi=96):
    d = pymupdf.open(pdf)
    pages = []
    for i, pg in enumerate(d):
        lines = []
        for b in pg.get_text('rawdict')['blocks']:
            if b.get('type') != 0:
                continue
            for ln in b['lines']:
                spans = [s for s in ln['spans'] if ''.join(c['c'] for c in s['chars']).strip()]
                if not spans:
                    continue
                chars = [c for s in ln['spans'] for c in s['chars']]
                text = ''.join(c['c'] for c in chars)
                lead = len(text) - len(text.lstrip())
                chars = chars[lead:]
                while chars and not chars[-1]['c'].strip():     # 줄 끝 빈칸은 글자가 아니다(한글은 줄 끝 빈칸을 여백 밖에 둠)
                    chars.pop()
                text = text.strip()
                # 줄머리 기호 다음 첫 글자의 x(묶음 빈칸은 PDF 글자로 나오지 않음)
                tx = None
                if chars and chars[0]['c'] in '■❍※·-':
                    j = 1
                    while j < len(chars) and chars[j]['c'] in '  ':
                        j += 1
                    if j < len(chars):
                        tx = round(chars[j]['bbox'][0], 2)
                s0 = spans[0]
                lines.append({
                    'text': text, 'x0': round(chars[0]['bbox'][0], 2) if chars else round(s0['bbox'][0], 2),
                    'y0': round(min(s['bbox'][1] for s in spans), 2),
                    'x1': round(chars[-1]['bbox'][2], 2) if chars else round(max(s['bbox'][2] for s in spans), 2),
                    'y1': round(max(s['bbox'][3] for s in spans), 2), 'tx': tx,
                    'size': round(s0['size'], 1), 'font': s0['font'],
                    'colors': sorted({'#%06X' % s['color'] for s in spans}),
                })
        img = os.path.join(out_dir, f'page_{i + 1}.png')
        pg.get_pixmap(dpi=dpi).save(img)
        # 표·박스 영역(선으로 둘러싼 사각형): 칸 안 글줄은 단계 정렬 검사에서 뺀다
        rects = []
        for dr in pg.get_drawings():
            r = dr['rect']
            if r.width > 40 and r.height > 8:
                rects.append([round(r.x0, 1), round(r.y0, 1), round(r.x1, 1), round(r.y1, 1)])
        hlines = []
        for dr in pg.get_drawings():
            for it in dr['items']:
                if it[0] == 'l':
                    p1, p2 = it[1], it[2]
                    if abs(p1.y - p2.y) < 0.5 and abs(p1.x - p2.x) > 30:
                        hlines.append([round(min(p1.x, p2.x), 1), round(p1.y, 1), round(max(p1.x, p2.x), 1)])
                    elif abs(p1.x - p2.x) < 0.5 and abs(p1.y - p2.y) > 6:
                        rects.append([round(p1.x, 1) - 0.5, round(min(p1.y, p2.y), 1), round(p1.x, 1) + 0.5,
                                      round(max(p1.y, p2.y), 1)])
        pages.append({'n': i + 1, 'w': pg.rect.width, 'h': pg.rect.height, 'img': os.path.basename(img),
                      'lines': lines, 'rects': rects, 'hlines': hlines})
    return pages


# ------------------------------------------------------------------ 규칙
def _in_table(p, ln):
    """세로선 두 개 사이·사각형 안·위아래 가로선 사이면 표 칸으로 본다."""
    cy, cx = (ln['y0'] + ln['y1']) / 2, (ln['x0'] + ln['x1']) / 2
    v = [r for r in p['rects'] if r[2] - r[0] < 2 and r[1] - 1 < cy < r[3] + 1]
    left = any(r[0] <= ln['x0'] + 0.5 for r in v)
    right = any(r[0] >= ln['x1'] - 0.5 for r in v)
    if left and right:
        return True
    if any(r[2] - r[0] >= 40 and r[0] + 1 < cx < r[2] - 1 and r[1] < cy < r[3] for r in p['rects']):
        return True
    hl = p['hlines']
    above = any(h[1] <= ln['y0'] + 1 and h[1] > ln['y0'] - 40 and h[0] <= cx <= h[2] for h in hl)
    below = any(h[1] >= ln['y1'] - 1 and h[1] < ln['y1'] + 40 and h[0] <= cx <= h[2] for h in hl)
    if above and below:
        return True
    far_above = any(h[1] <= ln['y0'] + 1 and h[1] > ln['y0'] - 150 and h[0] <= cx <= h[2] for h in hl)
    far_below = any(h[1] >= ln['y1'] - 1 and h[1] < ln['y1'] + 150 and h[0] <= cx <= h[2] for h in hl)
    return (left or right) and far_above and far_below


def _marker(t):
    if re.match(r'^- ?\d+ ?-$', t):
        return None
    m = re.match(r'^(■|❍|※|·|-)', t)
    return m.group(1) if m else None


def run_checks(pages, cfg):
    issues = []

    def add(p, ln, kind, msg, level='err'):
        issues.append({'page': p['n'], 'kind': kind, 'msg': msg, 'level': level,
                       'box': [ln['x0'], ln['y0'], ln['x1'], ln['y1']] if ln else None, 'text': ln['text'][:40] if ln else ''})
    sel = [p for p in pages if p['n'] not in cfg['skip']]
    allow = [c.upper() for c in cfg['colors']]
    for p in sel:                                                   # 1 글자색
        for ln in p['lines']:
            link = bool(LINK.search(ln['text']))
            bad = [c for c in ln['colors'] if c not in allow and not (link and c in LINK_COLORS)]
            if bad:
                add(p, ln, '색', f"허용되지 않은 글자색 {','.join(bad)}")
    issues.extend(cfg.get('extra') or [])
    groups = {}
    for p in sel:                                                   # 단계 줄머리 수집(표 밖 본문만)
        for i, ln in enumerate(p['lines']):
            if _in_table(p, ln):
                continue
            m = _marker(ln['text'])
            if m:
                groups.setdefault((m, ln['size']), []).append((p, ln, i))
    for (m, size), arr in groups.items():
        if len(arr) < 2:
            continue
        xm = Counter(round(a[1]['x0']) for a in arr).most_common(1)[0][0]
        for p, ln, _ in arr:                                        # 2 단계 정렬
            if abs(ln['x0'] - xm) > 1.6:
                add(p, ln, '정렬', f"'{m}' {size}pt 줄머리 x={ln['x0']:.1f} (기준 {xm})")
        fm = Counter(a[1]['font'] for a in arr).most_common(1)[0][0]
        for p, ln, _ in arr:                                        # 4 글꼴 통일
            if ln['font'] != fm:
                add(p, ln, '글꼴', f"같은 단계인데 글꼴이 다름: {ln['font']} (기준 {fm})")
        for p, ln, i in arr:                                        # 3 내어쓰기
            nx = p['lines'][i + 1] if i + 1 < len(p['lines']) else None
            if not nx or _marker(nx['text']) or _in_table(p, nx):
                continue
            if abs(nx['size'] - ln['size']) > 0.2:
                continue
            gap = nx['y0'] - ln['y1']
            if gap < -1 or gap > ln['size'] * 1.2 or ln['tx'] is None:
                continue
            if abs(nx['x0'] - ln['tx']) > 2.2:
                add(p, nx, '내어쓰기', f"둘째 줄 x={nx['x0']:.1f} 이 첫 줄 글자 시작 {ln['tx']:.1f} 에 맞지 않음", 'warn')
    last = pages[-1]['n'] if pages else 0
    for p in sel:                                                   # 5 여백, 6 겹침, 7 쪽 끝 소제목, 8 빈 쪽
        L = p['lines']
        for ln in L:
            if ln['x1'] > p['w'] - cfg['margin'] or ln['x0'] < cfg['margin'] - 6:
                add(p, ln, '여백', f"본문 영역 밖(x {ln['x0']:.0f}~{ln['x1']:.0f})")
        for i in range(len(L)):
            for j in range(i + 1, len(L)):
                a, b = L[i], L[j]
                ox = min(a['x1'], b['x1']) - max(a['x0'], b['x0'])
                oy = min(a['y1'], b['y1']) - max(a['y0'], b['y0'])
                if ox > 2 and oy > min(a['y1'] - a['y0'], b['y1'] - b['y0']) * 0.45:
                    add(p, a, '겹침', f"글줄 겹침: \"{b['text'][:20]}\"")
        body = [ln for ln in L if not re.match(r'^- ?\d+ ?-$', ln['text'])]
        for h in [ln for ln in body if ln['text'].startswith('■') and not _in_table(p, ln)]:
            after = [ln for ln in body if ln['y0'] > h['y1'] + 1]
            if not after or h['y1'] > p['h'] * 0.86:
                add(p, h, '쪽끝', '소제목이 쪽 끝에 홀로 남음')
        if body:
            top, bot = min(ln['y0'] for ln in body), max(ln['y1'] for ln in body)
            fill = (bot - top) / (p['h'] - 2 * cfg['margin'])
            if fill < cfg['minFill'] and p['n'] != last:
                add(p, None, '빈쪽', f'쪽 내용이 {round(fill * 100)}%만 채워짐', 'warn')
    return issues


# ------------------------------------------------------------------ 표시 그림·보고서
def annotate(out, pages, issues, dpi=96):
    from PIL import Image, ImageDraw
    s = dpi / 72
    saved = []
    for n in sorted({x['page'] for x in issues}):
        p = next((q for q in pages if q['n'] == n), None)
        if not p:
            continue
        path = os.path.join(out, p['img'])
        im = Image.open(path).convert('RGB')
        d = ImageDraw.Draw(im, 'RGBA')
        for x in issues:
            if x['page'] != n or not x.get('box'):
                continue
            col = (255, 153, 0) if x['level'] == 'warn' else (220, 0, 0)
            x0, y0, x1, y1 = [v * s for v in x['box']]
            d.rectangle([x0 - 2, y0 - 2, x1 + 2, y1 + 2], outline=col + (255,), width=2, fill=col + (28,))
            d.rectangle([x0 - 2, y0 - 16, x0 + 8 + 7 * len(x['kind']) * 2, y0 - 2], fill=col + (255,))
            try:
                from PIL import ImageFont
                from .charts import font_files
                f = ImageFont.truetype(font_files()['Regular'], 11)
            except Exception:  # noqa
                f = None
            d.text((x0 + 2, y0 - 15), x['kind'], fill=(255, 255, 255), font=f)
        dst = os.path.join(out, f'qa_page_{n}.png')
        im.save(dst)
        saved.append(dst)
    return saved


def write_html(out, pages, issues):
    errs = sum(1 for x in issues if x['level'] != 'warn')
    rows = ''.join(f"<li>{x['page']}쪽 [{_html.escape(x['kind'])}] {_html.escape(x['msg'])} "
                   f"{('— ' + _html.escape(x['text'])) if x['text'] else ''}</li>" for x in issues[:200])
    body = ''
    for p in pages:
        img = f"qa_page_{p['n']}.png" if any(x['page'] == p['n'] for x in issues) else p['img']
        body += f'<div class="page" id="p{p["n"]}"><img src="{img}" alt="{p["n"]}쪽"></div>'
    html = ('<!doctype html><html lang="ko"><head><meta charset="utf-8"><title>조판 점검</title><style>'
            'body{margin:0;background:#f2f2f2;font:13px/1.5 sans-serif;color:#111}'
            'header{padding:12px 16px;background:#fff;border-bottom:1px solid #ddd;position:sticky;top:0}'
            '.page{margin:16px auto;max-width:820px;background:#fff;box-shadow:0 1px 4px #0003}.page img{display:block;width:100%}'
            f'</style></head><body><header><b>조판 점검</b> 쪽 {len(pages)} · 오류 {errs} · 주의 {len(issues) - errs}'
            f'<ul>{rows}</ul></header>{body}</body></html>')
    path = os.path.join(out, 'report.html')
    with open(path, 'w', encoding='utf-8') as f:
        f.write(html)
    return path


def main(argv=None):
    ap = argparse.ArgumentParser(description='HWPX/PDF 조판 점검')
    ap.add_argument('pdf')
    ap.add_argument('-o', '--out', default=None)
    ap.add_argument('--skip', default='1', help='점검에서 뺄 쪽(쉼표, 기본: 표지 1쪽)')
    ap.add_argument('--colors', default='#000000,#FFFFFF,#C00000')
    ap.add_argument('--margin', type=float, default=40.0, help='본문 영역 판정 여백(pt)')
    ap.add_argument('--min-fill', type=float, default=0.35)
    ap.add_argument('--strict', action='store_true', help='오류가 하나라도 있으면 종료 코드 1(자동 반복 작업용)')
    a = ap.parse_args(argv)
    out = a.out or os.path.splitext(a.pdf)[0] + '_점검'
    if os.path.isdir(out):
        shutil.rmtree(out)
    os.makedirs(out)
    if a.pdf.lower().endswith('.hwpx'):          # HWPX 를 주면 먼저 PDF 로(한글 → LibreOffice → 내장 순)
        from .pdf import convert
        pdf = os.path.join(out, os.path.splitext(os.path.basename(a.pdf))[0] + '.pdf')
        engine, log = convert(a.pdf, pdf)
        if not engine:
            print('PDF 변환 실패:', '; '.join(log))
            return 2
        print(f'PDF({engine}):', pdf)
        a.pdf = pdf
    pages = extract(a.pdf, out)
    extra = []
    try:                                          # 공문: 결재란이 홀로 마지막 쪽에 남았는지
        from .gongmun import check_pdf
        extra = [{'page': len(pages), 'kind': '결재란', 'msg': m, 'level': 'err', 'box': None, 'text': ''}
                 for m in check_pdf(a.pdf)]
    except Exception:  # noqa
        pass
    cfg = {'skip': [int(x) for x in a.skip.split(',') if x.strip()], 'colors': a.colors.split(','),
           'margin': a.margin, 'minFill': a.min_fill, 'extra': extra}
    qa = run_checks(pages, cfg)
    with open(os.path.join(out, 'qa_result.json'), 'w', encoding='utf-8') as f:
        json.dump(qa, f, ensure_ascii=False, indent=1)
    annotate(out, pages, qa)
    html = write_html(out, pages, qa)
    for x in qa[:80]:
        print(f"  {x['page']}쪽 [{x['kind']}] {x['msg']} — {x['text']}")
    errs = sum(1 for x in qa if x.get('level') != 'warn')
    color = sum(1 for x in qa if x.get('level') != 'warn' and '색' in str(x.get('kind', '')))
    if errs >= 30 and color >= 0.8 * errs:
        print('※ 오류 대부분이 글자색입니다. 강조색을 쓰는 장편 보고서(hwpx-new report)로 만든 문서라면 qa 가 아니라 '
              '빌드 출력의 "점검: 오류 N" 과 `hwpx-new report check 원고 --pdf 결과.pdf` 로 점검하세요(qa 는 계획서·공문용).')
    print(f'결과: 오류 {errs}, 주의 {len(qa) - errs} (오류 0 이 될 때까지 고친 뒤, 쪽 그림도 눈으로 확인)')
    print('보고서:', html)
    return 1 if (a.strict and errs) else 0


if __name__ == '__main__':
    sys.exit(main())
