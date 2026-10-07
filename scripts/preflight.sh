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
echo "==> Network exposure"
# The backend publishes NO host port. The frontend does, and it is a reverse proxy
# to that backend — `nginx.conf` (`server_name _`, `location /api/`) in prod,
# `vite.config.js` in dev — so the frontend's bind address IS the API's reach.
# `docker-compose.yml:158` defaults it to loopback and Traefik reaches the
# service on the external `proxy` network without a host port, so a wildcard buys
# nothing and costs the entire unauthenticated API on every interface.
#
# This was measured, not assumed: `curl http://192.168.1.28:5174/api/ready`
# answered 200 while the backend answered nothing on any host port.
# The SHELL wins over `.env` in compose interpolation, so a value exported in the
# environment overrides the file and this check has to read both or it cannot
# report the binding that will actually be published. Demonstrated:
#
#   COMFY_FRONTEND_BIND=0.0.0.0 docker compose config
#     frontend_v2 ports -> 127.0.0.1:5174, 0.0.0.0:5174
#
# while reading `.env` alone still reported 100.150.0.4 and downgraded to a note —
# i.e. exactly the condition this check exists to catch was unreachable when set
# the way an operator would actually set it.
frontend_bind=${COMFY_FRONTEND_BIND:-$(grep -E "^COMFY_FRONTEND_BIND=" .env 2>/dev/null | head -1 | cut -d= -f2-)}
# 127.0.0.2 is the compose default for the second binding. The whole of
# 127.0.0.0/8 is loopback and unroutable, so it is a safe default rather than a
# wildcard — see the comment in docker-compose.yml.
frontend_bind=${frontend_bind:-127.0.0.2}
case "$frontend_bind" in
  ""|127.*|localhost|::1)
    ok "frontend is bound to loopback only (${frontend_bind}) — Traefik serves it on the proxy network"
    ;;
  0.0.0.0|::|"[::]")
    bad "COMFY_FRONTEND_BIND=${frontend_bind} serves the whole unauthenticated API on EVERY interface, including any LAN NetBird does not cover. Unset it, or name one VPN/LAN address."
    ;;
  *)
    note "frontend is also bound to ${frontend_bind} — correct if that is your VPN/LAN address, but the API is reachable by anything that can route to it"
    ;;
esac

echo
echo "==> Autostart path"
if grep -qE "^HOST_BACKEND_PATH=." .env 2>/dev/null; then
  ok "HOST_BACKEND_PATH is set (needed only for COMFY_PROVIDER_AUTOSTART_ENABLED=1 / deploy)"
else
  note "HOST_BACKEND_PATH unset — backend-driven provider autostart and deploy will raise ValueError"
fi

# `.env` is injected into the backend verbatim by `env_file:`, so a value written
# there really is in the container's environment — which is how a
# COMFY_DATABASE_URL=sqlite:///... line survives in a stack whose data is in
# Postgres, and how `docker exec backend printenv` ends up disagreeing with what
# the backend is actually using. POSTGRES_HOST decides, and the backend logs the
# discarded value at boot, but "read the logs" is not a preflight.
if grep -qE "^COMFY_DATABASE_URL=." .env 2>/dev/null; then
  note ".env sets COMFY_DATABASE_URL, which POSTGRES_HOST overrides for this stack — remove the line unless you intend a non-compose run (see .env.example)"
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
#
# Read from INSIDE the container, which is the only place the API is reachable.
# It used to `curl http://localhost:8002/...` on the host, and that stopped
# working the moment the `0.0.0.0` publish was removed on 2026-10-03: the host
# answer is 000, so this section could never fire again — the exact finding it
# was added for. It then `note`d the failure rather than failing, so preflight
# exited 0 while reporting nothing. `bad` is correct here: an operator who cannot
# read provider state cannot act on a disabled-provider surprise, and the exit
# code is the part they act on.
BACKEND_SVC=backend_v2
providers_json=$(
  docker compose exec -T "$BACKEND_SVC" \
    curl -sf --max-time 3 localhost:8002/api/v2/providers/ 2>/dev/null
)
if [[ -z "$providers_json" ]]; then
  # `exec` also fails when the container is not running, so this covers "not up"
  # and "up but not answering" with one message.
  bad "could not read provider state from inside '$BACKEND_SVC' (is it up? try: docker compose ps $BACKEND_SVC) — provider enable/disable state is unchecked"
