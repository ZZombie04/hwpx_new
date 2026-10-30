# -*- coding: utf-8 -*-
"""한글 자동화를 사용자 화면과 완전히 떼어 놓고 실행하기 (Windows).

사용자가 PC 를 쓰는 동안 COM 으로 띄운 한글이 키보드 포커스를 가져가거나 창이 잠깐 앞으로 나오는 일을 막는다.
방법: 이 도구 전용 '숨은 데스크톱'(CreateDesktop)을 만들고, 한글을 조작하는 PowerShell 을 그 데스크톱에서 실행한다.
그 PowerShell 이 COM 으로 띄우는 한글(Hwp.exe -Automation -Embedding)도 같은 숨은 데스크톱에 생긴다(2026-10-30 한글 2024 실측).
숨은 데스크톱의 창은 사용자가 보는 데스크톱의 전경 창이 될 수 없으므로 키보드·마우스 입력과 포커스를 절대 가져가지 않는다.

- 사용자 데스크톱의 창은 하나도 건드리지 않는다(SetForegroundWindow·마우스·키 입력 없음).
- 숨은 데스크톱을 만들 수 없으면(서비스 계정 등) 보통 방식으로 실행하되, 역시 포커스를 옮기는 호출은 하지 않는다.
- HWPX_NEW_VISIBLE=1 이면 숨은 데스크톱을 쓰지 않는다(문제 진단용).
"""
from __future__ import annotations

import os
import subprocess
import sys
import time

DESKTOP = 'hwpx_new_automation'
_desk_handle = None


def enabled() -> bool:
    return sys.platform == 'win32' and os.environ.get('HWPX_NEW_VISIBLE') != '1'


def _desktop():
    """숨은 데스크톱 핸들(처음 한 번 만들고 프로세스가 끝날 때까지 열어 둔다). 실패하면 None."""
    global _desk_handle
    if _desk_handle:
        return _desk_handle
    try:
        import ctypes
        import ctypes.wintypes as W
        u32 = ctypes.WinDLL('user32', use_last_error=True)
        u32.CreateDesktopW.restype = W.HANDLE
        u32.CreateDesktopW.argtypes = [W.LPCWSTR, W.LPCWSTR, ctypes.c_void_p, W.DWORD, W.DWORD, ctypes.c_void_p]
        h = u32.CreateDesktopW(DESKTOP, None, None, 0, 0x10000000, None)   # GENERIC_ALL, 이미 있으면 그것을 연다
        _desk_handle = h or None
    except Exception:  # noqa
        _desk_handle = None
    return _desk_handle


class _Proc:
    """CreateProcess 로 띄운 프로세스(subprocess.Popen 의 poll·wait·kill 만 흉내)."""

    def __init__(self, hproc, pid):
        self._h, self.pid, self.returncode = hproc, pid, None

    def poll(self):
        if self.returncode is not None:
            return self.returncode
        import ctypes
        import ctypes.wintypes as W
        k32 = ctypes.windll.kernel32
        if k32.WaitForSingleObject(W.HANDLE(self._h), 0) == 0:
            code = W.DWORD()
            k32.GetExitCodeProcess(W.HANDLE(self._h), ctypes.byref(code))
            self.returncode = code.value
            k32.CloseHandle(W.HANDLE(self._h))
        return self.returncode

    def wait(self, timeout=None):
        t0 = time.time()
        while self.poll() is None:
            if timeout is not None and time.time() - t0 > timeout:
                raise subprocess.TimeoutExpired('hidden-desktop process', timeout)
            time.sleep(0.2)
        return self.returncode

    def kill(self):
        if self.poll() is None:
            import ctypes
            import ctypes.wintypes as W
            ctypes.windll.kernel32.TerminateProcess(W.HANDLE(self._h), 1)
            self.wait(10)

    terminate = kill


def _quote(a: str) -> str:
    return subprocess.list2cmdline([a])


def spawn(args):
    """args(리스트)를 숨은 데스크톱에서 실행. 표준 입출력은 쓰지 않는다(결과는 파일로 주고받는다).
    숨은 데스크톱을 쓸 수 없으면 보통 방식(창 없음)으로 실행한다. 돌려줌: poll/wait/kill 이 있는 객체."""
    flags = getattr(subprocess, 'CREATE_NO_WINDOW', 0)
    desk = _desktop() if enabled() else None
    if not desk:
        return subprocess.Popen(args, stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL, creationflags=flags)
    import ctypes
    import ctypes.wintypes as W

    class SI(ctypes.Structure):
        _fields_ = [('cb', W.DWORD), ('lpReserved', W.LPWSTR), ('lpDesktop', W.LPWSTR), ('lpTitle', W.LPWSTR),
                    ('dwX', W.DWORD), ('dwY', W.DWORD), ('dwXSize', W.DWORD), ('dwYSize', W.DWORD),
                    ('dwXCountChars', W.DWORD), ('dwYCountChars', W.DWORD), ('dwFillAttribute', W.DWORD),
                    ('dwFlags', W.DWORD), ('wShowWindow', W.WORD), ('cbReserved2', W.WORD),
                    ('lpReserved2', ctypes.c_void_p), ('hStdInput', W.HANDLE), ('hStdOutput', W.HANDLE),
                    ('hStdError', W.HANDLE)]

    class PI(ctypes.Structure):
        _fields_ = [('hProcess', W.HANDLE), ('hThread', W.HANDLE), ('dwProcessId', W.DWORD), ('dwThreadId', W.DWORD)]

    si = SI()
    si.cb = ctypes.sizeof(SI)
    si.lpDesktop = 'WinSta0\\' + DESKTOP
    si.dwFlags = 0x1                      # STARTF_USESHOWWINDOW
    si.wShowWindow = 0                    # SW_HIDE
    pi = PI()
    cmd = ctypes.create_unicode_buffer(' '.join(_quote(str(a)) for a in args))
    k32 = ctypes.WinDLL('kernel32', use_last_error=True)
    ok = k32.CreateProcessW(None, cmd, None, None, False, flags, None, None, ctypes.byref(si), ctypes.byref(pi))
    if not ok:
        return subprocess.Popen(args, stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL, creationflags=flags)
    k32.CloseHandle(pi.hThread)
    return _Proc(pi.hProcess, pi.dwProcessId)


class HwpLock:
    """한글 작업을 한 번에 하나씩(여러 AI·여러 창이 동시에 돌려도 한글 COM 이 서로 부딪히지 않게)."""

    def __init__(self, folder: str, timeout: float = 900):
        self.path = os.path.join(folder, 'hwpx_new.lock')
        self.timeout = timeout
        self.fh = None

    def __enter__(self):
        t0 = time.time()
        while True:
            try:
                self.fh = open(self.path, 'a+b')
                if sys.platform == 'win32':
                    import msvcrt
                    self.fh.seek(0)
                    msvcrt.locking(self.fh.fileno(), msvcrt.LK_NBLCK, 1)
                return self
            except OSError:
                if self.fh:
                    self.fh.close()
                    self.fh = None
                if time.time() - t0 > self.timeout:
                    raise TimeoutError('다른 한글 작업이 끝나지 않아 기다리다 멈췄습니다.')
                time.sleep(0.5)

    def __exit__(self, *a):
        try:
            if self.fh and sys.platform == 'win32':
                import msvcrt
                self.fh.seek(0)
                msvcrt.locking(self.fh.fileno(), msvcrt.LK_UNLCK, 1)
        except OSError:
            pass
        finally:
            if self.fh:
                self.fh.close()
