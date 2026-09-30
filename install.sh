#!/usr/bin/env bash
# hwpx_new 설치 (macOS / Linux): 전용 가상환경(~/.hwpx_new/venv)에 설치하고 AI 프로그램에 연결
set -e
cd "$(dirname "$0")"
PY=""
for c in python3 python; do
  if command -v "$c" >/dev/null 2>&1 && "$c" -c 'import sys; raise SystemExit(0 if sys.version_info >= (3,9) else 1)'; then PY="$c"; break; fi
done
if [ -z "$PY" ]; then
  echo "[!] 파이썬 3.9 이상이 없습니다. https://www.python.org/downloads/ 에서 설치한 뒤 다시 실행하세요."
  exit 1
fi
HOME_DIR="$HOME/.hwpx_new"
VENV="$HOME_DIR/venv"
mkdir -p "$HOME_DIR"
[ -x "$VENV/bin/python" ] || "$PY" -m venv "$VENV"
"$VENV/bin/python" -m pip install --quiet --upgrade pip
"$VENV/bin/python" -m pip install --upgrade "$PWD"
printf '#!/usr/bin/env bash\nexec "%s/bin/python" -m hwpx_new "$@"\n' "$VENV" > "$HOME_DIR/hwpx-new"
chmod +x "$HOME_DIR/hwpx-new"
echo
"$VENV/bin/python" -m hwpx_new doctor
echo
"$VENV/bin/python" -m hwpx_new setup --skill
echo
echo "설치 완료! 명령: $HOME_DIR/hwpx-new doctor   (AI 프로그램은 완전히 종료했다가 다시 실행하세요)"
