"""Update TNHComfy_Colab_Worker.ipynb and remote_agent/TNHComfy_Colab_Worker.ipynb

Synchronizes both notebooks with multi-environment support (Google Colab and Modal Sandboxes/Notebooks),
Modal volume comfy-storage integration, low-RAM volume streaming toggle, and multi-GPU device allocation.
"""

import json
import shutil
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parent.parent

NOTEBOOK_PATHS = [
    REPO_ROOT / "TNHComfy_Colab_Worker.ipynb",
    REPO_ROOT / "remote_agent" / "TNHComfy_Colab_Worker.ipynb",
]


def build_cell_1_source() -> list[str]:
    code = """#@title 1. 📂 Environment, Storage & 🔍 GPU Hardware Inspection
import os
import sys
import subprocess

# 1. Automatic Environment & Persistent Storage Detection
IS_COLAB = False
IS_MODAL = False

try:
    import google.colab
    IS_COLAB = True
except Exception:
    pass

if not IS_COLAB:
    if os.path.exists("/mnt/data") or "MODAL_IMAGE_ID" in os.environ or "MODAL_ENVIRONMENT" in os.environ:
        IS_MODAL = True

PERSISTENT_ROOT = ""
if IS_COLAB:
    print("📁 Detected Google Colab environment. Mounting Google Drive for persistence...")
    try:
        from google.colab import drive
        if not os.path.exists("/content/drive/MyDrive"):
            drive.mount("/content/drive")
        PERSISTENT_ROOT = "/content/drive/MyDrive/tnhcomfy"
        os.makedirs(PERSISTENT_ROOT, exist_ok=True)
        print(f"✅ Google Drive mounted successfully at /content/drive/MyDrive (persistence: {PERSISTENT_ROOT})")
    except Exception as e:
        print(f"⚠️ Google Drive mount notice: {e}")
        PERSISTENT_ROOT = "/content/tnhcomfy_storage"
        os.makedirs(PERSISTENT_ROOT, exist_ok=True)
elif IS_MODAL or os.path.exists("/mnt/data"):
    print("⚡ Detected Modal Sandbox / Container environment with persistent Volume!")
    PERSISTENT_ROOT = "/mnt/data/tnhcomfy"
    modal_subdirs = [
        "/mnt/data/tnhcomfy",
        "/mnt/data/tnhcomfy/bin",
        "/mnt/data/tnhcomfy/llm_models",
        "/mnt/data/models",
        "/mnt/data/models/checkpoints",
        "/mnt/data/models/loras",
        "/mnt/data/models/vae",
        "/mnt/data/output",
        "/mnt/data/input",
    ]
    for d in modal_subdirs:
        os.makedirs(d, exist_ok=True)
    print(f"✅ Modal Volume active at /mnt/data (shared with Modal image worker comfy-storage!)")
else:
    print("💻 Detected generic Linux container / cloud VM environment.")
    PERSISTENT_ROOT = os.path.expanduser("~/tnhcomfy_storage")
    os.makedirs(PERSISTENT_ROOT, exist_ok=True)

# 2. GPU Hardware & Multi-GPU Topology Inspection
print("\\n" + "=" * 65)
try:
    import torch
    if torch.cuda.is_available():
        count = torch.cuda.device_count()
        print(f"✅ PyTorch CUDA Available: {count} GPU device(s) detected (CUDA {torch.version.cuda})")
        for i in range(count):
            d_name = torch.cuda.get_device_name(i)
            v_gb = torch.cuda.get_device_properties(i).total_memory / (1024 ** 3)
            print(f"   • [GPU {i}] {d_name} — {v_gb:.1f} GB VRAM")
        if count >= 2:
            print("\\n⚡ Multi-GPU Topology Detected:")
            print("   -> GPU 0: Dedicated to ComfyUI (Image Generation)")
            print("   -> GPU 1: Dedicated to llama-server (LLM) & Laya (Director)")
            print("   -> Parallel Concurrency: Mutual eviction BYPASSED (No switching latency!)")
        else:
            print("⚡ Single GPU Topology: Managed dynamically via cooperative VRAM Arbiter.")
    else:
        print("⚠️ WARNING: No CUDA GPU detected! Ensure GPU acceleration is enabled.")
except Exception as exc:
    print(f"⚠️ PyTorch GPU check notice: {exc}")
print("=" * 65 + "\\n")

subprocess.run(["nvidia-smi"], check=False)
"""
    return [line + "\n" for line in code.split("\n")[:-1]]


