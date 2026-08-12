#!/usr/bin/env bash
# tnhcomfy-agent launcher.
# Starts the standalone Remote Agent executable (no Docker, no Python).
#
# Usage:
#   ./agentctl.sh start      # run in foreground (Ctrl-C to stop)
#   ./agentctl.sh start &    # background
#   REMOTE_AGENT_TOKEN=... PORT=8001 ./agentctl.sh start
#
# Edit .env (see .env.example) for ComfyUI mount path, tokens, port, etc.
set -euo pipefail

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
EXEC="$SCRIPT_DIR/tnhcomfy-agent"

# Defaults (overridable by env or .env).
export DATA_DIR="${DATA_DIR:-$SCRIPT_DIR/data}"   # storage ROOT (contains models/, output/, input/)
export PORT="${PORT:-8001}"
export HOST="${HOST:-0.0.0.0}"

# Load .env (if present) WITHOUT clobbering already-set env vars.
if [ -f "$SCRIPT_DIR/.env" ]; then
    # shellcheck disable=SC2317
    while IFS='=' read -r key val; do
        key="${key%%#*}"; key="$(echo "$key" | xargs)"; [ -z "$key" ] && continue
        # Skip if already set in the environment.
        if [ -n "${PROTECTED:-}" ]; then :; fi
        if [ -n "${!key:-}" ]; then continue; fi
        # Strip optional surrounding quotes.
        val="${val%\"}"; val="${val#\"}"; val="${val%\'}"; val="${val#\'}"
        export "$key=$val"
    done < "$SCRIPT_DIR/.env"
fi

if [ ! -x "$EXEC" ]; then
    echo "error: agent executable not found at $EXEC" >&2
    echo "Build it with: pyinstaller --distpath $SCRIPT_DIR --workpath $SCRIPT_DIR/build $SCRIPT_DIR/tnhcomfy-agent.spec" >&2
    exit 1
fi

exec "$EXEC"
