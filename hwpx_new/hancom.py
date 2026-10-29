# -*- coding: utf-8 -*-
"""한글(Windows) 자동화: HWPX/HWP 열기 · PDF/HWPX 저장 · '파일 접근 허용' 승인 창 자동 처리.

- 한글은 COM(HWPFrame.HwpObject)으로 조작한다. 사용자가 열어 둔(또는 작업 중에 새로 연) 한글 창은 건드리지 않고,
  이 도구가 COM 으로 띄운 한글 프로세스(명령줄에 -Embedding)만 정리한다.
- 승인 창이 아예 뜨지 않게 한다: 한글(HwpAutomation.dll)은 Windows 임시 폴더(GetTempPath) 아래 파일은 묻지 않고 허용하므로
  작업 폴더를 그 안에 둔다(2026-10-29 한글 2024 13.0.0.1408 역분석·실측). 보안 설정·레지스트리는 바꾸지 않는다.
- 그래도 창이 뜨면(작업 폴더를 임시 폴더 밖으로 바꾼 경우 등) 이 도구가 띄운 프로세스의 창에 한해 [접근 허용]을
  UI Automation 호출로 누른다. 마우스 커서를 옮기거나 창을 앞으로 가져오지 않는다.
"""
from __future__ import annotations

import json
import os
import shutil
import subprocess
import sys
import tempfile
import time
import uuid

# ------------------------------------------------------------------ PowerShell 스크립트
# 한글 열기 → (선택) 쪽 수·글자 수 확인 → 저장.  결과는 마지막 줄 'RESULT {json}' 으로 돌려준다.
RUN_PS = r"""
param([string]$src, [string]$dst, [string]$fmtIn, [string]$fmtOut, [string]$hwndFile)
[Console]::OutputEncoding = [Text.Encoding]::UTF8
$ErrorActionPreference = 'Stop'
$sw = [Diagnostics.Stopwatch]::StartNew(); $tl = New-Object System.Collections.ArrayList
function Mark($n) { [void]$tl.Add(('{0}@{1:N1}' -f $n, $sw.Elapsed.TotalSeconds)) }
$res = @{ ok = $false; pages = 0; chars = 0; opened = $false; error = ''; openret = '' }
$h = $null
try {
  Mark 'new'
  $h = New-Object -ComObject HWPFrame.HwpObject
  Mark 'created'
  # 창 핸들을 남겨 두면 정리할 때 이 한글 프로세스만 정확히 끝낼 수 있다(작업 중 사용자가 연 한글은 그대로).
  if ($hwndFile) { try { [IO.File]::WriteAllText($hwndFile, [string]$h.XHwpWindows.Item(0).WindowHandle) } catch {} }
  try { $h.RegisterModule('FilePathCheckDLL', 'FilePathCheckerModule') | Out-Null } catch {}
  try { $h.XHwpWindows.Item(0).Visible = $false } catch {}
  Mark 'open-start'
  $r = $h.Open($src, $fmtIn, '')
  Mark 'open-end'
  $res.openret = [string]$r
  # Open 의 반환값은 버전에 따라 믿을 수 없어, 실제로 문서가 열렸는지 쪽 수·글자 수로 판단한다.
  $res.pages = [int]$h.PageCount
  try { $res.chars = ([string]$h.GetTextFile('TEXT', '')).Length } catch {}
  $res.opened = ($res.pages -ge 1 -and $res.chars -gt 0) -or ($r -eq $true)
  if ($dst) {
    Mark 'save-start'
    $h.SaveAs($dst, $fmtOut, '') | Out-Null
    Mark 'save-end'
    $res.ok = Test-Path -LiteralPath $dst
  } else {
    $res.ok = $res.opened
  }
} catch {
  $res.error = [string]$_.Exception.Message
} finally {
  if ($h -ne $null) {
    Mark 'clear'
    try { $h.Clear(1) | Out-Null } catch {}
    Mark 'quit'
    try { $h.Quit() | Out-Null } catch {}
    Mark 'release'
    try { [void][Runtime.InteropServices.Marshal]::ReleaseComObject($h) } catch {}
    Mark 'end'
  }
}
$res.timeline = ($tl -join ' ')
'RESULT ' + ($res | ConvertTo-Json -Compress)
"""

