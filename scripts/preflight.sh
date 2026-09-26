#!/usr/bin/env bash
# Preflight checks for `docker compose up`.
#
# Compose declares the `metrics` and `proxy` networks as external, so on a host
# that does not already have them `docker compose up` fails at *network
# creation* — for every service, including `db`. That failure surfaces as an
# error that has nothing to do with the real cause. This script creates the
# networks if they are missing and reports the other things that silently
# disable features.
#
# Usage:  bash scripts/preflight.sh          # check and create what is missing
#         bash scripts/preflight.sh --check  # report only, create nothing
set -uo pipefail

CHECK_ONLY=0
[[ "${1:-}" == "--check" ]] && CHECK_ONLY=1

cd "$(dirname "${BASH_SOURCE[0]}")/.." || exit 1

warn=0
ok()   { printf '  \033[32mok\033[0m    %s\n' "$1"; }
bad()  { printf '  \033[31mFAIL\033[0m  %s\n' "$1"; warn=1; }
note() { printf '  \033[33mnote\033[0m  %s\n' "$1"; }

echo
echo "==> Docker networks"
# `metrics` and `proxy` are declared external in docker-compose.yml. Create any
# that are absent so compose can attach to them.
for net in tnhcomfy metrics proxy; do
  if docker network inspect "$net" >/dev/null 2>&1; then
    ok "network '$net' exists"
  elif [[ $CHECK_ONLY -eq 1 ]]; then
    bad "network '$net' is MISSING (compose declares it external)"
  elif docker network create "$net" >/dev/null 2>&1; then
    ok "network '$net' created"
  else
    bad "network '$net' is MISSING and could not be created"
  fi
done

echo
echo "==> Provider env files"
# These are gitignored and machine-specific; a clean checkout has none of them
# and compose aborts with "env file ... not found".
for f in .env.modal-zetsuke .env.modal-hp196 .env.modal-stepmania .env.llm-local .env.direct-url; do
  [[ -f "$f" ]] && ok "$f" || note "$f absent — the matching provider service will fail to start"
done

echo
echo "==> Auth tokens"
# Both provider containers and the backend now fail CLOSED without these.
if [[ -f .env ]]; then
  for key in PROVIDER_WORKER_TOKEN COMFY_DISCOVERY_TOKEN; do
    value=$(grep -E "^${key}=." .env | head -1 | cut -d= -f2-)
    if [[ -n "$value" ]]; then
      ok "$key is set"
    else
      bad "$key is empty — provider management routes and provider self-registration will refuse to work"
    fi
  done
else
  bad ".env not found"
fi

echo
echo "==> Autostart path"
if grep -qE "^HOST_BACKEND_PATH=." .env 2>/dev/null; then
  ok "HOST_BACKEND_PATH is set (needed only for COMFY_PROVIDER_AUTOSTART_ENABLED=1 / deploy)"
else
  note "HOST_BACKEND_PATH unset — backend-driven provider autostart and deploy will raise ValueError"
fi

echo
if [[ $warn -eq 0 ]]; then
  printf '\033[32mPreflight passed.\033[0m\n\n'
else
  printf '\033[31mPreflight found problems (see FAIL above).\033[0m\n\n'
fi
exit $warn