def build_cell_2_source() -> list[str]:
    code = """#@title 2. ⚙️ Worker Configuration { run: "client" }
#@markdown Choose your worker mode and networking setup:

WORKER_MODE = "hybrid (all-in-one: image + llm + tts)" #@param ["hybrid (all-in-one: image + llm + tts)", "image (remote_comfy)", "llm (remote_llm)", "tts (remote_tts)"]
TUNNEL_METHOD = "netbird (private mesh VPN)" #@param ["netbird (private mesh VPN)", "cloudflared (free, no setup)", "direct_port (Modal / public IP)"]

#@markdown ---
#@markdown #### ⚡ Concurrency & Hardware Policy:
#@markdown - `auto`: Probes GPU VRAM & count automatically (>=2 GPUs or >=70GB -> concurrent, >=35GB -> semi_concurrent, else exclusive)
#@markdown - `exclusive`: Mutual exclusion on single GPU (Best for L4 24GB / T4)
#@markdown - `concurrent`: Full parallel execution without restrictions (Best for Multi-GPU or A100 80GB)
CONCURRENCY_POLICY = "auto (detect from GPU VRAM & count)" #@param ["auto (detect from GPU VRAM & count)", "exclusive (budget L4/T4)", "semi_concurrent (A100 40GB)", "concurrent (Multi-GPU / A100 80GB)"]

#@markdown ---
#@markdown #### 🧠 System RAM Caching Policy (Models-in-RAM):
#@markdown - `auto`: Automatically uses RAM cache on high-RAM machines (>20GB RAM, e.g. Colab), or direct volume streaming on low-RAM containers (e.g. Modal 12-16GB RAM)
#@markdown - `always`: Force pre-warm into `/dev/shm` (Sub-second VRAM swaps, requires >=32GB system RAM)
#@markdown - `disabled`: Direct NVMe disk streaming (Keeps Modal container RAM bill minimal, 0 MB host RAM waste)
CACHE_IN_RAM_SETTING = "auto (detect RAM capacity)" #@param ["auto (detect RAM capacity)", "always (pre-warm into /dev/shm)", "disabled (direct disk streaming for low RAM)"]

#@markdown ---
#@markdown #### 🌐 NetBird Mesh VPN (Default & Recommended):
#@markdown Your setup key is only needed ONCE. Config will be saved to persistent storage so your IP is static forever:
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
#@markdown #### 🔒 Credentials & Private Repository Access:
#@markdown Enter a GitHub Personal Access Token (PAT) with repo read permissions (or save as GITHUB_TOKEN in Secrets):
GITHUB_TOKEN = "" #@param {type:"string"}
HF_TOKEN = "" #@param {type:"string"}

#@markdown ---
#@markdown #### ⚡ Model Storage & Download Strategy:
#@markdown - `direct_download_fast` (Recommended): Download directly from Hugging Face CDN into local NVMe SSD / RAM (~150-250 MB/s, ~2 min for 20GB). Bypasses slow FUSE throttling!
#@markdown - `persistent_volume`: Download & cache models in persistent storage (Modal Volume or Google Drive).
STORAGE_STRATEGY = "direct_download_fast (recommended: 150+ MB/s from HF)" #@param ["direct_download_fast (recommended: 150+ MB/s from HF)", "persistent_volume (Google Drive / Modal Volume)"]

#@markdown ---
#@markdown #### 🎨 Image / Hybrid Mode — Storage Paths:
MODAL_VOLUME_PATH = "/mnt/data" #@param {type:"string"}
GDRIVE_COMFY_PATH = "/content/drive/MyDrive/comfyui" #@param {type:"string"}

#@markdown ---
#@markdown #### 💬 LLM / Hybrid Mode — Curated Models from models.json:
LLM_RP_MODEL = "artemis_31b_q4" #@param ["artemis_31b_q4", "artemis_31b", "sompoa_26b_a4b", "goetia_26b_a4b", "styletune_v2_26b_a4b", "dark_thoughts_v2_31b", "split_untied_31b", "weirdcompound_24b", "gemma3_12b_heretic", "writers_31b_v2", "gemma4_31b_heretic", "magnum_diamond_24b"]
LLM_UTIL_MODEL = "same_as_rp" #@param ["same_as_rp", "artemis_31b_q4", "artemis_31b", "sompoa_26b_a4b", "gemma3_12b_heretic_util", "gemma4_26b_a4b_heretic_util", "gemma4_31b_heretic_util", "mistral_small_32_it", "qwen2.5_14b"]
GDRIVE_LLM_PATH = "/content/drive/MyDrive/tnhcomfy/llm_models" #@param {type:"string"}

# Unified secret resolution across environment variables and Colab Secrets
def resolve_secret(key_name, current_val=""):
    val = (current_val or "").strip()
    if val:
        return val
    val = os.environ.get(key_name, "").strip()
    if val:
        return val
    try:
        from google.colab import userdata
        val = userdata.get(key_name, "").strip()
        if val:
            return val
    except Exception:
        pass
    return ""

GITHUB_TOKEN = resolve_secret("GITHUB_TOKEN", GITHUB_TOKEN)
NETBIRD_SETUP_KEY = resolve_secret("NETBIRD_SETUP_KEY", NETBIRD_SETUP_KEY)
NETBIRD_MANAGEMENT_URL = resolve_secret("NETBIRD_MANAGEMENT_URL", NETBIRD_MANAGEMENT_URL)
NETBIRD_ADMIN_URL = resolve_secret("NETBIRD_ADMIN_URL", NETBIRD_ADMIN_URL)
BACKEND_URL = resolve_secret("BACKEND_URL", BACKEND_URL)
HF_TOKEN = resolve_secret("HF_TOKEN", HF_TOKEN)
if HF_TOKEN:
    os.environ["HF_TOKEN"] = HF_TOKEN

print("⚙️ Configuration saved!")
print(f"• Mode: {WORKER_MODE}")
print(f"• Network: {TUNNEL_METHOD}")
print(f"• Concurrency Policy: {CONCURRENCY_POLICY}")
print(f"• RAM Caching Policy: {CACHE_IN_RAM_SETTING}")
print(f"• Storage Strategy: {STORAGE_STRATEGY}")
if BACKEND_URL:
    print(f"• Backend Sync: {BACKEND_URL} (Sole source of truth for active models)")
if os.path.exists(MODAL_VOLUME_PATH):
    print(f"• Persistent Volume: {MODAL_VOLUME_PATH} (Modal comfy-storage volume active)")
"""
    return [line + "\n" for line in code.split("\n")[:-1]]


def build_cell_3_source() -> list[str]:
    code = """#@title 3. 📥 Clone / Update TNHComfy Repository
import os
import shutil
import subprocess

workspace_root = "/content" if os.path.exists("/content") else "/root"
repo_dir = os.path.join(workspace_root, "tnhcomfy")
token = GITHUB_TOKEN.strip() if "GITHUB_TOKEN" in locals() else ""

if token:
    clone_url = f"https://x-access-token:{token}@github.com/TheNaha/TNHComfy.git"
else:
    clone_url = "https://github.com/TheNaha/TNHComfy.git"

git_env = dict(os.environ, GIT_TERMINAL_PROMPT="0")

def run_git(cmd, cwd=None):
    res = subprocess.run(cmd, cwd=cwd, env=git_env, capture_output=True, text=True)
    if res.returncode != 0:
        err = res.stderr.strip() or f"Git command failed with code {res.returncode}"
        raise RuntimeError(err)
    return res.stdout

if not os.path.exists(repo_dir):
    print(f"📥 Cloning TNHComfy repository to {repo_dir}...")
    run_git(["git", "clone", "--depth", "1", clone_url, repo_dir])
else:
    print(f"🔄 Updating existing repository at {repo_dir}...")
    lock_file = os.path.join(repo_dir, ".git", "index.lock")
    if os.path.exists(lock_file):
        try: os.remove(lock_file)
        except Exception: pass
    try:
        run_git(["git", "remote", "set-url", "origin", clone_url], cwd=repo_dir)
        run_git(["git", "fetch", "origin", "master"], cwd=repo_dir)
        run_git(["git", "reset", "--hard", "origin/master"], cwd=repo_dir)
    except Exception as e:
        print(f"⚠️ Git update notice ({e}). Re-cloning fresh repository...")
        subprocess.run(["rm", "-rf", repo_dir], check=True)
        run_git(["git", "clone", "--depth", "1", clone_url, repo_dir])

print("✅ TNHComfy workspace ready at:", repo_dir)
"""
    return [line + "\n" for line in code.split("\n")[:-1]]


