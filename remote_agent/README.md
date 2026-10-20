# Remote Agent (standalone executable)

The **Remote Agent** is the local file/storage daemon that the `remote-comfy`
provider worker talks to. It must run on the **machine that hosts ComfyUI**
(i.e. inside the GPU rig / your Comfy Desktop install). The provider worker
downloads models, downloads sidecars, validates storage, and uploads results
*through* this agent instead of hitting ComfyUI directly — giving the same
storage semantics as the Modal/Beam workers.

A standalone executable (`tnhcomfy-agent` on Linux, `tnhcomfy-agent.exe` on
Windows) is provided so you do **not** need Docker or Python installed on the
ComfyUI host.

## Quick start (no Python, no Docker)

1. **Get the binary**
   - **Linux**: grab the `linux` artifact from a CI run of
     `build-agent-binaries.yml`, or build it yourself:
     ```bash
     cd remote_agent
     pip install -r build-requirements.txt
     pip install -r requirements.txt
     pyinstaller --noconfirm --distpath ./dist --workpath ./build tnhcomfy-agent.spec
     ```
     → `dist/tnhcomfy-agent`
   - **Windows**: grab the `windows` artifact from the same workflow (the
     `.spec` cross-compiles cleanly on a Windows runner). To build locally on
     Windows: install Python 3.13, `pip install -r build-requirements.txt` and
     the runtime pins, then run the same `pyinstaller` command →
     `dist\tnhcomfy-agent.exe`.

2. **Configure**
   ```bash
   cp remote_agent/.env.example remote_agent/.env
   # — then edit .env — set DATA_DIR to your ComfyUI repo root (see below)
   ```

3. **Run**
   - Linux: `./agentctl.sh start` (foreground) or `./agentctl.sh start &`
   - Windows: `agentctl.bat` (double-click to run in a console, or
     `start "" agentctl.bat` to run backgrounded)

   `start` is the default, so a bare `./agentctl.sh` does the same thing. There is
   **no `stop` subcommand**: the script neither daemonises nor writes a pidfile,
   so it cannot stop anything it did not start. Ctrl-C stops a foreground run;
   for a detached one, use your own supervisor (systemd, tmux, Task Scheduler).
   Any other subcommand is rejected with a usage message rather than ignored.

4. **Verify**
   ```bash
   curl http://localhost:8001/health
   ```

## Running under Docker on the GPU rig

`remote_agent/docker-compose.yml` is a separate stack from the orchestrator's.
It is the only supported way to run the agent in a container.

```bash
cd remote_agent
cp .env.agent.example .env.agent
# edit .env.agent and set a real REMOTE_AGENT_TOKEN

# DATA_DIR goes to COMPOSE, not into .env.agent:
DATA_DIR=/home/user/ComfyUI/models docker compose up -d
```

`DATA_DIR` is read by compose at **parse** time to build the bind mount, so it
has to be in compose's own environment (a prefix on the command line, the
exported shell environment, or a `.env` file *next to the compose file*). Putting
it in `.env.agent` has no effect: `env_file:` populates the container
environment, and by then the mount has already been resolved. The compose file
fails fast with a message saying so rather than mounting a placeholder path.

### The RAM cache needs a sized `/dev/shm`

The RAM cache is the reason this worker can share one 24 GB card between
ComfyUI, the prose model, the utility model and Laya: the weights are staged
in system RAM, so a reload is a RAM→VRAM copy rather than a re-read from a
volume.

`/dev/shm` is tmpfs — RAM-backed — and **Docker sizes it to 64 MB by
default**. The agent cannot change that: `mount -o remount,size=…` needs
`CAP_SYS_ADMIN`, which it does not have. So the compose file declares it:

```yaml
shm_size: ${AGENT_SHM_SIZE:-8gb}
```

Raise it to roughly the largest model you intend to stage — 8 GB is a
reasonable default on a 32 GB box, and a 19.5 GB GGUF wants more. Without it
the cache silently cannot hold anything, the agent streams from the volume
instead, and every model load pays the full disk cost. The agent's
`/ram-cache/status` reports the store's real capacity against the budget, so
a mismatch is visible rather than inferred.

