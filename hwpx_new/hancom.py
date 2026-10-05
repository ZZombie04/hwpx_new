# -*- coding: utf-8 -*-
"""한글(Windows) 자동화: HWPX/HWP 열기 · PDF/HWPX 저장 · '파일 접근 허용' 승인 창 자동 처리.

- 한글은 COM(HWPFrame.HwpObject)으로 조작한다. 사용자가 이미 열어 둔 한글 창은 건드리지 않고,
  이 도구가 띄운 한글 프로세스(시작 시각이 이번 작업 이후인 것)만 정리한다.
- 한글이 '프로그램이 파일에 접근하려 한다'는 보안 승인 창을 띄우면, 이 도구가 띄운 프로세스의 창에 한해 [허용]을 대신 눌러 준다.
  (작업 폴더 안의 임시 파일만 열기 때문에 사용자 문서에는 영향이 없다.)
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
param([string]$src, [string]$dst, [string]$fmtIn, [string]$fmtOut)
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
param([string]$log, [string]$stop, [long]$since, [string]$workdir, [int]$maxSec = 900)
[Console]::OutputEncoding = [Text.Encoding]::UTF8
$ErrorActionPreference = 'SilentlyContinue'
Add-Type -AssemblyName UIAutomationClient
Add-Type -AssemblyName UIAutomationTypes
Add-Type -AssemblyName System.Windows.Forms
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
  [StructLayout(LayoutKind.Sequential)] public struct PT { public int X, Y; }
  [DllImport("user32.dll")] public static extern bool SetCursorPos(int x, int y);
  [DllImport("user32.dll")] public static extern bool GetCursorPos(out PT p);
  [DllImport("user32.dll")] public static extern void mouse_event(uint f, uint dx, uint dy, uint d, UIntPtr e);
  [DllImport("user32.dll")] public static extern bool SetForegroundWindow(IntPtr h);
  [DllImport("user32.dll")] public static extern bool ShowWindow(IntPtr h, int n);
  // 지정한 프로세스들의 '보이는' 작은 창(대화상자 크기)만 가볍게 나열한다. 한글 본창(큰 창)은 건드리지 않는다.
  public static List<string> Dialogs(HashSet<uint> pids) {
    var res = new List<string>();
    EnumWindows((h, l) => {
      uint p; GetWindowThreadProcessId(h, out p);
      if (pids.Contains(p) && IsWindowVisible(h)) {
        RECT r; GetWindowRect(h, out r);
        int w = r.R - r.L, hh = r.B - r.T;
        if (w > 0 && hh > 0 && w < 1100 && hh < 800) {
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
Log "approver start"
while (-not (Test-Path -LiteralPath $stop) -and ((Get-Date) - $t0).TotalSeconds -lt $maxSec) {
  $set = New-Object 'System.Collections.Generic.HashSet[uint32]'
  foreach ($p in @(Get-Process -Name Hwp)) { try { if ($p.StartTime.ToFileTimeUtc() -ge $since) { [void]$set.Add([uint32]$p.Id) } } catch {} }
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
        # 1차: 실제 마우스 클릭(한글 승인 창은 접근성 호출을 무시하는 경우가 있음). 창이 남아 있으면 2차: 접근성 호출, 3차: 단축키(Alt+글자), 이후 번갈아 재시도.
        $how = if ($n -eq 1) { 'mouse' } elseif ($n -eq 2) { 'invoke' } elseif ($n -eq 3) { 'keys' } elseif ($n % 2 -eq 0) { 'mouse' } else { 'invoke' }
        try {
          if ($how -eq 'invoke') {
            $pick.GetCurrentPattern([System.Windows.Automation.InvokePattern]::Pattern).Invoke()
          } elseif ($how -eq 'mouse') {
            $r = $pick.Current.BoundingRectangle
            if (-not $r.IsEmpty) {
              $old = New-Object HwpWin+PT; [void][HwpWin]::GetCursorPos([ref]$old)
              [void][HwpWin]::SetCursorPos([int]($r.X + $r.Width / 2), [int]($r.Y + $r.Height / 2))
              Start-Sleep -Milliseconds 80
              [HwpWin]::mouse_event(0x0002, 0, 0, 0, [UIntPtr]::Zero); [HwpWin]::mouse_event(0x0004, 0, 0, 0, [UIntPtr]::Zero)
              Start-Sleep -Milliseconds 80
              [void][HwpWin]::SetCursorPos($old.X, $old.Y)
            }
          } else {
            [void][HwpWin]::ShowWindow([IntPtr][int64]$parts[0], 5); [void][HwpWin]::SetForegroundWindow([IntPtr][int64]$parts[0])
            Start-Sleep -Milliseconds 200
            $acc = [regex]::Match($pick.Current.Name, 'ALT\+(\w)').Groups[1].Value
            if ($acc) { [System.Windows.Forms.SendKeys]::SendWait('%' + $acc.ToLower()) }
          }
          Log ("CLICK[{0}] [{1}]" -f $how, $pick.Current.Name)
        } catch { Log ("CLICK-FAIL[{0}] [{1}] {2}" -f $how, $pick.Current.Name, $_.Exception.Message) }
      }
    }
  }
  if ($wasOpen -and -not $sawNow) { Log 'CLEARED' }
  $wasOpen = $sawNow
  Start-Sleep -Milliseconds 300
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


def kill_new_hwp(before: set):
    """이 도구가 띄운 한글 프로세스만 종료(이미 떠 있던 것은 그대로 둔다)."""
    for pid in hwp_pids() - before:
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


def work_dir() -> str:
    """변환용 임시 파일 폴더. 한글의 승인은 폴더 단위로 기억되므로 항상 같은 폴더를 쓴다."""
    d = os.environ.get('HWPX_NEW_WORK') or os.path.join(os.path.expanduser('~'), '.hwpx_new', 'work')
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
        self.proc = subprocess.Popen(
            [_ps(), '-NoProfile', '-ExecutionPolicy', 'Bypass', '-File', self.script, self.log, self.stop,
             str(_filetime_now()), self.wd],
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
        if old.startswith(('convert_', 'approve_', 'approver_', 'run_')):
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
    try:
        appr.start()
        with open(fout, 'wb') as fo, open(ferr, 'wb') as fe:
            proc = subprocess.Popen([ps, '-NoProfile', '-ExecutionPolicy', 'Bypass', '-File', script, w_in, w_out,
                                     fmt_in, fmt_out], stdout=fo, stderr=fe,
                                    creationflags=getattr(subprocess, 'CREATE_NO_WINDOW', 0))
            t0 = time.time()
            dialog_wait = float(os.environ.get('HWPX_NEW_DIALOG_WAIT', '50'))
            last_len, last_change = 0, t0
            while proc.poll() is None:
                time.sleep(0.5)
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
        kill_new_hwp(before)
        for f in (script, w_in, w_out, fout, ferr):
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
        hint = ('한글이 "파일 접근 허용" 창을 띄웠는데 자동으로 닫히지 않았습니다. 화면보호기·잠금 상태이거나 다른 프로그램이 입력을 막고 있을 수 있습니다. '
                '화면을 켜고 다시 실행하거나, 한글 창의 [접근 허용]을 눌러 주세요.')
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