# 한글이 띄우는 승인 창을 대신 누르는 도우미(이 도구가 띄운 한글 프로세스만 대상).
APPROVE_PS = r"""
param([string]$log, [string]$stop, [long]$since, [string]$workdir, [int]$maxSec = 900, [long]$fgInit = 0)
[Console]::OutputEncoding = [Text.Encoding]::UTF8
$ErrorActionPreference = 'SilentlyContinue'
Add-Type -AssemblyName UIAutomationClient
Add-Type -AssemblyName UIAutomationTypes
Add-Type @"
using System; using System.Collections.Generic; using System.Runtime.InteropServices; using System.Text;
public class HwpWin {
  public delegate bool EnumProc(IntPtr h, IntPtr l);
  [DllImport("user32.dll")] static extern bool EnumWindows(EnumProc p, IntPtr l);
  [DllImport("user32.dll")] static extern uint GetWindowThreadProcessId(IntPtr h, out uint pid);
  [DllImport("user32.dll", CharSet=CharSet.Unicode)] static extern int GetWindowText(IntPtr h, StringBuilder s, int n);
  [DllImport("user32.dll")] static extern bool IsWindowVisible(IntPtr h);
  [DllImport("user32.dll")] static extern bool GetWindowRect(IntPtr h, out RECT r);
  [StructLayout(LayoutKind.Sequential)] public struct RECT { public int L, T, R, B; }
  [DllImport("user32.dll")] public static extern IntPtr GetForegroundWindow();
  [DllImport("user32.dll")] public static extern bool SetForegroundWindow(IntPtr h);
  [DllImport("user32.dll")] public static extern bool IsWindow(IntPtr h);
  [DllImport("user32.dll")] static extern bool AttachThreadInput(uint a, uint b, bool f);
  [DllImport("kernel32.dll")] static extern uint GetCurrentThreadId();
  public static uint PidOf(IntPtr h) { uint p; GetWindowThreadProcessId(h, out p); return p; }
  public static bool Visible(IntPtr h) { return IsWindowVisible(h); }
  // 포커스를 쥔 한글 스레드의 입력 큐에 잠깐 붙어야 Windows 가 되돌리기를 허락한다(그냥 부르면 거절됨, 실측).
  [DllImport("user32.dll")] static extern void SwitchToThisWindow(IntPtr h, bool alt);
  [DllImport("user32.dll")] static extern bool IsIconic(IntPtr h);
  [DllImport("user32.dll")] static extern IntPtr GetWindow(IntPtr h, uint cmd);
  [DllImport("user32.dll")] static extern int GetWindowLong(IntPtr h, int i);
  // 되돌릴 창을 모를 때: 화면 맨 위에 있는 사용자 창(보이고, 최소화 아니고, 제목 있고, 도구 창 아님, 이 도구가 띄운 한글 아님)
  public static IntPtr NextUserWindow(HashSet<uint> skip) {
    IntPtr found = IntPtr.Zero;
    EnumWindows((h, l) => {
      uint p; GetWindowThreadProcessId(h, out p);
      if (skip.Contains(p) || !IsWindowVisible(h) || IsIconic(h) || GetWindow(h, 4) != IntPtr.Zero) return true;
      if ((GetWindowLong(h, -20) & 0x80) != 0) return true;   // WS_EX_TOOLWINDOW
      var t = new StringBuilder(8); if (GetWindowText(h, t, 8) == 0) return true;
      found = h; return false;
    }, IntPtr.Zero);
    return found;
  }
  public static string How = "";
  public static bool GiveBack(IntPtr target) {
    How = "set";
    if (SetForegroundWindow(target)) return true;
    uint p; uint ft = GetWindowThreadProcessId(GetForegroundWindow(), out p);
    uint me = GetCurrentThreadId();
    if (ft != 0 && ft != me) {
      bool att = AttachThreadInput(me, ft, true);
      How = "attach=" + att;
      bool ok = att && SetForegroundWindow(target);
      if (att) AttachThreadInput(me, ft, false);
      if (ok) return true;
    }
    How += "+switch";
    SwitchToThisWindow(target, true);
    return GetForegroundWindow() == target;
  }
  // 지정한 프로세스들의 '보이는' 작은 창(대화상자 크기)만 가볍게 나열한다. 한글 본창(큰 창)은 건드리지 않는다.
  public static List<string> Dialogs(HashSet<uint> pids) {
    var res = new List<string>();
    EnumWindows((h, l) => {
      uint p; GetWindowThreadProcessId(h, out p);
      if (pids.Contains(p) && IsWindowVisible(h)) {
        RECT r; GetWindowRect(h, out r);
        int w = r.R - r.L, hh = r.B - r.T;
        // 한글이 시작할 때 잠깐 띄우는 작은 창(157x25 따위)은 빼야 바쁜 한글을 UI Automation 으로 기다리며 멈추지 않는다.
        if (w >= 250 && hh >= 90 && w < 1100 && hh < 800) {
          var t = new StringBuilder(256); GetWindowText(h, t, 256);
          res.Add(h.ToInt64() + "|" + p + "|" + w + "x" + hh + "|" + t.ToString());
        }
      }
      return true;
    }, IntPtr.Zero);
    return res;
  }
}
"@
$AE = [System.Windows.Automation.AutomationElement]
$TS = [System.Windows.Automation.TreeScope]
$CT = [System.Windows.Automation.ControlType]
function Log($m) { Add-Content -LiteralPath $log -Value ("{0:HH:mm:ss.fff} {1}" -f (Get-Date), $m) -Encoding UTF8 }
$t0 = Get-Date
$handled = @{}
$tries = @{}
$wasOpen = $false
$goodFg = if ($fgInit) { [IntPtr]$fgInit } else { [HwpWin]::GetForegroundWindow() }   # 도우미가 뜨기 전에 한글이 포커스를 가져가도 되돌릴 곳을 알도록
$firstSeen = @{}
$restored = 0
Log "approver start"
while (-not (Test-Path -LiteralPath $stop) -and ((Get-Date) - $t0).TotalSeconds -lt $maxSec) {
  $set = New-Object 'System.Collections.Generic.HashSet[uint32]'
  foreach ($p in @(Get-Process -Name Hwp)) { try { if ($p.StartTime.ToFileTimeUtc() -ge $since) { [void]$set.Add([uint32]$p.Id); if (-not $firstSeen.ContainsKey($p.Id)) { $firstSeen[$p.Id] = Get-Date } } } catch {} }
  # 포커스 돌려주기: COM 으로 뜬 한글은 창이 숨겨져 있어도 키보드 포커스를 가져간다(사용자가 200초 넘게 입력이 없으면 Windows 가 허용, 2026-10-29 실측).
  # 앞 창이 이 도구가 띄운 한글의 '보이지 않는' 창이거나, 한글이 막 뜬 직후(4초) 앞 창이 비면 사용자가 쓰던 창으로 되돌린다.
  # 보이는 한글 창(사용자가 연 것·승인 창)은 건드리지 않는다.
  $fg = [HwpWin]::GetForegroundWindow()
  $justStarted = $false
  foreach ($k in $firstSeen.Keys) { if (((Get-Date) - $firstSeen[$k]).TotalSeconds -lt 4) { $justStarted = $true } }
  $hijack = ($fg -ne [IntPtr]::Zero -and $set.Contains([HwpWin]::PidOf($fg)) -and -not [HwpWin]::Visible($fg)) -or ($fg -eq [IntPtr]::Zero -and $justStarted)
  # 이 도구가 띄운 한글 창은 시작할 때 잠깐 보였다가 숨겨지므로 되돌릴 곳으로 기억하지 않는다.
  if (-not $hijack) { if ($fg -ne [IntPtr]::Zero -and -not $set.Contains([HwpWin]::PidOf($fg))) { $goodFg = $fg } }
  else {
    if (-not ($goodFg -ne [IntPtr]::Zero -and [HwpWin]::IsWindow($goodFg) -and [HwpWin]::Visible($goodFg))) { $goodFg = [HwpWin]::NextUserWindow($set) }
    if ($goodFg -ne [IntPtr]::Zero -and [HwpWin]::GiveBack($goodFg)) { $restored++; if ($restored -le 3) { Log 'FOCUS-RESTORE' } }
  }
  $sawNow = $false
  if ($set.Count -gt 0) {
    foreach ($line in [HwpWin]::Dialogs($set)) {
      $parts = $line.Split('|', 4)
      $key = $parts[0]
      if ($handled.ContainsKey($key) -and (((Get-Date) - $handled[$key]).TotalSeconds -lt 1.2)) { $sawNow = $true; continue }
      $w = $null
      try { $w = $AE::FromHandle([IntPtr][int64]$parts[0]) } catch { continue }
      if ($w -eq $null) { continue }
      $msgEl = $w.FindFirst($TS::Descendants, (New-Object System.Windows.Automation.PropertyCondition($AE::AutomationIdProperty, 'PART_Message')))
      if ($msgEl -eq $null) { continue }
      $sawNow = $true
      $msg = $msgEl.Current.Name
      $btns = @($w.FindAll($TS::Descendants, (New-Object System.Windows.Automation.PropertyCondition($AE::ControlTypeProperty, $CT::Button))))
      $names = @(); foreach ($b in $btns) { if ($b.Current.Name) { $names += $b.Current.Name } }
      $short = ($msg -replace '\s+', ' ')
      if ($short.Length -gt 300) { $short = $short.Substring(0, 300) }
      $first = -not $handled.ContainsKey($key)
      $handled[$key] = Get-Date
      if ($first) { Log ("DIALOG title=[{0}] msg=[{1}] buttons=[{2}]" -f $parts[3], $short, ($names -join ' | ')) }
      $isAccess = ($msg -match '접근')
      $ours = $false
      if ($workdir) { $ours = ($msg.ToLower().Contains($workdir.ToLower())) -or ($msg -match 'convert_[0-9a-f]{8}\.') }
      $pick = $null
      if ($isAccess -and $ours) {
        # 이 도구의 작업 폴더 안 파일에 대한 요청만 [접근 허용](이번 한 번)을 누른다. [모두 허용]·[허용 안 함]·[모두 안 함] 은 누르지 않는다.
        foreach ($b in $btns) { if ($b.Current.IsEnabled -and $b.Current.Name -match '^\s*접근\s*허용') { $pick = $b; break } }
      } elseif (-not $isAccess -and $names.Count -gt 0) {
        # 오류·안내 창: 확인만 눌러 흐름이 멈추지 않게 하고, 내용은 기록(오류 원인 안내에 쓴다)
        foreach ($b in $btns) { if ($b.Current.IsEnabled -and $b.Current.Name -match '^\s*(확인|OK|닫기|Close)\s*(:|$)') { $pick = $b; break } }
      } elseif ($isAccess -and -not $ours) {
        if ($first) { Log 'FOREIGN-ACCESS (작업 폴더 밖 파일: 누르지 않음)' }
      }
      if ($pick) {
        $n = 1 + [int]$tries[$key]; $tries[$key] = $n
        if ($n -gt 6) { if ($n -eq 7) { Log 'GIVEUP (승인 창이 닫히지 않음)' }; continue }
        # UI Automation 호출로만 누른다(2026-10-29 실측: 한글 2024 승인 창은 Invoke 로 바로 닫힘).
        # 사용자가 PC 를 쓰는 중이므로 마우스 커서를 옮기거나 창을 앞으로 가져와 키를 보내지 않는다.
        try {
          # 한글 승인 창은 비활성 상태에서 Invoke 를 무시한다(실측) → 그 창만 잠깐 앞으로(마우스는 그대로), 누른 뒤 사용자 창으로 돌려준다.
          $dlg = [IntPtr][int64]$parts[0]
          if ([HwpWin]::GetForegroundWindow() -ne $dlg) { [void][HwpWin]::GiveBack($dlg); Start-Sleep -Milliseconds 120 }
          $pick.GetCurrentPattern([System.Windows.Automation.InvokePattern]::Pattern).Invoke()
          Start-Sleep -Milliseconds 150
          if ($goodFg -ne [IntPtr]::Zero -and [HwpWin]::IsWindow($goodFg)) { [void][HwpWin]::GiveBack($goodFg) }
          Log ("CLICK[invoke] [{0}]" -f $pick.Current.Name)
        } catch { Log ("CLICK-FAIL[invoke] [{0}] {1}" -f $pick.Current.Name, $_.Exception.Message) }
      }
    }
  }
  if ($wasOpen -and -not $sawNow) { Log 'CLEARED' }
  $wasOpen = $sawNow
  Start-Sleep -Milliseconds 150
}
Log 'approver end'
"""


