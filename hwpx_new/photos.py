# -*- coding: utf-8 -*-
"""사진 폴더 살펴보기: 목록 + 번호가 붙은 한눈에 보기 이미지(AI 가 사진을 한 번에 보고 배치를 정하도록)."""
from __future__ import annotations

import os

from .images import IMG_EXT, ImageError, _pil, photo_info


def list_photos(folder: str):
    if os.path.isfile(folder):
        files = [folder]
    else:
        files = [os.path.join(folder, f) for f in sorted(os.listdir(folder)) if f.lower().endswith(IMG_EXT)]
    infos = [photo_info(f) for f in files]
    infos.sort(key=lambda i: (i.get('taken') or '9999', i['name']))
    return infos


def contact_sheet(infos, out_path, thumb=280, cols=4):
    Image, ImageOps = _pil()
    from PIL import ImageDraw
    if not infos:
        raise ImageError('사진이 없습니다.')
    rows = (len(infos) + cols - 1) // cols
    W, H = cols * (thumb + 10) + 10, rows * (thumb + 34) + 10
    sheet = Image.new('RGB', (W, H), 'white')
    d = ImageDraw.Draw(sheet)
    for i, inf in enumerate(infos):
        try:
            im = ImageOps.exif_transpose(Image.open(inf['path'])).convert('RGB')
            im.thumbnail((thumb, thumb))
        except Exception:  # noqa
            continue
        x = 10 + (i % cols) * (thumb + 10)
        y = 10 + (i // cols) * (thumb + 34)
        sheet.paste(im, (x + (thumb - im.width) // 2, y + 24 + (thumb - im.height) // 2))
        d.rectangle([x, y, x + 46, y + 20], fill='black')
        d.text((x + 6, y + 4), f'#{i + 1}', fill='white')
    sheet.save(out_path)
    return out_path


def describe_folder(folder: str, out: str | None = None):
    infos = list_photos(folder)
    if not infos:
        return f'사진이 없습니다: {folder}', None
    base = folder if os.path.isdir(folder) else os.path.dirname(folder)
    out = out or os.path.join(base or '.', '_photo_sheet.png')
    contact_sheet(infos, out)
    L = [f'사진 {len(infos)}장 (촬영 시각 순). 번호는 한눈에 보기 이미지 {out} 의 #번호와 같습니다.', '']
    L.append('| # | 파일 | 촬영일시 | 크기(px) | 방향 | 용량 |')
    L.append('|:-:|---|---|---|:-:|---:|')
    for i, inf in enumerate(infos, 1):
        L.append(f'| {i} | {inf["name"]} | {inf.get("taken") or "-"} | {inf.get("width", "?")}×{inf.get("height", "?")} | '
                 f'{inf.get("orientation", "?")} | {inf["size_kb"]}KB |')
    L.append('')
    L.append('다음 단계: 한눈에 보기 이미지를 열어 각 사진이 무엇인지 파악한 뒤, 알맞은 절에 '
             '`![캡션](경로)` 또는 `:::photos` 로 넣으세요.')
    return chr(10).join(L), out