def build_cell_4_source() -> list[str]:
    code = """#@title 4. 📦 Install Dependencies & Prepare Environment
import os
import sys
import shutil
import urllib.request
import subprocess
from concurrent.futures import ThreadPoolExecutor, as_completed

os.environ["PYTORCH_CUDA_ALLOC_CONF"] = "expandable_segments:True"

mode_key = "hybrid" if "hybrid" in WORKER_MODE else ("model" if "image" in WORKER_MODE else ("llm" if "llm" in WORKER_MODE else "tts"))
tunnel_key = "netbird" if "netbird" in TUNNEL_METHOD else ("cloudflared" if "cloudflared" in TUNNEL_METHOD else "direct")

is_colab = False
try:
    import google.colab
    is_colab = True
except Exception:
    pass

is_modal = os.path.exists("/mnt/data") or ("MODAL_ENVIRONMENT" in os.environ)
workspace_root = "/content" if is_colab else ("/root" if os.path.exists("/root") else os.path.expanduser("~"))

if is_modal:
    persistent_root = "/mnt/data/tnhcomfy"
elif is_colab:
    try:
        from google.colab import drive
        if not os.path.exists("/content/drive/MyDrive"):
            drive.mount("/content/drive")
    except Exception:
        pass
    persistent_root = "/content/drive/MyDrive/tnhcomfy"
else:
    persistent_root = f"{workspace_root}/tnhcomfy_storage"

os.makedirs(persistent_root, exist_ok=True)
gdrive_bin = os.path.join(persistent_root, "bin")
os.makedirs(gdrive_bin, exist_ok=True)

print(f"📦 Setting up environment for {WORKER_MODE} (Storage: {persistent_root})...")

def safe_symlink(source: str, link_name: str):
    # Safely creates a symlink link_name -> source.
    if os.path.islink(link_name):
        try:
            if os.path.realpath(link_name) == os.path.realpath(source):
                return
            os.unlink(link_name)
        except Exception:
            os.unlink(link_name)
    elif os.path.isdir(link_name):
        shutil.rmtree(link_name)
    elif os.path.exists(link_name):
        os.remove(link_name)
    os.makedirs(os.path.dirname(link_name), exist_ok=True)
    os.symlink(source, link_name)

# 0. High-Speed Package Installer (uv) Bootstrap
def bootstrap_uv():
    os.environ["UV_BREAK_SYSTEM_PACKAGES"] = "1"
    os.environ["PIP_BREAK_SYSTEM_PACKAGES"] = "1"
    if shutil.which("uv"):
        return "uv"
    for candidate in ["/usr/local/bin/uv", "/root/.cargo/bin/uv", "/root/.local/bin/uv"]:
        if os.path.exists(candidate) and os.access(candidate, os.X_OK):
            return candidate
    try:
        subprocess.run([sys.executable, "-m", "pip", "install", "--break-system-packages", "-q", "uv"], check=True)
        if shutil.which("uv"):
            return "uv"
    except Exception:
        pass
    return False

USE_UV = bootstrap_uv()

def install_python_packages(req_files=None, packages=None):
    req_files = [f for f in (req_files or []) if os.path.isfile(f)]
    packages = packages or []
    if not req_files and not packages:
        return

    if USE_UV:
        uv_cmd = [USE_UV, "pip", "install", "--system", "--break-system-packages"]
        for r in req_files:
            uv_cmd.extend(["-r", r])
        uv_cmd.extend(packages)
        res = subprocess.run(uv_cmd, capture_output=True, text=True)
        if res.returncode == 0:
            return
    pip_cmd = [sys.executable, "-m", "pip", "install", "--break-system-packages", "-q"]
    for r in req_files:
        pip_cmd.extend(["-r", r])
    pip_cmd.extend(packages)
    subprocess.run(pip_cmd, check=False)

# 1. Install Base Remote Agent & Networking Dependencies
print("⚡ Installing Remote Agent core packages...")
core_pkgs = ["fastapi", "uvicorn", "httpx", "websockets", "pydantic", "psutil", "pysocks", "huggingface_hub", "hydra-core", "iopath"]
install_python_packages(packages=core_pkgs)

# 2. Setup Tunnel Clients
if tunnel_key == "netbird":
    if not shutil.which("netbird"):
        print("🌐 Installing NetBird CLI...")
        subprocess.run("curl -fsSL https://pkgs.netbird.io/install.sh | sh", shell=True, check=False)
elif tunnel_key == "cloudflared":
    if not shutil.which("cloudflared"):
        print("🌐 Installing Cloudflared...")
        subprocess.run("curl -fsSL https://github.com/cloudflare/cloudflared/releases/latest/download/cloudflared-linux-amd64.deb -o /tmp/cf.deb && dpkg -i /tmp/cf.deb && rm /tmp/cf.deb", shell=True, check=False)

# 3. ComfyUI Setup & Modal Volume Integration
comfy_dir = f"{workspace_root}/ComfyUI"
if mode_key in ("hybrid", "model"):
    if not os.path.exists(comfy_dir):
        print(f"📥 Cloning ComfyUI to {comfy_dir}...")
        subprocess.run(["git", "clone", "--depth", "1", "https://github.com/comfyanonymous/ComfyUI.git", comfy_dir], check=False)

    # If running on Modal Volume comfy-storage, link directly to /mnt/data/models
    if os.path.exists("/mnt/data/models"):
        print("⚡ Modal Volume detected: Linking ComfyUI model directories directly to /mnt/data/models (zero duplicate downloads!)...")
        for sub in ["checkpoints", "loras", "vae", "controlnet", "unet", "clip"]:
            vol_sub = f"/mnt/data/models/{sub}"
            os.makedirs(vol_sub, exist_ok=True)
            safe_symlink(vol_sub, f"{comfy_dir}/models/{sub}")

# 4. Initialize High-Speed System RAM Cache (if enabled)
ram_setting = CACHE_IN_RAM_SETTING.lower() if "CACHE_IN_RAM_SETTING" in locals() else "auto"
tot_ram = 16.0
try:
    import psutil
    tot_ram = psutil.virtual_memory().total / (1024**3)
except Exception:
    pass

enable_ram_cache = False if "disabled" in ram_setting else (tot_ram >= 20.0 if "auto" in ram_setting else True)
ram_cache_dir = "/dev/shm/tnh_ram_cache"

if enable_ram_cache:
    target_shm_gb = min(44, int(tot_ram * 0.82))
    subprocess.run(["mount", "-o", f"remount,size={target_shm_gb}G", "/dev/shm"], check=False)
    print(f"⚡ Expanded /dev/shm filesystem capacity to {target_shm_gb} GB for High-Speed RAM caching.")
    os.makedirs(ram_cache_dir, exist_ok=True)
    for sub in ["checkpoints", "loras", "vae", "llm"]:
        os.makedirs(f"{ram_cache_dir}/{sub}", exist_ok=True)
else:
    print(f"📦 Direct NVMe Storage Mode Active (RAM caching disabled; 0 MB host RAM overhead).")

if mode_key in ("hybrid", "model") and os.path.exists(comfy_dir):
    extra_paths_file = f"{comfy_dir}/extra_model_paths.yaml"
    extra_paths_content = f\"\"\"
tnh_ram_cache:
    base_path: {ram_cache_dir}
    is_default: true
    checkpoints: checkpoints
    loras: loras
    vae: vae
tnh_modal_volume:
    base_path: /mnt/data
    is_default: false
    checkpoints: models/checkpoints
    loras: models/loras
    vae: models/vae
\"\"\"
    try:
        with open(extra_paths_file, "w") as f:
            f.write(extra_paths_content.strip() + "\\n")
    except Exception as e:
        print(f"⚠️ Could not write extra_model_paths.yaml: {e}")

# 5. llama-server Setup with Persistent Binary Cache
if mode_key in ("llm", "hybrid"):
    llama_dir = "/usr/local/llama.cpp"
    target_llama = "/usr/local/bin/llama-server"
    cached_bundle = f"{gdrive_bin}/llama-cuda12-bundle.tar.gz"

    llama_ready = False
    if os.path.exists(target_llama) or shutil.which("llama-server"):
        try:
            test_run = subprocess.run([target_llama, "--version"], capture_output=True, text=True, timeout=5)
            if test_run.returncode == 0:
                llama_ready = True
        except Exception:
            llama_ready = False

    if not llama_ready:
        os.makedirs(llama_dir, exist_ok=True)
        if os.path.exists(cached_bundle) and os.path.getsize(cached_bundle) > 50_000_000:
            print(f"⚡ Restoring CUDA-accelerated llama.cpp bundle from persistent cache ({cached_bundle})...")
            subprocess.run(f"tar -xzf '{cached_bundle}' -C '{llama_dir}'", shell=True, check=True)
        else:
            print("📥 Fetching CUDA-accelerated llama.cpp binary & runtime libraries...")
            llama_tar = "/tmp/llama_server.tar.gz"
            llama_url = "https://github.com/ggml-org/llama.cpp/releases/download/b11647/llama-b11647-bin-ubuntu-cuda-12.8-x64.tar.gz"
            subprocess.run(["curl", "-fsSL", "--retry", "3", llama_url, "-o", llama_tar], check=True)
            subprocess.run(f"tar -xzf '{llama_tar}' -C '{llama_dir}' --strip-components=1", shell=True, check=True)
            try:
                shutil.copy(llama_tar, cached_bundle)
                print(f"💾 Cached complete llama.cpp bundle to {cached_bundle} for instant future restores.")
            except Exception as e:
                print(f"⚠️ Could not cache bundle: {e}")
            if os.path.exists(llama_tar):
                try: os.remove(llama_tar)
                except Exception: pass

        # Clean up stray symlinks and link CUDA runtimes into llama_dir
        cuda_dirs = [llama_dir, "/usr/local/lib", "/usr/local/cuda/lib64", "/usr/local/cuda-12/lib64", "/usr/lib64-nvidia", "/usr/lib/x86_64-linux-gnu"]
        import glob
        for pat in ["/usr/local/lib/python*/dist-packages/nvidia/*/lib", f"{sys.prefix}/lib/python*/dist-packages/nvidia/*/lib"]:
            cuda_dirs.extend(glob.glob(pat))
        cuda_dirs = [p for p in list(dict.fromkeys(cuda_dirs)) if os.path.isdir(p)]
        for c_dir in cuda_dirs:
            for root, dirs, files in os.walk(c_dir):
                for f in files:
                    if f.startswith(("libcudart.so", "libcublas.so", "libcublasLt.so", "libcuda.so")):
                        dst = os.path.join(llama_dir, f)
                        if not os.path.exists(dst):
                            try: os.symlink(os.path.join(root, f), dst)
                            except Exception: pass
        subprocess.run(["ldconfig"], check=False)
        ld_path = ":".join(cuda_dirs) + ":/usr/local/llama.cpp:" + os.environ.get("LD_LIBRARY_PATH", "")
        os.environ["LD_LIBRARY_PATH"] = ld_path

        # Link llama-server into /usr/local/bin
        for root, dirs, files in os.walk(llama_dir):
            for f in files:
                if f == "llama-server":
                    src_p = os.path.join(root, f)
                    try:
                        if os.path.exists(target_llama) or os.path.islink(target_llama):
                            os.remove(target_llama)
                        os.symlink(src_p, target_llama)
                    except Exception:
                        shutil.copy(src_p, target_llama)
                    os.chmod(target_llama, 0o755)

        print("✅ Installed CUDA-enabled llama-server!")

    llm_dir = "/mnt/data/tnhcomfy/llm_models" if is_modal else (GDRIVE_LLM_PATH.strip() if "GDRIVE_LLM_PATH" in locals() and GDRIVE_LLM_PATH.strip() else f"{persistent_root}/llm_models")
    os.makedirs(llm_dir, exist_ok=True)
    os.makedirs(f"{workspace_root}/agent-data/llm", exist_ok=True)
    safe_symlink(llm_dir, f"{workspace_root}/agent-data/llm/models")
    print(f"✅ LLM model storage ready at {llm_dir}")

# 6. System 1 Decision Maker (Laya System 1 GPU/RAM Engine)
print("🧠 Installing & pre-downloading Laya System 1 Engine...")
subprocess.run([sys.executable, "-m", "pip", "install", "--break-system-packages", "--quiet", "laya"], check=False)
try:
    from huggingface_hub import snapshot_download
    laya_target = f"{workspace_root}/agent-data/decisions/laya_multilingual"
    os.makedirs(laya_target, exist_ok=True)
    print("⚡ Pre-downloading Laya multilingual weights from Hugging Face...")
    snapshot_download("convaiinnovations/laya-multilingual", local_dir=laya_target, token=os.environ.get("HF_TOKEN") or None)
    print("✅ Laya multilingual model pre-downloaded to local storage!")
except Exception as e:
    print(f"⚠️ Laya pre-download notice: {e}")
print("✅ Laya System 1 Engine ready (GPU-accelerated, <100ms).")

print("\\n🎉 Environment setup complete!")
"""
    return [line + "\n" for line in code.split("\n")[:-1]]