def _ps():
    return shutil.which('powershell') or shutil.which('pwsh')


def hwp_pids() -> set:
    try:
        r = subprocess.run(['tasklist', '/FO', 'CSV', '/NH', '/FI', 'IMAGENAME eq Hwp.exe'],
                           capture_output=True, text=True, errors='replace', timeout=20)
        return {int(l.split('","')[1]) for l in r.stdout.splitlines() if l.startswith('"Hwp.exe"')}
    except Exception:  # noqa
        return set()


def _automation_pids(pids: set) -> set:
    """pids 가운데 COM 으로 뜬 한글만(명령줄 'Hwp.exe -Automation -Embedding'). 사용자가 직접 연 한글에는 이 표시가 없다."""
    if not pids or not _ps():
        return set()
    try:
        r = subprocess.run([_ps(), '-NoProfile', '-Command',
                            "Get-CimInstance Win32_Process -Filter \"Name='Hwp.exe'\" | "
                            "ForEach-Object { [string]$_.ProcessId + '|' + $_.CommandLine }"],
                           capture_output=True, text=True, errors='replace', timeout=30,
                           creationflags=getattr(subprocess, 'CREATE_NO_WINDOW', 0))
        out = set()
        for line in r.stdout.splitlines():
            pid, _, cmd = line.partition('|')
            if pid.strip().isdigit() and int(pid) in pids and '-embedding' in cmd.lower():
                out.add(int(pid))
        return out
    except Exception:  # noqa
        return set()


