#!/usr/bin/env bash
# ============================================================
#  One-click launcher for macOS / Linux.
#  All the real logic lives in scripts/bootstrap.py so that
#  Windows and Unix behave exactly the same.
#
#  Usage:
#      ./start.sh
#      ./start.sh --api-port 8010 --web-port 8090
#      ./start.sh --check          # 只检查环境，不起服务
# ============================================================
set -euo pipefail
cd "$(dirname "$0")"

PY=""
if [ -x ".venv/bin/python" ]; then
  PY=".venv/bin/python"
elif command -v python3 >/dev/null 2>&1; then
  PY="python3"
elif command -v python >/dev/null 2>&1; then
  PY="python"
else
  echo "[ERROR] 找不到 Python。请先安装 Python 3.10+。"
  exit 1
fi

exec "$PY" scripts/bootstrap.py "$@"
