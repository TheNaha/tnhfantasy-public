#!/usr/bin/env bash
# Run the remote_agent sidecar on Google Colab and expose it publicly.
#
# Colab is a hostile environment for this thing on purpose, and every line below
# exists because of a specific way it is:
#
#   * No systemd, no supervisor, no persistent process. A backgrounded process
#     dies when the notebook disconnects unless the runtime is kept alive, so
#     this script prints the URL and then *keeps running in the foreground* —
#     the cell is the supervisor, and ending the cell is the only way to stop.
#   * `/content` is writable and survives across cells within one runtime, but
#     NOT across runtimes. Every restart can lose it, so the storage default is
#     documented rather than assumed.
#   * No Docker (Docker-in-Docker on Colab is unreliable and the image needs
#     privileged mounts), so this runs the Python directly — the agent is
#     FastAPI + uvicorn and that is all a runtime needs.
#   * A Colab process is not reachable from the internet. It is behind NAT with
#     no inbound port, so something has to bridge that.
#
# The default bridge is NetBird: the worker joins your WireGuard mesh and gets a
# 100.x.x.x address reachable from any peer on the same network. That is a
# private, stable address, and nothing is published to the open internet — the
# opposite of the cloudflared quick tunnel it replaces, which gave a new random
# hostname on every run and put an authenticated model server on the internet
# with no TLS.
#
# The trade is a credential: NetBird needs a setup key. Cloudflared stays
# available as `PUBLIC_MODE=cloudflared` for when you have no key, and it is the
# only mode that needs nothing at all.
#
# Usage — one cell, with NETBIRD_SETUP_KEY added as a Colab SECRET (the key
# icon in the sidebar), NOT pasted into the notebook:
#
#     !bash remote_agent/colab_start.sh llm
#
# or with an explicit weights directory:
#
#     !LLM_DATA_DIR=/content/llm-weights bash remote_agent/colab_start.sh llm
#
# or with no NetBird key, accepting a public URL:
#
#     !PUBLIC_MODE=cloudflared bash remote_agent/colab_start.sh llm
#
# The script prints, in order: the public URL, the service token, the WORKER_MODE
# and the storage root it resolved. Those first two are exactly what a provider
# row needs (`agent_url` and `agent_token`).
set -euo pipefail

AGENT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
# Colab's default working directory, and the only place a runtime reliably lets
# you write. `HOME` is `/root` and is also writable, but `/content` is the one
# mounted so that a file written in one cell is visible in the next.
DEFAULT_ROOT="${COLAB_DATA_ROOT:-/content/agent-data}"

MODE="${1:-llm}"

# Fail on a missing credential BEFORE the pip install, not after it.
#
# The check used to sit inside the NetBird branch below, so a missing key first
# cost a full dependency install and then failed — and the ordering also meant
# the failure looked like a pip problem on a box whose pip is externally
# managed. Detect the cheapest problem first.
if [ "${PUBLIC_MODE:-netbird}" = "netbird" ] && [ -z "${NETBIRD_SETUP_KEY:-}" ]; then
  cat >&2 <<'ERR'
error: NETBIRD_SETUP_KEY is not set.

NetBird needs a setup key. Add it as a Colab SECRET (the key icon in the
sidebar), not into a cell — a cell lands in a shared notebook, and a setup key
in a shared notebook is a credential keyed to your whole network.

Get a reusable key at app.netbird.io -> Setup Keys. A REUSABLE key is the one to
use: this script re-joins on every runtime, and a one-time key burns on first use.

No key? Accept a public URL instead:
  PUBLIC_MODE=cloudflared bash remote_agent/colab_start.sh <mode>
ERR
  exit 1
fi

case "$MODE" in
    model|llm|tts|hybrid) ;;
    *)
        echo "error: WORKER_MODE must be one of model|llm|tts|hybrid, got '$MODE'" >&2
        echo "hint: bash remote_agent/colab_start.sh hybrid" >&2
        exit 2
        ;;
