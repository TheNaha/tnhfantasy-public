#!/usr/bin/env bash
set -euo pipefail

ROOT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
BACKEND_DIR="$ROOT_DIR/backend_v2"
FRONTEND_DIR="$ROOT_DIR/frontend_v2"
VENV_DIR="$BACKEND_DIR/.venv"
BACKEND_PID=""
FRONTEND_PID=""

cleanup() {
    trap - EXIT INT TERM
    if [ -n "$FRONTEND_PID" ]; then kill "$FRONTEND_PID" 2>/dev/null || true; fi
    if [ -n "$BACKEND_PID" ]; then kill "$BACKEND_PID" 2>/dev/null || true; fi
}
trap cleanup EXIT INT TERM

if [ ! -d "$VENV_DIR" ]; then
    python3 -m venv "$VENV_DIR"
fi

"$VENV_DIR/bin/python" -m pip install -r "$BACKEND_DIR/requirements.txt"
(cd "$FRONTEND_DIR" && npm ci)

if [ -f "$ROOT_DIR/.env" ]; then
    set -a
    source "$ROOT_DIR/.env"
    set +a
fi

UVICORN_ARGS=(--host 0.0.0.0 --port 8002)
if [ "${COMFY_UVICORN_RELOAD:-1}" = "1" ]; then
    UVICORN_ARGS+=(--reload)
fi
(
    cd "$BACKEND_DIR"
    exec "$VENV_DIR/bin/uvicorn" api.main:app "${UVICORN_ARGS[@]}"
) &
BACKEND_PID=$!

(cd "$FRONTEND_DIR" && exec npm run dev -- --host 0.0.0.0 --port 5174) &
FRONTEND_PID=$!

printf '%s\n' 'Setup complete. Backend: http://localhost:8002; Frontend: http://localhost:5174'
wait "$BACKEND_PID" "$FRONTEND_PID"