else
  # Counted with a JSON parse, not a grep: the list response nests an `enabled`
  # and several `id`s per provider (runtime_state, capabilities), so a grep count
  # reads 10 disabled "of 6".
  counts=$(printf '%s' "$providers_json" | python3 -c '
import json, sys
try:
    body = json.load(sys.stdin)
except Exception:
    sys.exit(1)
# The list route answers {"providers": [...]}, not a bare array.
rows = body.get("providers") if isinstance(body, dict) else body
if not isinstance(rows, list):
    sys.exit(1)
off = sum(1 for r in rows if isinstance(r, dict) and r.get("enabled") is False)
# Chat is non-functional without an enabled LLM provider, and that is not
# visible anywhere else in this script: the count above reports "1 of 6
# providers are switched off" and leaves the operator to work out which.
# `/api/v2/llm/available-models` is the route the chat composer actually calls,
# so its emptiness is the honest signal.
llm_enabled = sum(
    1 for r in rows
    if isinstance(r, dict)
    and r.get("enabled") is not False
    and (r.get("worker_type") == "llm" or str(r.get("type", "")).startswith(("openai", "anthropic", "google", "ollama", "vllm", "modal_llm")))
)
models = None
print(f"{off} {len(rows)} {llm_enabled}")
')
  if [[ -z "$counts" ]]; then
    bad "provider list from '$BACKEND_SVC' was not the expected JSON shape — provider enable/disable state is unchecked"
  else
    disabled=${counts%% *}
    rest=${counts#* }
    total=${rest%% *}
    llm_on=${rest##* }
    if [[ "${disabled:-0}" -gt 0 ]]; then
      note "$disabled of ${total:-?} registered providers are switched off, so the load balancer has no failover and llm-local/direct_url are idle"
      note "  enable on the Providers page, or PATCH /api/v2/providers/{id} {\"enabled\": true}"
    elif [[ "${total:-0}" -gt 1 ]]; then
      ok "all ${total} providers are enabled"
    fi
    # The single most consequential thing on this page, and the only one that
    # makes a whole feature dead rather than degraded.
    if [[ "${llm_on:-0}" -eq 0 ]]; then
      bad "NO ENABLED LLM PROVIDER — every chat turn will fail. /roleplay, /chat and every story beat that asks a character to reply depend on it."
      bad "  enable one of the llm providers above, or add one: POST /api/v2/providers {\"type\": \"openai_compat\", \"worker_type\": \"llm\", ...}"
      bad "  verify with: docker compose exec $BACKEND_SVC curl -s localhost:8002/api/v2/llm/available-models   (an empty [] means no model is reachable)"
    elif [[ "${llm_on:-0}" -eq 1 ]]; then
      note "exactly 1 LLM provider is enabled — chat works, with no failover if it goes away"
    fi
  fi
fi

echo
echo "==> Feature gates"
# A gate that defaults to OFF is invisible: the feature is simply missing and
# nothing logs an error. Preflight already reports HOST_BACKEND_PATH above; these
# are the rest of the same class, and each entry states what it costs you when it
# is unset rather than restating the variable name.
#
# The container's environment is the authoritative one: compose `environment:`
# overrides `env_file:`, so reading `.env` from the host reports the wrong value
# for anything compose pins.
backend_env() {
  docker compose exec -T "$BACKEND_SVC" printenv "$1" 2>/dev/null | tr -d '\r'
}
gate() {
  # gate <VAR> <consequence-when-unset-or-default> <effective-value-label>
  local var=$1 consequence=$2 label=$3 value
  value=$(backend_env "$var")
  if [[ -z "$value" ]]; then
    note "$var is unset — $consequence"
  else
    ok "$var=$value ($label)"
  fi
}
gate COMFY_IDLE_SIM_ENABLED \
  "idle simulation is off; no autonomous character activity" \
  "idle sim enabled"
gate COMFY_LB_HEALTH_CHECKS_ENABLED \
  "defaults to on; set 0 only to silence provider probes" \
  "LB health checks on"
gate COMFY_PROVIDER_AUTOSTART_ENABLED \
  "backend-driven provider autostart and deploy are off (also needs HOST_BACKEND_PATH)" \
  "provider autostart on"
gate COMFY_ASSET_MIGRATION_FORCE \
  "off by default; set 1 to force a full asset re-scan on boot" \
  "forced asset re-scan on EVERY boot"
gate COMFY_DB_POOL_SIZE \
  "defaults to 30; the SQLAlchemy default of 5 is a hard 15-connection ceiling that 500s a gallery page" \
  "DB pool size"
gate COMFY_DB_MAX_OVERFLOW \
  "defaults to 30 (see COMFY_DB_POOL_SIZE)" \
  "DB pool overflow"
gate COMFY_DB_POOL_TIMEOUT \
  "defaults to 30s; this is how long a request waits before the pool gives up" \
  "DB pool wait"
gate COMFY_WORKER_HOSTS \
  "no exclusions; provider hosts are resolved from the provider table instead, so this only matters for a genuinely external host that must NOT receive the shared token" \
  "hosts excluded from token attachment"
gate COMFY_DISCOVERY_ALLOWED_HOSTS \
  "no allowlist, so any provider may register. Setting it is a RESTRICTION: a provider whose hostname is not listed is refused with 422" \
  "discovery host allowlist (restrictive)"
gate COMFY_UVICORN_WORKERS \
  "single worker, which is required: >1 raises at boot (the websocket broadcast is in-process)" \
  "requested uvicorn workers"

echo
if [[ $warn -eq 0 ]]; then
  printf '\033[32mPreflight passed.\033[0m\n\n'
else
  printf '\033[31mPreflight found problems (see FAIL above).\033[0m\n\n'
fi
exit $warn