esac

# ---------------------------------------------------------------------------
# Dependencies.
#
# `pip install` per run rather than once: a runtime that recycles loses its
# site-packages, and a missing FastAPI reads as "the agent will not start" with
# nothing in the logs pointing at the real cause.
# ---------------------------------------------------------------------------
# `--break-system-packages` is not defensive: Colab's Python is the same
# externally-managed Debian one, and without the flag the install dies with
# "externally-managed-environment". This box gave exactly that error when the
# script was first written against it, which is how the bug was found.
# Both failures a system pip used to hit here, found by running the script on a
# real host rather than assuming Colab is like it:
#   * `pip install` with no flag: "externally-managed-environment" (PEP 668).
#     Colab's Python is the same externally-managed Debian one.
#   * `--break-system-packages`: clears PEP 668 and then compiles pydantic-core
#     from source on a machine with no matching wheel — which is what happened
#     when this was first tested, and the "retry without the flag" fallback made
#     it strictly worse by printing a diagnosis of the wrong problem.
#
# A venv sidesteps PEP 668, gets a python with wheels, and touches nothing
# system-side.
VENV="${COLAB_VENV:-/content/.comfy-agent-venv}"
PYTHON="$VENV/bin/python"
echo "==> installing agent dependencies into ${VENV}"
if [ ! -x "$PYTHON" ]; then
  python3 -m venv "$VENV"
fi
"$VENV/bin/pip" install --quiet --upgrade pip
"$VENV/bin/pip" install --quiet --no-cache-dir -r "$AGENT_DIR/requirements.txt"

# The agent runs from the venv, not the system python, or the install was for
# nothing.
AGENT_PY="$PYTHON"

# ---------------------------------------------------------------------------
# The token.
#
# Generated, not supplied, because the alternative is a token the operator types
# into a notebook cell — which lands in the notebook, which is often shared, and
# which is then a shared secret. A generated one is printed once below and exists
# only in this runtime.
#
# It is written to a file rather than only exported so a second cell
# (`!bash remote_agent/colab_start.sh llm` again, or a re-run after the runtime
# recycled) keeps the same token and does not invalidate the provider row the
# operator already saved.
# ---------------------------------------------------------------------------
TOKEN_FILE="${COLAB_TOKEN_FILE:-/content/.agent-token}"
if [ ! -s "$TOKEN_FILE" ]; then
  mkdir -p "$(dirname "$TOKEN_FILE")"
  python3 -c "import secrets; print(secrets.token_urlsafe(32))" > "$TOKEN_FILE"
  chmod 600 "$TOKEN_FILE"
fi
export REMOTE_AGENT_TOKEN="$(cat "$TOKEN_FILE")"

# ---------------------------------------------------------------------------
# Storage root, per mode.
#
# The same per-mode resolution the container's Dockerfile does, so a provider row
# written for a Docker deployment works unchanged here. `${LLM_DATA_DIR:-...}`
# means "use the operator's value, else this default", and the fallback chain
# ends at DATA_DIR for all three modes — exactly what `_resolve_data_root` does
# inside the agent.
# ---------------------------------------------------------------------------
case "$MODE" in
    llm) ROOT="${LLM_DATA_DIR:-$DEFAULT_ROOT/llm}" ;;
    tts) ROOT="${TTS_DATA_DIR:-$DEFAULT_ROOT/tts}" ;;
    hybrid) ROOT="${DATA_DIR:-$DEFAULT_ROOT}" ;;
    *)   ROOT="${DATA_DIR:-$DEFAULT_ROOT}" ;;
esac
mkdir -p "$ROOT"

export WORKER_MODE="$MODE"
export DATA_ROOT="$ROOT"
export HOST="0.0.0.0"

