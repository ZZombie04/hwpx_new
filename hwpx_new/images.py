# -*- coding: utf-8 -*-
"""사진 처리: 읽기 · 방향 보정(EXIF) · 크기 축소 · 한글이 여는 형식으로 변환 · HWPX 그림(hp:pic) 요소 생성."""
from __future__ import annotations

import io
import os
import re

from lxml import etree

from .package import HP

HC_NS = 'http://www.hancom.co.kr/hwpml/2011/core'
HC = '{%s}' % HC_NS
MM = 283.465          # 1mm = 283.465 HWPUNIT
IMG_EXT = ('.jpg', '.jpeg', '.png', '.bmp', '.gif', '.webp', '.heic', '.heif', '.tif', '.tiff')
MEDIA = {'.jpg': 'image/jpg', '.png': 'image/png', '.bmp': 'image/bmp', '.gif': 'image/gif'}


class ImageError(Exception):
    pass


def is_image(path: str) -> bool:
    return path.lower().endswith(IMG_EXT)


def _pil():
    try:
        from PIL import Image, ImageOps
        try:  # 아이폰 HEIC 지원(선택)
            import pillow_heif  # type: ignore
            pillow_heif.register_heif_opener()
        except Exception:  # noqa
            pass
        return Image, ImageOps
    except ImportError as e:  # pragma: no cover
        raise ImageError('사진 처리에는 Pillow 가 필요합니다: pip install pillow') from e


_CACHE = {}

# 문서에 넣는 그림의 해상도 기준: 인쇄해도 또렷한 200dpi(화면은 96~150dpi 면 충분). 표시 크기보다 큰 픽셀은 버린다.
DPI = 200
JPEG_QUALITY = 82          # 사진: 82 이상은 눈으로 구별이 거의 안 되고 용량만 커진다(4:2:0, 점진적 JPEG)
MAX_PX = 1600              # 표시 크기를 모를 때의 긴 변 상한


def image_size(path: str):
    """방향(EXIF)을 반영한 원본 픽셀 크기(가로, 세로). 그림 전체를 읽지 않는다."""
    Image, ImageOps = _pil()
    with Image.open(path) as im:
        w, h = im.size
        try:
            if im.getexif().get(0x0112, 1) in (5, 6, 7, 8):     # 90°/270° 회전
                w, h = h, w
        except Exception:  # noqa
            pass
    return w, h


def prepare_image(path: str, max_px: int = MAX_PX, box_mm=None, dpi: int = DPI):
    """캐시 래퍼(자동 보정으로 여러 번 조립해도 사진은 한 번만 처리).
    box_mm=(가로mm, 세로mm): 문서에 표시될 크기 — 이 크기를 dpi 로 채울 만큼만 픽셀을 남긴다."""
    box = (round(box_mm[0], 1), round(box_mm[1], 1)) if box_mm else None
    try:
        key = (os.path.abspath(path), os.path.getmtime(path), max_px, box, dpi)
    except OSError:
        key = None
    if key and key in _CACHE:
        return _CACHE[key]
    if not os.path.exists(path):
        raise ImageError(f'사진 파일을 찾을 수 없습니다: {path}')
    with open(path, 'rb') as f:
        raw = f.read()
    res = optimize_image(raw, os.path.splitext(path)[1].lower(), max_px=max_px, box_mm=box, dpi=dpi, name=path)
    if key:
        _CACHE[key] = res
    return res


def prepare_for_box(path: str, max_w: int, max_h: int, want_w=None, dpi: int = DPI):
    """표시 칸(HWPUNIT)에 맞춰 그림을 준비. 반환: (bytes, 확장자, 가로px, 세로px, 표시가로, 표시세로)."""
    try:
        w0, h0 = image_size(path)
    except Exception as e:  # noqa
        raise ImageError(f'사진을 열 수 없습니다({path}): {e}') from e
    w, h = fit_size(w0, h0, max_w, max_h, want_w)
    data, ext, wpx, hpx = prepare_image(path, box_mm=(w / MM, h / MM), dpi=dpi)
    return data, ext, wpx, hpx, w, h


def _colors(im, limit=256):
    """작게 줄인 사본의 색 수(limit 초과면 None) — 사진(색 많음)과 도표·QR·로고(색 적음)를 가른다."""
    t = im.convert('RGB')
    t.thumbnail((256, 256))
    c = t.getcolors(maxcolors=limit)
    return len(c) if c else None


