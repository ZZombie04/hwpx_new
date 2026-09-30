# -*- coding: utf-8 -*-
"""HWPX → PDF 변환. 한글(Windows) → LibreOffice → 내장 미리보기 렌더러 순으로 시도."""
from __future__ import annotations

import os
import shutil
import subprocess
import sys
import tempfile

from . import hancom


def _hancom(hwpx, pdf, timeout=None):
    ok, msg, _info = hancom.export_pdf(hwpx, pdf, timeout)
    return ok, msg


def _libreoffice(hwpx, pdf, timeout=150):
    exe = shutil.which('soffice') or shutil.which('libreoffice')
    if not exe:
        for c in (r'C:\Program Files\LibreOffice\program\soffice.exe',
                  '/Applications/LibreOffice.app/Contents/MacOS/soffice'):
            if os.path.exists(c):
                exe = c
    if not exe:
        return False, 'LibreOffice 를 찾지 못했습니다.'
    out = tempfile.mkdtemp()
    try:
        subprocess.run([exe, '--headless', '--convert-to', 'pdf', '--outdir', out, hwpx],
                       capture_output=True, text=True, timeout=timeout)
        cand = os.path.join(out, os.path.splitext(os.path.basename(hwpx))[0] + '.pdf')
        if os.path.exists(cand) and os.path.getsize(cand) > 1000:
            shutil.move(cand, pdf)
            return True, ''
        return False, 'LibreOffice 가 HWPX 를 열지 못했습니다(HWPX 필터 미설치).'
    except Exception as e:  # noqa
        return False, str(e)
    finally:
        shutil.rmtree(out, ignore_errors=True)


def _html(hwpx, pdf):
    from .render_html import render_pdf
    return render_pdf(hwpx, pdf)


ENGINES = {'hancom': _hancom, 'libreoffice': _libreoffice, 'html': _html}


def available_engines():
    res = {}
    res['hancom'] = hancom.installed() and bool(hancom._ps())
    res['libreoffice'] = bool(shutil.which('soffice') or shutil.which('libreoffice'))
    from .render_html import find_browser
    res['html'] = True
    res['browser'] = find_browser()
    return res


_FAILED = set()    # 이번 실행에서 실패한 엔진(자동 보정 반복 때 같은 대기를 되풀이하지 않도록)


def convert(hwpx, pdf, prefer=None):
    """반환: (engine, log). 엔진명이 None 이면 실패."""
    order = [prefer] if prefer else []
    order += [e for e in ('hancom', 'libreoffice', 'html') if e not in order]
    log = []
    for name in order:
        if name in _FAILED:
            continue
        ok, msg = ENGINES[name](hwpx, pdf)
        tries = 0
        while not ok and name == 'hancom' and tries < 2 and ('제한 시간' in msg or 'CO_E_SERVER' in msg
                                                             or 'New-Object' in msg or 'RPC' in msg or '80080005' in msg):
            tries += 1
            import time
            time.sleep(4)
            ok, msg = ENGINES[name](hwpx, pdf)     # 한글 첫 실행이 느려 타임아웃 나는 경우가 있어 최대 3번까지 시도
        if ok:
            return name, log
        if name != 'html':
            _FAILED.add(name)
        log.append(f'{name}: {msg}')
    return None, log


def hwp_to_hwpx(hwp, out, timeout=120):
    """옛 .hwp 를 .hwpx 로 변환(Windows + 한글 필요). 반환: (성공, 메시지)"""
    if sys.platform != 'win32':
        return False, '.hwp → .hwpx 자동 변환은 Windows + 한글에서만 가능합니다. 한글에서 [다른 이름으로 저장 → HWPX] 로 저장하세요.'
    return hancom.hwp_to_hwpx(hwp, out, timeout)