## Storage roots — a different tree per worker

An image worker exposes a ComfyUI **repo root** (`models/`, `output/`, `input/`
live under it). An LLM worker usually wants a plain weights directory with no
ComfyUI structure in it at all, and a TTS worker is typically back on a ComfyUI
rig because it shares one. So the root is selected by `WORKER_MODE`, one variable
per mode, each falling back to `DATA_DIR`:

| `WORKER_MODE` | variable read | falls back to |
|---|---|---|
| `model` (default) | `DATA_DIR` | `./data` |
| `llm` | `LLM_DATA_DIR` | `DATA_DIR` |
| `tts` | `TTS_DATA_DIR` | `DATA_DIR` |

```bash
# image worker on its ComfyUI rig — unchanged
DATA_DIR=/opt/ComfyUI docker compose up -d

# LLM worker on a different box, pointing at a plain weights tree
WORKER_MODE=llm LLM_DATA_DIR=/opt/llm-weights docker compose up -d

# TTS worker, deliberately back on a ComfyUI rig
WORKER_MODE=tts TTS_DATA_DIR=/opt/ComfyUI docker compose up -d
```

The root is the container's storage **root**, not a `models/` subdirectory, so
setting `LLM_DATA_DIR=/opt/llm-weights` puts the LLM worker's models tree at
`/opt/llm-weights/models` and leaves the ComfyUI tree alone.

`/setup`, `/list-models`, `/download-model`, `/validate-models`, `/delete-model`,
`/get-file`, `/upload-file` and `/delete-file` all resolve against the root for
the mode — in **every** mode, not just `model`. That is what makes a `remote_llm`
or `remote_tts` provider able to manage files the same way a `remote_comfy` one
can, and what makes the remote transport 1-to-1 with `modal` per category.

## `WORKER_MODE=llm` serves its own weights

An LLM worker is not a proxy by default. It reads the model registry
(`backend_v2/modal_llm/models.json`), launches **one llama-server per distinct
model** on loopback ports, and routes by the model id in the payload — the same
thing Modal's app (`deployables/modal/llm/app.py`) does, from the same file. That
is what makes a `remote_llm` provider the same thing as `modal_llm` rather than a
lookalike: the tree the worker manages is the tree that answers, and there is
nothing to reconcile.

```bash
CUDA_RUNTIME=runtime-llama WORKER_MODE=llm \
    LLM_DATA_DIR=/mnt/llm-weights docker compose up -d --build
```

The registry is one file read by all three sides — the Modal app, this worker, and
the backend's `services/llm_router.py` — so a role's model cannot disagree between
transports. Both roles resolving to the same weights is the shared-model setting,
and `distinct_primaries()` collapses it to one launch: the same 24.7 GB GGUF is
not started twice to double the VRAM for nothing.

With no weights present the worker starts healthy and `/info` reports each role
`not_downloaded` with its reason — the shape Modal's `health` answers, so polling
either side shows an actionable state instead of a crash-loop to infer from
retries.

## `WORKER_MODE=hybrid` runs Image + LLM + TTS concurrently

A hybrid worker runs ComfyUI (`:8188`), the storage agent (`:8001`), and `llama-server` (`:8003`) on a single hardware node (such as Google Colab Pro, a local multi-modal workstation, or a dedicated GPU server).

The backend's `remote_hybrid` engine inspects the node's GPU capabilities via the `/info` endpoint and schedules jobs according to the chosen hardware concurrency policy:
- **`exclusive`**: Cooperative VRAM mutual exclusion. Ideal for budget 16-24GB cards (L4, T4). ComfyUI calls `/free` after image generation to flush CUDA cache before LLM tasks execute.
- **`semi_concurrent`**: Co-locates RP chat and ComfyUI image tasks simultaneously; utility tasks swap exclusively (ideal for A100 40GB).
- **`concurrent`**: Unconstrained parallel multi-modal processing (ideal for A100 80GB and H100).
- **`auto`**: Auto-detects the GPU via `/info` and applies the policy based on reported VRAM.