def optimize_image(raw: bytes, ext: str = '', max_px: int = MAX_PX, box_mm=None, dpi: int = DPI, name='그림'):
    """그림 바이트 → (bytes, 확장자, 가로px, 세로px). 문서 용량을 줄이되 화질은 표시 크기에서 티 나지 않게.
    - 방향(EXIF) 보정, 표시 크기 × dpi 보다 큰 픽셀은 줄임(키우지는 않음)
    - 사진(색 많음) → JPEG(품질 82, 4:2:0, 점진적), 도표·QR·로고(색 256 이하) → 팔레트 PNG(2색이면 계단 없이 또렷하게)
    - 투명 배경 → PNG. 원본이 이미 더 작으면 원본을 그대로 쓴다."""
    Image, ImageOps = _pil()
    try:
        im = Image.open(io.BytesIO(raw))
        im.load()
    except Exception as e:  # noqa
        raise ImageError(f'사진을 열 수 없습니다({name}): {e}') from e
    fmt0 = (im.format or '').upper()
    rotated = False
    try:
        if im.getexif().get(0x0112, 1) != 1:
            im = ImageOps.exif_transpose(im)
            rotated = True
    except Exception:  # noqa
        pass
    w, h = im.size
    if box_mm:
        tw, th = box_mm[0] / 25.4 * dpi, box_mm[1] / 25.4 * dpi
        scale = min(1.0, tw / w, th / h) if tw > 0 and th > 0 else 1.0
    else:
        scale = min(1.0, max_px / max(w, h))
    has_alpha = im.mode in ('RGBA', 'LA', 'PA') or (im.mode == 'P' and 'transparency' in im.info)
    ncol = _colors(im)
    graphic = ncol is not None
    if scale < 0.98:
        nw, nh = max(1, round(w * scale)), max(1, round(h * scale))
        if graphic and ncol <= 2:
            im = im.convert('L').resize((nw, nh), Image.LANCZOS).point(lambda v: 0 if v < 128 else 255)
        else:
            src = im.convert('RGBA' if has_alpha else 'RGB') if im.mode not in ('RGB', 'RGBA', 'L') else im
            im = src.resize((nw, nh), Image.LANCZOS)
    buf = io.BytesIO()
    if has_alpha:
        im = im.convert('RGBA')
        im.save(buf, 'PNG', optimize=True)
        out_ext = '.png'
    elif graphic:
        if im.mode == 'L' and ncol <= 2:
            im = im.convert('1', dither=Image.NONE)
        elif im.mode != 'P':
            im = im.convert('RGB').quantize(colors=max(2, min(256, ncol)), dither=Image.NONE)
        im.save(buf, 'PNG', optimize=True)
        out_ext = '.png'
    else:
        im = im.convert('RGB')
        im.save(buf, 'JPEG', quality=JPEG_QUALITY, optimize=True, progressive=True, subsampling=2)
        out_ext = '.jpg'
    data = buf.getvalue()
    keep = scale >= 0.98 and not rotated and fmt0 in ('JPEG', 'PNG') and len(raw) <= len(data)
    if keep:                                     # 줄일 것이 없고 원본이 더 작으면 원본 그대로(재압축 손실 없음)
        return raw, ('.jpg' if fmt0 == 'JPEG' else '.png'), w, h
    return data, out_ext, im.size[0], im.size[1]


