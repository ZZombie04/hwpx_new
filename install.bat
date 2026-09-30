@echo off
setlocal EnableDelayedExpansion
chcp 65001 >nul
title hwpx_new 설치
echo ==========================================
echo   hwpx_new 설치 (Windows)
echo   - 이 창을 닫지 말고 끝날 때까지 기다려 주세요.
echo ==========================================
echo.

rem step 1 find python
set "PY="
for %%C in ("py -3" "python" "python3") do (
  if not defined PY (
    %%~C -c "import sys; raise SystemExit(0 if sys.version_info >= (3,9) else 1)" >nul 2>nul && set "PY=%%~C"
  )
)
if not defined PY (
  echo [!] 파이썬 3.9 이상이 없습니다.
  echo     1^) 아래 명령을 실행하거나, 2^) https://www.python.org/downloads/ 에서 설치하세요.
  echo        설치할 때 "Add python.exe to PATH" 를 꼭 체크하세요.
  echo.
  echo        winget install -e --id Python.Python.3.12
  echo.
  echo     설치가 끝나면 이 파일을 다시 실행하세요.
  pause
  exit /b 1
)
echo [1/4] 파이썬: %PY%

rem step 2 make venv
set "HOME_DIR=%LOCALAPPDATA%\hwpx_new"
set "VENV=%HOME_DIR%\venv"
if not exist "%HOME_DIR%" mkdir "%HOME_DIR%"
if not exist "%VENV%\Scripts\python.exe" (
  %PY% -m venv "%VENV%"
  if errorlevel 1 (
    echo [!] 가상환경을 만들지 못했습니다. 위 오류 메시지를 AI 에게 보여 주세요.
    pause
    exit /b 1
  )
)
echo [2/4] 설치 위치: %VENV%

rem step 3 install
"%VENV%\Scripts\python.exe" -m pip install --quiet --upgrade pip
"%VENV%\Scripts\python.exe" -m pip install --upgrade "%~dp0."
if errorlevel 1 (
  echo.
  echo [!] 설치에 실패했습니다. 인터넷 연결을 확인하고 다시 실행하세요.
  echo     계속 안 되면 위 오류 메시지를 AI 에게 보여 주세요.
  pause
  exit /b 1
)
echo [3/4] 설치 완료

rem step 4 launcher and setup
> "%HOME_DIR%\hwpx-new.cmd" echo @"%VENV%\Scripts\python.exe" -m hwpx_new %%*
echo.
"%VENV%\Scripts\python.exe" -m hwpx_new doctor
echo.
echo [4/4] AI 프로그램(Claude, Codex, Gemini, Cursor 등) 연결
"%VENV%\Scripts\python.exe" -m hwpx_new setup --skill
echo.
echo ------------------------------------------
echo 설치가 끝났습니다.
echo  - 명령: "%HOME_DIR%\hwpx-new.cmd" doctor
echo  - AI 프로그램을 완전히 종료했다가 다시 실행하면 hwpx_new 도구가 나타납니다.
echo  - 연결되지 않은 AI 는:  "%HOME_DIR%\hwpx-new.cmd" mcp-config  (나오는 설정을 붙여 넣기)
echo ------------------------------------------
pause
