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

4. **Verify**
   ```bash
   curl http://localhost:8001/health
   ```

## Environment variables (`.env`)

| Key | Default | Meaning |
|---|---|---|
| `DATA_DIR` | `./data` | **Storage root** that contains `models/`, `output/`, `input/`. Point this at your **ComfyUI repo root** (e.g. `C:\ComfyUI` or `/opt/ComfyUI`), **not** its `models/` subfolder. |
| `HOST` | `0.0.0.0` | Listen address. |
| `PORT` | `8001` | Listen port. |
| `REMOTE_AGENT_TOKEN` | *(empty)* | If set, the worker must send `Authorization: Bearer <token>`. |
| `HF_TOKEN` | *(from env)* | HuggingFace token for model downloads. |
| `CIVITAI_TOKEN` | *(from env)* | CivitAI token (`?token=`) for model downloads. |
| `DOWNLOAD_TIMEOUT` | `1800` | Per-download seconds. |

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
