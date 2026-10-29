#!/usr/bin/env bash
# Development launcher (Linux/macOS/Git Bash). Reads .env from the repository root.
#   ./run.sh            -> http://127.0.0.1:8000
#   HOST=0.0.0.0 PORT=8080 ./run.sh
set -euo pipefail
cd "$(dirname "$0")/backend"
if [ ! -d .venv ]; then
  python3 -m venv .venv
fi
if [ -x .venv/bin/python ]; then PY=.venv/bin/python; else PY=.venv/Scripts/python.exe; fi
"$PY" -m pip install --quiet -r requirements.txt
echo "Serving on http://${HOST:-127.0.0.1}:${PORT:-8000} (Ctrl+C to stop)"
exec "$PY" -m uvicorn app.main:app --host "${HOST:-127.0.0.1}" --port "${PORT:-8000}"