def pid_of_hwnd(hwnd) -> int:
    """한글 COM 의 창 핸들(XHwpWindows.Item(0).WindowHandle) → 그 한글 프로세스 번호(모르면 0)."""
    try:
        import ctypes
        pid = ctypes.c_ulong(0)
        ctypes.windll.user32.GetWindowThreadProcessId(ctypes.c_void_p(int(hwnd)), ctypes.byref(pid))
        return int(pid.value)
    except Exception:  # noqa
        return 0


def kill_new_hwp(before: set, only: set = None):
    """이 도구가 띄운 한글 프로세스만 종료.

    only 를 주면 그 프로세스만(정확한 방법). 없으면 작업 시작 뒤 새로 뜬 한글 가운데 COM 으로 뜬 것만 끝낸다 —
    작업 중에 사용자가 연 한글(명령줄에 -Embedding 없음)과 이미 떠 있던 한글은 그대로 둔다."""
    new = hwp_pids() - set(before)
    targets = (new & set(only)) if only else _automation_pids(new)
    for pid in targets:
        try:
            subprocess.run(['taskkill', '/F', '/PID', str(pid)], capture_output=True, timeout=20)
        except Exception:  # noqa
            pass


def installed() -> bool:
    if sys.platform != 'win32':
        return False
    for p in (r'C:\Program Files (x86)\Hnc', r'C:\Program Files\Hnc', r'C:\Program Files (x86)\HNC',
              r'C:\Program Files\HNC'):
        if os.path.exists(p):
            return True
    return False


