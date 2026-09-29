@echo off
chcp 65001 >nul
echo ==========================================
echo   hwpx_new 설치 (Windows)
echo ==========================================
where python >nul 2>nul
if errorlevel 1 (
  echo [!] Python 이 없습니다. https://www.python.org/downloads/ 에서 설치할 때
  echo     "Add python.exe to PATH" 를 꼭 체크한 뒤 이 파일을 다시 실행하세요.
  pause
  exit /b 1
)
python -m pip install --upgrade pip
python -m pip install -e "%~dp0"
if errorlevel 1 (
  echo [!] 설치에 실패했습니다. 위 오류 메시지를 AI 에게 보여 주세요.
  pause
  exit /b 1
)
echo.
python -m hwpx_new doctor
echo.
echo ------------------------------------------
echo 설치 완료! 이제 AI 프로그램에 연결하세요:
echo    python -m hwpx_new mcp-config
echo 위 명령이 출력하는 설정을 AI 프로그램(Claude, Codex, Gemini, Cursor 등)에 붙여 넣으면 됩니다.
echo ------------------------------------------
pause
