# -*- coding: utf-8 -*-
"""그림 용량 최적화(표시 크기 × 200dpi, 사진 JPEG·도표 팔레트 PNG)·shrink·공문 결재란 점검 시험."""
import io
import os
import random
import sys
import tempfile
import zipfile

import pytest
from PIL import Image, ImageDraw

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, ROOT)
from hwpx_new import images, spec  # noqa: E402
from hwpx_new.images import MM  # noqa: E402

TPL = os.path.join(ROOT, 'hwpx_new', 'data', 'sample_template.hwpx')


@pytest.fixture(scope='module')
def tmp():
    return tempfile.mkdtemp(prefix='hwpx_img_')


def _photo(path, w=3000, h=2000):
    """색이 많은 사진 같은 그림(PNG 로 저장 — 원본이 PNG 사진이어도 JPEG 로 바뀌어야 함)."""
    rnd = random.Random(1)
    im = Image.new('RGB', (w // 10, h // 10))
    im.putdata([(rnd.randrange(256), (x * 7) % 256, (x * 3) % 256) for x in range((w // 10) * (h // 10))])
    im = im.resize((w, h), Image.BICUBIC)
    im.save(path)
    return path


def _diagram(path):
    im = Image.new('RGB', (2400, 1600), 'white')
    d = ImageDraw.Draw(im)
    for i in range(0, 2400, 120):
        d.rectangle([i, 200, i + 60, 1400], outline='navy', width=8)
    d.text((100, 80), 'diagram', fill='red')
    im.save(path)
    return path


def test_photo_becomes_jpeg_sized_to_display(tmp):
    p = _photo(os.path.join(tmp, 'photo.png'))
    raw = os.path.getsize(p)
    data, ext, w, h, dw, dh = images.prepare_for_box(p, int(150 * MM), int(120 * MM))
    assert ext == '.jpg'
    assert w <= round(150 / 25.4 * images.DPI) + 1 and w < 3000          # 150mm × 200dpi ≈ 1181px
    assert len(data) < raw / 5
    assert abs(dw / dh - 3000 / 2000) < 0.01                              # 비율 유지


def test_diagram_stays_png_palette(tmp):
    p = _diagram(os.path.join(tmp, 'diagram.png'))
    data, ext, w, h, _, _ = images.prepare_for_box(p, int(100 * MM), int(80 * MM))
    assert ext == '.png' and w < 2400
    assert Image.open(io.BytesIO(data)).mode in ('P', '1', 'L')
    assert len(data) < os.path.getsize(p)


def test_small_jpeg_kept_as_is(tmp):
    p = os.path.join(tmp, 'small.jpg')
    Image.open(_photo(os.path.join(tmp, 'small_src.png'), 300, 200)).save(p, quality=70)
    raw = open(p, 'rb').read()
    data, ext, w, h, _, _ = images.prepare_for_box(p, int(150 * MM), int(100 * MM))
    assert (w, h) == (300, 200) and ext == '.jpg' and len(data) <= len(raw)   # 키우지 않고, 더 작으면 원본 그대로


def test_qr_stays_readable(tmp):
    segno = pytest.importorskip('segno')
    p = os.path.join(tmp, 'qr.png')
    segno.make('https://example.org/apply', error='q').save(p, scale=20, border=2)
    data, ext, w, h, _, _ = images.prepare_for_box(p, int(21 * MM), int(21 * MM))
    assert ext == '.png' and w < Image.open(p).size[0]
    zx = pytest.importorskip('zxingcpp')
    assert [r.text for r in zx.read_barcodes(Image.open(io.BytesIO(data)))] == ['https://example.org/apply']


def test_shrink_hwpx(tmp):
    src = os.path.join(tmp, 'doc.hwpx')
    spec.build({'template': TPL, 'blocks': [{'image': {'path': _photo(os.path.join(tmp, 'p2.png')), 'width_mm': 120}}]}, src)
    # 원본 사진을 그대로 넣은 문서처럼 만들기(BinData 를 큰 PNG 로 바꿔치기)
    big = os.path.join(tmp, 'big.hwpx')
    with zipfile.ZipFile(src) as zin, zipfile.ZipFile(big, 'w') as zout:
        for info in zin.infolist():
            data = zin.read(info.filename)
            if info.filename.startswith('BinData/'):
                buf = io.BytesIO()
                Image.open(os.path.join(tmp, 'p2.png')).save(buf, 'PNG')
                data = buf.getvalue()
                name = os.path.splitext(info.filename)[0] + '.png'
                hpf_fix = (info.filename, name)
                zout.writestr(name, data)
                continue
            zout.writestr(info, data)
    with zipfile.ZipFile(big) as z:
        hpf = z.read('Contents/content.hpf').decode('utf-8').replace(hpf_fix[0], hpf_fix[1])
    tmp2 = big + '.2'
    with zipfile.ZipFile(big) as zin, zipfile.ZipFile(tmp2, 'w') as zout:
        for info in zin.infolist():
            zout.writestr(info, hpf.encode('utf-8') if info.filename == 'Contents/content.hpf' else zin.read(info.filename))
    os.replace(tmp2, big)
    out = os.path.join(tmp, 'small.hwpx')
    rep, (b, f) = images.shrink_hwpx(big, out)
    assert rep and f < b / 3
    with zipfile.ZipFile(out) as z:
        names = z.namelist()
        hpf = z.read('Contents/content.hpf').decode('utf-8')
    jpgs = [n for n in names if n.startswith('BinData/') and n.endswith('.jpg')]
    assert jpgs and all(j in hpf for j in jpgs)                       # 이름이 바뀌면 매니페스트도 함께


def test_gongmun_check_pdf_detects_lone_approval(tmp):
    import pymupdf
    from hwpx_new.gongmun import check_pdf

    def make(path, body_on_last):
        d = pymupdf.open()
        p1 = d.new_page()
        p1.insert_text((72, 100), '1. 관련: 예시', fontname='korea')
        p2 = d.new_page()
        y = 100
        if body_on_last:
            for t in ('3. 협조 사항', '가. 문의: 예시과'):
                p2.insert_text((72, y), t, fontname='korea')
                y += 20
        y += 200
        for t in ('장학사', '협조자', '시행', '전화'):
            p2.insert_text((72, y), t, fontname='korea')
            y += 20
        d.save(path)
        return path
    assert check_pdf(make(os.path.join(tmp, 'alone.pdf'), False))
    assert not check_pdf(make(os.path.join(tmp, 'ok.pdf'), True))