def temp_root() -> str:
    """한글이 승인 창 없이 여는 폴더 = 한글 프로세스의 GetTempPath (보통 %LOCALAPPDATA%\\Temp)."""
    if sys.platform == 'win32':
        try:
            import ctypes
            buf = ctypes.create_unicode_buffer(1024)
            n = ctypes.windll.kernel32.GetTempPathW(1024, buf)
            if 0 < n < 1024:
                long_ = ctypes.create_unicode_buffer(1024)      # 8.3 짧은 이름이면 한글이 비교하는 긴 이름으로
                if ctypes.windll.kernel32.GetLongPathNameW(buf.value, long_, 1024):
                    return long_.value
                return buf.value
        except Exception:  # noqa
            pass
    return tempfile.gettempdir()


def auto_allowed(path: str) -> bool:
    """한글이 이 경로를 승인 창 없이 여는가(임시 폴더 아래인가). HwpAutomation.dll 은 대소문자 무시 접두어 비교를 한다."""
    root = os.path.normcase(os.path.abspath(temp_root())).rstrip('\\/') + os.sep
    return os.path.normcase(os.path.abspath(path)).startswith(root)


def work_dir() -> str:
    """변환용 임시 파일 폴더. 임시 폴더 안에 두어 한글이 '파일 접근 허용' 창을 띄우지 않게 한다(HWPX_NEW_WORK 로 바꿀 수 있음)."""
    d = os.environ.get('HWPX_NEW_WORK') or os.path.join(temp_root(), 'hwpx_new_work')
    os.makedirs(d, exist_ok=True)
    return d