Fetch a model's weights, by registry id (repo and destination both come from
`models.json`, so a typo cannot land a file where llama-server will not find it):

```bash
curl -X POST -H "Authorization: Bearer $REMOTE_AGENT_TOKEN" \
     -H 'Content-Type: application/json' \
     -d '{"model_id": "artemis_31b"}' \
     http://localhost:8001/download-model
```

then recreate the container so the new model loads.

**Two builds, one Dockerfile.** `llm` needs a GPU and a llama-server binary, and
it uses the *same* llama.cpp image the Modal app does, so the two transports run
the same llama-server from the same GGUFs. `model` and `tts` do not, and carrying
a CUDA runtime they never use would allocate a card on a rig that may have none.

```bash
docker build -f remote_agent/Dockerfile -t tnhcomfy-agent ..            # model / tts
docker build -f remote_agent/Dockerfile \
    --build-arg CUDA_RUNTIME=runtime-llama -t tnhcomfy-agent-llm ..     # llm
```

Two notes on the CUDA base, both found by building rather than by reading: it
ships no `pip` and no `ensurepip` module (Debian splits it out), so `apt-get
install python3-pip` is the one spelling that works; and it ships no `passwd`
package, so `useradd` exits 4 and the llama image runs as root. Both are guarded
in the Dockerfile with comments.

`LLM_UPSTREAM_BASE` still works and is now the **opt-out**: set it to front a
llama.cpp or vLLM you already run, and the worker becomes an authenticated proxy
instead of a model server.

### Two things the sidecar deliberately does not copy from `backend_v2`

`backend_v2` uses `logger.info("msg", key=value)` everywhere. This sidecar
imports nothing from `backend_v2` and gets a plain stdlib `Logger`, whose
`info(**kwargs)` forwards to `_log(level, msg, args, exc_info, extra, ...)` — so
`key=value` raises `TypeError` at the **first** log line on a worker at INFO,
which is every deployment. Use `extra={...}` here.

`backend_v2/modal_llm/registry.py` is not imported either; `llama_server.py`
carries the ~40 lines of parsing that shape needs. The *file* is shared (one
`models.json`, mounted or copied in) — a second copy of the registry is what
would drift, a second copy of the parser is not.

## Google Colab