def shrink_hwpx(src: str, out: str, dpi: int = DPI, min_gain: float = 0.1):
    """이미 만든 HWPX 안의 그림을 표시 크기에 맞춰 다시 줄인다(글·서식·나머지 파일은 그대로).
    그림마다 문서에 표시된 가장 큰 크기(hp:curSz)를 찾아 그 크기 × dpi 만큼만 남기고, 사진은 JPEG·도표는 팔레트 PNG 로.
    min_gain(기본 10%) 이상 줄어들 때만 바꾼다. 반환: [(그림, 전 KB, 후 KB)], (전체 전 KB, 후 KB)."""
    import zipfile
    zin = zipfile.ZipFile(src)
    names = zin.namelist()
    sizes = {}
    for n in names:
        if not n.startswith('Contents/section'):
            continue
        root = etree.fromstring(zin.read(n))
        for pic in root.iter(HP + 'pic'):
            img = pic.find('.//' + HC + 'img')
            sz = pic.find(HP + 'curSz')
            if sz is None or int(sz.get('width', '0')) <= 0:
                sz = pic.find(HP + 'sz')
            if img is None or sz is None:
                continue
            bid = img.get('binaryItemIDRef')
            w, h = int(sz.get('width', '0')), int(sz.get('height', '0'))
            ow, oh = sizes.get(bid, (0, 0))
            sizes[bid] = (max(ow, w), max(oh, h))
    opf = '{http://www.idpf.org/2007/opf/}'
    hpf = etree.fromstring(zin.read('Contents/content.hpf'))
    items = {it.get('id'): it for it in hpf.iter(opf + 'item')}
    replace, rename, report = {}, {}, []
    for bid, (w, h) in sizes.items():
        it = items.get(bid)
        if it is None or w <= 0 or h <= 0 or it.get('href') not in names:
            continue
        href = it.get('href')
        raw = zin.read(href)
        try:
            data, ext, _, _ = optimize_image(raw, os.path.splitext(href)[1].lower(), box_mm=(w / MM, h / MM), dpi=dpi,
                                             name=href)
        except ImageError:
            continue
        if len(data) > len(raw) * (1 - min_gain):
            continue
        new_href = os.path.splitext(href)[0] + ext
        if new_href.lower() != href.lower():
            rename[href] = new_href
            it.set('href', new_href)
            it.set('media-type', MEDIA.get(ext, 'image/png'))
        replace[href] = data
        report.append((href, round(len(raw) / 1024), round(len(data) / 1024)))
    before = sum(i.compress_size for i in zin.infolist())
    tmp = out + '.tmp'
    with zipfile.ZipFile(tmp, 'w') as zout:
        for info in zin.infolist():
            n = info.filename
            data = zin.read(n)
            if n == 'Contents/content.hpf' and rename:
                data = etree.tostring(hpf, xml_declaration=True, encoding='UTF-8', standalone=True)
            if n in replace:
                data = replace[n]
            zi = zipfile.ZipInfo(rename.get(n, n), date_time=info.date_time)
            zi.compress_type = info.compress_type
            zi.external_attr, zi.create_system = info.external_attr, info.create_system
            zout.writestr(zi, data)
    zin.close()
    os.replace(tmp, out)
    with zipfile.ZipFile(out) as z:
        after = sum(i.compress_size for i in z.infolist())
    return report, (round(before / 1024), round(after / 1024))


def photo_info(path: str):
    """사진 목록용 정보(크기·촬영일시·방향)."""
    Image, ImageOps = _pil()
    info = {'path': path, 'name': os.path.basename(path), 'size_kb': round(os.path.getsize(path) / 1024)}
    try:
        im = Image.open(path)
        ex = im.getexif()
        dt = ex.get(36867) or ex.get(306)
        try:
            sub = ex.get_ifd(0x8769)
            dt = sub.get(36867) or dt
        except Exception:  # noqa
            pass
        im2 = ImageOps.exif_transpose(im)
        info.update(width=im2.size[0], height=im2.size[1], taken=str(dt) if dt else None)
        info['orientation'] = '가로' if im2.size[0] >= im2.size[1] else '세로'
    except Exception as e:  # noqa
        info['error'] = str(e)
    return info


def fit_size(w_px, h_px, max_w, max_h, want_w=None):
    """가로·세로 제한 안에서 비율을 유지한 표시 크기(HWPUNIT). want_w 가 있으면 그 폭(제한 안에서)."""
    w = min(want_w or max_w, max_w)
    h = w * h_px / w_px
    if h > max_h:
        h = max_h
        w = h * w_px / h_px
    return int(w), int(h)