def _filetime_now() -> int:
    # Windows FILETIME(UTC, 100ns) — 지금보다 조금 앞(2초)을 기준으로 해 방금 뜬 프로세스를 놓치지 않는다.
    return int((time.time() + 11644473600 - 2) * 10_000_000)


class _Approver:
    def __init__(self, wd: str):
        self.wd = wd
        self.proc = None
        self.log = os.path.join(wd, f'approver_{uuid.uuid4().hex[:6]}.log')
        self.stop = os.path.join(wd, f'approver_{uuid.uuid4().hex[:6]}.stop')
        self.script = None

    def start(self):
        if os.environ.get('HWPX_NEW_NO_APPROVER') == '1' or not _ps():
            return
        self.script = os.path.join(self.wd, f'approve_{uuid.uuid4().hex[:6]}.ps1')
        with open(self.script, 'w', encoding='utf-8-sig') as f:
            f.write(APPROVE_PS)
        try:
            import ctypes
            fg = int(ctypes.windll.user32.GetForegroundWindow() or 0)
        except Exception:  # noqa
            fg = 0
        self.proc = subprocess.Popen(
            [_ps(), '-NoProfile', '-ExecutionPolicy', 'Bypass', '-File', self.script, self.log, self.stop,
             str(_filetime_now()), self.wd, '900', str(fg)],
            stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL,
            creationflags=getattr(subprocess, 'CREATE_NO_WINDOW', 0))

    def peek(self) -> str:
        try:
            if os.path.exists(self.log):
                with open(self.log, encoding='utf-8-sig', errors='replace') as f:
                    return f.read()
        except Exception:  # noqa
            pass
        return ''

    def finish(self) -> str:
        """승인 도우미를 끝내고, 그동안 처리한 내용(창 문구·누른 버튼)을 돌려준다."""
        text = ''
        try:
            if self.proc is not None:
                open(self.stop, 'w').close()
                try:
                    self.proc.wait(timeout=6)
                except subprocess.TimeoutExpired:
                    self.proc.terminate()
            if os.path.exists(self.log):
                with open(self.log, encoding='utf-8-sig', errors='replace') as f:
                    text = f.read()
        except Exception:  # noqa
            pass
        finally:
            for f in (self.stop, self.script, self.log):
                try:
                    if f:
                        os.unlink(f)
                except OSError:
                    pass
        return text