[![Open In Colab](https://colab.research.google.com/assets/colab-badge.svg)](https://colab.research.google.com/github/TheNaha/TNHComfy/blob/main/remote_agent/TNHComfy_Colab_Worker.ipynb)

A ready-to-use Jupyter Notebook is provided at [`remote_agent/TNHComfy_Colab_Worker.ipynb`](TNHComfy_Colab_Worker.ipynb) (and copied to repo root [`TNHComfy_Colab_Worker.ipynb`](../TNHComfy_Colab_Worker.ipynb)). It provides a graphical Colab Form with step-by-step cells for:
1. **Google Drive Persistence & GPU Detection**: Mounts `/content/drive/MyDrive` to persist NetBird configuration, bearer tokens, and model directories.
2. **Private Repository Access**: Clones the private TNHComfy repository using your GitHub Personal Access Token (`GITHUB_TOKEN` from form or Colab Secrets).
3. **NetBird by Default with Static IP**: Saves `/var/lib/netbird` to Google Drive upon initial setup so the setup key is only required **once**. On subsequent runs, it reconnects automatically with the **same static WireGuard IP** without burning peer licenses.
4. **Google Drive ComfyUI Integration**: Directly mounts and runs your existing ComfyUI workspace from Google Drive (`/content/drive/MyDrive/comfyui` copied from Modal). All checkpoints, LoRAs, VAEs, and custom nodes are immediately available without re-downloading.
5. **Multi-Model LLM Parity**: Serves curated roleplay (`rp`) and utility/tool (`util`) models matching `backend_v2/modal_llm/models.json` via CUDA-accelerated `llama-server`.
6. **Zero Duplicate Secrets**: `HF_TOKEN` and `CIVITAI_TOKEN` are resolved on-demand directly from your TNHComfy backend per request.
7. **Connection Card & Keep-Alive**: Renders a styled HTML card with connection parameters, and includes an inaudible audio context keep-alive to prevent Colab idle timeouts.
8. **Automatic provider registration**: The notebook creates (or updates) the
   provider row on your backend itself, using a provider id derived from the
   endpoint, so re-running the cell updates the same row rather than
   accumulating duplicates. The credentials are still printed, because the
   backend may be unreachable from the notebook and the manual path has to
   remain.

**One owner per GPU.** In `llm` mode the agent's stack serves the LLM — one
`llama-server` per registry primary on adjacent loopback ports — and the
notebook does not start a second one. The VRAM arbiter also stands down when
something else is already serving, so the same 19.5 GB of weights are never
loaded twice onto one 24 GB card. The agent's `/info` reports which models
are live, and the notebook's health check reads it rather than assuming.

Alternatively, if you prefer running via a direct bash script in a single cell:
`colab_start.sh` runs the agent directly in a notebook runtime — no Docker, no
Python, no GPU-adjacent host required — and exposes it through a Cloudflare quick
tunnel so the backend can reach it:

```python
!bash remote_agent/colab_start.sh llm
```

It prints the address, the service token and the storage root, plus the exact
`type` / `agent_url` / `agent_token` to put on a provider row. Keep the cell
running: it is the process supervisor, and ending it stops the agent and the
tunnel. A runtime recycle loses the storage root and the address; the token file
(`/content/.agent-token`) survives, so re-running against a fresh runtime only
needs `agent_url` updated.

Reachability is **NetBird by default**: the worker joins your WireGuard mesh and
gets a `100.x.x.x` address, which is what you put in `agent_url`. Private, stable,
and nothing is published.

```python
from google.colab import userdata   # add NETBIRD_SETUP_KEY as a Colab SECRET
!bash remote_agent/colab_start.sh llm
```

`PUBLIC_MODE=cloudflared` is the fallback for when you have no key: a public
`*.trycloudflare.com` URL with a new random hostname on every run. Prefer NetBird
— the quick tunnel puts an authenticated model server on the open internet with
no TLS, and its address changes on every recycle.

### Three NetBird-specific things worth knowing

**The key is a network-level credential**, which is why the script reads
`NETBIRD_SETUP_KEY` from the environment and not from an argument you type into a
cell — a cell lands in a notebook, the notebook is often shared, and a setup key
in a shared notebook is a credential keyed to your whole network. Add it as a
Colab secret, which injects it into the runtime's environment.

**Every runtime is a new peer.** Colab's filesystem resets, so NetBird's state
under `/var/lib/netbird` goes with it and each run re-registers. NetBird Cloud's
free tier caps peers (5 as of writing), so a runtime you recycle ten times burns
ten. A self-hosted management server removes the cap; otherwise clean up dead
peers in the dashboard. The peer is named
`comfy-agent-<mode>-<8 hex of your service token>` so its identity is stable and
recognizable even as it re-registers.

**A peer that joins may need approving.** NetBird and any policy gating peer
groups hold new peers until a human approves them, so a key that works can still
join invisibly. If `netbird status` never reaches "connected", look there before
the firewall.

Three Colab-specific behaviours are deliberate and commented in the script: the
token is **generated** rather than typed (a cell is often shared, and a shared
secret is the failure mode), the startup wait is a `/health` loop rather than a
fixed sleep (a cold runtime takes variable time to import uvicorn), and the LLM
worker takes port **8003** so a runtime can host more than one mode side by side.

## Environment variables (`.env`)

| Key | Default | Meaning |
|---|---|---|
| `DATA_DIR` | `./data` | **Storage root** that contains `models/`, `output/`, `input/`. Point this at your **ComfyUI repo root** (e.g. `C:\ComfyUI` or `/opt/ComfyUI`), **not** its `models/` subfolder. |
| `HOST` | `0.0.0.0` | Listen address. |
| `PORT` | `8001` | Listen port. |
| `REMOTE_AGENT_TOKEN` | *(no default — the agent refuses to start without it)* | Shared secret the worker must send as `Authorization: Bearer <token>`. |
| `REMOTE_AGENT_ALLOW_INSECURE` | `0` | Set to `1`/`true`/`yes` to start with **no authentication at all**. |
| `HF_TOKEN` | *(from env)* | HuggingFace token for model downloads. |
| `CIVITAI_TOKEN` | *(from env)* | CivitAI token (`?token=`) for model downloads. |
| `DOWNLOAD_TIMEOUT` | `1800` | Per-download seconds. |
| `REMOTE_AGENT_SEED_MAX_CONCURRENT` | `3` | Concurrent `/setup` seed downloads. |

### `REMOTE_AGENT_TOKEN` is REQUIRED — there is no "empty means open" mode

`server.py` runs this at **import**, before the app is even constructed:

```python
TOKEN = os.getenv("REMOTE_AGENT_TOKEN", "").strip()
ALLOW_INSECURE = os.getenv("REMOTE_AGENT_ALLOW_INSECURE", "").lower() in {"1", "true", "yes"}
if not TOKEN and not ALLOW_INSECURE:
    raise RuntimeError("REMOTE_AGENT_TOKEN must be set unless REMOTE_AGENT_ALLOW_INSECURE=1")
```

So an empty `REMOTE_AGENT_TOKEN=` does **not** give you an open agent. It gives
you an agent that raises during import and a container that crash-loops, with the
`RuntimeError` in the logs and nothing serving on 8001. The only two states that
start are: a real token, or `REMOTE_AGENT_ALLOW_INSECURE=1` and no auth at all.

The freeze is deliberate: this process is single-purpose and mostly unauthenticated
by default in most agents of this shape, and `/delete-model`, `/delete-file` and
`/get-file` are all reachable by anything that can reach the port. Set a token.
`python3 -c "import secrets; print(secrets.token_urlsafe(32))"` is enough.

## Windows — after installing Comfy Desktop / ComfyUI

1. Run the agent once to create the storage layout and confirm the port is
   reachable:
   ```bat
   cd remote_agent
   agentctl.bat
   curl http://localhost:8001/health
   ```
2. **Windows Defender Firewall** — allow `tnhcomfy-agent.exe` (or port 8001) on
   *Private* networks so the backend machine can reach it.
3. On the **backend orchestrator** machine, point
   `.env.remote-comfy` (used by the `provider-remote-comfy` worker) at your
   Windows host:
   ```ini
   REMOTE_AGENT_URL=http://<WINDOWS_HOST_LAN_IP>:8001
   REMOTE_AGENT_TOKEN=your-secret-token-here
   CIVITAI_TOKEN=...
   HF_TOKEN=hf_...
   COMFYUI_URL=http://<WINDOWS_HOST_LAN_IP>:8188
   ```
4. (Optional) Make the agent start automatically: run it as a background task
   via Task Scheduler (run whether user is logged on / run with highest
   privileges) or pin `agentctl.bat` to your shell-startup folder.

## Endpoint parity with Modal/Beam

| Operation | Agent endpoint | Matches |
|---|---|---|
| Download a model (blocking, validated, `.downloading` → atomic rename) | `POST /download-model` | Modal `download_model_to_path` / Beam `download-model` |
| List models (sidecars + dotfiles excluded) | `POST /list-models` | `list_models` |
| Validate storage (magic bytes / min size; `.downloading`→partial) | `POST /validate-models`, `POST /validate-all-models` | Modal/Beam model validation |
| Delete a model + sidecars | `POST /delete-model` / `POST /delete-file` | `delete_downloaded_file` |
| Read any file the worker needs | `GET /get-file/{path}` | `get_file` (provider side proxies ComfyUI `/view` → now the agent) |
| Seed default models + create dirs | `POST /setup` | `setup_models` |

All file paths are routed through `provider_core.utils.get_safe_path` and reject
path-traversal attempts with HTTP 403.
