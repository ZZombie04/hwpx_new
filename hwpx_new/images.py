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


def prepare_image(path: str, max_px: int = 1600):
    """캐시 래퍼(자동 보정으로 여러 번 조립해도 사진은 한 번만 처리)."""
    try:
        key = (os.path.abspath(path), os.path.getmtime(path), max_px)
    except OSError:
        key = None
    if key and key in _CACHE:
        return _CACHE[key]
    res = _prepare_image(path, max_px)
    if key:
        _CACHE[key] = res
    return res


def _prepare_image(path: str, max_px: int = 1600):
    """사진 파일 → (bytes, 확장자, 가로px, 세로px). EXIF 방향 보정, 큰 사진 축소, 한글 비지원 형식은 PNG/JPG 로 변환."""
    if not os.path.exists(path):
        raise ImageError(f'사진 파일을 찾을 수 없습니다: {path}')
    Image, ImageOps = _pil()
    ext = os.path.splitext(path)[1].lower()
    try:
        im = Image.open(path)
        im.load()
    except Exception as e:  # noqa
        raise ImageError(f'사진을 열 수 없습니다({path}): {e}') from e
    try:
        im = ImageOps.exif_transpose(im)
    except Exception:  # noqa
        pass
    w, h = im.size
    scale = min(1.0, max_px / max(w, h))
    if scale < 1.0:
        im = im.resize((max(1, int(w * scale)), max(1, int(h * scale))), Image.LANCZOS)
    w, h = im.size
    has_alpha = im.mode in ('RGBA', 'LA') or (im.mode == 'P' and 'transparency' in im.info)
    buf = io.BytesIO()
    if ext in ('.png',) or has_alpha:
        if im.mode not in ('RGB', 'RGBA', 'L'):
            im = im.convert('RGBA' if has_alpha else 'RGB')
        im.save(buf, 'PNG', optimize=True)
        out_ext = '.png'
    else:
        if im.mode != 'RGB':
            im = im.convert('RGB')
        im.save(buf, 'JPEG', quality=85, optimize=True)
        out_ext = '.jpg'
    return buf.getvalue(), out_ext, w, h


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