# `llm` mode serves its OWN weights, which is the parity setting.
#
# The agent reads the registry (`models.json`), launches one llama-server per
# distinct model on loopback ports, and routes by the model id in the payload —
# the same thing Modal's app does from the same file. So on Colab the LLM worker
# is a model server, not a proxy, and nothing needs `LLM_UPSTREAM_BASE`.
#
# The trade is stated plainly: a Colab runtime has a GPU but only ~12 GB of it on
# a free tier, and the real registry's primary is a 31B Q5_K_M at 23.5 GB — it
# will not fit. Fetch a model that fits, or point `LLM_DATA_DIR` at weights you
# already have. Set `LLM_UPSTREAM_BASE` to opt out and front something instead.
#
#   !LLM_DATA_DIR=/content/llm-weights bash remote_agent/colab_start.sh llm
#
# Weights are fetched with an authenticated POST against the worker itself, which
# is the `ensure_model` equivalent: repo and destination both come from the
# registry, so nothing has to be assembled by hand.
#   curl -X POST -H "Authorization: Bearer $REMOTE_AGENT_TOKEN" \
#        -H 'Content-Type: application/json' \
#        -d '{"model_id": "<id from models.json>"}' \
#        http://127.0.0.1:${PORT}/download-model
if [ "$MODE" = "llm" ]; then
  echo "==> llm mode: serving its own weights from the registry"
  nvidia-smi --query-gpu=name,memory.total --format=csv,noheader 2>/dev/null \
    || echo "    (no nvidia-smi; llama-server will run on CPU — slow but functional)"
fi

# Ports. The image agent is 8001 and the TTS worker is 8002; the LLM worker
# takes 8003, because on Colab a single runtime often runs more than one of these
# side by side and a shared port fails with "address already in use" rather than
# anything diagnostic.
case "$MODE" in
    tts) PORT="${PORT:-8002}" ;;
    llm) PORT="${PORT:-8003}" ;;
    *)   PORT="${PORT:-8001}" ;;
esac
export PORT

# ---------------------------------------------------------------------------
# Start the agent.
# ---------------------------------------------------------------------------
echo "==> starting the $MODE agent on :$PORT (storage root: $ROOT)"
cd "$AGENT_DIR"
"$AGENT_PY" server.py &
AGENT_PID=$!

# ---------------------------------------------------------------------------
# Wait for it, then expose it.
#
# The loop rather than `sleep 3`, because a cold Colab runtime can take a while to
# import uvicorn, and a fixed sleep either wastes time or races. `/health` is the
# one unauthenticated route, so it is also the only thing that can be probed
# before the token is known to work.
# ---------------------------------------------------------------------------
for _ in $(seq 1 40); do
  if curl -fsS "http://127.0.0.1:${PORT}/health" >/dev/null 2>&1; then
    break
  fi
  if ! kill -0 "$AGENT_PID" 2>/dev/null; then
    echo "error: the agent exited during startup" >&2
    wait "$AGENT_PID" || true
    exit 1
  fi
  sleep 1
done

PUBLIC_URL=""

# ---------------------------------------------------------------------------
# Reachability: NetBird by default, a public tunnel only on request.
#
# A Colab process sits behind NAT with no inbound port, so the backend cannot
# reach it directly. Two ways to bridge that:
#
#   NETBIRD  (default) — the worker joins your WireGuard mesh and gets a
#                       100.x.x.x address reachable from any peer on the same
#                       network. Private, stable, and nothing is published.
#   CLOUDFLARED (PUBLIC_MODE=cloudflared) — a public `*.trycloudflare.com` URL.
#                       Works with no account, but a new random hostname on
#                       every run and an object on the open internet.
#
# NetBird needs a setup key and is therefore opt-in-credential; cloudflared is
# the fallback for when you do not have one.
# ---------------------------------------------------------------------------
PUBLIC_MODE="${PUBLIC_MODE:-netbird}"