def summarize_dialogs(log: str) -> str:
    lines = [l for l in (log or '').splitlines() if ' DIALOG ' in l or ' CLICK' in l or 'NO-SAFE' in l]
    return '\n'.join(lines[-8:])


def run(src: str, dst: str | None, fmt_in: str, fmt_out: str = '', timeout: int = None):
    """한글로 src 를 열어 (dst 가 있으면) fmt_out 형식으로 저장. 반환: dict(ok, opened, pages, chars, error, dialogs)."""
    timeout = timeout or int(os.environ.get('HWPX_NEW_TIMEOUT', '240'))
    out = {'ok': False, 'opened': False, 'pages': 0, 'chars': 0, 'error': '', 'dialogs': ''}
    if sys.platform != 'win32':
        out['error'] = '한글은 Windows 에서만 자동으로 쓸 수 있습니다.'
        return out
    ps = _ps()
    if not ps:
        out['error'] = 'PowerShell 을 찾지 못했습니다.'
        return out
    wd = work_dir()
    tag = uuid.uuid4().hex[:8]
    for old in os.listdir(wd):                      # 이전 실행이 남긴(10분 넘은) 임시 파일 정리 — 동시에 도는 다른 작업의 파일은 건드리지 않는다
        if old.startswith(('convert_', 'approve_', 'approver_', 'run_', 'hwnd_')):
            try:
                pth = os.path.join(wd, old)
                if time.time() - os.path.getmtime(pth) > 600:
                    os.remove(pth)
            except OSError:
                pass
    ext_in = os.path.splitext(src)[1] or '.hwpx'
    w_in = os.path.join(wd, f'convert_{tag}{ext_in}')
    w_out = os.path.join(wd, f'convert_{tag}.{(fmt_out or "out").lower()}') if dst else ''
    shutil.copyfile(src, w_in)
    script = os.path.join(wd, f'run_{tag}.ps1')
    with open(script, 'w', encoding='utf-8-sig') as f:
        f.write(RUN_PS)
    before = hwp_pids()
    appr = _Approver(wd)
    proc = None
    fout = os.path.join(wd, f'run_{tag}.out')
    ferr = os.path.join(wd, f'run_{tag}.err')
    fhwnd = os.path.join(wd, f'hwnd_{tag}.txt')
    mine = set()                                     # 이번 작업이 COM 으로 띄운 한글 프로세스(창 핸들로 찾음)

    def _find_mine():
        if not mine and os.path.exists(fhwnd):
            try:
                pid = pid_of_hwnd(open(fhwnd).read().strip() or 0)
                if pid:
                    mine.add(pid)
            except (OSError, ValueError):
                pass
    try:
        appr.start()
        with open(fout, 'wb') as fo, open(ferr, 'wb') as fe:
            proc = subprocess.Popen([ps, '-NoProfile', '-ExecutionPolicy', 'Bypass', '-File', script, w_in, w_out,
                                     fmt_in, fmt_out, fhwnd], stdout=fo, stderr=fe,
                                    creationflags=getattr(subprocess, 'CREATE_NO_WINDOW', 0))
            t0 = time.time()
            dialog_wait = float(os.environ.get('HWPX_NEW_DIALOG_WAIT', '50'))
            last_len, last_change = 0, t0
            while proc.poll() is None:
                time.sleep(0.5)
                _find_mine()
                now = time.time()
                log = appr.peek()
                if len(log) != last_len:
                    last_len, last_change = len(log), now
                lines = [l for l in log.splitlines() if (' DIALOG ' in l or ' CLICK' in l or 'CLEARED' in l or 'GIVEUP' in l)]
                dialog_open = bool(lines) and 'CLEARED' not in lines[-1]
                if dialog_open and now - last_change > dialog_wait:
                    out['error'] = 'dialog_stuck'
                    break
                if now - t0 > timeout:
                    out['error'] = 'timeout'
                    break
        if out['error']:
            proc.kill()
        else:
            def _read(p):
                try:
                    return open(p, encoding='utf-8-sig', errors='replace').read()
                except OSError:
                    return ''
            stdout, stderr = _read(fout), _read(ferr)
            line = next((l for l in reversed((stdout or '').splitlines()) if l.startswith('RESULT ')), None)
            if line:
                try:
                    out.update(json.loads(line[7:]))
                except ValueError:
                    out['error'] = 'RESULT 해석 실패: ' + line[:120]
            else:
                out['error'] = ((stderr or stdout or '').strip() or '한글 응답 없음')[:300]
            if dst and out.get('ok') and os.path.exists(w_out) and os.path.getsize(w_out) > 500:
                shutil.copyfile(w_out, dst)
            elif dst:
                out['ok'] = False
    finally:
        out['dialogs'] = summarize_dialogs(appr.finish())
        _find_mine()
        kill_new_hwp(before, only=mine or None)
        for f in (script, w_in, w_out, fout, ferr, fhwnd):
            try:
                if f:
                    os.unlink(f)
            except OSError:
                pass
    return out


