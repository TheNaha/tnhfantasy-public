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
# One secret, both directions. Both ends fail CLOSED without it: a container
# answers 503 on every protected route, and the backend refuses unauthenticated
# provider registration. This check exists because that failure is otherwise
# only visible as `discovery_token_not_configured` in the container logs.
if [[ -f .env ]]; then
  value=$(grep -E "^COMFY_PROVIDER_TOKEN=." .env | head -1 | cut -d= -f2-)
  if [[ -n "$value" ]]; then
    ok "COMFY_PROVIDER_TOKEN is set"
  else
    bad "COMFY_PROVIDER_TOKEN is empty — provider management routes AND provider self-registration will refuse to work (generate one: python3 -c 'import secrets; print(secrets.token_urlsafe(32))')"
  fi
  # A leftover from the two-token era is silently ignored by compose now, so it
  # reads as configured while the real variable is empty.
  for stale in PROVIDER_WORKER_TOKEN COMFY_DISCOVERY_TOKEN; do
    if grep -qE "^${stale}=" .env; then
      note ".env still declares $stale, which nothing reads any more — remove it"
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
echo "==> Providers"
# `COMFY_DISCOVERY_ALLOW_NEW_PROVIDERS` is gone and this section no longer checks
# it. It was an opt-in gate dressed as a security control: all providers share the
# COMFY_PROVIDER_TOKEN, so the token was the entire boundary, and the heartbeat
# path ignored the flag while overwriting the URL jobs dispatch to. A new provider
# now registers enabled. See docs/audit-2026-10-03.md.
#
# What is genuinely worth knowing at setup time is how many registered providers
# are switched on. "disabled" is a per-provider field the Providers page edits,
# not an env var, and it is the only control that decides whether a provider takes
# your jobs. It is invisible everywhere else in the stack, which is why an audit
# found five of six off with no failover and no local LLM.
if curl -sf --max-time 3 http://localhost:8002/api/v2/providers/ >/dev/null 2>&1; then
  # Counted with a JSON parse, not a grep: the list response nests an `enabled`
  # and several `id`s per provider (runtime_state, capabilities), so a grep count
  # reads 10 disabled "of 6".
  counts=$(curl -sf --max-time 3 http://localhost:8002/api/v2/providers/ 2>/dev/null | python3 -c '
import json, sys
try:
    body = json.load(sys.stdin)
except Exception:
    sys.exit(0)
# The list route answers {"providers": [...]}, not a bare array.
rows = body.get("providers") if isinstance(body, dict) else body
if not isinstance(rows, list):
    sys.exit(0)
off = sum(1 for r in rows if isinstance(r, dict) and r.get("enabled") is False)
print(f"{off} {len(rows)}")
' 2>/dev/null)
  disabled=${counts%% *}
  total=${counts##* }
  if [[ "${disabled:-0}" -gt 0 ]]; then
    note "$disabled of ${total:-?} registered providers are switched off, so the load balancer has no failover and llm-local/direct_url are idle"
    note "  enable on the Providers page, or PATCH /api/v2/providers/{id} {\"enabled\": true}"
  elif [[ "${total:-0}" -gt 1 ]]; then
    ok "all ${total} providers are enabled"
  fi
else
  note "could not reach the backend to read provider state (is it up?)"
fi

echo
if [[ $warn -eq 0 ]]; then
  printf '\033[32mPreflight passed.\033[0m\n\n'
else
  printf '\033[31mPreflight found problems (see FAIL above).\033[0m\n\n'
fi
exit $warn