def build_cell_5_source() -> list[str]:
    code = """#@title 5. 🚀 Launch Worker & Start Networking
import os
import sys
import time
import re
import secrets
import shutil
import subprocess
import json
import urllib.request
import urllib.parse
import ssl
from IPython.display import display, HTML

mode_key = "hybrid" if "hybrid" in WORKER_MODE else ("model" if "image" in WORKER_MODE else ("llm" if "llm" in WORKER_MODE else "tts"))
tunnel_key = "netbird" if "netbird" in TUNNEL_METHOD else ("cloudflared" if "cloudflared" in TUNNEL_METHOD else "direct")
policy_key = "auto" if "auto" in CONCURRENCY_POLICY else ("exclusive" if "exclusive" in CONCURRENCY_POLICY else ("semi_concurrent" if "semi_concurrent" in CONCURRENCY_POLICY else "concurrent"))

is_colab = False
try:
    import google.colab
    is_colab = True
except Exception:
    pass

is_modal = os.path.exists("/mnt/data") or ("MODAL_ENVIRONMENT" in os.environ)
workspace_root = "/content" if is_colab else ("/root" if os.path.exists("/root") else os.path.expanduser("~"))

# 0. Persistent Storage Path
if is_modal:
    persistent_storage_root = "/mnt/data/tnhcomfy"
elif is_colab:
    try:
        from google.colab import drive
        if not os.path.exists("/content/drive/MyDrive"):
            drive.mount("/content/drive")
    except Exception:
        pass
    persistent_storage_root = "/content/drive/MyDrive/tnhcomfy"
else:
    persistent_storage_root = f"{workspace_root}/tnhcomfy_storage"

os.makedirs(persistent_storage_root, exist_ok=True)

# 1. Multi-GPU Device Allocation & Smart Routing
device_count = 1
try:
    import torch
    if torch.cuda.is_available():
        device_count = torch.cuda.device_count()
except Exception:
    pass

if device_count >= 2:
    comfy_gpu_device = 0
    llm_gpu_device = 1
    laya_gpu_device = 1
    is_multi_gpu = True
    print(f"⚡ Multi-GPU Parallel Mode Active ({device_count} GPUs detected):")
    print(f"   • GPU 0: ComfyUI (Image Generation)")
    print(f"   • GPU 1: llama-server (LLM) & Laya System 1 (Director)")
    print(f"   • Cooperative cross-eviction is BYPASSED for zero switching latency!")
else:
    comfy_gpu_device = 0
    llm_gpu_device = 0
    laya_gpu_device = 0
    is_multi_gpu = False
    print("⚡ Single GPU Mode: Dynamic cooperative VRAM Arbiter active.")

# 2. RAM Caching Policy
ram_strat = CACHE_IN_RAM_SETTING.lower() if "CACHE_IN_RAM_SETTING" in locals() else "auto"
tot_ram_gb = 16.0
try:
    import psutil
    tot_ram_gb = psutil.virtual_memory().total / (1024**3)
except Exception:
    pass

if "disabled" in ram_strat:
    enable_ram_cache = False
elif "always" in ram_strat:
    enable_ram_cache = True
else:
    enable_ram_cache = tot_ram_gb >= 20.0

print(f"🧠 Host RAM: {tot_ram_gb:.1f} GB | Models-in-RAM Cache: {'ENABLED (/dev/shm)' if enable_ram_cache else 'DISABLED (Direct Volume Streaming)'}")

# 3. Persistent Agent Token
token_file = os.path.join(persistent_storage_root, ".agent-token")
if os.path.exists(token_file):
    with open(token_file, "r") as f:
        agent_token = f.read().strip()
else:
    agent_token = secrets.token_urlsafe(32)
    with open(token_file, "w") as f:
        f.write(agent_token)
os.environ["REMOTE_AGENT_TOKEN"] = agent_token

agent_dir = os.path.join(workspace_root, "tnhcomfy", "remote_agent")
scratch_downloads = os.path.join(workspace_root, "tmp_downloads")
os.makedirs(scratch_downloads, exist_ok=True)
log_comfy = os.path.join(workspace_root, "comfyui.log")
log_agent = os.path.join(workspace_root, "agent.log")
log_llm = os.path.join(workspace_root, "llama_server.log")
comfy_port = 8188
agent_port = 8001 if mode_key in ("model", "hybrid") else (8003 if mode_key == "llm" else 8002)
llm_port = 8003

# 4. Networking Setup (NetBird VPN Mesh / Cloudflare / Direct)
assigned_ip = ""
public_url = ""

if tunnel_key == "netbird":
    netbird_dir = os.path.join(persistent_storage_root, "netbird")
    os.makedirs(netbird_dir, exist_ok=True)
    os.makedirs("/var/lib/netbird", exist_ok=True)
    os.makedirs("/etc/netbird", exist_ok=True)
    os.makedirs("/var/log/netbird", exist_ok=True)
    os.makedirs("/var/run", exist_ok=True)

    subprocess.run("pkill -9 -f 'netbird' || true", shell=True)
    for p in ["/var/run/netbird.sock", "/var/run/netbird.pid"]:
        if os.path.exists(p):
            try: os.remove(p)
            except Exception: pass

    mgmt_url_file = os.path.join(netbird_dir, "management_url.txt")
    admin_url_file = os.path.join(netbird_dir, "admin_url.txt")

    mgmt_url = NETBIRD_MANAGEMENT_URL.strip() if "NETBIRD_MANAGEMENT_URL" in locals() else ""
    if not mgmt_url:
        try:
            from google.colab import userdata
            mgmt_url = userdata.get("NETBIRD_MANAGEMENT_URL", "").strip()
        except Exception: pass
    if not mgmt_url and os.path.exists(mgmt_url_file):
        try:
            with open(mgmt_url_file, "r") as f: mgmt_url = f.read().strip()
        except Exception: pass

    admin_url = NETBIRD_ADMIN_URL.strip() if "NETBIRD_ADMIN_URL" in locals() else ""
    if not admin_url:
        try:
            from google.colab import userdata
            admin_url = userdata.get("NETBIRD_ADMIN_URL", "").strip()
        except Exception: pass
    if not admin_url and os.path.exists(admin_url_file):
        try:
            with open(admin_url_file, "r") as f: admin_url = f.read().strip()
        except Exception: pass

    if mgmt_url:
        if not mgmt_url.startswith("http://") and not mgmt_url.startswith("https://"):
            mgmt_url = f"https://{mgmt_url}"
        mgmt_url = mgmt_url.rstrip("/")
        try:
            with open(mgmt_url_file, "w") as f: f.write(mgmt_url)
        except Exception: pass
        print(f"🌐 Self-hosted NetBird Management Server: {mgmt_url}")

    if admin_url:
        if not admin_url.startswith("http://") and not admin_url.startswith("https://"):
            admin_url = f"https://{admin_url}"
        admin_url = admin_url.rstrip("/")
        try:
            with open(admin_url_file, "w") as f: f.write(admin_url)
        except Exception: pass

    persisted_files = os.listdir(netbird_dir) if os.path.exists(netbird_dir) else []
    config_backed_up = any(f.endswith(".json") for f in persisted_files) or ("config.json" in persisted_files)
    if config_backed_up:
        print("🔄 Restoring existing NetBird peer credentials from persistent storage (Static IP preserved!)...")
        for f in os.listdir(netbird_dir):
            src = os.path.join(netbird_dir, f)
            dst = os.path.join("/var/lib/netbird", f)
            try:
                if os.path.isdir(src): shutil.copytree(src, dst, dirs_exist_ok=True)
                else: shutil.copy2(src, dst)
            except Exception: pass
            dst_etc = os.path.join("/etc/netbird", f)
            try:
                if not os.path.isdir(src): shutil.copy2(src, dst_etc)
            except Exception: pass

    print("🚀 Starting NetBird daemon in Userspace Netstack mode...")
    env_daemon = dict(
        os.environ,
        NB_LOG_FILE="/var/log/netbird/service.log",
        NB_LOG_LEVEL="info",
        NB_WG_KERNEL_DISABLED="true",
        NB_INTERFACE_NAME="wt0",
        NB_NETSTACK_MODE="true",
        NB_USE_NETSTACK_MODE="true",
        NB_ENABLE_NETSTACK_LOCAL_FORWARDING="true",
        NB_SOCKS5_LISTENER_PORT="1080",
        NB_SOCKS5_LISTENER_ADDRESS="127.0.0.1",
    )
    daemon_cmd = ["netbird", "service", "run", "--log-file", "/var/log/netbird/client.log"]
    if mgmt_url: daemon_cmd.extend(["--management-url", mgmt_url])
    if admin_url: daemon_cmd.extend(["--admin-url", admin_url])
    with open("/var/log/netbird/daemon.stdout.log", "w") as out:
        subprocess.Popen(daemon_cmd, env=env_daemon, stdout=out, stderr=out)

    time.sleep(2)

    extra_flags = []
    if mgmt_url: extra_flags.append(f"--management-url {mgmt_url}")
    if admin_url: extra_flags.append(f"--admin-url {admin_url}")
    flags_str = (" " + " ".join(extra_flags)) if extra_flags else ""
    env_up = dict(os.environ, NB_WG_KERNEL_DISABLED="true", NB_USE_NETSTACK_MODE="true", NB_SOCKS5_LISTENER_PORT="1080", NB_SOCKS5_LISTENER_ADDRESS="127.0.0.1")

    if config_backed_up:
        print("🚀 Bringing up restored NetBird connection...")
        cmd_up = f"netbird up{flags_str}".strip()
        subprocess.run(cmd_up, shell=True, env=env_up, check=False)
    else:
        setup_key = NETBIRD_SETUP_KEY.strip() if "NETBIRD_SETUP_KEY" in locals() else ""
        if not setup_key:
            try:
                from google.colab import userdata
                setup_key = userdata.get("NETBIRD_SETUP_KEY", "").strip()
            except Exception: pass

        if setup_key:
            print("🔑 Registering new NetBird peer key...")
            cmd_up = f"netbird up --setup-key {setup_key} --hostname comfy-worker{flags_str}".strip()
            res_up = subprocess.run(cmd_up, shell=True, env=env_up, capture_output=True, text=True)
            if res_up.returncode == 0:
                print("✅ Peer registered! Saving credentials for permanent static IP...")
                for f in os.listdir("/var/lib/netbird"):
                    src = os.path.join("/var/lib/netbird", f)
                    dst = os.path.join(netbird_dir, f)
                    try:
                        if os.path.isdir(src): shutil.copytree(src, dst, dirs_exist_ok=True)
                        else: shutil.copy2(src, dst)
                    except Exception: pass

    # Resolve assigned NetBird IP
    print("⏳ Waiting for NetBird IP assignment...")
    for _ in range(30):
        time.sleep(1)
        res = subprocess.run(["netbird", "status"], capture_output=True, text=True)
        out = res.stdout
        m = re.search(r"NetBird IP:\\s*([0-9a-fA-F\\.:]+)", out) or re.search(r"IP:\\s*([0-9a-fA-F\\.:]+)", out)
        if m:
            assigned_ip = m.group(1).split("/")[0].strip()
            break

    if assigned_ip:
        print(f"✅ Connected to NetBird Mesh with Static IP: {assigned_ip}")
        for f in os.listdir("/var/lib/netbird"):
            src = os.path.join("/var/lib/netbird", f)
            dst = os.path.join(netbird_dir, f)
            try:
                if os.path.isdir(src): shutil.copytree(src, dst, dirs_exist_ok=True)
                else: shutil.copy2(src, dst)
            except Exception: pass

# 5. Model Catalog Sync with Backend
catalog = {}
catalog_source = "local models.json"
backend_sync_ok = False
backend_url_clean = BACKEND_URL.strip().rstrip("/") if "BACKEND_URL" in locals() else ""

if backend_url_clean:
    candidates = [backend_url_clean]
    try:
        parsed = urllib.parse.urlparse(backend_url_clean)
        if parsed.scheme == "http" and parsed.port == 8002:
            candidates.append(f"https://{parsed.hostname}")
            candidates.append(f"http://{parsed.hostname}")
        elif parsed.scheme == "https" and not parsed.port:
            candidates.append(f"http://{parsed.hostname}:8002")
    except Exception:
        pass

    def fetch_backend_json(url, timeout=4):
        for socks_port in ("1080", None):
            try:
                cmd = ["curl", "-fsSL", "--connect-timeout", "3", "-m", str(timeout), "-H", "Accept: application/json", "-k"]
                if socks_port: cmd.extend(["--socks5-hostname", f"127.0.0.1:{socks_port}"])
                cmd.append(url)
                res = subprocess.run(cmd, capture_output=True, text=True, timeout=timeout + 2)
                if res.returncode == 0 and res.stdout.strip().startswith("{"):
                    return json.loads(res.stdout.strip())
            except Exception:
                pass
        return None

    print(f"⏳ Syncing Model Catalog from backend ({backend_url_clean})...")
    for attempt in range(1, 12):
        for cand in candidates:
            for path in ("/api/v2/models/catalog", "/api/v2/world-vault/llm-config/catalog"):
                cat_data = fetch_backend_json(f"{cand}{path}", timeout=3)
                if cat_data and isinstance(cat_data, dict) and ("models" in cat_data or "catalog" in cat_data):
                    catalog = cat_data
                    backend_sync_ok = True
                    catalog_source = f"backend ({cand})"
                    break
            if backend_sync_ok: break
        if backend_sync_ok: break
        time.sleep(1.5)

if not catalog:
    local_cat = os.path.join(workspace_root, "tnhcomfy", "backend_v2", "modal_llm", "models.json")
    if os.path.exists(local_cat):
        try:
            with open(local_cat, "r") as f: catalog = json.load(f)
        except Exception: pass

models_dict = catalog.get("models") or catalog.get("catalog", {})
active_spec = catalog.get("active", {})
active_rp = active_spec.get("rp") or (LLM_RP_MODEL if "LLM_RP_MODEL" in locals() else "artemis_31b_q4")
active_util = active_spec.get("util") or (LLM_UTIL_MODEL if "LLM_UTIL_MODEL" in locals() else "same_as_rp")
active_image = active_spec.get("image") or ""
shared_weights = (active_util in ("same_as_rp", active_rp))
distinct_active_llm = [active_rp] if shared_weights else [active_rp, active_util]

print(f"🌐 Active Models (Catalog: {catalog_source}):")
print(f"   • RP:   {active_rp}")
print(f"   • Util: {active_util} (Shared: {shared_weights})")
if active_image: print(f"   • Image: {active_image}")

# 6. Check Active LLM Weights
llm_persistent_dir = "/mnt/data/tnhcomfy/llm_models" if is_modal else (GDRIVE_LLM_PATH.strip() if "GDRIVE_LLM_PATH" in locals() and GDRIVE_LLM_PATH.strip() else f"{persistent_storage_root}/llm_models")
llm_local_dir = f"{workspace_root}/models/llm"
os.makedirs(llm_persistent_dir, exist_ok=True)
os.makedirs(llm_local_dir, exist_ok=True)

resolved_weights = {}
for mid in distinct_active_llm:
    spec = models_dict.get(mid, {})
    vol_dir = spec.get("dir") or mid
    gguf_name = spec.get("gguf")
    repo = spec.get("repo")

    # Candidates in persistent storage or local NVMe
    cand_p = os.path.join(llm_persistent_dir, vol_dir, gguf_name) if gguf_name else ""
    cand_flat = os.path.join(llm_persistent_dir, gguf_name) if gguf_name else ""
    cand_local = os.path.join(llm_local_dir, vol_dir, gguf_name) if gguf_name else ""

    chosen = None
    for c in [cand_p, cand_flat, cand_local]:
        if c and os.path.exists(c):
            chosen = c
            break

    if not chosen and repo and gguf_name:
        target_folder = os.path.join(llm_persistent_dir, vol_dir) if is_modal else os.path.join(llm_local_dir, vol_dir)
        os.makedirs(target_folder, exist_ok=True)
        print(f"📥 Downloading active weights for [{mid}] ({repo} :: {gguf_name})...")
        try:
            from huggingface_hub import snapshot_download
            snapshot_download(repo, allow_patterns=[gguf_name], local_dir=target_folder, token=os.environ.get("HF_TOKEN") or None)
            downloaded = os.path.join(target_folder, gguf_name)
            if os.path.exists(downloaded):
                chosen = downloaded
                print(f"✅ Downloaded [{mid}] ({os.path.getsize(downloaded)/(1024**3):.2f} GB)!")
        except Exception as exc:
            print(f"⚠️ HF download notice for {mid}: {exc}")

    if chosen:
        resolved_weights[mid] = chosen

# 7. RAM Setup & Pre-Warming
if agent_dir not in sys.path:
    sys.path.insert(0, agent_dir)

from ram_manager import RamModelManager
ram_mgr = RamModelManager(ram_dir=ram_cache_dir, budget_gb=40.0 if enable_ram_cache else 0.0)

if enable_ram_cache:
    ram_mgr.set_anchors([active_rp] if shared_weights else [active_rp, active_util])

# 8. Service Launches
worker_procs = {}

def start_remote_agent():
    print(f"🚀 Starting Remote Agent on :{agent_port} (DATA_DIR={workspace_root}/ComfyUI)...")
    comfy_dir_path = f"{workspace_root}/ComfyUI"
    env_agent = dict(
        os.environ,
        DATA_DIR=comfy_dir_path,
        WORKER_MODE="hybrid" if mode_key == "hybrid" else mode_key,
        PORT=str(agent_port),
        HOST="127.0.0.1",
        LLM_UPSTREAM_BASE=f"http://127.0.0.1:{llm_port}/v1",
        RAM_CACHE_DIR=ram_cache_dir,
        RAM_CACHE_BUDGET_GB="40" if enable_ram_cache else "0",
        CACHE_IN_RAM="1" if enable_ram_cache else "0",
        COMFY_GPU_DEVICE=str(comfy_gpu_device),
        LLM_GPU_DEVICE=str(llm_gpu_device),
        LAYA_GPU_DEVICE=str(laya_gpu_device),
        PERSISTENT_STORAGE_PATH=persistent_storage_root,
        PYTHONUNBUFFERED="1",
        PROVIDER_DOWNLOAD_SCRATCH_DIR=scratch_downloads,
        REMOTE_AGENT_DOWNLOAD_MAX_CONCURRENT="1",
    )
    with open(log_agent, "w") as out:
        worker_procs["agent"] = subprocess.Popen([sys.executable, f"{agent_dir}/server.py"], cwd=agent_dir, env=env_agent, stdout=out, stderr=out)

def launch_comfyui_track():
    comfy_dir_path = f"{workspace_root}/ComfyUI"
    print(f"🚀 [ComfyUI Track] Launching on GPU {comfy_gpu_device} (:{comfy_port})...")
    with open(log_comfy, "w") as out:
        env_comfy = dict(os.environ, PYTORCH_CUDA_ALLOC_CONF="expandable_segments:True", PYTHONUNBUFFERED="1")
        cmd_comfy = [sys.executable, f"{comfy_dir_path}/main.py", "--listen", "127.0.0.1", "--port", str(comfy_port), "--cuda-device", str(comfy_gpu_device)]
        worker_procs["comfy"] = subprocess.Popen(cmd_comfy, env=env_comfy, stdout=out, stderr=out)

def launch_llm_track():
    src_expected = resolved_weights.get(active_rp, "")
    rp_target_file = src_expected
    if enable_ram_cache and src_expected:
        print(f"⚡ [LLM Track] Pre-warming {os.path.basename(src_expected)} into RAM cache (/dev/shm)...")
        try:
            ram_mgr.ensure_in_ram(src_expected, model_id=active_rp, role="rp", is_anchor=True)
            ram_mgr.aliases["default"] = active_rp
            ram_mgr.aliases["rp"] = active_rp
            rp_target_file = ram_mgr.entries[active_rp].ram_path
        except Exception:
            pass
    elif not enable_ram_cache and src_expected:
        print(f"📦 [LLM Track] Direct volume streaming mode active: {os.path.basename(src_expected)}")

    if mode_key == "llm":
        # Launch llama-server directly
        ngl = 99
        cmd_llm = [
            "/usr/local/bin/llama-server",
            "--port", str(llm_port),
            "--host", "127.0.0.1",
            "--main-gpu", str(llm_gpu_device),
            "-ngl", str(ngl),
            "-c", "8192",
            "--cache-type-k", "q8_0",
            "--cache-type-v", "q8_0",
            "--jinja",
        ]
        if rp_target_file and os.path.exists(rp_target_file):
            cmd_llm.extend(["-m", rp_target_file, "--alias", f"{active_rp},default,rp"])
        with open(log_llm, "a", buffering=1) as out:
            worker_procs["llm"] = subprocess.Popen(cmd_llm, env=dict(os.environ, PYTHONUNBUFFERED="1"), stdout=out, stderr=out)
    else:
        print(f"⚡ [LLM Track] Standby JIT mode active on GPU {llm_gpu_device}. Starts automatically on first turn!")

def launch_laya_track():
    print(f"⚡ [Laya Track] Pre-warming Laya on GPU {laya_gpu_device}...")
    try:
        import laya
        laya_dir = f"{workspace_root}/agent-data/decisions/laya_multilingual"
        src = laya_dir if (os.path.exists(laya_dir) and os.listdir(laya_dir)) else "convaiinnovations/laya-multilingual"
        hf_tok = os.environ.get("HF_TOKEN") or None
        target_dev = f"cuda:{laya_gpu_device}"
        _ = laya.load(src, device=target_dev, token=hf_tok)
        print(f"✅ [Laya Track] Laya pre-warmed on GPU {laya_gpu_device} (<100ms inference ready)!")
    except Exception as exc:
        print(f"⚠️ [Laya Track] Pre-warming notice: {exc}")

import threading
start_remote_agent()
active_threads = []
if mode_key in ("hybrid", "model"):
    t_c = threading.Thread(target=launch_comfyui_track, daemon=True)
    t_c.start()
    active_threads.append(t_c)
if mode_key in ("hybrid", "llm"):
    t_l = threading.Thread(target=launch_llm_track, daemon=True)
    t_l.start()
    active_threads.append(t_l)
t_y = threading.Thread(target=launch_laya_track, daemon=True)
t_y.start()
active_threads.append(t_y)

# 9. Health Checks
print("⏳ Waiting for services to become healthy...")
services_to_check = [("agent", agent_port, "/health", "Remote Agent")]
if mode_key in ("hybrid", "model"):
    services_to_check.append(("comfy", comfy_port, "/system_stats", "ComfyUI"))
if mode_key == "llm":
    services_to_check.append(("llm", llm_port, "/health", "llama-server"))

healthy = set()
for _ in range(90):
    for s_name, s_port, s_path, s_label in services_to_check:
        if s_name in healthy: continue
        try:
            req = urllib.request.Request(f"http://127.0.0.1:{s_port}{s_path}")
            with urllib.request.urlopen(req, timeout=1) as res:
                if res.status in (200, 307):
                    print(f"✅ {s_label} is healthy on :{s_port}!")
                    healthy.add(s_name)
        except Exception:
            pass
    if len(healthy) == len(services_to_check):
        break
    time.sleep(1)

for t in active_threads:
    t.join(timeout=30)

# 10. Tunnel Fallback & Cloudflared
if tunnel_key == "cloudflared":
    print("🌐 Starting Cloudflare Named / Quick Tunnel...")
    cf_log = f"{workspace_root}/cloudflared.log"
    target_tunnel_port = comfy_port if mode_key == "model" else agent_port
    with open(cf_log, "w") as out:
        subprocess.Popen(["cloudflared", "tunnel", "--url", f"http://127.0.0.1:{target_tunnel_port}", "--no-autoupdate"], stdout=out, stderr=out)
    for _ in range(30):
        time.sleep(1)
        if os.path.exists(cf_log):
            with open(cf_log, "r") as f:
                content = f.read()
                m = re.search(r"https://[a-zA-Z0-9-]+\\.trycloudflare\\.com", content)
                if m:
                    public_url = m.group(0)
                    break
    if public_url:
        print(f"✅ Cloudflare Tunnel is live: {public_url}")

# 11. Credentials & Status Card
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
    base_endpoint = "http://<WORKER_IP>"
    comfy_endpoint = f"http://<WORKER_IP>:{comfy_port}"
    agent_endpoint = f"http://<WORKER_IP>:{agent_port}"
    llm_endpoint = f"http://<WORKER_IP>:{llm_port}"

gpu_topo_badge = f'''
<div style="background: rgba(30, 41, 59, 0.7); border: 1px solid #334155; border-radius: 8px; padding: 10px 14px; margin-bottom: 12px; font-size: 13px;">
    <div style="display: flex; justify-content: space-between; align-items: center;">
        <span style="font-weight: 700; color: #38bdf8;">⚡ Hardware & GPU Topology:</span>
        <span style="color: {'#22c55e' if is_multi_gpu else '#f59e0b'}; font-weight: 600;">{'Multi-GPU Parallel Concurrency' if is_multi_gpu else 'Single-GPU Cooperative Arbiter'}</span>
    </div>
    <div style="margin-top: 4px; color: #94a3b8; font-size: 11px;">
        {'<b>GPU 0:</b> ComfyUI | <b>GPU 1:</b> llama-server + Laya (Zero eviction latency)' if is_multi_gpu else f'<b>GPU 0:</b> Shared across ComfyUI, LLM, and Laya'}
    </div>
</div>
'''

print(f"\\n✨ Worker Ready ({provider_category} Mode)! Base: {agent_endpoint} | Token: {agent_token}")
display(HTML(f'''
<div style="background: linear-gradient(135deg, #0f172a 0%, #1e1b4b 100%); border: 1px solid #3b82f6; border-radius: 14px; padding: 20px; color: #f8fafc; font-family: system-ui, sans-serif; max-width: 760px;">
    <h3 style="margin: 0 0 10px 0; color: #60a5fa;">✨ TNHComfy Worker is Live ({provider_category} Mode)</h3>
    {gpu_topo_badge}
    <div style="background: rgba(15, 23, 42, 0.85); border: 1px solid #334155; border-radius: 8px; padding: 12px; font-size: 13px; font-family: monospace;">
        <div><b>Provider Type:</b> <code style="color: #38bdf8;">{provider_type}</code></div>
        <div style="margin-top: 4px;"><b>Base Endpoint:</b> <span style="color: #a5f3fc;">{agent_endpoint}</span></div>
        <div style="margin-top: 4px;"><b>Agent Token:</b> <span style="color: #34d399;">{agent_token}</span></div>
    </div>
</div>
'''))

# 12. Live Stream Box
log_files = {"Agent": log_agent}
if mode_key in ("hybrid", "model"): log_files["ComfyUI"] = log_comfy
if mode_key in ("hybrid", "llm"): log_files["LLM"] = log_llm

handles = {}
for label, p in log_files.items():
    if os.path.exists(p):
        f = open(p, "r", errors="replace")
        sz = os.path.getsize(p)
        if sz > 16384: f.seek(max(0, sz - 8192), os.SEEK_SET)
        handles[label] = f

TAG_COLORS = {"Agent": "\\033[92m[Agent]\\033[0m", "ComfyUI": "\\033[94m[ComfyUI]\\033[0m", "LLM": "\\033[93m[LLM]\\033[0m"}
try:
    while True:
        activity = False
        for label, f in list(handles.items()):
            for _ in range(50):
                line = f.readline()
                if not line: break
                activity = True
                line_c = line.strip()
                if line_c:
                    tag = TAG_COLORS.get(label, f"[{label}]")
                    print(f"{tag} {line_c}", flush=True)
        for label, p in log_files.items():
            if label not in handles and os.path.exists(p):
                handles[label] = open(p, "r", errors="replace")
        if not activity:
            time.sleep(0.3)
except KeyboardInterrupt:
    print("\\n🛑 Stopped log monitor. Background services continue running happily!")
finally:
    for f in handles.values():
        try: f.close()
        except Exception: pass
"""
    return [line + "\n" for line in code.split("\n")[:-1]]


