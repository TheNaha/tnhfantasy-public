#!/usr/bin/env bash
# Deploy a cloud provider worker.
#
# Every provider the backend talks to is one of four deployables, and this is
# the single documented way to ship new code to them. It exists because
# `deployables/` was deleted in `acc86aa3` while the engines kept naming every
# class and function in it: the tree was un-deployable, so a fix to a Modal
# function could not be written. See `deployables/README.md` for the name
# contract and for what is *not* here and why.
#
# This is a HOST operator tool, not a backend feature. There is deliberately no
# `POST /providers/{id}/deploy`: `InProcessEngine.deploy()` returns
# `{"status": "not_applicable"}` with no production caller, and shelling out to
# a vendor CLI from a request handler would put a network round-trip, a
# credential lookup and a multi-minute build inside an HTTP timeout.
#
# Usage:
#   bash scripts/deploy.sh list                 # what can be deployed from here
#   bash scripts/deploy.sh check [target]       # preconditions only, deploy nothing
#   bash scripts/deploy.sh image [--dry-run]    # Modal app `comfy-modal-stack`
#   bash scripts/deploy.sh tts [--dry-run]      # Modal app `comfy-modal-tts`
#   bash scripts/deploy.sh llm [--dry-run]      # Modal app `tnh-llm` (llama.cpp)
#   bash scripts/deploy.sh beam [--dry-run]     # all four Beam deployments
#   bash scripts/deploy.sh all [--dry-run]      # every target whose check passes
#
# Run it from anywhere; it `cd`s to the repo root first. That is not cosmetic:
# the Modal apps find `remote_agent/provider_core` and
# `deployables/provider_worker_core` by walking up to the repo root, and Beam
# syncs the *working directory* into the container, so Beam must be deployed
# from the root too.
set -uo pipefail

cd "$(dirname "${BASH_SOURCE[0]}")/.." || exit 1

DRY_RUN=0
declare -a TARGETS=()

die()  { printf '\033[31merror\033[0m %s\n' "$*" >&2; exit 1; }
note() { printf '\033[33mnote\033[0m  %s\n' "$*"; }
ok()   { printf '\033[32mok\033[0m    %s\n' "$*"; }

# ---------------------------------------------------------------- arguments
for arg in "$@"; do
  case "$arg" in
    --dry-run) DRY_RUN=1 ;;
    -h|--help) sed -n '2,28p' "$0" | sed 's/^# \{0,1\}//'; exit 0 ;;
    -*) die "unknown flag: $arg (try --help)" ;;
    *) TARGETS+=("$arg") ;;
  esac
done
[[ ${#TARGETS[@]} -eq 0 ]] && TARGETS=(list)

is_known() {
  case "$1" in
    # list/check are handled before this loop; they are here so a typo in a
    # deploy target is caught early rather than silently deploying nothing.
    list|check|all|image|tts|llm|beam) return 0 ;;
    *) return 1 ;;
  esac
}
for t in "${TARGETS[@]}"; do
  is_known "$t" || die "unknown target '$t' (try: bash scripts/deploy.sh list)"
done

# ------------------------------------------------------------- preconditions
MODAL_ENV_HINT=".env.modal-<provider-id> or the process environment"

check_modal() {
  local missing=0
  if ! command -v modal >/dev/null 2>&1; then
    printf '\033[31mFAIL\033[0m  modal CLI not found (pip install modal)\n'; missing=1
  else ok "modal CLI: $(modal --version 2>/dev/null | head -1)"
  fi
  if [[ -z "${MODAL_TOKEN_ID:-}" || -z "${MODAL_TOKEN_SECRET:-}" ]]; then
    # If unpopulated, check if candidate env files exist in the project root
    local cand
    for cand in ${PROVIDER_ID:+.env."$PROVIDER_ID"} .env.modal-* .env; do
      if [[ -f "$cand" ]]; then
        set -a; # shellcheck disable=SC1090
        source "$cand" 2>/dev/null; set +a
        if [[ -n "${MODAL_TOKEN_ID:-}" && -n "${MODAL_TOKEN_SECRET:-}" ]]; then
          break
        fi
      fi
    done
  fi
  if [[ -z "${MODAL_TOKEN_ID:-}" || -z "${MODAL_TOKEN_SECRET:-}" ]]; then
    printf '\033[31mFAIL\033[0m  MODAL_TOKEN_ID / MODAL_TOKEN_SECRET unset (%s)\n' "$MODAL_ENV_HINT"
    missing=1
  else ok "modal credentials present"
  fi
  return $missing
}

check_beam() {
  local missing=0
  if ! command -v beam >/dev/null 2>&1; then
    printf '\033[31mFAIL\033[0m  beam CLI not found (pip install beam-client)\n'; missing=1
  else ok "beam CLI: $(beam --version 2>/dev/null | head -1)"
  fi
  if [[ -z "${BEAM_API_KEY:-}" ]]; then
    local cand
    for cand in ${PROVIDER_ID:+.env."$PROVIDER_ID"} .env.beam-* .env; do
      if [[ -f "$cand" ]]; then
        set -a; # shellcheck disable=SC1090
        source "$cand" 2>/dev/null; set +a
        if [[ -n "${BEAM_API_KEY:-}" ]]; then
          break
        fi
      fi
    done
  fi
  note "beam needs an authenticated workspace: 'beam configure' if you have not"
  return $missing
}

# ------------------------------------------------------------------ targets
# Each target is: <source file>|<app or deployment>|<extra check>.
deploy_modal_app() {
  local src="$1" app="$2" what="$3"
  echo
  echo "==> $what ($app)"
  if ! check_modal; then
    note "skipped: preconditions not met"
    return 1
  fi
  echo "     modal deploy $src"
  if [[ $DRY_RUN -eq 1 ]]; then note "dry run: not deploying"; return 0; fi
  modal deploy "$src" || return 1
  ok "$app deployed"
  note "the backend reaches it by name ($app); redeploying does not change any"
  note "provider row. Verify with: curl /api/v2/providers or the Diagnostics tab."
}

case "${TARGETS[0]}" in
  list)
    echo "==> deployable targets"
    printf '  %-10s %s\n' TARGET SOURCE
    printf '  %-10s %s\n' 'image -> comfy-modal-stack' deployables/modal/image/modal_app.py
    printf '  %-10s %s\n' 'tts -> comfy-modal-tts' deployables/modal/tts/modal_app.py
    printf '  %-10s %s\n' 'llm -> tnh-llm' deployables/modal/llm/app.py
    printf '  %-10s %s\n' 'beam -> 4 deployments' deployables/beam/beam_app.py
    echo
    note "container workers (provider_containers/) are gone; in-process engines are the only path"
    exit 0
    ;;
  check)
    rc=0
    for t in "${TARGETS[@]:1}"; do
      echo "==> checking $t"
      case "$t" in
        beam) check_beam || rc=1 ;;
        *)    check_modal || rc=1 ;;
      esac
    done
    [[ "${#TARGETS[@]}" -eq 1 ]] && { check_modal || rc=1; check_beam || rc=1; }
    exit $rc
    ;;
