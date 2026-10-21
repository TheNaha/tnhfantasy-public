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

# The backend's bind.
#
# It used to be a hard-coded `0.0.0.0`, which publishes the ENTIRE
# unauthenticated API - every route, `DELETE /api/jobs`,
# `PATCH /api/v2/providers/{id}` - on every interface the host has. Nothing
# in front of it authenticates. On 2026-10-01 an ordinary audit probe called
# `DELETE /api/jobs` from the LAN and destroyed 154 rows of job history.
#
# Loopback is the safe default, and the same knob the compose stack uses:
# `COMFY_BACKEND_BIND` in `.env` names one address to publish on. The
# frontend is a reverse proxy to this API, so whatever reaches the frontend
# reaches the API.
UVICORN_ARGS=(--host "${COMFY_BACKEND_BIND:-127.0.0.1}" --port 8002)
if [ "${COMFY_UVICORN_RELOAD:-1}" = "1" ]; then
    # Keep the reload watcher off the test suite and the one-off scripts. The
    # watcher follows the whole backend_v2 tree, so touching a test otherwise
    # restarts the API — dropping WebSockets and stopping the job queue and
    # scheduler for a change that cannot affect the running app. Keep in sync
    # with the excludes in backend_v2/Dockerfile.
    UVICORN_ARGS+=(
        --reload
        --reload-exclude '**/tests/**'
        --reload-exclude '**/scripts/**'
        --reload-exclude '**/memory_snapshot_helper/**'
    )
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
