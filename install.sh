#!/usr/bin/env bash
# hwpx_new 설치 (macOS / Linux)
set -e
cd "$(dirname "$0")"
if ! command -v python3 >/dev/null 2>&1; then
  echo "[!] python3 이 없습니다. https://www.python.org/downloads/ 에서 설치한 뒤 다시 실행하세요."
  exit 1
fi
python3 -m pip install --upgrade pip
python3 -m pip install -e .
echo
python3 -m hwpx_new doctor
echo
echo "설치 완료! AI 프로그램에 연결하려면:  python3 -m hwpx_new mcp-config"