def build_cell_6_source() -> list[str]:
    code = """#@title 6. 📥 (Optional) Live Models-in-RAM Dashboard & Model Manager
OPERATION = "📊 View Models-in-RAM Dashboard & Status" #@param ["📊 View Models-in-RAM Dashboard & Status", "⚡ Pre-Warm Model into RAM Cache", "🧹 Evict Model from RAM Cache", "🔍 List Available Checkpoints"]
MODEL_OR_CHECKPOINT_FILTER = "" #@param {type:"string"}

import os
import sys
from IPython.display import display, HTML

is_colab = False
try:
    import google.colab
    is_colab = True
except Exception:
    pass

is_modal = os.path.exists("/mnt/data") or ("MODAL_ENVIRONMENT" in os.environ)
workspace_root = "/content" if is_colab else ("/root" if os.path.exists("/root") else os.path.expanduser("~"))

agent_dir = os.path.join(workspace_root, "tnhcomfy", "remote_agent")
if agent_dir not in sys.path:
    sys.path.insert(0, agent_dir)

from ram_manager import get_ram_manager
ram_mgr = get_ram_manager()

comfy_dir = f"{workspace_root}/ComfyUI"
ckpt_dir = "/mnt/data/models/checkpoints" if is_modal else f"{comfy_dir}/models/checkpoints"

if OPERATION == "📊 View Models-in-RAM Dashboard & Status":
    status = ram_mgr.get_status()
    print(f"⚡ RAM Budget: {status['used_gb']} GB / {status['budget_gb']} GB ({status['percent_used']}%)")
    print(f"⚡ Anchors: {[a['model_id'] for a in status['anchor_models']]}")
    print(f"⚡ Spares:  {[s['model_id'] for s in status['spare_cached_models']]}")
elif OPERATION == "🔍 List Available Checkpoints":
    if os.path.exists(ckpt_dir):
        print(f"📂 Checkpoints in {ckpt_dir}:")
        for root, _, files in os.walk(ckpt_dir):
            for f in sorted(files):
                if f.endswith((".safetensors", ".ckpt")):
                    full_p = os.path.join(root, f)
                    mb = os.path.getsize(full_p) / (1024 * 1024)
                    print(f"  • {f} ({mb:.1f} MB)")
    else:
        print(f"⚠️ Checkpoint directory not found: {ckpt_dir}")
"""
    return [line + "\n" for line in code.split("\n")[:-1]]