_TRANSIENT = ('80080005', 'CO_E_SERVER_EXEC_FAILURE', '800706BA', '800706BE', '80010001', 'RPC_E_CALL_REJECTED')


def _run_retry(src, dst, fmt_in, fmt_out, timeout, tries=4):
    """한글 COM 서버가 이전 변환을 막 끝낸 직후에는 '서버 실행 실패'가 잠깐 날 수 있다(실측). 잠시 쉬었다 다시 시도한다."""
    import time
    r = run(src, dst, fmt_in, fmt_out, timeout)
    for i in range(tries - 1):
        if r.get('ok') or not any(k in (r.get('error') or '') for k in _TRANSIENT):
            break
        time.sleep(6 + 6 * i)
        r = run(src, dst, fmt_in, fmt_out, timeout)
    return r


def export_pdf(hwpx: str, pdf: str, timeout: int = None):
    """HWPX → PDF. 반환: (성공, 메시지, 정보 dict)."""
    r = _run_retry(hwpx, pdf, 'HWPX', 'PDF', timeout)
    if r['ok']:
        if not r.get('opened'):
            return False, '한글이 문서를 열지 못했습니다(파일이 손상됐거나 한글이 읽지 못하는 구조).', r
        return True, '', r
    if r['error'] == 'dialog_stuck':
        hint = ('한글이 "파일 접근 허용" 창을 띄웠는데 자동으로 닫히지 않았습니다(이 도구는 마우스를 쓰지 않습니다). '
                + ('' if auto_allowed(work_dir()) else
                   f'작업 폴더({work_dir()})가 임시 폴더 밖이라 창이 뜬 것입니다. HWPX_NEW_WORK 환경변수를 지우면 창 없이 동작합니다. ')
                + '한글 창의 [접근 허용]을 직접 눌러도 됩니다.')
        if r.get('dialogs'):
            hint += chr(10) + '한글이 띄운 창: ' + r['dialogs'].replace(chr(10), ' / ')
        return False, hint, r
    if r['error'] == 'timeout':
        hint = ('한글이 제한 시간 안에 응답하지 않았습니다. 사진이 많은 큰 문서는 PDF 저장에 몇 분 걸릴 수 있습니다'
                '(환경변수 HWPX_NEW_TIMEOUT 로 초 단위 조절).')
        if r.get('dialogs'):
            hint += '\n한글이 띄운 창: ' + r['dialogs'].replace('\n', ' / ')
        return False, hint, r
    return False, r['error'] or '한글 변환 실패', r


def hwp_to_hwpx(hwp: str, out: str, timeout: int = 120):
    """옛 .hwp → .hwpx. 반환: (성공, 메시지)"""
    if os.path.exists(out):
        try:
            os.remove(out)
        except OSError:
            pass
    r = run(os.path.abspath(hwp), os.path.abspath(out), 'HWP', 'HWPX', timeout)
    if r['ok'] and os.path.exists(out) and os.path.getsize(out) > 1000:
        return True, out
    return False, (r.get('error') or '변환 실패')[:300]