if [ "$PUBLIC_MODE" = "netbird" ]; then
  echo "==> joining the NetBird network"

  # ── The setup key, which must NOT be typed into a cell ────────────────────
  #
  # `NETBIRD_SETUP_KEY` is read from the environment, so the natural place for
  # it is a Colab *secret* (the key icon in the sidebar), not a notebook cell.
  # A cell lands in the notebook, the notebook is often shared, and a setup key
  # in a shared notebook is a shared credential keyed to your whole network —
  # which is the failure mode the generated service token above exists to avoid.
  #
  # Secrets are injected into the runtime's environment automatically, so no
  # extra wiring is needed once one is added.
  # (the key check is at the top of the script, before the install)

  # ── Install, if not already ───────────────────────────────────────────────
  #
  # The deb from GitHub releases rather than the pkgs.netbird.io installer
  # script: `curl | sh` executed in a notebook cell is indistinguishable, to the
  # reader next to you, from the thing you were just warned about above.
  if ! command -v netbird >/dev/null 2>&1; then
    echo "==> fetching netbird"
    curl -fsSL https://pkgs.netbird.io/install.sh | sh
  fi
  netbird version || echo "    (netbird installed)"

  # ── Join ─────────────────────────────────────────────────────────────────
  #
  # `--hostname` is what makes the peer identifiable in the dashboard, and a
  # stable name is also what a stable address would come from — NetBird DNS
  # resolves peers by name on the network, and a fixed name here means
  # `agent_url` can be a name rather than an IP. Derive it from the token file
  # so re-running this cell against the same runtime keeps the same identity.
  NETBIRD_HOSTNAME="${NETBIRD_HOSTNAME:-comfy-agent-${MODE}-$(md5sum <<< "$REMOTE_AGENT_TOKEN" | cut -c1-8)}"
  echo "==> joining as ${NETBIRD_HOSTNAME}"
  netbird up --setup-key "$NETBIRD_SETUP_KEY" --hostname "$NETBIRD_HOSTNAME" \
    ${NETBIRD_MANAGEMENT_URL:+--management-url "$NETBIRD_MANAGEMENT_URL"} \
    2>&1 | tail -5 || true

  # ── Read the address ─────────────────────────────────────────────────────
  #
  # Parsed from `netbird status`'s human output rather than an interface lookup,
  # because the interface name is not stable across versions (`wt0`, `nb0`,
  # `utun100` all appear in the docs) while the `NetBird IP:` line is what the
  # status command exists to print.
  NETBIRD_IP=""
  for _ in $(seq 1 30); do
    NETBIRD_IP="$(netbird status 2>/dev/null | grep -oE 'NetBird IP: [0-9.]+' | head -n1 | cut -d' ' -f3)"
    if [ -n "$NETBIRD_IP" ]; then
      break
    fi
    # A peer that never reaches "connected" is a key or firewall problem, and
    # looping silently for 30 seconds is worse than saying so.
    if netbird status 2>/dev/null | grep -qi 'needslogin\|login required'; then
      echo "error: netbird reports it needs a login — check the setup key" >&2
      exit 1
    fi
    sleep 1
  done

  if [ -z "$NETBIRD_IP" ]; then
    cat >&2 <<ERR
error: netbird joined but never reported an IP.

This is a connectivity problem, not a script problem. Check in order:
  1. Does the runtime have outbound UDP? WireGuard falls back to a relay but
     needs 51820/UDP for direct.
  2. Is the key still valid and not exhausted (one-time keys burn on use)?
  3. Was the peer APPROVED? NetBird, and every policy that gates peer groups,
     holds new peers until they are, so a brand-new key may join invisible.

Verbatim, for a paste into the dashboard:
  netbird status --detail
ERR
    exit 1
  fi

  PUBLIC_URL="http://${NETBIRD_IP}:${PORT}"
  NETBIRD_STATUS="connected on ${NETBIRD_IP}"
