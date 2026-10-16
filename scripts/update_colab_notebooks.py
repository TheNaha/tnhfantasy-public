"""Update TNHComfy_Colab_Worker.ipynb and remote_agent/TNHComfy_Colab_Worker.ipynb

Synchronizes both notebooks with the Models-in-RAM management system and backend-as-single-source-of-truth.
"""

import json
import os
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parent.parent

NOTEBOOK_PATHS = [
    REPO_ROOT / "TNHComfy_Colab_Worker.ipynb",
    REPO_ROOT / "remote_agent" / "TNHComfy_Colab_Worker.ipynb",
]


def build_cell_2_source() -> list[str]:
    code = """#@title 2. ⚙️ Worker Configuration { run: "client" }
#@markdown Choose your worker mode and networking setup:

WORKER_MODE = "hybrid (all-in-one: image + llm + tts)" #@param ["hybrid (all-in-one: image + llm + tts)", "image (remote_comfy)", "llm (remote_llm)", "tts (remote_tts)"]
TUNNEL_METHOD = "netbird (private mesh VPN)" #@param ["netbird (private mesh VPN)", "cloudflared (free, no setup)"]

#@markdown ---
#@markdown #### ⚡ Concurrency & Hardware Policy (Hybrid Mode):
#@markdown - `auto`: Probes GPU VRAM automatically (>=70GB -> concurrent, >=35GB -> semi_concurrent, else exclusive)
#@markdown - `exclusive`: Mutual exclusion on GPU; ComfyUI cooperatively frees VRAM before LLM executes (Best for L4 24GB / T4)
#@markdown - `semi_concurrent`: Runs RP LLM and ComfyUI simultaneously; swaps utility models exclusively (Best for A100 40GB)
#@markdown - `concurrent`: Full parallel execution without restrictions (Best for A100 80GB / H100)
CONCURRENCY_POLICY = "auto (detect from GPU VRAM)" #@param ["auto (detect from GPU VRAM)", "exclusive (budget L4/T4)", "semi_concurrent (A100 40GB)", "concurrent (A100 80GB)"]

#@markdown ---
#@markdown #### 🌐 NetBird Mesh VPN (Default & Recommended):
#@markdown Your setup key is only needed ONCE. Config will be saved to Google Drive so your IP is static forever:
NETBIRD_SETUP_KEY = "" #@param {type:"string"}
#@markdown Self-hosted NetBird Management URL (e.g. https://netbird.yourdomain.com:443; leave blank if using default NetBird Cloud):
NETBIRD_MANAGEMENT_URL = "" #@param {type:"string"}
#@markdown Optional Admin URL for self-hosted NetBird (leave blank unless specifically needed):
NETBIRD_ADMIN_URL = "" #@param {type:"string"}

#@markdown ---
#@markdown #### 🌐 TNHComfy Backend Sync (Backend as Single Source of Truth):
#@markdown Enter your TNHComfy backend URL (e.g. http://100.150.0.1:8002 via NetBird or domain). If left blank, uses local curated catalog:
BACKEND_URL = "" #@param {type:"string"}

#@markdown ---
#@markdown #### 🔒 Private Repository Access (TNHComfy is private):
#@markdown Enter a GitHub Personal Access Token (PAT) with repo read permissions (or save as GITHUB_TOKEN in Colab Secrets):
GITHUB_TOKEN = "" #@param {type:"string"}

#@markdown ---
#@markdown #### 🎨 Image / Hybrid Mode — Google Drive ComfyUI:
#@markdown Path to your ComfyUI folder copied from Modal (default is /content/drive/MyDrive/comfyui):
GDRIVE_COMFY_PATH = "/content/drive/MyDrive/comfyui" #@param {type:"string"}

#@markdown ---
#@markdown #### 💬 LLM / Hybrid Mode — Curated Models from models.json:
LLM_RP_MODEL = "artemis_31b" #@param ["artemis_31b", "writers_31b_v2", "gemma4_31b_heretic", "sompoa_26b_a4b", "weirdcompound_24b", "magnum_diamond_24b"]
LLM_UTIL_MODEL = "same_as_rp" #@param ["same_as_rp", "gemma3_12b_heretic_util", "mistral_small_32_it"]
GDRIVE_LLM_PATH = "/content/drive/MyDrive/tnhcomfy/llm_models" #@param {type:"string"}

# Try resolving tokens from Google Colab Secrets (the Key icon on left sidebar)
try:
    from google.colab import userdata
    if not GITHUB_TOKEN: GITHUB_TOKEN = userdata.get("GITHUB_TOKEN", "")
    if not NETBIRD_SETUP_KEY: NETBIRD_SETUP_KEY = userdata.get("NETBIRD_SETUP_KEY", "")
    if not NETBIRD_MANAGEMENT_URL: NETBIRD_MANAGEMENT_URL = userdata.get("NETBIRD_MANAGEMENT_URL", "")
    if not NETBIRD_ADMIN_URL: NETBIRD_ADMIN_URL = userdata.get("NETBIRD_ADMIN_URL", "")
    if not BACKEND_URL: BACKEND_URL = userdata.get("BACKEND_URL", "")
except Exception:
    pass

print("⚙️ Configuration saved!")
print(f"• Mode: {WORKER_MODE}")
print(f"• Network: {TUNNEL_METHOD}")
if BACKEND_URL.strip():
    print(f"• Backend Sync: {BACKEND_URL.strip()} (single source of truth for active models)")
if "netbird" in TUNNEL_METHOD and NETBIRD_MANAGEMENT_URL.strip():
    print(f"• NetBird Management: {NETBIRD_MANAGEMENT_URL.strip()}")
if "hybrid" in WORKER_MODE:
    print(f"• Policy: {CONCURRENCY_POLICY}")
    print(f"• ComfyUI Drive Path: {GDRIVE_COMFY_PATH}")
    print(f"• LLM Drive Path: {GDRIVE_LLM_PATH}")
elif "image" in WORKER_MODE:
    print(f"• ComfyUI Drive Path: {GDRIVE_COMFY_PATH}")
elif "llm" in WORKER_MODE:
    print(f"• LLM RP Model: {LLM_RP_MODEL}")
    print(f"• LLM Util Model: {LLM_UTIL_MODEL}")
"""
    return [line + "\n" for line in code.split("\n")[:-1]]