def pic_run(char_id: str, bin_id: str, w: int, h: int, w_px: int, h_px: int, inline: bool = True,
            uid: int = 1, name: str = 'photo'):
    """`<hp:run>` 안에 넣을 그림 요소를 만든다(한글이 만든 파일의 구조와 동일)."""
    org_w, org_h = w_px * 75, h_px * 75          # 96dpi 기준 원본 크기
    run = etree.Element(HP + 'run')
    run.set('charPrIDRef', char_id)
    pic = etree.SubElement(run, HP + 'pic')
    for k, v in (('id', str(2000000000 + uid)), ('zOrder', str(uid)), ('numberingType', 'PICTURE'),
                 ('textWrap', 'TOP_AND_BOTTOM'), ('textFlow', 'BOTH_SIDES'), ('lock', '0'),
                 ('dropcapstyle', 'None'), ('href', ''), ('groupLevel', '0'), ('instid', str(900000000 + uid)),
                 ('reverse', '0')):
        pic.set(k, v)
    etree.SubElement(pic, HP + 'offset', x='0', y='0')
    etree.SubElement(pic, HP + 'orgSz', width=str(org_w), height=str(org_h))
    etree.SubElement(pic, HP + 'curSz', width=str(w), height=str(h))
    etree.SubElement(pic, HP + 'flip', horizontal='0', vertical='0')
    etree.SubElement(pic, HP + 'rotationInfo', angle='0', centerX=str(w // 2), centerY=str(h // 2), rotateimage='1')
    ri = etree.SubElement(pic, HP + 'renderingInfo')
    etree.SubElement(ri, HC + 'transMatrix', e1='1', e2='0', e3='0', e4='0', e5='1', e6='0')
    etree.SubElement(ri, HC + 'scaMatrix', e1=f'{w / org_w:.6f}', e2='0', e3='0', e4='0', e5=f'{h / org_h:.6f}', e6='0')
    etree.SubElement(ri, HC + 'rotMatrix', e1='1', e2='0', e3='0', e4='0', e5='1', e6='0')
    etree.SubElement(pic, HC + 'img', binaryItemIDRef=bin_id, bright='0', contrast='0', effect='REAL_PIC', alpha='0')
    rect = etree.SubElement(pic, HP + 'imgRect')
    for i, (x, y) in enumerate(((0, 0), (org_w, 0), (org_w, org_h), (0, org_h))):
        etree.SubElement(rect, HC + f'pt{i}', x=str(x), y=str(y))
    etree.SubElement(pic, HP + 'imgClip', left='0', right=str(org_w), top='0', bottom=str(org_h))
    etree.SubElement(pic, HP + 'inMargin', left='0', right='0', top='0', bottom='0')
    etree.SubElement(pic, HP + 'imgDim', dimwidth=str(org_w), dimheight=str(org_h))
    etree.SubElement(pic, HP + 'effects')
    etree.SubElement(pic, HP + 'sz', width=str(w), widthRelTo='ABSOLUTE', height=str(h), heightRelTo='ABSOLUTE',
                     protect='0')
    etree.SubElement(pic, HP + 'pos', treatAsChar='1' if inline else '0', affectLSpacing='0', flowWithText='1',
                     allowOverlap='0', holdAnchorAndSO='0', vertRelTo='PARA', horzRelTo='COLUMN' if not inline else 'PARA',
                     vertAlign='TOP', horzAlign='LEFT', vertOffset='0', horzOffset='0')
    etree.SubElement(pic, HP + 'outMargin', left='0', right='0', top='0', bottom='0')
    cm = etree.SubElement(pic, HP + 'shapeComment')
    cm.text = f'그림입니다.\n원본 그림의 이름: {name}'
    etree.SubElement(run, HP + 't')
    return run


def register_images(pkg, images):
    """images: [(bin_id, ext, bytes)] → BinData 파일 추가 + content.hpf 매니페스트 등록."""
    if not images:
        return
    hpf = etree.fromstring(pkg.files['Contents/content.hpf'])
    opf = 'http://www.idpf.org/2007/opf/'
    manifest = hpf.find('{%s}manifest' % opf)
    for bin_id, ext, data in images:
        href = f'BinData/{bin_id}{ext}'
        pkg.files[href] = data
        it = etree.SubElement(manifest, '{%s}item' % opf)
        it.set('id', bin_id)
        it.set('href', href)
        it.set('media-type', MEDIA.get(ext, 'image/png'))
        it.set('isEmbeded', '1')
    pkg.files['Contents/content.hpf'] = etree.tostring(hpf, xml_declaration=True, encoding='UTF-8', standalone=True)


def next_image_index(pkg) -> int:
    used = [int(m.group(1)) for n in pkg.files for m in [re.match(r'BinData/image(\d+)\.', n)] if m]
    hpf = pkg.files.get('Contents/content.hpf', b'').decode('utf-8', 'ignore')
    used += [int(x) for x in re.findall(r'id="image(\d+)"', hpf)]
    return (max(used) if used else 0) + 1
