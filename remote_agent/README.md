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