esac

rc=0
if [[ "${TARGETS[0]}" == "all" ]]; then TARGETS=(image tts llm beam); fi
for t in "${TARGETS[@]}"; do
  case "$t" in
    image)
      deploy_modal_app deployables/modal/image/modal_app.py \
        comfy-modal-stack "Modal image worker" || rc=1
      ;;
    tts)
      deploy_modal_app deployables/modal/tts/modal_app.py \
        "${MODAL_TTS_APP_NAME:-comfy-modal-tts}" "Modal TTS worker" || rc=1
      ;;
    llm)
      # The llama.cpp app lives in backend_v2/modal_llm/ because its module and
      # the backend's model registry share models.json; deployables/ holds only
      # the workers that no backend module imports.
      deploy_modal_app deployables/modal/llm/app.py \
        "${MODAL_LLM_APP_NAME:-tnh-llm}" "Modal llama.cpp LLM worker" || rc=1
      ;;
    beam)
      echo
      echo "==> Beam workers (6 deployments)"
      if ! check_beam; then note "skipped: preconditions not met"; rc=1; continue; fi
      # Deploy from the repo root, not from deployables/beam: these files add
      # no source to their images and every decorator syncs the working
      # directory, so workflow_executor.py / models_utils.py / provider_core /
      # provider_worker_core / remote_agent/llama_server.py have to be inside
      # it. See deployables/README.md.
      for dep in comfy_gpu comfy_storage comfy_download comfy_extractor; do
        echo "     beam deploy deployables/beam/beam_app.py:$dep"
        [[ $DRY_RUN -eq 1 ]] && continue
        beam deploy "deployables/beam/beam_app.py:$dep" || rc=1
      done
      # The LLM and TTS cells live in their own module because their contract is
      # a websocket, not a ComfyUI graph: `@realtime` binds one handler at a
      # deployment root with no path routing, so `/llm` and `/tts` have to be
      # `@asgi` FastAPI apps. Both engine types were advertised in the Providers
      # modal before this existed and dialled paths nothing served.
      for dep in comfy_llm comfy_tts; do
        echo "     beam deploy deployables/beam/llm_tts_app.py:$dep"
        [[ $DRY_RUN -eq 1 ]] && continue
        beam deploy "deployables/beam/llm_tts_app.py:$dep" || rc=1
      done
      [[ $DRY_RUN -eq 0 ]] && note "publish the returned URLs into the provider row (gpu_url / storage_url / download_url / extractor_url)"
      ;;
  esac
done

echo
if [[ $rc -ne 0 ]]; then
  die "one or more targets did not deploy"
fi
ok "all requested targets deployed"