def build_cell_7_source() -> list[str]:
    code = """#@title 7. ⏱️ Prevent Colab Disconnect (Keep-Alive Audio Context)
import os

is_colab = False
try:
    import google.colab
    is_colab = True
except Exception:
    pass

if is_colab:
    from IPython.display import Audio, display
    import numpy as np

    framerate = 44100
    t = np.linspace(0, 5, framerate * 5)
    data = np.sin(2 * np.pi * 20 * t) * 0.001
    display(Audio(data, rate=framerate, autoplay=True))
    print("🔊 Colab background keep-alive audio context initialized.")
else:
    print("ℹ️ Standalone / Modal environment: Keep-alive audio context skipped.")
"""
    return [line + "\n" for line in code.split("\n")[:-1]]


def update_notebook(path: Path) -> None:
    print(f"Updating {path}...")
    with open(path, "r", encoding="utf-8") as f:
        nb = json.load(f)

    # Cell 1: Environment, Storage & Hardware Check
    nb["cells"][1]["source"] = build_cell_1_source()

    # Cell 2: Configuration
    nb["cells"][2]["source"] = build_cell_2_source()

    # Cell 3: Clone / Update TNHComfy
    nb["cells"][3]["source"] = build_cell_3_source()

    # Cell 4: Dependencies and Environment
    nb["cells"][4]["source"] = build_cell_4_source()

    # Cell 5: Launch & Sync
    nb["cells"][5]["source"] = build_cell_5_source()

    # Cell 6: Models-in-RAM Dashboard
    nb["cells"][6]["source"] = build_cell_6_source()

    # Cell 7: Audio Keep-Alive
    nb["cells"][7]["source"] = build_cell_7_source()

    with open(path, "w", encoding="utf-8") as f:
        json.dump(nb, f, indent=1)
    print(f"✅ Successfully updated {path}!")


def main():
    # If root notebook doesn't exist, seed it from remote_agent
    root_nb = REPO_ROOT / "TNHComfy_Colab_Worker.ipynb"
    agent_nb = REPO_ROOT / "remote_agent" / "TNHComfy_Colab_Worker.ipynb"
    if not root_nb.exists() and agent_nb.exists():
        shutil.copy2(agent_nb, root_nb)
        print("Copied worker notebook to repo root.")

    for nb_path in NOTEBOOK_PATHS:
        if nb_path.exists():
            update_notebook(nb_path)
        else:
            print(f"⚠️ Not found: {nb_path}")


if __name__ == "__main__":
    main()
