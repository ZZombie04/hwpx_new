# -*- coding: utf-8 -*-
"""원본과 재조립본을 한글로 PDF 로 만들어 쪽별로 겹쳐 보고, 차이가 큰 쪽을 나란히 놓은 그림을 저장한다.

사용: python tools/visual.py 번호[,번호...]   (번호는 _out/corpus.txt 의 줄 번호, --cls 로 class 지정 조립)
"""
from __future__ import annotations

import os
import sys

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))

import pymupdf  # noqa: E402

import roundtrip  # noqa: E402
from hwpx_new import hancom  # noqa: E402

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))


def render(pdf, dpi=60):
    d = pymupdf.open(pdf)
    out = []
    for p in d:
        pix = p.get_pixmap(dpi=dpi, colorspace=pymupdf.csGRAY)
        out.append((pix.width, pix.height, bytes(pix.samples)))
    return out


def page_diff(a, b):
    """두 쪽(회색조 원시 바이트)의 평균 밝기 차이(0~255). 크기가 다르면 작은 쪽 기준."""
    w = min(a[0], b[0])
    h = min(a[1], b[1])
    tot = 0
    for y in range(h):
        ra = a[2][y * a[0]:y * a[0] + w]
        rb = b[2][y * b[0]:y * b[0] + w]
        tot += sum(abs(x - y_) for x, y_ in zip(ra, rb))
    return tot / float(w * h)


def side_by_side(pdf_a, pdf_b, page, out_png, dpi=70):
    da, db = pymupdf.open(pdf_a), pymupdf.open(pdf_b)
    pa = da[page].get_pixmap(dpi=dpi) if page < len(da) else None
    pb = db[page].get_pixmap(dpi=dpi) if page < len(db) else None
    w = (pa.width if pa else 0) + (pb.width if pb else 0) + 10
    h = max(pa.height if pa else 0, pb.height if pb else 0)
    canvas = pymupdf.Pixmap(pymupdf.csRGB, pymupdf.IRect(0, 0, w, h), False)
    canvas.set_rect(canvas.irect, (255, 255, 255))
    if pa:
        canvas.copy(pa, pymupdf.IRect(0, 0, pa.width, pa.height)) if False else None
    # 간단히: 두 그림을 각각 저장하고 합침
    import io
    from PIL import Image
    ia = Image.open(io.BytesIO(pa.tobytes('png'))) if pa else None
    ib = Image.open(io.BytesIO(pb.tobytes('png'))) if pb else None
    im = Image.new('RGB', (w, h), (255, 255, 255))
    if ia:
        im.paste(ia, (0, 0))
    if ib:
        im.paste(ib, ((ia.width if ia else 0) + 10, 0))
    im.save(out_png)


def main():
    use_cls = '--cls' in sys.argv
    nums = [a for a in sys.argv[1:] if not a.startswith('--')]
    lst = [l.strip() for l in open(os.path.join(ROOT, '_out', 'corpus.txt'), encoding='utf-8') if l.strip()]
    sel = []
    for a in nums:
        sel += [int(x) for x in a.split(',') if x.strip()]
    for n in sel:
        path = lst[n]
        out = os.path.join(ROOT, '_out', 'vis', f'{n:02d}')
        os.makedirs(out, exist_ok=True)
        r = roundtrip.run_one(path, out, with_class=use_cls)
        pa, pb = os.path.join(out, 'orig.pdf'), os.path.join(out, 'rebuilt.pdf')
        if '--html' in sys.argv:
            from hwpx_new import pdf as _pdf
            ok1, m1 = _pdf.ENGINES['html'](r['orig'], pa)
            ok2, m2 = _pdf.ENGINES['html'](r['rebuilt'], pb)
        else:
            ok1, m1, _ = hancom.export_pdf(r['orig'], pa)
            ok2, m2, _ = hancom.export_pdf(r['rebuilt'], pb)
        if not (ok1 and ok2):
            print(f'[{n}] PDF 실패: {m1} / {m2}')
            continue
        A, B = render(pa), render(pb)
        diffs = []
        for i in range(min(len(A), len(B))):
            diffs.append(round(page_diff(A[i], B[i]), 1))
        print(f'[{n}] {os.path.basename(path)[:40]}: 쪽 수 원본 {len(A)} / 결과 {len(B)} / 쪽별 차이 {diffs}')
        worst = sorted(range(len(diffs)), key=lambda i: -diffs[i])[:2]
        for i in worst:
            side_by_side(pa, pb, i, os.path.join(out, f'cmp_p{i + 1}.png'))


if __name__ == '__main__':
    main()
