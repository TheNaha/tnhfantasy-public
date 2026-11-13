#!/usr/bin/env bash
set -euo pipefail

# Subcommands: start (default), run. The README documented `./agentctl.sh start`,
# and the script was `exec "$EXEC"` with no "$1" — so `./agentctl.sh stop` started
# an agent, which is the worst possible response to someone trying to shut one
# down. `stop` is rejected rather than silently ignored.
SUBCOMMAND="${1:-start}"
case "$SUBCOMMAND" in
    start|run)
        shift || true
        ;;
    -h|--help|help)
        cat <<'USAGE'
usage: agentctl.sh [start|run]

  start   run the agent in the foreground (default when no argument is given)
  run     identical to `start`

There is no `stop` subcommand: this script does not daemonise and does not track a
pidfile, so it cannot stop anything it did not start. Ctrl-C in the foreground
stops the agent. To run it detached, start it under your own supervisor
(systemd, tmux, `nohup ... &`).
USAGE
        exit 0
        ;;
    *)
        printf 'error: unknown subcommand %q\n\n' "$SUBCOMMAND" >&2
        printf 'Run `%s --help` for usage.\n' "$0" >&2
        exit 2
        ;;
esac

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
# PyInstaller writes to ./dist (see build-agent-binaries.yml and the README), so
# the binary is one directory below this script. Looking in SCRIPT_DIR meant the
# documented "build then ./agentctl.sh" always failed with "executable not found".
if [ -x "$SCRIPT_DIR/tnhfantasy-agent" ]; then
  EXEC="$SCRIPT_DIR/tnhfantasy-agent"
elif [ -x "$SCRIPT_DIR/dist/tnhfantasy-agent" ]; then
  EXEC="$SCRIPT_DIR/dist/tnhfantasy-agent"
else
  echo "error: agent executable not found at $SCRIPT_DIR/tnhfantasy-agent or $SCRIPT_DIR/dist/tnhfantasy-agent" >&2
  echo "hint: build it with  cd remote_agent && pyinstaller --noconfirm --distpath ./dist tnhcomfy-agent.spec" >&2
  exit 1
fi

if [ -f "$SCRIPT_DIR/.env" ]; then
    while IFS= read -r line || [ -n "$line" ]; do
        line="${line%$'\r'}"
        case "$line" in
            ''|'#'*) continue ;;
            export\ *) line="${line#export }" ;;
        esac
        [[ "$line" == *=* ]] || continue
        key="${line%%=*}"
        val="${line#*=}"
        key="${key#"${key%%[![:space:]]*}"}"
        key="${key%"${key##*[![:space:]]}"}"
        [[ "$key" =~ ^[A-Za-z_][A-Za-z0-9_]*$ ]] || continue
        val="${val%"${val##*[![:space:]]}"}"
        val="${val#"${val%%[![:space:]]*}"}"
        if [ "${val:0:1}" = '"' ] && [ "${val: -1}" = '"' ]; then val="${val:1:${#val}-2}"; fi
        if [ "${val:0:1}" = "'" ] && [ "${val: -1}" = "'" ]; then val="${val:1:${#val}-2}"; fi
        if [ -z "${!key+x}" ]; then export "$key=$val"; fi
    done < "$SCRIPT_DIR/.env"
fi

export DATA_DIR="${DATA_DIR:-$SCRIPT_DIR/data}"
export PORT="${PORT:-8001}"
# Only exported when the operator actually set one. server.py resolves its own
# default, and it clamps that default to 127.0.0.1 under
# REMOTE_AGENT_ALLOW_INSECURE — exporting 0.0.0.0 here would hand the flag an
# unauthenticated *writer* bound to every interface by default, which is exactly
# what the clamp exists to prevent.
# Only exported when the operator actually set one, and never as an empty
# string: `export HOST="${HOST-}"` exported `HOST=""` when unset, and uvicorn
# binds an empty host as INADDR_ANY — so this line defeated server.py's own
# loopback clamp and handed REMOTE_AGENT_ALLOW_INSECURE an unauthenticated
# writer on every interface. server.py now treats empty as unset; not producing
# it in the first place is the other half.
if [ -n "${HOST-}" ]; then
    export HOST
fi

if [ ! -x "$EXEC" ]; then
    printf 'error: agent executable not found at %s\n' "$EXEC" >&2
    printf 'Build it with: pyinstaller --distpath %s --workpath %s/build %s/tnhfantasy-agent.spec\n' "$SCRIPT_DIR" "$SCRIPT_DIR" "$SCRIPT_DIR" >&2
    exit 1
fi

exec "$EXEC"
