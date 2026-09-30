# -*- coding: utf-8 -*-
"""한글 공식 '자동화 보안 모듈' 등록 도우미(사용자가 직접 실행하는 선택 기능).

한글은 외부 프로그램이 파일을 열 때 "파일 접근 허용" 창을 띄웁니다. 한글이 공식으로 제공하는 해결책은
'보안 모듈'(FilePathChecker DLL)을 등록하는 것입니다. 등록하면 이 PC 의 한글이 그 모듈의 판단에 따라 자동으로 승인하므로 창이 뜨지 않습니다.

- 이 도구는 DLL 을 내려받거나 만들지 않습니다. 한글 개발자 자료(자동화 SDK)의 'FilePathCheckerModule' DLL 을 직접 구한 경로를 넘겨야 합니다.
- 등록은 현재 사용자(HKCU) 레지스트리에만 하며 `remove` 로 되돌릴 수 있습니다.
- 보안 설정을 바꾸는 일이므로 기본 동작(자동 클릭)과 달리 **명령을 직접 실행했을 때만** 합니다.
"""
from __future__ import annotations

import os
import subprocess
import sys

KEY = r'Software\HNC\HwpAutomation\Modules'
NAME = 'FilePathCheckerModule'     # hancom.RUN_PS 가 RegisterModule('FilePathCheckDLL', 이 이름) 으로 부른다


def _winreg():
    if sys.platform != 'win32':
        raise RuntimeError('한글 보안 모듈 등록은 Windows 에서만 할 수 있습니다.')
    import winreg
    return winreg


def status(key=KEY):
    """등록된 모듈 목록 {이름: DLL 경로}."""
    wr = _winreg()
    out = {}
    try:
        with wr.OpenKey(wr.HKEY_CURRENT_USER, key) as k:
            i = 0
            while True:
                try:
                    n, v, _t = wr.EnumValue(k, i)
                except OSError:
                    break
                out[n] = v
                i += 1
    except FileNotFoundError:
        pass
    return out


def register(dll, name=NAME, key=KEY):
    wr = _winreg()
    dll = os.path.abspath(dll)
    if not os.path.isfile(dll) or not dll.lower().endswith('.dll'):
        raise RuntimeError(f'DLL 파일을 찾을 수 없습니다: {dll}')
    with wr.CreateKeyEx(wr.HKEY_CURRENT_USER, key, 0, wr.KEY_SET_VALUE) as k:
        wr.SetValueEx(k, name, 0, wr.REG_SZ, dll)
    return dll


def remove(name=NAME, key=KEY):
    wr = _winreg()
    try:
        with wr.OpenKey(wr.HKEY_CURRENT_USER, key, 0, wr.KEY_SET_VALUE) as k:
            wr.DeleteValue(k, name)
        return True
    except FileNotFoundError:
        return False


def verify():
    """한글을 열어 RegisterModule 이 True 를 돌려주는지 확인(한글 프로세스는 스스로 띄운 것만 정리)."""
    from . import hancom
    ps = hancom._ps()
    if not ps:
        return False, 'PowerShell 을 찾지 못했습니다.'
    script = ("$h = New-Object -ComObject HWPFrame.HwpObject; "
              f"$r = $h.RegisterModule('FilePathCheckDLL', '{NAME}'); "
              "try { $h.Quit() | Out-Null } catch {}; if ($r) { 'OK' } else { 'FAIL' }")
    before = hancom.hwp_pids()
    try:
        r = subprocess.run([ps, '-NoProfile', '-Command', script], capture_output=True, text=True, errors='replace',
                           timeout=60)
        ok = 'OK' in (r.stdout or '')
        return ok, (r.stdout or r.stderr or '').strip()[:200]
    except Exception as e:  # noqa
        return False, str(e)
    finally:
        hancom.kill_new_hwp(before)
