# -*- coding: utf-8 -*-
"""HWPX → PDF 변환. 한글(Windows) → LibreOffice → 내장 미리보기 렌더러 순으로 시도."""
from __future__ import annotations

import os
import shutil
import subprocess
import sys
import tempfile

PS_SCRIPT = r"""
$ErrorActionPreference = 'Stop'
# 사용자가 이미 열어 둔 한글 창은 건드리지 않기 위해, 이 스크립트가 띄운 프로세스만 정리한다.
$before = @(Get-Process -Name Hwp -ErrorAction SilentlyContinue | ForEach-Object { $_.Id })
try {
  $h = New-Object -ComObject HWPFrame.HwpObject
  try { $h.RegisterModule('FilePathCheckDLL','FilePathCheckerModule') | Out-Null } catch {}
  $h.Open($args[0], 'HWPX', '') | Out-Null
  $h.SaveAs($args[1], 'PDF', '') | Out-Null
  try { $h.Clear(1) | Out-Null } catch {}
  try { $h.Quit() | Out-Null } catch {}
} finally {
  Start-Sleep -Milliseconds 300
  Get-Process -Name Hwp -ErrorAction SilentlyContinue | Where-Object { $before -notcontains $_.Id } | Stop-Process -Force -ErrorAction SilentlyContinue
}
"""


def _hwp_pids():
    try:
        r = subprocess.run(['tasklist', '/FO', 'CSV', '/NH', '/FI', 'IMAGENAME eq Hwp.exe'],
                           capture_output=True, text=True, errors='replace', timeout=20)
        return {int(l.split('","')[1]) for l in r.stdout.splitlines() if l.startswith('"Hwp.exe"')}
    except Exception:  # noqa
        return set()


def _kill_new_hwp(before):
    """이 도구가 띄운 한글 프로세스만 종료(사용자가 열어 둔 한글은 건드리지 않음)."""
    for pid in _hwp_pids() - before:
        subprocess.run(['taskkill', '/F', '/PID', str(pid)], capture_output=True, timeout=20)


HANCOM_HINT = ('한글이 응답하지 않았습니다. 한글 화면에 "파일 접근 허용" 보안 승인 창이 떠 있을 수 있습니다. '
               '그 창에서 [허용]을 누르면(또는 README 의 "한글 자동화 승인" 참고) 다음부터 자동 변환됩니다.')


def _hancom(hwpx, pdf, timeout=75):
    if sys.platform != 'win32':
        return False, '한글은 Windows 에서만 자동 변환할 수 있습니다.'
    ps = shutil.which('powershell') or shutil.which('pwsh')
    if not ps:
        return False, 'PowerShell 을 찾지 못했습니다.'
    tmp = tempfile.NamedTemporaryFile('w', suffix='.ps1', delete=False, encoding='utf-8-sig')
    tmp.write(PS_SCRIPT)
    tmp.close()
    before = _hwp_pids()
    try:
        if os.path.exists(pdf):
            os.remove(pdf)
        r = subprocess.run([ps, '-NoProfile', '-ExecutionPolicy', 'Bypass', '-File', tmp.name,
                            os.path.abspath(hwpx), os.path.abspath(pdf)],
                           capture_output=True, text=True, errors='replace', timeout=timeout)
        if os.path.exists(pdf) and os.path.getsize(pdf) > 1000:
            return True, ''
        return False, (r.stderr or r.stdout or '한글 변환 실패').strip()[:300]
    except subprocess.TimeoutExpired:
        return False, HANCOM_HINT
    except Exception as e:  # noqa
        return False, str(e)
    finally:
        _kill_new_hwp(before)
        os.unlink(tmp.name)


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
    res['hancom'] = sys.platform == 'win32' and bool(shutil.which('powershell') or shutil.which('pwsh')) and any(
        os.path.exists(p) for p in (
            r'C:\Program Files (x86)\Hnc', r'C:\Program Files\Hnc', r'C:\Program Files (x86)\HNC',
            r'C:\Program Files\HNC'))
    res['libreoffice'] = bool(shutil.which('soffice') or shutil.which('libreoffice'))
    from .render_html import find_browser
    res['html'] = True
    res['browser'] = find_browser()
    return res


def convert(hwpx, pdf, prefer=None):
    """반환: (engine, log). 엔진명이 None 이면 실패."""
    order = [prefer] if prefer else []
    order += [e for e in ('hancom', 'libreoffice', 'html') if e not in order]
    log = []
    for name in order:
        ok, msg = ENGINES[name](hwpx, pdf)
        if ok:
            return name, log
        log.append(f'{name}: {msg}')
    return None, log


PS_HWP2HWPX = r"""
$ErrorActionPreference = 'Stop'
$before = @(Get-Process -Name Hwp -ErrorAction SilentlyContinue | ForEach-Object { $_.Id })
try {
  $h = New-Object -ComObject HWPFrame.HwpObject
  try { $h.RegisterModule('FilePathCheckDLL','FilePathCheckerModule') | Out-Null } catch {}
  $h.Open($args[0], 'HWP', '') | Out-Null
  $h.SaveAs($args[1], 'HWPX', '') | Out-Null
  try { $h.Clear(1) | Out-Null } catch {}
  try { $h.Quit() | Out-Null } catch {}
} finally {
  Start-Sleep -Milliseconds 300
  Get-Process -Name Hwp -ErrorAction SilentlyContinue | Where-Object { $before -notcontains $_.Id } | Stop-Process -Force -ErrorAction SilentlyContinue
}
"""


def hwp_to_hwpx(hwp, out, timeout=90):
    """옛 .hwp 를 .hwpx 로 변환(Windows + 한글 필요). 반환: (성공, 메시지)"""
    if sys.platform != 'win32':
        return False, '.hwp → .hwpx 자동 변환은 Windows + 한글에서만 가능합니다. 한글에서 [다른 이름으로 저장 → HWPX] 로 저장하세요.'
    ps = shutil.which('powershell') or shutil.which('pwsh')
    tmp = tempfile.NamedTemporaryFile('w', suffix='.ps1', delete=False, encoding='utf-8-sig')
    tmp.write(PS_HWP2HWPX)
    tmp.close()
    try:
        if os.path.exists(out):
            os.remove(out)
        r = subprocess.run([ps, '-NoProfile', '-ExecutionPolicy', 'Bypass', '-File', tmp.name,
                            os.path.abspath(hwp), os.path.abspath(out)],
                           capture_output=True, text=True, errors='replace', timeout=timeout)
        if os.path.exists(out) and os.path.getsize(out) > 1000:
            return True, out
        return False, (r.stderr or r.stdout or '변환 실패').strip()[:300]
    except Exception as e:  # noqa
        return False, str(e)
    finally:
        os.unlink(tmp.name)
