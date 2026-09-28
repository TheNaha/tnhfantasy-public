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
# `metrics` and `proxy` are declared `external: true` in docker-compose.yml, so
# compose will NOT create them and every service fails at network creation if
# they are missing — with an error that does not name the cause.
for net in metrics proxy; do
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

# `tnhcomfy` is NOT external — compose creates and owns it. It used to be in the
# loop above, which meant every `up` warned that an existing network was not
# created by compose. Check it for information only; never create it.
if docker network inspect tnhcomfy >/dev/null 2>&1; then
  ok "network 'tnhcomfy' exists (compose-managed; safe to delete while stopped)"
else
  echo "  note 'tnhcomfy' not present yet; compose will create it on first up"
fi

echo
echo "==> Provider env files"
# These are gitignored and machine-specific, and `docker compose` aborts with
# "env file ... not found" if one is missing — for EVERY service, with an
# unrelated-looking error, before anything starts. This used to `note` the
# absence, so `warn` stayed 0 and the script printed "Preflight passed" and
# exited 0 on precisely the clean checkout it exists to catch. It is a hard
# failure unless the service that needs it is not being started, which is why
# the recommendation is to create the file rather than to proceed.
#
# The list is derived from the `env_file:` entries in docker-compose.yml so it
# cannot fall behind a new provider — but comments are stripped FIRST. grep does
# not know about YAML comments, and docker-compose.yml keeps the
# `provider-remote-comfy` block (and its `env_file: - .env.remote-comfy`) present
# but commented out, so the raw extraction demanded an env file for a service
# compose will not start. A shipped script that refuses to pass on a valid
# checkout is worse than the note it replaced.
provider_env_files=$(sed -e 's/#.*//' docker-compose.yml | grep -oE '\.env\.[a-z0-9-]+' | sort -u)
for f in $provider_env_files; do
  [[ -f "$f" ]] && ok "$f" || bad "$f missing — docker compose will refuse to start (create it or remove the service)"
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