def update_cell_4_source(existing_lines: list[str]) -> list[str]:
    content = "".join(existing_lines)

    # 1. Ensure huggingface_hub and psutil are in extra_packages
    if '"huggingface_hub"' not in content:
        content = content.replace(
            '"hydra-core", "iopath"',
            '"hydra-core", "iopath", "huggingface_hub", "psutil"',
        )

    # 2. Add RAM cache directory setup and ComfyUI extra_model_paths.yaml before "Environment setup complete!"
    ram_cache_setup = """
# 5. Initialize High-Speed System RAM Cache & ComfyUI Extra Paths
ram_cache_dir = "/dev/shm/tnh_ram_cache"
os.makedirs(ram_cache_dir, exist_ok=True)
os.makedirs(f"{ram_cache_dir}/checkpoints", exist_ok=True)
os.makedirs(f"{ram_cache_dir}/loras", exist_ok=True)
os.makedirs(f"{ram_cache_dir}/vae", exist_ok=True)
os.makedirs(f"{ram_cache_dir}/llm", exist_ok=True)

if mode_key in ("hybrid", "model"):
    comfy_dir = "/content/ComfyUI"
    extra_paths_file = f"{comfy_dir}/extra_model_paths.yaml"
    extra_paths_content = f\"\"\"
tnh_ram_cache:
    base_path: {ram_cache_dir}
    checkpoints: checkpoints
    loras: loras
    vae: vae
\"\"\"
    try:
        with open(extra_paths_file, "w") as f:
            f.write(extra_paths_content.strip() + "\\n")
        print(f"⚡ Configured high-speed RAM cache at {ram_cache_dir} (extra_model_paths.yaml active).")
    except Exception as e:
        print(f"⚠️ Could not write extra_model_paths.yaml: {e}")

print("\\n🎉 Environment setup complete!")
"""
    if "tnh_ram_cache" not in content:
        content = content.replace('print("\n🎉 Environment setup complete!")', ram_cache_setup.strip())

    return [line + "\n" for line in content.split("\n")[:-1]]


