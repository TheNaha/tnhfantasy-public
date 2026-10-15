# `deployables/` — cloud worker source for the Modal and Beam providers

These are the **deploy sources** for the two Modal apps and the four Beam
deployments that the backend's in-process engines talk to. They are not
imported by the backend, not tested by the backend suite, and not built by the
repo's compose stack: each one is uploaded to someone else's cloud, built
there, and reached over the network through the Modal SDK or a URL. The backend
side is `backend_v2/services/engines/`; this directory is what is on the other
end of those calls.

The tree was deleted in `acc86aa3` ("Remove containerized provider workers;
provider_core moves to remote_agent") along with the container workers whose
only reason to exist was a `worker.py` HTTP app between the backend and these
deployments. Nothing in `backend_v2/` imports these files, but the engines
still name every class and function in here, so the tree was un-deployable
while it was absent: a fix to a Modal function could not be written, because
there was nothing to write it in.

## What is here

| Path | Cloud artifact | Engine that talks to it |
| --- | --- | --- |
| `modal/image/modal_app.py` | Modal app **`comfy-modal-stack`** | `backend_v2/services/engines/modal_engine.py:89` (`ModalEngine`) |
| `modal/tts/modal_app.py` | Modal app **`comfy-modal-tts`** | `backend_v2/services/engines/modal_tts_engine.py:136` (`ModalTTSEngine`) |
| `modal/llm/app.py` | Modal app **`tnh-llm`** (llama.cpp) | `backend_v2/services/engines/llm_engine.py` (`ModalLlamaCPPEngine`) |
| `beam/beam_app.py` | Beam deployments `comfy-gpu`, `comfy-storage`, `comfy-download`, `comfyui-extractor` | `backend_v2/services/engines/beam_engine.py:69` (`BeamEngine`) |
| `provider_worker_core/` | `provider_core` modules the 2026-10-08 slimming deleted | imported by all three of the above |

`modal/llm/app.py` is the odd one: its registry (`registry.py` +
`models.json`) is shared with the backend's `llm_router` and with
`remote_agent/llama_server.py`, so the registry stayed in
`backend_v2/modal_llm/` and this file resolves it by walking up to the repo root
— the same bootstrap the image and beam apps use. `bash scripts/deploy.sh llm`
is the shortest path to it; see `backend_v2/modal_llm/README.md` for the roles.

Supporting files: `modal/image/load_profiler_node/` and
`modal/image/memory_snapshot_helper/` are ComfyUI custom nodes packaged into the
Modal image (`tnh_load_profiler`, `memory_snapshot_helper`); `beam/workflow_executor.py`
is the ComfyUI executor shared by the GPU deployment (its Modal twin is inlined
at the top of `modal/image/modal_app.py`); `beam/models_utils.py` is the
listing implementation behind `POST /list-models`.

Engines are selected by provider type in
`backend_v2/services/engines/engine_factory.py:641` (`"comfy-modal-stack"`) and
`:367` (`"comfy-modal-tts"`); both names are overridable per provider row.

## The name contract, verified

Every name below was checked against both sides — the revived source and the
engine that looks it up. They agree. All ten exist, and no engine looks up a
name that is absent here.

**`comfy-modal-stack`** (`modal/image/modal_app.py:485`)

| Looked up by | Name | Defined at |
| --- | --- | --- |
| `modal_engine.py:197,212` | `ComfyUISnapshot` / `ComfyUIStable` | `image/modal_app.py:757`, `:665` |
| `modal_engine.py:567` | `ComfyUINodeExtractor` | `image/modal_app.py:863` |
| `modal_engine.py:387,555,575` | `FileStorage` | `image/modal_app.py:1319` |
| `modal_engine.py:158,363` | function `list_models_with_metadata` | `image/modal_app.py:1058` |
| `modal_engine.py:487` | function `validate_models` | `image/modal_app.py:1074` |
| `modal_engine.py:463` | function `download_model` | `image/modal_app.py:926` |
| `modal_engine.py:520` | function `setup_models` | `image/modal_app.py:1485` |

**`comfy-modal-tts`** (`modal/tts/modal_app.py:94,280`)

| Looked up by | Name | Defined at |
| --- | --- | --- |
| `modal_tts_engine.py:152,206,376` | `TTSWorker` | `tts/modal_app.py:297` |
| `modal_tts_engine.py:153,261,312,346` | `TTSFileStorage` | `tts/modal_app.py:487` |

**Beam** has no name contract — it is URLs, not SDK lookups. `BeamEngine`
resolves `gpu_url` / `storage_url` / `download_url` / `extractor_url` from the
provider row, and every route it calls exists in `beam/beam_app.py`:
`/list-models` (`beam_app.py:440`), `/get-file` (`:496`), `/delete-file`
(`:534`), `/delete-model` (`:463`), `/upload-file` (`:569`), `/validate-models`
(`:589`), `/validate-all-models` (`:705`), `/setup` (`:322`), `/download-model`
(`:893`, `:434`), `/object_info` (`:1000`), `/health`, and the `comfy_gpu`
realtime websocket (`beam_app.py:797`).

## Deploying

Use `scripts/deploy.sh`. It checks the preconditions for each target (CLI
present, credentials present) and then shells out to `modal deploy` /
`beam deploy`; this section is what it does, and why.

```bash
bash scripts/deploy.sh list            # what can be deployed from here
bash scripts/deploy.sh check           # preconditions only, deploy nothing
bash scripts/deploy.sh image --dry-run
```

There is deliberately no `POST /providers/{id}/deploy`. `InProcessEngine.deploy()`
returns `{"status": "not_applicable", "mode": "in_process"}` with no production
caller, and a request handler that shells out to a vendor CLI would put a
network round-trip, a credential lookup and a multi-minute build inside an HTTP
timeout. For a single-operator deployment the CLI is the whole surface; the
`deploy_config` / `deploy_state` JSON columns on a provider row are a record of
what is running, not a trigger for it.

### Modal — image (`comfy-modal-stack`)

```bash
# Credentials: MODAL_TOKEN_ID / MODAL_TOKEN_SECRET, read from the provider's
# env file (.env.modal-<provider-id>) or the process environment. HF_TOKEN /
# CIVITAI_TOKEN are optional (gated model downloads).
modal deploy deployables/modal/image/modal_app.py
```

Deploy from the repository root: the app packages `remote_agent/provider_core`
and `deployables/provider_worker_core` into the image, and it finds them by
walking up to the repo root. Deploying from the app's own directory resolves
those paths the same way, so either works, but the repo root is the one to use.

The build reads `MODAL_GPU_TYPE` (default `L4`) for **both** the runtime classes
and the image's CUDA build steps; `MODAL_BUILD_GPU_TYPE` overrides only the
build. Timeouts, concurrency, scaledown and the volume name
(`MODAL_VOLUME_NAME`, default `comfy-storage`) are all read at deploy time —
see the configuration block at `modal/image/modal_app.py:431`.

### Modal — TTS (`comfy-modal-tts`)

```bash
# Same Modal workspace as the image app; no new account.
MODAL_TTS_APP_NAME=comfy-modal-tts modal deploy deployables/modal/tts/modal_app.py
```

(`scripts/deploy.sh tts` runs this, honouring `MODAL_TTS_APP_NAME`.)

Knobs: `MODAL_TTS_APP_NAME`, `MODAL_TTS_GPU_TYPE`, `MODAL_TTS_SCALEDOWN`
(default 300s), `MODAL_TTS_TIMEOUT`, `MODAL_TTS_MODEL_DIR`
(`/mnt/data/models/TTS`), `MODAL_VOLUME_NAME`. The two apps deliberately share
the volume so a TTS model downloaded once is visible to both.

### Beam

```bash
# NOT INSTALLED in this environment: pip install beam-client, then `beam configure`.
beam deploy deployables/beam/beam_app.py:comfy_gpu
beam deploy deployables/beam/beam_app.py:comfy_storage
beam deploy deployables/beam/beam_app.py:comfy_download
beam deploy deployables/beam/beam_app.py:comfy_extractor
```

`scripts/deploy.sh beam` runs exactly these. Run them **from the repository
root**, and read this before you do: unlike the
Modal apps, `beam_app.py` adds no source to its images (`gpu_image`/
`cpu_image` at `beam_app.py:128,163` are built from commands and pip packages
only), and every one of the four decorators it uses (`@realtime`, `@asgi` ×2,
`@rest_api`) syncs the local working directory into the container, with
`deployables/beam/.beamignore` deciding what is excluded. So
`workflow_executor.py`, `models_utils.py`, `provider_core` and
`provider_worker_core` all have to be inside the directory you deploy from.

**This is a change from the 2026-08 procedure**, which was
`cd provider_containers/image_worker/engines/beam && beam deploy beam_app.py`.
That worked because `provider_core` was a sibling; it is not any more, and the
deleted tree's own docs recorded this exact failure
(`ModuleNotFoundError: No module named 'provider_core'`). Deploying from the
repo root restores it, at the cost of syncing the entire checkout — extend
`.beamignore` (`**/node_modules/**`, `.git`, `__pycache__` are already there) if
the sync is a problem. The `sys.path` bootstrap at `beam_app.py:53` then finds
both packages by their repo-relative location, and falls back to this file's own
directory when there is no repo at all.

The backend side needs `BEAM_API_KEY`, `BEAM_WORKSPACE_ID` and the four
deployment URLs the deploy publishes; see `.env.example.provider.engines`.

## This is a CLOUD artifact: reviving the source does not redeploy it

The live `modal-zetsuke` provider is running a Modal app **deployed on
2026-08-12**, from a revision whose source was deleted with the container tree.
Restoring the files in this directory changed nothing about what is running.
A redeploy is a separate, deliberate act — and it is not a no-op, because the
deployed build and this source disagree on the wire:

> `FileStorage.file_exists()` and `FileStorage.get_file_size()` existed in the
> 2026-08-12 build and **do not exist here**. `FileStorage.file_size()` and
> `FileStorage.read_file_range()` did not exist then and **are what
> `modal_engine.py:392` and `modal_engine.py:409` call today**. The swap
> happened in `0ece3eb6` (2026-09-26, "perf(providers): stream model files
> instead of materialising them").
>
> So `get_file` against the old deployment raises a Modal "method not found",
> and the provider still reports **healthy**, because `check_health`
> (`modal_engine.py:158`) probes only `list_models_with_metadata`, which has the
> same signature in both revisions. The health check cannot see this; the first
> symptom is a `get_file` failure on the backend side.

Before redeploying, diff the surface you care about against what is live:

```bash
git show 174ccf5d:provider_containers/image_worker/engines/modal/modal_app.py \
  | grep -nE '^class |^async def |^def '   # 2026-08-13, the closest revision to the live build
```

Everything else the engine calls — `ComfyUIStable`, `ComfyUISnapshot`,
`ComfyUINodeExtractor`, `FileStorage.read_file/put_file/delete_file/
list_directory`, `download_model`, `validate_models`, `setup_models`,
`list_models_with_metadata` — is identical in both revisions, so a redeploy of
the image app carries thirteen revisions of behaviour fixes to that file (29
across it and the provider_core modules it imports: download validation, artifact
sweeps, VRAM lifecycle unification, partial-download classification) and no
contract change beyond those two methods.

The TTS app's history has the opposite shape: `bd36e272` (2026-09-29, "fix(tts):
the TTS Modal app could not be imported, so it could not be deployed") means a
deployment from before that date could not have succeeded at all. Its source
here is the fixed revision.

## `provider_worker_core/`, and the drift it invites

The apps import `provider_core`, which now lives at
`remote_agent/provider_core/` — its only consumer is `remote_agent/server.py`,
and the 2026-10-08 slimming removed everything the deployables need:
`comfy_lifecycle` and `model_scan` were deleted outright, and the shared
`http_client` was cut down to a 30-line stub holding `get_file_size_cap` while
`responses.outcome` was dropped.

`deployables/provider_worker_core/` restores exactly those, at `acc86aa3^`, and
nothing else. Three of the four are whole modules the apps had no reason to
touch (`comfy_lifecycle`, `model_scan`, `http_client`); `responses.py` is a
fork of the live one that still exists upstream. **A bug fixed in
`remote_agent/provider_core/` is not fixed here.** The two copies no longer
share a test suite, so copy the change across deliberately. Do not grow this
package: anything the live `provider_core` still exports should be imported from
there instead.

Each app resolves both packages explicitly at import time rather than assuming
they are siblings — see the bootstrap at `modal/image/modal_app.py:27`,
`modal/tts/modal_app.py:65` and `beam/beam_app.py:53`. The deleted layout
required `provider_core` to sit next to the app file, and that assumption was
what made the tree un-deployable once the container layout changed. On Modal the
packages are copied into `/root` beside the uploaded module, which is why
`sys.path[0]` resolves them in the container and no `PYTHONPATH` is needed;
`image_download` (`modal/image/modal_app.py:590`) is the exception and keeps
`PYTHONPATH=/`.

## Lint

`deployables/ruff.toml` mirrors `backend_v2/ruff.toml`: pyflakes (`F`) only, no
per-file `F401` exemptions. `ruff check deployables/` is clean.

## What is NOT here, and why

- **`provider_containers/llm_worker/engines/modal/modal_app.py` is not
  revived.** It was the vLLM LLM app and it is superseded: the LLM provider is
  now `deployables/modal/llm/app.py` (`tnh-llm`, llama.cpp, one `ChatLLM` class
  parametrized by model id) and is now a sibling of this directory rather than a
  file inside `backend_v2/`. Nothing looks up the vLLM app name, class or
  functions any more. Do not resurrect it — see `backend_v2/modal_llm/README.md`.
- **`beam/client.py` is not revived.** It was the *backend-side* HTTP client for
  the Beam **container** worker; `backend_v2/services/engines/beam_engine.py` is
  its in-process replacement (it even documents itself as the "parity twin" of
  `client.py`). It also imports `provider_core.background` and
  `provider_core.base_client`, both deleted in `acc86aa3`.
- **`beam/worker.py` and `beam/Dockerfile` are not revived.** Both were the
  container deployment path and were already deleted upstream in `c319b96b`
  (2026-08-01, "Remove unused Beam and Modal provider worker files"); the same
  commit removed `image_worker/engines/modal/Dockerfile` and `modal/worker.py`.
  The cloud deployables are built by the SDK, not by a Dockerfile.
- **The image worker container's `worker.py`, its `Dockerfile`, and the
  `modal/`, `direct_url/`, `remote_comfy/` container clients are not revived.**
  All of it was the HTTP app between the backend and these deployments, replaced
  by `backend_v2/services/engines/` on 2026-10-08.
- **Everything deleted in `acc86aa3` for the same reason** — the provider
  router, background-task, deploy, SSE, ranged-read and model-scan modules that
  the container workers used. `model_scan` is the exception, and it is back
  above, because the deployables still call it.
- **`provider_containers/requirements-test.txt` and `provider_containers/tests/`
  are not revived.** They tested the container HTTP apps and the container
  clients, which are gone. The only test that still described a live contract
  (`tests/test_tts_modal_contract.py`) is now documentation: the table above.