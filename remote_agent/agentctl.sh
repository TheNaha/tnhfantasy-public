#!/usr/bin/env bash
set -euo pipefail

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
EXEC="$SCRIPT_DIR/tnhcomfy-agent"

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
export HOST="${HOST:-0.0.0.0}"

if [ ! -x "$EXEC" ]; then
    printf 'error: agent executable not found at %s\n' "$EXEC" >&2
    printf 'Build it with: pyinstaller --distpath %s --workpath %s/build %s/tnhcomfy-agent.spec\n' "$SCRIPT_DIR" "$SCRIPT_DIR" "$SCRIPT_DIR" >&2
    exit 1
fi

exec "$EXEC"
