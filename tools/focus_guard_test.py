# -*- coding: utf-8 -*-
"""한글 변환이 사용자 화면을 방해하지 않는지 실측한다.

변환하는 동안 50ms 마다 (1) 전경 창이 바뀌는지 (2) 사용자 데스크톱에 이 도구가 띄운 한글 창이 생기는지
(3) 마우스 커서가 움직였는지를 기록한다. 사용: python tools/focus_guard_test.py [hwpx 파일]
성공 기준: 한글·PowerShell 이 전경 창이 된 횟수 0, 사용자 데스크톱의 새 한글 창 0(사용자가 직접 창을 바꾼 것은 제외).
"""
import ctypes
import ctypes.wintypes as W
import os
import sys
import tempfile
import threading
import time

sys.path.insert(0, os.path.join(os.path.dirname(os.path.abspath(__file__)), '..'))
from hwpx_new import hancom  # noqa: E402

u32 = ctypes.windll.user32
EnumProc = ctypes.WINFUNCTYPE(W.BOOL, W.HWND, W.LPARAM)


def proc_name(hwnd):
    p = W.DWORD()
    u32.GetWindowThreadProcessId(hwnd, ctypes.byref(p))
    k32 = ctypes.windll.kernel32
    h = k32.OpenProcess(0x1000, False, p.value)      # PROCESS_QUERY_LIMITED_INFORMATION
    if not h:
        return '?'
    buf = ctypes.create_unicode_buffer(260)
    n = W.DWORD(260)
    k32.QueryFullProcessImageNameW(h, 0, buf, ctypes.byref(n))
    k32.CloseHandle(h)
    return os.path.basename(buf.value) or '?'


def visible_windows_of(pids):
    found = []

    def cb(h, _l):
        p = W.DWORD()
        u32.GetWindowThreadProcessId(h, ctypes.byref(p))
        if p.value in pids and u32.IsWindowVisible(h):
            found.append(h)
        return True
    u32.EnumWindows(EnumProc(cb), 0)
    return found


def main():
    src = sys.argv[1] if len(sys.argv) > 1 else os.path.join(os.path.dirname(hancom.__file__), 'data', 'sample_template.hwpx')
    out = os.path.join(tempfile.mkdtemp(prefix='hwpx_focus_'), 'out.pdf')
    before = hancom.hwp_pids()
    fg0 = u32.GetForegroundWindow()
    pt0 = W.POINT()
    u32.GetCursorPos(ctypes.byref(pt0))
    stats = {'fg_changes': 0, 'fg_to_tool': 0, 'hwp_windows_on_user_desktop': 0, 'cursor_moves': 0, 'samples': 0}
    seen = []
    stop = threading.Event()

    def watch():
        last = fg0
        while not stop.is_set():
            fg = u32.GetForegroundWindow()
            if fg != last:
                stats['fg_changes'] += 1
                name = proc_name(fg)
                seen.append(name)
                if name.lower() in ('hwp.exe', 'powershell.exe', 'pwsh.exe'):
                    stats['fg_to_tool'] += 1
                last = fg
            new = hancom.hwp_pids() - before if stats['samples'] % 10 == 0 else set()
            if new and visible_windows_of(new):
                stats['hwp_windows_on_user_desktop'] += 1
            pt = W.POINT()
            u32.GetCursorPos(ctypes.byref(pt))
            if (pt.x, pt.y) != (pt0.x, pt0.y):
                stats['cursor_moves'] += 1
            stats['samples'] += 1
            time.sleep(0.05)
    th = threading.Thread(target=watch, daemon=True)
    th.start()
    t = time.time()
    ok, msg, info = hancom.export_pdf(src, out, timeout=180)
    stop.set()
    th.join()
    print(f'변환: {"성공" if ok else "실패"} {round(time.time() - t, 1)}초 {info.get("pages")}쪽 {msg[:120]}')
    print('관찰:', stats, '전경이 된 프로그램:', seen)
    print('(마우스를 직접 움직였다면 cursor_moves 는 사용자의 움직임입니다)')
    good = ok and stats['fg_to_tool'] == 0 and stats['hwp_windows_on_user_desktop'] == 0
    print('판정:', '방해 없음' if good else '확인 필요')
    return 0 if good else 1


if __name__ == '__main__':
    sys.exit(main())