def build_cell_5_source() -> list[str]:
    code = """#@title 5. 🚀 Launch Worker & Start Networking
import os
import sys
import time
import re
import secrets
import subprocess
from IPython.display import display, HTML

mode_key = "hybrid" if "hybrid" in WORKER_MODE else ("model" if "image" in WORKER_MODE else ("llm" if "llm" in WORKER_MODE else "tts"))
tunnel_key = "netbird" if "netbird" in TUNNEL_METHOD else "cloudflared"
policy_key = "auto" if "auto" in CONCURRENCY_POLICY else ("exclusive" if "exclusive" in CONCURRENCY_POLICY else ("semi_concurrent" if "semi_concurrent" in CONCURRENCY_POLICY else "concurrent"))
gdrive_root = "/content/drive/MyDrive/tnhcomfy"
os.makedirs(gdrive_root, exist_ok=True)

# 1. Persistent Agent Service Token
token_file = os.path.join(gdrive_root, ".agent-token")
if os.path.exists(token_file):
    with open(token_file, "r") as f:
        agent_token = f.read().strip()
else:
    agent_token = secrets.token_urlsafe(32)
    with open(token_file, "w") as f:
        f.write(agent_token)
os.environ["REMOTE_AGENT_TOKEN"] = agent_token

agent_dir = "/content/tnhcomfy/remote_agent"
scratch_downloads = "/content/tmp_downloads"
os.makedirs(scratch_downloads, exist_ok=True)
log_comfy = "/content/comfyui.log"
log_agent = "/content/agent.log"
log_llm = "/content/llama_server.log"
comfy_port = 8188
agent_port = 8001 if mode_key in ("model", "hybrid") else (8003 if mode_key == "llm" else 8002)
llm_port = 8003

# 2. Sync Model Catalog with Backend (Sole Source of Truth)
catalog = {}
catalog_source = "local models.json"
backend_sync_ok = False
backend_url_clean = BACKEND_URL.strip().rstrip("/")

if backend_url_clean:
    try:
        import urllib.request
        import json
        cat_endpoint = f"{backend_url_clean}/api/v2/models/catalog"
        req = urllib.request.Request(cat_endpoint, headers={"Accept": "application/json"})
        with urllib.request.urlopen(req, timeout=5) as resp:
            if resp.status == 200:
                catalog = json.loads(resp.read().decode())
                backend_sync_ok = True
                catalog_source = f"backend ({backend_url_clean})"
    except Exception as exc:
        print(f"⚠️ Notice: Could not contact backend catalog at {backend_url_clean} ({exc}). Using local catalog.")

if not catalog:
    import json
    local_cat = "/content/tnhcomfy/backend_v2/modal_llm/models.json"
    if os.path.exists(local_cat):
        with open(local_cat, "r") as f:
            catalog = json.load(f)

models_dict = catalog.get("models", {})
active_spec = catalog.get("active", {})
active_rp = active_spec.get("rp") or LLM_RP_MODEL
active_util = active_spec.get("util") or LLM_UTIL_MODEL
active_image = active_spec.get("image") or ""
shared_weights = (active_util in ("same_as_rp", active_rp))
distinct_active_llm = [active_rp] if shared_weights else [active_rp, active_util]

print(f"🌐 Model Catalog synced from {catalog_source}:")
print(f"   • Active RP Model:   {active_rp}")
print(f"   • Active Util Model: {active_util} (Shared Weights: {shared_weights})")
if active_image:
    print(f"   • Active Image Model: {active_image}")

# 3. Check & Auto-Download Active LLM GGUF Weights in Google Drive
llm_gdrive_dir = GDRIVE_LLM_PATH.strip() or "/content/drive/MyDrive/tnhcomfy/llm_models"
os.makedirs(llm_gdrive_dir, exist_ok=True)

resolved_weights = {}
for mid in distinct_active_llm:
    spec = models_dict.get(mid, {})
    vol_dir = spec.get("dir") or mid
    gguf_name = spec.get("gguf")
    repo = spec.get("repo")
    mmproj_name = spec.get("mmproj")
    mmproj_repo = spec.get("mmproj_repo") or repo

    target_folder = os.path.join(llm_gdrive_dir, vol_dir)
    os.makedirs(target_folder, exist_ok=True)
    local_gguf = os.path.join(target_folder, gguf_name) if gguf_name else ""

    if not (local_gguf and os.path.exists(local_gguf)):
        if repo and gguf_name:
            print(f"📥 Active LLM weights for [{mid}] not found in Google Drive.")
            print(f"   Downloading {repo} :: {gguf_name} directly to Google Drive...")
            try:
                from huggingface_hub import snapshot_download
                snapshot_download(
                    repo,
                    allow_patterns=[gguf_name],
                    local_dir=target_folder,
                    token=os.environ.get("HF_TOKEN") or None,
                )
                if mmproj_name and not os.path.exists(os.path.join(target_folder, mmproj_name)):
                    snapshot_download(
                        mmproj_repo,
                        allow_patterns=[mmproj_name],
                        local_dir=target_folder,
                        token=os.environ.get("HF_TOKEN") or None,
                    )
                print(f"✅ Successfully downloaded [{mid}] to Google Drive!")
            except Exception as exc:
                print(f"⚠️ HF download error for {mid}: {exc}")
        else:
            print(f"⚠️ Model [{mid}] has no repository metadata in catalog.")

    if local_gguf and os.path.exists(local_gguf):
        resolved_weights[mid] = local_gguf
    else:
        # Fallback candidate scan
        for cdir in [llm_gdrive_dir, "/content/agent-data/llm/models", "/content/ComfyUI/models/llm"]:
            if os.path.exists(cdir):
                for root, _, files in os.walk(cdir):
                    for f in files:
                        if f.endswith(".gguf") and not f.startswith("."):
                            resolved_weights[mid] = os.path.join(root, f)
                            break
                    if mid in resolved_weights:
                        break
            if mid in resolved_weights:
                break

# 4. Tiered RAM Pre-warming (Anchors + Opportunistic Spare RAM)
if agent_dir not in sys.path:
    sys.path.insert(0, agent_dir)
from ram_manager import RamModelManager
ram_mgr = RamModelManager(ram_dir="/dev/shm/tnh_ram_cache", budget_gb=40.0)

anchor_ids = [active_rp]
if not shared_weights:
    anchor_ids.append(active_util)
if active_image:
    anchor_ids.append(active_image)
ram_mgr.set_anchors(anchor_ids)

prewarm_queue = []
for mid in distinct_active_llm:
    if mid in resolved_weights:
        prewarm_queue.append({
            "id": mid,
            "source_path": resolved_weights[mid],
            "role": "rp" if mid == active_rp else "util",
            "is_anchor": True,
        })

comfy_dir = "/content/ComfyUI"
ckpt_dir = f"{comfy_dir}/models/checkpoints"
all_ckpts = []
if os.path.exists(ckpt_dir):
    for root, _, files in os.walk(ckpt_dir):
        for f in files:
            if f.endswith((".safetensors", ".ckpt")):
                all_ckpts.append(os.path.join(root, f))
    all_ckpts.sort(key=lambda x: os.path.getmtime(x), reverse=True)

active_ckpt_path = None
if active_image:
    for c in all_ckpts:
        if active_image.lower() in os.path.basename(c).lower():
            active_ckpt_path = c
            break
if not active_ckpt_path and all_ckpts:
    active_ckpt_path = all_ckpts[0]

if active_ckpt_path:
    img_id = os.path.basename(active_ckpt_path)
    prewarm_queue.append({
        "id": img_id,
        "source_path": active_ckpt_path,
        "role": "image",
        "is_anchor": True,
    })
    anchor_ids.append(img_id)
    ram_mgr.set_anchors(anchor_ids)

# Opportunistic: Most recently used secondary checkpoint & recent LoRAs
if len(all_ckpts) > 1:
    sec_ckpt = all_ckpts[1] if all_ckpts[0] == active_ckpt_path else all_ckpts[0]
    prewarm_queue.append({
        "id": os.path.basename(sec_ckpt),
        "source_path": sec_ckpt,
        "role": "image_secondary",
        "is_anchor": False,
    })

lora_dir = f"{comfy_dir}/models/loras"
if os.path.exists(lora_dir):
    all_loras = []
    for root, _, files in os.walk(lora_dir):
        for f in files:
            if f.endswith((".safetensors", ".ckpt")):
                all_loras.append(os.path.join(root, f))
    all_loras.sort(key=lambda x: os.path.getmtime(x), reverse=True)
    for l in all_loras[:2]:
        prewarm_queue.append({
            "id": os.path.basename(l),
            "source_path": l,
            "role": "lora",
            "is_anchor": False,
        })

print("⚡ Pre-warming Models into High-Speed System RAM (/dev/shm)...")
prewarmed_ids = ram_mgr.prewarm_models(prewarm_queue)
ram_status = ram_mgr.get_status()
print(f"✅ RAM Cache Ready: {ram_status['used_gb']} GB / {ram_status['budget_gb']} GB used ({ram_status['percent_used']}%)")
print(f"   • Anchors in RAM: {[a['model_id'] for a in ram_status['anchor_models']]}")
if ram_status['spare_cached_models']:
    print(f"   • Spare Pre-warmed Models: {[s['model_id'] for s in ram_status['spare_cached_models']]}")

# 5. Launch Background Processes
if mode_key == "hybrid":
    print("🚀 [Hybrid] Starting ComfyUI server on :8188...")
    with open(log_comfy, "w") as out:
        env_comfy = dict(os.environ, PYTORCH_CUDA_ALLOC_CONF="expandable_segments:True", PYTHONUNBUFFERED="1")
        subprocess.Popen([sys.executable, f"{comfy_dir}/main.py", "--listen", "127.0.0.1", "--port", str(comfy_port)], env=env_comfy, stdout=out, stderr=out)

    print(f"🚀 [Hybrid] Starting Remote Storage Agent on :{agent_port} (DATA_DIR={comfy_dir})...")
    env_agent = dict(
        os.environ,
        DATA_DIR=comfy_dir,
        WORKER_MODE="hybrid",
        PORT=str(agent_port),
        HOST="127.0.0.1",
        LLM_UPSTREAM_BASE=f"http://127.0.0.1:{llm_port}/v1",
        RAM_CACHE_DIR="/dev/shm/tnh_ram_cache",
        RAM_CACHE_BUDGET_GB="40",
        PYTHONUNBUFFERED="1",
        PROVIDER_DOWNLOAD_SCRATCH_DIR=scratch_downloads,
        REMOTE_AGENT_DOWNLOAD_MAX_CONCURRENT="1",
        LD_LIBRARY_PATH="/usr/local/llama.cpp:/usr/local/lib:" + os.environ.get("LD_LIBRARY_PATH", ""),
        PATH="/usr/local/llama.cpp:/usr/local/bin:" + os.environ.get("PATH", ""),
    )
    with open(log_agent, "w") as out:
        subprocess.Popen([sys.executable, f"{agent_dir}/server.py"], cwd=agent_dir, env=env_agent, stdout=out, stderr=out)

    print(f"🚀 [Hybrid] Starting CUDA llama-server on :{llm_port}...")
    rp_ram_file = ""
    if active_rp in ram_mgr.entries:
        rp_ram_file = ram_mgr.entries[active_rp].ram_path
    elif active_rp in resolved_weights:
        rp_ram_file = resolved_weights[active_rp]

    llama_args = ["llama-server", "--port", str(llm_port), "--host", "127.0.0.1", "-ngl", "99", "--jinja"]
    if rp_ram_file and os.path.exists(rp_ram_file):
        print(f"  🧠 Loading RAM-cached GGUF: {os.path.basename(rp_ram_file)} (sub-second VRAM transfer)")
        llama_args.extend(["-m", rp_ram_file, "--alias", active_rp, "--alias", "default"])
        if shared_weights and active_util != active_rp:
            llama_args.extend(["--alias", active_util])
    else:
        print("  🧠 Auto-loading Qwen2.5-1.5B via Hugging Face...")
        llama_args.extend(["--hf-repo", "Qwen/Qwen2.5-1.5B-Instruct-GGUF", "--hf-file", "qwen2.5-1.5b-instruct-q4_k_m.gguf", "--alias", "default"])

    env_llm = dict(
        os.environ,
        LD_LIBRARY_PATH="/usr/local/llama.cpp:/usr/local/lib:" + os.environ.get("LD_LIBRARY_PATH", ""),
        PATH="/usr/local/llama.cpp:/usr/local/bin:" + os.environ.get("PATH", ""),
        PYTHONUNBUFFERED="1",
    )
    with open(log_llm, "w") as out:
        proc_llm = subprocess.Popen(llama_args, env=env_llm, stdout=out, stderr=out)

elif mode_key == "model":
    print("🚀 Starting ComfyUI server on :8188...")
    with open(log_comfy, "w") as out:
        env_comfy = dict(os.environ, PYTORCH_CUDA_ALLOC_CONF="expandable_segments:True", PYTHONUNBUFFERED="1")
        subprocess.Popen([sys.executable, f"{comfy_dir}/main.py", "--listen", "127.0.0.1", "--port", str(comfy_port)], env=env_comfy, stdout=out, stderr=out)

    print(f"🚀 Starting Remote Agent on :{agent_port} (DATA_DIR={comfy_dir})...")
    env = dict(
        os.environ,
        DATA_DIR=comfy_dir,
        WORKER_MODE="model",
        PORT=str(agent_port),
        HOST="127.0.0.1",
        RAM_CACHE_DIR="/dev/shm/tnh_ram_cache",
        RAM_CACHE_BUDGET_GB="40",
        PYTHONUNBUFFERED="1",
        PROVIDER_DOWNLOAD_SCRATCH_DIR=scratch_downloads,
        REMOTE_AGENT_DOWNLOAD_MAX_CONCURRENT="1",
    )
    with open(log_agent, "w") as out:
        subprocess.Popen([sys.executable, f"{agent_dir}/server.py"], cwd=agent_dir, env=env, stdout=out, stderr=out)

elif mode_key == "llm":
    llm_dir = "/content/agent-data/llm/models"
    print(f"🚀 Starting Remote LLM Agent on :{agent_port}...")
    env = dict(
        os.environ,
        DATA_DIR=llm_dir,
        LLM_DATA_DIR=llm_dir,
        WORKER_MODE="llm",
        PORT=str(agent_port),
        HOST="127.0.0.1",
        RAM_CACHE_DIR="/dev/shm/tnh_ram_cache",
        RAM_CACHE_BUDGET_GB="40",
        PYTHONUNBUFFERED="1",
        PROVIDER_DOWNLOAD_SCRATCH_DIR=scratch_downloads,
        REMOTE_AGENT_DOWNLOAD_MAX_CONCURRENT="1",
    )
    with open(log_agent, "w") as out:
        subprocess.Popen([sys.executable, f"{agent_dir}/server.py"], cwd=agent_dir, env=env, stdout=out, stderr=out)

elif mode_key == "tts":
    tts_dir = "/content/agent-data/tts"
    os.makedirs(tts_dir, exist_ok=True)
    print(f"🚀 Starting Remote TTS Agent on :{agent_port}...")
    env = dict(
        os.environ,
        TTS_DATA_DIR=tts_dir,
        WORKER_MODE="tts",
        PORT=str(agent_port),
        HOST="127.0.0.1",
        PYTHONUNBUFFERED="1",
        PROVIDER_DOWNLOAD_SCRATCH_DIR=scratch_downloads,
        REMOTE_AGENT_DOWNLOAD_MAX_CONCURRENT="1",
    )
    with open(log_agent, "w") as out:
        subprocess.Popen([sys.executable, f"{agent_dir}/server.py"], cwd=agent_dir, env=env, stdout=out, stderr=out)

# Wait for agent & llama-server healthchecks
print("⏳ Waiting for agent healthcheck...")
for _ in range(40):
    try:
        import urllib.request
        with urllib.request.urlopen(f"http://127.0.0.1:{agent_port}/health", timeout=1) as res:
            if res.status == 200:
                print("✅ Agent is online and healthy!")
                break
    except Exception:
        time.sleep(1)

if mode_key in ("hybrid", "llm"):
    print("⏳ Waiting for llama-server healthcheck...")
    llm_ready = False
    for _ in range(45):
        if "proc_llm" in locals() and proc_llm.poll() is not None:
            print(f"❌ llama-server process exited unexpectedly (code {proc_llm.returncode})!")
            if os.path.exists(log_llm):
                with open(log_llm, "r", errors="replace") as f:
                    print("".join(f.readlines()[-20:]))
            break
        try:
            import urllib.request
            with urllib.request.urlopen(f"http://127.0.0.1:{llm_port}/health", timeout=1) as res:
                if res.status == 200:
                    print("✅ llama-server is online and healthy!")
                    llm_ready = True
                    break
        except Exception:
            time.sleep(1)

# 6. Networking & Tunneling
assigned_ip = ""
public_url = ""

if tunnel_key == "netbird":
    netbird_dir = f"{gdrive_root}/netbird"
    os.makedirs(netbird_dir, exist_ok=True)
    os.makedirs("/var/lib/netbird", exist_ok=True)
    os.makedirs("/var/log/netbird", exist_ok=True)

    # Clean up stale pid/sock
    for p in ["/var/run/netbird.sock", "/var/run/netbird.pid"]:
        if os.path.exists(p):
            try: os.remove(p)
            except Exception: pass

    # Resolve custom management URL
    mgmt_url = NETBIRD_MANAGEMENT_URL.strip()
    if not mgmt_url:
        try:
            from google.colab import userdata
            mgmt_url = userdata.get("NETBIRD_MANAGEMENT_URL", "").strip()
        except Exception: pass

    mgmt_flag = f"--management-url {mgmt_url}" if mgmt_url else ""
    if mgmt_url:
        print(f"🌐 Self-hosted NetBird Management Server: {mgmt_url}")
    else:
        print("🌐 Using default NetBird Cloud (api.netbird.io)")

    # Restore existing NetBird peer credentials from Google Drive
    config_backed_up = os.path.exists(f"{netbird_dir}/config.json")
    if config_backed_up:
        print("🔄 Restoring existing NetBird peer credentials from Google Drive (Static IP preserved!)...")
        for f in os.listdir(netbird_dir):
            src = os.path.join(netbird_dir, f)
            dst = os.path.join("/var/lib/netbird", f)
            try:
                if os.path.isdir(src): shutil.copytree(src, dst, dirs_exist_ok=True)
                else: shutil.copy2(src, dst)
            except Exception: pass

    # Launch daemon in userspace netstack mode
    print("🚀 Starting NetBird daemon in Userspace Netstack mode (bypasses container TUN restrictions)...")
    env_daemon = dict(
        os.environ,
        NB_LOG_FILE="/var/log/netbird/service.log",
        NB_LOG_LEVEL="info",
        NB_WG_KERNEL_DISABLED="true",
        NB_INTERFACE_NAME="wt0",
        NB_NETSTACK_MODE="true",
    )
    with open("/var/log/netbird/daemon.stdout.log", "w") as out:
        subprocess.Popen(["netbird", "service", "run"], env=env_daemon, stdout=out, stderr=out)

    daemon_ready = False
    for _ in range(20):
        time.sleep(1)
        res = subprocess.run(["netbird", "status"], capture_output=True, text=True)
        if "Management:" in res.stdout or "Signal:" in res.stdout or "NeedsLogin" in res.stdout or "Connected" in res.stdout:
            daemon_ready = True
            break

    if daemon_ready:
        print("✅ NetBird daemon is running and responsive in Netstack mode!")
    else:
        print("⚠️ NetBird daemon took longer than expected to start; proceeding with connection attempt.")

    # Bring up connection
    if config_backed_up:
        print("🚀 Bringing up restored NetBird connection...")
        cmd_up = f"netbird up --extra-dns-hosts=false"
        env_up = dict(os.environ, NB_WG_KERNEL_DISABLED="true")
        res_up = subprocess.run(cmd_up, shell=True, env=env_up, capture_output=True, text=True)
        if res_up.returncode != 0:
            print(f"⚠️ Restored connection notice: {res_up.stderr.strip() or res_up.stdout.strip()}")
    else:
        setup_key = NETBIRD_SETUP_KEY.strip()
        if not setup_key:
            try:
                from google.colab import userdata
                setup_key = userdata.get("NETBIRD_SETUP_KEY", "").strip()
            except Exception: pass

        if not setup_key:
            print("❌ Error: NETBIRD_SETUP_KEY was not provided!")
        else:
            print("🔑 Registering new NetBird peer key...")
            cmd_up = f"netbird up --setup-key {setup_key} {mgmt_flag} --extra-dns-hosts=false"
            env_up = dict(os.environ, NB_WG_KERNEL_DISABLED="true")
            res_up = subprocess.run(cmd_up, shell=True, env=env_up, capture_output=True, text=True)
            if res_up.returncode == 0:
                print("✅ Peer registered! Backing up credentials to Google Drive for permanent static IP...")
                for f in os.listdir("/var/lib/netbird"):
                    src = os.path.join("/var/lib/netbird", f)
                    dst = os.path.join(netbird_dir, f)
                    try:
                        if os.path.isdir(src): shutil.copytree(src, dst, dirs_exist_ok=True)
                        else: shutil.copy2(src, dst)
                    except Exception: pass
                print(f"💾 NetBird credentials securely saved to {netbird_dir}")

    # Wait for IP
    print("⏳ Waiting for NetBird IP assignment...")
    for _ in range(30):
        time.sleep(1)
        res = subprocess.run(["netbird", "status"], capture_output=True, text=True)
        out = res.stdout
        m = re.search(r"NetBird IP:\s*([0-9a-fA-F\.\:]+)", out)
        if m:
            assigned_ip = m.group(1).split("/")[0].strip()
            break
        m2 = re.search(r"IP:\s*([0-9a-fA-F\.\:]+)", out)
        if m2:
            assigned_ip = m2.group(1).split("/")[0].strip()
            break

    if assigned_ip:
        print(f"✅ Connected to NetBird Mesh with Static IP: {assigned_ip}")
    else:
        print("⚠️ NetBird status details:")
        res = subprocess.run(["netbird", "status", "--detail"], capture_output=True, text=True)
        print(res.stdout or res.stderr)

elif tunnel_key == "cloudflared":
    print("🌐 Starting Cloudflare Named / Quick Tunnel...")
    cf_log = "/content/cloudflared.log"
    target_tunnel_port = comfy_port if mode_key == "model" else agent_port
    with open(cf_log, "w") as out:
        subprocess.Popen(["cloudflared", "tunnel", "--url", f"http://127.0.0.1:{target_tunnel_port}", "--no-autoupdate"], stdout=out, stderr=out)
    
    for _ in range(40):
        time.sleep(1)
        if os.path.exists(cf_log):
            with open(cf_log, "r") as f:
                content = f.read()
                m = re.search(r"https://[a-zA-Z0-9-]+\.trycloudflare\.com", content)
                if m:
                    public_url = m.group(0)
                    break
    if public_url:
        print(f"✅ Cloudflare Tunnel is live: {public_url}")
    else:
        print("⚠️ Could not extract Cloudflare URL; check /content/cloudflared.log.")

# 7. Worker Credentials & Visual Banner
provider_category = "Hybrid" if mode_key == "hybrid" else ("Image" if mode_key == "model" else ("LLM" if mode_key == "llm" else "TTS"))
provider_type = "remote_hybrid" if mode_key == "hybrid" else ("remote_comfy" if mode_key == "model" else ("remote_llm" if mode_key == "llm" else "remote_tts"))

if tunnel_key == "netbird" and assigned_ip:
    base_endpoint = f"http://{assigned_ip}"
    comfy_endpoint = f"http://{assigned_ip}:{comfy_port}"
    agent_endpoint = f"http://{assigned_ip}:{agent_port}"
    llm_endpoint = f"http://{assigned_ip}:{llm_port}"
elif public_url:
    base_endpoint = public_url
    comfy_endpoint = public_url if mode_key == "model" else ""
    agent_endpoint = public_url
    llm_endpoint = public_url if mode_key == "llm" else ""
else:
    base_endpoint = "http://<YOUR_IP>"
    comfy_endpoint = f"http://<YOUR_IP>:{comfy_port}"
    agent_endpoint = f"http://<YOUR_IP>:{agent_port}"
    llm_endpoint = f"http://<YOUR_IP>:{llm_port}"

def _copy_btn(text):
    return f'''<button onclick="navigator.clipboard.writeText('{text}').then(() => {{ this.innerText = '✅ Copied!'; setTimeout(() => this.innerText = '📋 Copy', 2000); }})" style="background: #2563eb; color: white; border: none; padding: 4px 10px; border-radius: 4px; font-size: 11px; cursor: pointer; font-weight: bold;">📋 Copy</button>'''

rows_html = f'''
<tr><td style="padding: 8px 12px; font-weight: 600; color: #475569;">Provider Category & Type</td><td style="padding: 8px 12px; font-family: monospace; color: #0f172a;"><b>{provider_category}</b> &rarr; <code>{provider_type}</code></td><td style="padding: 8px 12px;"></td></tr>
'''

if mode_key == "hybrid":
    rows_html += f'''
<tr><td style="padding: 8px 12px; font-weight: 600; color: #475569;">Unified Base URL (base_url)</td><td style="padding: 8px 12px; font-family: monospace; color: #0f172a;">{base_endpoint}</td><td style="padding: 8px 12px;">{_copy_btn(base_endpoint)}</td></tr>
<tr><td style="padding: 8px 12px; font-weight: 600; color: #475569;">ComfyUI Server URL (comfy_url)</td><td style="padding: 8px 12px; font-family: monospace; color: #0f172a;">{comfy_endpoint}</td><td style="padding: 8px 12px;">{_copy_btn(comfy_endpoint)}</td></tr>
<tr><td style="padding: 8px 12px; font-weight: 600; color: #475569;">Remote Agent URL (agent_url)</td><td style="padding: 8px 12px; font-family: monospace; color: #0f172a;">{agent_endpoint}</td><td style="padding: 8px 12px;">{_copy_btn(agent_endpoint)}</td></tr>
<tr><td style="padding: 8px 12px; font-weight: 600; color: #475569;">LLM Server URL (llm_url)</td><td style="padding: 8px 12px; font-family: monospace; color: #0f172a;">{llm_endpoint}</td><td style="padding: 8px 12px;">{_copy_btn(llm_endpoint)}</td></tr>
<tr><td style="padding: 8px 12px; font-weight: 600; color: #475569;">Hardware Concurrency Policy</td><td style="padding: 8px 12px; font-family: monospace; color: #0f172a;"><b>{policy_key}</b></td><td style="padding: 8px 12px;"></td></tr>
'''
elif mode_key == "model":
    rows_html += f'''
<tr><td style="padding: 8px 12px; font-weight: 600; color: #475569;">ComfyUI Server URL (comfy_url)</td><td style="padding: 8px 12px; font-family: monospace; color: #0f172a;">{comfy_endpoint}</td><td style="padding: 8px 12px;">{_copy_btn(comfy_endpoint)}</td></tr>
<tr><td style="padding: 8px 12px; font-weight: 600; color: #475569;">Remote Storage Agent URL (agent_url)</td><td style="padding: 8px 12px; font-family: monospace; color: #0f172a;">{agent_endpoint}</td><td style="padding: 8px 12px;">{_copy_btn(agent_endpoint)}</td></tr>
'''
elif mode_key == "llm":
    rows_html += f'''
<tr><td style="padding: 8px 12px; font-weight: 600; color: #475569;">Remote LLM Base URL (base_url)</td><td style="padding: 8px 12px; font-family: monospace; color: #0f172a;">{agent_endpoint}</td><td style="padding: 8px 12px;">{_copy_btn(agent_endpoint)}</td></tr>
'''
elif mode_key == "tts":
    rows_html += f'''
<tr><td style="padding: 8px 12px; font-weight: 600; color: #475569;">Remote TTS Base URL (base_url)</td><td style="padding: 8px 12px; font-family: monospace; color: #0f172a;">{agent_endpoint}</td><td style="padding: 8px 12px;">{_copy_btn(agent_endpoint)}</td></tr>
'''

rows_html += f'''
<tr><td style="padding: 8px 12px; font-weight: 600; color: #475569;">Remote Agent Token (agent_token)</td><td style="padding: 8px 12px; font-family: monospace; color: #0f172a;">{agent_token}</td><td style="padding: 8px 12px;">{_copy_btn(agent_token)}</td></tr>
'''

ram_badge = f'''
<div style="background: #f8fafc; border: 1px solid #e2e8f0; border-radius: 8px; padding: 12px 16px; margin: 12px 0; font-size: 13px;">
  <span style="font-weight: 700; color: #0f172a;">⚡ High-Speed RAM Cache Status:</span>
  <span style="color: #2563eb; font-weight: 600; margin-left: 8px;">{ram_status['used_gb']} GB / {ram_status['budget_gb']} GB ({ram_status['percent_used']}%)</span>
  <div style="margin-top: 6px; color: #64748b; font-size: 12px;">
    <b>Pinned Anchors (Protected):</b> {", ".join([a["model_id"] for a in ram_status["anchor_models"]]) or "None"}
  </div>
</div>
'''

banner_html = f'''
<div style="background: #ffffff; border: 1px solid #cbd5e1; border-radius: 12px; padding: 20px; font-family: -apple-system, BlinkMacSystemFont, 'Segoe UI', Roboto, Helvetica, Arial, sans-serif; box-shadow: 0 4px 12px rgba(0,0,0,0.06); max-width: 820px; margin: 16px 0;">
  <div style="display: flex; align-items: center; justify-content: space-between; border-bottom: 2px solid #e2e8f0; padding-bottom: 12px; margin-bottom: 14px;">
    <h3 style="margin: 0; color: #0f172a; font-size: 18px; font-weight: 700;">✨ TNHComfy Colab Worker is Ready! ({provider_category} Mode)</h3>
    <span style="background: #22c55e; color: white; padding: 3px 10px; border-radius: 20px; font-size: 11px; font-weight: bold; text-transform: uppercase;">● Online</span>
  </div>
  <p style="color: #64748b; margin: 0 0 12px 0; font-size: 13px;">Your worker is online, connected, and primed. Copy the credentials below into your TNHComfy Providers page:</p>
  {ram_badge}
  <table style="width: 100%; border-collapse: collapse; font-size: 13px; text-align: left; background: #f8fafc; border-radius: 8px; overflow: hidden;">
    {rows_html}
  </table>
  <div style="margin-top: 14px; padding: 10px 14px; background: #ecfdf5; border-left: 4px solid #10b981; border-radius: 4px; font-size: 12px; color: #065f46;">
    <b>💡 Static Configuration:</b> Because your NetBird state and token are saved in Google Drive, the IP and token above are permanent. You do not need to reconfigure the TNHComfy provider on subsequent restarts.
  </div>
</div>
'''
display(HTML(banner_html))

# 8. Live Background Streaming Monitor
print("\n👀 Streaming service logs (Ctrl+C or interrupt cell anytime to stop streaming; processes will stay running):")
try:
    with open(log_agent, "r") as fa:
        fa.seek(0, 2)
        while True:
            line_a = fa.readline()
            if line_a:
                print(f"[Agent] {line_a.rstrip()}")
            time.sleep(0.5)
except KeyboardInterrupt:
    print("\n🛑 Stopped live log monitor. Your background services are still running happily!")
"""
    return [line + "\n" for line in code.split("\n")[:-1]]