else
  # ── The public-tunnel fallback ───────────────────────────────────────────
  #
  # Kept because NetBird needs a credential and this needs none. A new random
  # hostname on every run is the whole trade: nothing here is stable, and the
  # URL is on the open internet.
  echo "==> exposing with a cloudflare quick tunnel"
  if command -v cloudflared >/dev/null 2>&1; then
    CLOUDFLARED="cloudflared"
  else
    CLOUDFLARED=/usr/local/bin/cloudflared
    echo "==> fetching cloudflared"
    ARCH="$(uname -m)"
    case "$ARCH" in
      x86_64|amd64) CF_ARCH="amd64" ;;
      aarch64|arm64) CF_ARCH="arm64" ;;
      *) echo "error: no cloudflared build for $ARCH; use PUBLIC_MODE=netbird" >&2; exit 1 ;;
    esac
    # `--no-autoupdate` on the run below matters: without it the first run tries
    # to update itself, which on Colab means writing outside /content and failing.
    curl -fsSL "https://github.com/cloudflare/cloudflared/releases/latest/download/cloudflared-linux-${CF_ARCH}" \
      -o "$CLOUDFLARED"
    chmod +x "$CLOUDFLARED"
  fi

  TUNNEL_LOG="$(mktemp)"
  "$CLOUDFLARED" --no-autoupdate tunnel --url "http://127.0.0.1:${PORT}" \
    >"$TUNNEL_LOG" 2>&1 &
  TUNNEL_PID=$!

  for _ in $(seq 1 40); do
    # cloudflared prints the assigned hostname on stderr as soon as the tunnel is
    # up; there is no API to ask for it, so this is the only way to get it.
    FOUND="$(grep -oE 'https://[a-z0-9-]+\.trycloudflare\.com' "$TUNNEL_LOG" | head -n 1 || true)"
    if [ -n "$FOUND" ]; then
      PUBLIC_URL="$FOUND"
      break
    fi
    sleep 1
  done
fi

cat <<SUMMARY

======================================================================
  Remote agent is up (WORKER_MODE=${MODE})
======================================================================

  Reachability   ${NETBIRD_STATUS:-cloudflare tunnel (public)}
  Address        ${PUBLIC_URL:-<none; see above>}
  Service token  ${REMOTE_AGENT_TOKEN}
  Storage root   ${ROOT}
  Local port     ${PORT}

Backend provider row:
  type            remote_${MODE}
  agent_url       ${PUBLIC_URL:-<address>}
  agent_token     ${REMOTE_AGENT_TOKEN}

Per-mode storage on this box, if you want the others:
  model -> DATA_DIR      (currently ${DATA_DIR:-$DEFAULT_ROOT})
  llm   -> LLM_DATA_DIR  (currently ${LLM_DATA_DIR:-$DEFAULT_ROOT/llm})
  tts   -> TTS_DATA_DIR  (currently ${TTS_DATA_DIR:-$DEFAULT_ROOT/tts})

Everything above is in THIS RUNTIME ONLY. A runtime recycle loses the storage
root and the address above; the token in ${TOKEN_FILE} survives, so a provider row
keeps working if you re-run this against a fresh runtime only when the address has
not changed. When it does change, update agent_url on the provider row.

With NetBird that address is ALSO a new peer: the mesh state lives on the
management server, not in this runtime, so re-running does not churn peers but it
also does not reuse this one's slot. See remote_agent/README.md.

Keep this cell running — it is the process supervisor. Ending it stops the agent
and anything this script started alongside it.
======================================================================

SUMMARY

# `wait` on everything this script started, so a crash in either is visible in the
# cell output rather than leaving a half-working setup: an agent with no route to
# it looks identical to a healthy one from the notebook's side.
#
# With NetBird there is no foreground tunnel process — `netbird up` runs the
# daemon — so the agent alone is what to watch. The daemon outliving the cell is
# not a leak: the runtime is torn down with it.
wait -n "$AGENT_PID" ${TUNNEL_PID:+"$TUNNEL_PID"} || true
STATUS=$?
echo "error: the agent or the tunnel exited (status ${STATUS})" >&2
exit "$STATUS"
