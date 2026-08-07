#!/usr/bin/env bash
set -e
cd "$(dirname "$0")"
# 3.12 explicitly. The system python3 is 3.9 and cannot parse `str | None`,
# so a venv built with it fails at import — override with TOWER_PYTHON if needed.
PY="${TOWER_PYTHON:-/opt/homebrew/bin/python3.12}"
[ -d .venv ] || "$PY" -m venv .venv
./.venv/bin/pip install -q -r requirements.txt
[ -f .env ] && set -a && . ./.env && set +a
# NO --reload: reload resets in-memory handle state mid-demo.
exec ./.venv/bin/uvicorn app:app --host 127.0.0.1 --port 8100