def build_cell_6_source() -> list[str]:
    code = """#@title 6. 📥 (Optional) Live Models-in-RAM Dashboard & Model Manager
#@markdown Manage, view high-speed RAM cache residency, or pre-warm models on the fly:

OPERATION = "📊 View Models-in-RAM Dashboard & Status" #@param ["📊 View Models-in-RAM Dashboard & Status", "⚡ Pre-Warm Model into RAM Cache", "🧹 Evict Model from RAM Cache", "📥 Download Model from URL", "🔍 List Checkpoints in Google Drive"]
MODEL_OR_CHECKPOINT_FILTER = "" #@param {type:"string"}
DOWNLOAD_TARGET = "ComfyUI Checkpoint" #@param ["ComfyUI Checkpoint", "ComfyUI LoRA", "ComfyUI VAE", "LLM GGUF Model"]
DOWNLOAD_URL = "" #@param {type:"string"}
FILENAME_OVERRIDE = "" #@param {type:"string"}

import os
import sys
import time
import shutil
import subprocess
from IPython.display import display, HTML

agent_dir = "/content/tnhcomfy/remote_agent"
if agent_dir not in sys.path:
    sys.path.insert(0, agent_dir)
from ram_manager import get_ram_manager
ram_mgr = get_ram_manager()

comfy_dir = "/content/ComfyUI"
ckpt_dir = f"{comfy_dir}/models/checkpoints"
lora_dir = f"{comfy_dir}/models/loras"
llm_dir = GDRIVE_LLM_PATH.strip() or "/content/drive/MyDrive/tnhcomfy/llm_models"

if OPERATION == "📊 View Models-in-RAM Dashboard & Status":
    status = ram_mgr.get_status()
    anchors_html = ""
    for a in status["anchor_models"]:
        anchors_html += f"<tr><td style='padding: 6px 10px;'>🔒 <b>{a['model_id']}</b></td><td style='padding: 6px 10px;'><code>{a['role']}</code></td><td style='padding: 6px 10px;'>{a['size_mb']} MB</td><td style='padding: 6px 10px;'>Pinned Anchor</td></tr>"
    
    spare_html = ""
    for s in status["spare_cached_models"]:
        spare_html += f"<tr><td style='padding: 6px 10px;'>⚡ {s['model_id']}</td><td style='padding: 6px 10px;'><code>{s['role']}</code></td><td style='padding: 6px 10px;'>{s['size_mb']} MB</td><td style='padding: 6px 10px;'>{s['last_used_ago_s']}s ago (LRU)</td></tr>"

    dash_html = f'''
    <div style="font-family: -apple-system, BlinkMacSystemFont, 'Segoe UI', Roboto, sans-serif; background: #ffffff; border: 1px solid #cbd5e1; border-radius: 10px; padding: 16px; max-width: 760px;">
      <h3 style="margin: 0 0 10px 0; color: #0f172a;">⚡ Models-in-RAM Live Dashboard</h3>
      <div style="display: flex; gap: 16px; margin-bottom: 12px;">
        <div style="background: #f1f5f9; padding: 10px 14px; border-radius: 6px; flex: 1;">
          <div style="color: #64748b; font-size: 11px; font-weight: 600;">RAM CACHE BUDGET</div>
          <div style="font-size: 18px; font-weight: 700; color: #0f172a;">{status['used_gb']} / {status['budget_gb']} GB <span style="font-size: 13px; color: #2563eb;">({status['percent_used']}%)</span></div>
        </div>
        <div style="background: #f1f5f9; padding: 10px 14px; border-radius: 6px; flex: 1;">
          <div style="color: #64748b; font-size: 11px; font-weight: 600;">SYSTEM RAM (HOST)</div>
          <div style="font-size: 18px; font-weight: 700; color: #0f172a;">{status['system_ram']['available_gb']} GB avail <span style="font-size: 13px; color: #64748b;">({status['system_ram']['total_gb']} GB total)</span></div>
        </div>
        <div style="background: #f1f5f9; padding: 10px 14px; border-radius: 6px; flex: 1;">
          <div style="color: #64748b; font-size: 11px; font-weight: 600;">RESIDENT MODELS</div>
          <div style="font-size: 18px; font-weight: 700; color: #0f172a;">{status['models_count']} models</div>
        </div>
      </div>
      <table style="width: 100%; border-collapse: collapse; font-size: 12px; margin-top: 8px;">
        <thead><tr style="background: #e2e8f0; color: #334155; text-align: left;"><th style="padding: 6px 10px;">Model ID</th><th style="padding: 6px 10px;">Role</th><th style="padding: 6px 10px;">Size</th><th style="padding: 6px 10px;">Residency</th></tr></thead>
        <tbody>
          {anchors_html}
          {spare_html}
        </tbody>
      </table>
    </div>
    '''
    display(HTML(dash_html))

elif OPERATION == "⚡ Pre-Warm Model into RAM Cache":
    filter_str = MODEL_OR_CHECKPOINT_FILTER.strip().lower()
    candidate_file = None
    role = "image"

    all_files = []
    for d, r in [(ckpt_dir, "image"), (lora_dir, "lora"), (llm_dir, "llm")]:
        if os.path.exists(d):
            for root, _, files in os.walk(d):
                for f in files:
                    if f.endswith((".safetensors", ".ckpt", ".gguf")):
                        all_files.append((os.path.join(root, f), r))

    if filter_str:
        for p, r in all_files:
            if filter_str in os.path.basename(p).lower():
                candidate_file, role = p, r
                break
    elif all_files:
        all_files.sort(key=lambda x: os.path.getmtime(x[0]), reverse=True)
        candidate_file, role = all_files[0]

    if candidate_file and os.path.exists(candidate_file):
        mid = os.path.basename(candidate_file)
        sz_mb = os.path.getsize(candidate_file) / (1024 * 1024)
        print(f"⚡ Pre-warming '{mid}' ({sz_mb:.1f} MB) into RAM cache...")
        t0 = time.time()
        ram_p = ram_mgr.ensure_in_ram(candidate_file, model_id=mid, role=role, is_anchor=False)
        dt = max(time.time() - t0, 0.05)
        print(f"✅ Pre-warmed into RAM ({ram_p}) in {dt:.2f}s ({sz_mb / dt:.1f} MB/s)!")
    else:
        print("⚠️ No matching model file found to pre-warm.")

elif OPERATION == "🧹 Evict Model from RAM Cache":
    filter_str = MODEL_OR_CHECKPOINT_FILTER.strip().lower()
    if not filter_str:
        print("Please enter a model ID or keyword in MODEL_OR_CHECKPOINT_FILTER to evict.")
    else:
        target_mid = None
        for mid in ram_mgr.entries:
            if filter_str in mid.lower():
                target_mid = mid
                break
        if target_mid:
            ok = ram_mgr.evict_model(target_mid, force=True)
            if ok:
                print(f"✅ Successfully evicted '{target_mid}' from RAM cache.")
            else:
                print(f"⚠️ Could not evict '{target_mid}'.")
        else:
            print(f"⚠️ '{filter_str}' is not currently in RAM cache.")

elif OPERATION == "🔍 List Checkpoints in Google Drive":
    if os.path.exists(ckpt_dir):
        ckpts = []
        for root, _, files in os.walk(ckpt_dir):
            for f in files:
                if f.endswith((".safetensors", ".ckpt")):
                    ckpts.append(os.path.join(root, f))
        print(f"📂 Found {len(ckpts)} checkpoint(s) in {ckpt_dir}:")
        for c in sorted(ckpts):
            mb = os.path.getsize(c) / (1024 * 1024)
            rel = os.path.relpath(c, ckpt_dir)
            in_ram = "⚡ [IN RAM]" if ram_mgr.is_cached(os.path.basename(c)) else ""
            print(f"  • {rel} ({mb:.1f} MB) {in_ram}")
    else:
        print(f"⚠️ Checkpoint directory not found: {ckpt_dir}")

elif OPERATION == "📥 Download Model from URL":
    if DOWNLOAD_URL.strip():
        if "LLM" in DOWNLOAD_TARGET:
            dest_dir = llm_dir
        elif "Checkpoint" in DOWNLOAD_TARGET:
            dest_dir = ckpt_dir
        elif "LoRA" in DOWNLOAD_TARGET:
            dest_dir = lora_dir
        else:
            dest_dir = f"{comfy_dir}/models/vae"

        os.makedirs(dest_dir, exist_ok=True)
        fname = FILENAME_OVERRIDE.strip() or DOWNLOAD_URL.split("/")[-1].split("?")[0]
        scratch_dir = "/content/tmp_downloads"
        os.makedirs(scratch_dir, exist_ok=True)
        scratch_path = os.path.join(scratch_dir, fname)
        final_path = os.path.join(dest_dir, fname)

        print(f"📥 High-speed streaming '{fname}' to local scratch ({scratch_path})...")
        subprocess.run(f"curl -fL '{DOWNLOAD_URL.strip()}' -o '{scratch_path}'", shell=True, check=True)
        if os.path.exists(scratch_path) and os.path.getsize(scratch_path) > 1000:
            print(f"📦 Safely copying to Google Drive ({final_path})...")
            dst_tmp = f"{final_path}.publishing"
            shutil.copyfile(scratch_path, dst_tmp)
            os.replace(dst_tmp, final_path)
            os.remove(scratch_path)
            print(f"✅ Successfully downloaded and saved to Google Drive: {final_path}!")
            # Automatically pre-warm into RAM
            try:
                ram_mgr.ensure_in_ram(final_path, model_id=fname, is_anchor=False)
                print(f"⚡ Also pre-warmed '{fname}' into High-Speed RAM!")
            except Exception as e:
                print(f"⚠️ Could not pre-warm to RAM: {e}")
        else:
            print("⚠️ Download was empty or failed.")
    else:
        print("Please enter a valid DOWNLOAD_URL.")
"""
    return [line + "\n" for line in code.split("\n")[:-1]]


def update_notebook(path: Path) -> None:
    print(f"Updating {path}...")
    with open(path, "r", encoding="utf-8") as f:
        nb = json.load(f)

    # Cell 2: Configuration
    nb["cells"][2]["source"] = build_cell_2_source()

    # Cell 4: Dependencies and RAM directory
    nb["cells"][4]["source"] = update_cell_4_source(nb["cells"][4]["source"])

    # Cell 5: Launch & Sync
    nb["cells"][5]["source"] = build_cell_5_source()

    # Cell 6: Models-in-RAM Dashboard
    nb["cells"][6]["source"] = build_cell_6_source()

    with open(path, "w", encoding="utf-8") as f:
        json.dump(nb, f, indent=1)
    print(f"✅ Successfully updated {path}!")


def main():
    for nb_path in NOTEBOOK_PATHS:
        if nb_path.exists():
            update_notebook(nb_path)
        else:
            print(f"⚠️ Not found: {nb_path}")


if __name__ == "__main__":
    main()
