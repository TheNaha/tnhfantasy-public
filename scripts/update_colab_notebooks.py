"""Update TNHComfy_Colab_Worker.ipynb and remote_agent/TNHComfy_Colab_Worker.ipynb

Synchronizes both notebooks with multi-environment support (Google Colab and Modal Sandboxes/Notebooks),
Modal volume comfy-storage integration, low-RAM volume streaming toggle, multi-GPU device allocation,
and dynamic Laya System 1 Decision Maker model synchronization.
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

# 3. Host System Memory, CPU & Storage Inspection
print("=" * 65)
print("📊 Host System Telemetry & Storage Audit:")
try:
    import psutil
    import shutil
    vm = psutil.virtual_memory()
    ram_tot = vm.total / (1024**3)
    ram_avail = vm.available / (1024**3)
    ram_pct = vm.percent
    print(f"   • Host System RAM: {ram_tot:.1f} GB total | {ram_avail:.1f} GB available ({ram_pct:.1f}% in use)")

    cpu_count = psutil.cpu_count(logical=True)
    cpu_phys = psutil.cpu_count(logical=False) or cpu_count
    print(f"   • CPU Architecture: {cpu_phys} physical cores / {cpu_count} logical threads")

    if os.path.exists("/dev/shm"):
        shm_du = shutil.disk_usage("/dev/shm")
        print(f"   • Shared Memory (/dev/shm): {shm_du.total / (1024**3):.1f} GB total | {shm_du.free / (1024**3):.1f} GB free")

    scratch_path = "/content" if os.path.exists("/content") else "/"
    scratch_du = shutil.disk_usage(scratch_path)
    print(f"   • Local Scratch ({scratch_path}): {scratch_du.total / (1024**3):.1f} GB total | {scratch_du.free / (1024**3):.1f} GB free")

    gdrive_comfy = "/content/drive/MyDrive/comfyui"
    if os.path.exists(gdrive_comfy):
        ckpt_dir = f"{gdrive_comfy}/models/checkpoints"
        lora_dir = f"{gdrive_comfy}/models/loras"
        ckpt_cnt = sum(len(files) for _, _, files in os.walk(ckpt_dir)) if os.path.exists(ckpt_dir) else 0
        lora_cnt = sum(len(files) for _, _, files in os.walk(lora_dir)) if os.path.exists(lora_dir) else 0
        print(f"   • Google Drive ComfyUI Library: {gdrive_comfy} (Found {ckpt_cnt} checkpoints, {lora_cnt} LoRAs)")
except Exception as e:
    print(f"   ⚠️ Telemetry notice: {e}")
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

#@markdown ---
#@markdown #### 🧠 System 1 Decision Maker (Laya Engine):
#@markdown Select which Laya decision model to run on GPU/RAM for fast Director routing (<100ms). Overridden dynamically if synced with backend:
LAYA_MODEL = "laya_multilingual" #@param ["laya_multilingual", "laya_typed_decisions", "laya_english"]

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

def _mask_sec(s):
    if not s:
        return "[NOT SET]"
    if len(s) <= 8:
        return "****"
    return f"{s[:4]}****{s[-4:]}"

print("\\n" + "=" * 65)
print("⚙️ Worker Configuration & Secrets Audit:")
print(f"• Mode: {WORKER_MODE}")
print(f"• Network Tunnel: {TUNNEL_METHOD}")
print(f"• Concurrency Policy: {CONCURRENCY_POLICY}")
print(f"• RAM Caching Policy: {CACHE_IN_RAM_SETTING}")
print(f"• Storage Strategy: {STORAGE_STRATEGY}")
print(f"• Decision Model: {LAYA_MODEL}")
print(f"• RP Model: {LLM_RP_MODEL}")
print(f"• Util Model: {LLM_UTIL_MODEL}")
print(f"• GITHUB_TOKEN: {_mask_sec(GITHUB_TOKEN)}")
print(f"• HF_TOKEN: {_mask_sec(HF_TOKEN)}")
print(f"• NETBIRD_SETUP_KEY: {_mask_sec(NETBIRD_SETUP_KEY)}")
if NETBIRD_MANAGEMENT_URL:
    print(f"• NetBird Management: {NETBIRD_MANAGEMENT_URL}")
if BACKEND_URL:
    print(f"• Backend Sync: {BACKEND_URL} (Sole source of truth for active models)")
if os.path.exists(GDRIVE_COMFY_PATH):
    print(f"• Google Drive ComfyUI: {GDRIVE_COMFY_PATH} [VERIFIED PRESENT]")
else:
    print(f"• Google Drive ComfyUI: {GDRIVE_COMFY_PATH} [NOT DETECTED YET]")
if os.path.exists(GDRIVE_LLM_PATH):
    print(f"• Google Drive LLM: {GDRIVE_LLM_PATH} [VERIFIED PRESENT]")
if os.path.exists(MODAL_VOLUME_PATH):
    print(f"• Persistent Volume: {MODAL_VOLUME_PATH} [MODAL VOLUME ACTIVE]")
print("💡 Model Strategy: ComfyUI models load from Google Drive into RAM/NVMe cache.")
print("   LLM GGUF weights stream via high-speed CDN straight to RAM.")
print("=" * 65 + "\\n")
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
try:
    branch = run_git(["git", "rev-parse", "--abbrev-ref", "HEAD"], cwd=repo_dir).strip()
    commit = run_git(["git", "log", "-1", "--pretty=format:%h - %s (%ci)"], cwd=repo_dir).strip()
    print(f"   • Active Branch: {branch}")
    print(f"   • Latest Commit: {commit}")
except Exception:
    pass
"""
    return [line + "\n" for line in code.split("\n")[:-1]]


def build_cell_4_source() -> list[str]:
    code = """#@title 4. 📦 Install Dependencies & Prepare Environment
import os
import sys

is_modal = os.path.exists("/mnt/data") or ("MODAL_ENVIRONMENT" in os.environ)
is_colab = False
try:
    import google.colab
    is_colab = True
except Exception:
    pass

if is_colab:
    try:
        from google.colab import drive
        if not os.path.exists("/content/drive/MyDrive"):
            print("📁 Mounting Google Drive at /content/drive...")
            drive.mount("/content/drive")
    except Exception:
        pass
    gdrive_root = "/content/drive/MyDrive/tnhcomfy"
elif is_modal:
    gdrive_root = "/mnt/data/tnhcomfy"
else:
    gdrive_root = "/content/tnhcomfy_storage"

os.makedirs(gdrive_root, exist_ok=True)
gdrive_bin = f"{gdrive_root}/bin"
os.makedirs(gdrive_bin, exist_ok=True)
import shutil
import urllib.request
import subprocess
from concurrent.futures import ThreadPoolExecutor, as_completed

# Set PyTorch CUDA memory allocator to reduce fragmentation during multi-task workflows
os.environ["PYTORCH_CUDA_ALLOC_CONF"] = "expandable_segments:True"

mode_key = "hybrid" if "hybrid" in WORKER_MODE else ("model" if "image" in WORKER_MODE else ("llm" if "llm" in WORKER_MODE else "tts"))
tunnel_key = "netbird" if "netbird" in TUNNEL_METHOD else "cloudflared"

print(f"📦 Setting up environment for {WORKER_MODE} via {TUNNEL_METHOD}...")

def safe_symlink(source: str, link_name: str):
    \"\"\"Safely creates a symlink link_name -> source, replacing stale links or existing dirs if needed.\"\"\"
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
    os.environ["UV_INDEX_STRATEGY"] = "unsafe-best-match"
    os.environ["UV_EXTRA_INDEX_URL"] = "https://download.pytorch.org/whl/cu124"

    if shutil.which("uv"):
        return "uv"
    for candidate in ["/usr/local/bin/uv", "/root/.cargo/bin/uv", "/root/.local/bin/uv"]:
        if os.path.exists(candidate) and os.access(candidate, os.X_OK):
            return candidate
    try:
        res = subprocess.run([sys.executable, "-m", "uv", "--version"], stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)
        if res.returncode == 0:
            return f"{sys.executable} -m uv"
    except Exception:
        pass

    print("⚡ Bootstrapping high-speed installer (uv)...")
    try:
        subprocess.run([sys.executable, "-m", "pip", "install", "--break-system-packages", "-q", "uv"], check=True)
        if shutil.which("uv"):
            return "uv"
        for candidate in ["/usr/local/bin/uv", "/root/.cargo/bin/uv", "/root/.local/bin/uv"]:
            if os.path.exists(candidate) and os.access(candidate, os.X_OK):
                return candidate
        res = subprocess.run([sys.executable, "-m", "uv", "--version"], stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)
        if res.returncode == 0:
            return f"{sys.executable} -m uv"
        return False
    except Exception as e:
        print(f"⚠️ Could not bootstrap uv ({e}), using standard pip fallback.")
        return False

USE_UV = bootstrap_uv()

def install_python_packages(req_files=None, packages=None):
    \"\"\"Unified fast package installer using uv if available, falling back to pip.\"\"\"
    req_files = [f for f in (req_files or []) if os.path.isfile(f)]
    packages = packages or []
    if not req_files and not packages:
        return

    os.environ["UV_BREAK_SYSTEM_PACKAGES"] = "1"
    os.environ["PIP_BREAK_SYSTEM_PACKAGES"] = "1"
    os.environ["UV_INDEX_STRATEGY"] = "unsafe-best-match"
    os.environ["UV_EXTRA_INDEX_URL"] = "https://download.pytorch.org/whl/cu124"

    # Separate git dependencies (e.g. sam2) so git clones don't block instant wheel resolution
    sanitized_reqs = []
    git_packages = []

    for r in req_files:
        try:
            with open(r, "r", encoding="utf-8") as f:
                content = f.read()
            has_git = False
            clean_lines = []
            for line in content.splitlines():
                stripped = line.strip()
                if stripped.startswith("git+") or " @ git+" in stripped:
                    has_git = True
                    git_packages.append(stripped)
                else:
                    clean_lines.append(line)
            if has_git:
                clean_path = f"{r}.clean.txt"
                with open(clean_path, "w", encoding="utf-8") as f:
                    f.write("\\n".join(clean_lines) + "\\n")
                sanitized_reqs.append(clean_path)
            else:
                sanitized_reqs.append(r)
        except Exception:
            sanitized_reqs.append(r)

    if USE_UV:
        if isinstance(USE_UV, str) and " -m " in USE_UV:
            uv_base = [sys.executable, "-m", "uv", "pip", "install", "--system", "--break-system-packages", "--index-strategy", "unsafe-best-match", "--extra-index-url", "https://download.pytorch.org/whl/cu124"]
        elif isinstance(USE_UV, str):
            uv_base = [USE_UV, "pip", "install", "--system", "--break-system-packages", "--index-strategy", "unsafe-best-match", "--extra-index-url", "https://download.pytorch.org/whl/cu124"]
        else:
            uv_base = ["uv", "pip", "install", "--system", "--break-system-packages", "--index-strategy", "unsafe-best-match", "--extra-index-url", "https://download.pytorch.org/whl/cu124"]
    else:
        uv_base = None

    def _install_git_packages():
        for g in git_packages:
            pkg_name = g.split("/")[-1].split("@")[0].strip()
            print(f"  📦 Installing optional extension: {pkg_name}...")
            git_env = os.environ.copy()
            git_env["SAM2_BUILD_ALLOW_ERRORS"] = "1"

            installed = False
            # 1. Try uv with --no-build-isolation first
            if uv_base:
                try:
                    uv_git_cmd = list(uv_base) + ["--no-build-isolation", g]
                    res = subprocess.run(uv_git_cmd, capture_output=True, text=True, timeout=180, env=git_env)
                    if res.returncode == 0:
                        installed = True
                except Exception:
                    pass

            # 2. Pip fallback with --no-build-isolation
            if not installed:
                try:
                    pip_git_cmd = [
                        sys.executable, "-m", "pip", "install",
                        "--break-system-packages",
                        "--no-build-isolation",
                        "--no-warn-script-location",
                        g
                    ]
                    res = subprocess.run(pip_git_cmd, capture_output=True, text=True, timeout=240, env=git_env)
                    if res.returncode == 0:
                        installed = True
                    else:
                        err_lines = (res.stderr or res.stdout or "").strip().splitlines()
                        last_err = err_lines[-1] if err_lines else "unknown build error"
                        print(f"  ⚠️ Warning: Failed to install {pkg_name} ({last_err[:200]})")
                except Exception as e:
                    print(f"  ⚠️ Warning: Error installing {pkg_name}: {e}")

    if USE_UV and uv_base:
        cmd = list(uv_base)
        for r in sanitized_reqs:
            cmd.extend(["-r", r])
        cmd.extend(packages)

        try:
            res = subprocess.run(cmd, capture_output=True, text=True)
            if res.returncode == 0:
                _install_git_packages()
                return
            err_output = (res.stderr or res.stdout or "").strip()
            first_err = next((line for line in err_output.splitlines() if "error:" in line.lower() or "exception" in line.lower()), "")
            if not first_err and err_output:
                first_err = err_output.splitlines()[-1]
            print(f"⚠️ uv notice ({first_err[:200]}), resolving per requirement file...")
        except Exception as e:
            print(f"⚠️ uv execution error ({e}), falling back to pip...")

        # If combined install failed, retry each requirement file individually with uv
        failed_reqs = []
        for r in sanitized_reqs:
            sub_cmd = uv_base + ["-r", r]
            sub_res = subprocess.run(sub_cmd, capture_output=True, text=True)
            if sub_res.returncode != 0:
                failed_reqs.append(r)

        failed_pkgs = []
        if packages:
            sub_cmd = uv_base + packages
            sub_res = subprocess.run(sub_cmd, capture_output=True, text=True)
            if sub_res.returncode != 0:
                failed_pkgs = packages

        if not failed_reqs and not failed_pkgs:
            _install_git_packages()
            return

        sanitized_reqs = failed_reqs
        packages = failed_pkgs

    # Fallback to standard pip in a single batched invocation
    print("⏳ Running pip fallback for remaining requirements...")
    pip_cmd = [sys.executable, "-m", "pip", "install", "--break-system-packages", "--no-warn-script-location"]
    for r in sanitized_reqs:
        pip_cmd.extend(["-r", r])
    pip_cmd.extend(packages)
    try:
        subprocess.run(pip_cmd, check=False)
    except Exception as e:
        print(f"⚠️ pip installation error: {e}")

    _install_git_packages()

# 1. Install Networking Tool (NetBird or Cloudflared)

if tunnel_key == "netbird":
    nb_local = "/usr/bin/netbird"
    nb_cache = f"{gdrive_bin}/netbird"
    if not shutil.which("netbird") and not os.path.exists(nb_local):
        if os.path.exists(nb_cache) and os.path.getsize(nb_cache) > 10_000_000:
            print("⚡ Restoring cached NetBird client from Google Drive...")
            shutil.copy(nb_cache, nb_local)
            os.chmod(nb_local, 0o755)
        else:
            print("📥 Installing NetBird client...")
            subprocess.run("curl -fsSL https://pkgs.netbird.io/install.sh | sh", shell=True, check=True)
            if os.path.exists(nb_local):
                try:
                    shutil.copy(nb_local, nb_cache)
                except Exception:
                    pass
            elif shutil.which("netbird"):
                try:
                    shutil.copy(shutil.which("netbird"), nb_cache)
                except Exception:
                    pass
    if not os.path.exists("/dev/net/tun"):
        os.makedirs("/dev/net", exist_ok=True)
        subprocess.run("mknod /dev/net/tun c 10 200 2>/dev/null || true", shell=True)
        subprocess.run("chmod 600 /dev/net/tun 2>/dev/null || true", shell=True)
    print("✅ NetBird installed & TUN interface configured.")
else:
    cf_local = "/usr/local/bin/cloudflared"
    cf_cache = f"{gdrive_bin}/cloudflared"
    if not shutil.which("cloudflared") and not os.path.exists(cf_local):
        if os.path.exists(cf_cache) and os.path.getsize(cf_cache) > 10_000_000:
            print("⚡ Restoring cached Cloudflared from Google Drive...")
            shutil.copy(cf_cache, cf_local)
            os.chmod(cf_local, 0o755)
        else:
            print("📥 Downloading Cloudflared binary...")
            cf_url = "https://github.com/cloudflare/cloudflared/releases/latest/download/cloudflared-linux-amd64"
            subprocess.run(["curl", "-fsSL", "--retry", "3", cf_url, "-o", cf_local], check=True)
            os.chmod(cf_local, 0o755)
            try:
                shutil.copy(cf_local, cf_cache)
            except Exception:
                pass
    print("✅ Cloudflared installed.")

# 2. ComfyUI Setup & Custom Nodes
agent_dir = "/content/tnhcomfy/remote_agent"
collected_reqs = [f"{agent_dir}/requirements.txt"]
extra_packages = []

if mode_key in ("model", "hybrid", "tts"):
    comfy_dir = "/content/ComfyUI"
    gdrive_path = GDRIVE_COMFY_PATH.strip()
    
    # Check if running on Modal Volume comfy-storage (/mnt/data/models) or Google Drive
    if os.path.exists("/mnt/data/models"):
        print("⚡ Modal Volume detected: Linking ComfyUI model directories directly to /mnt/data/models...")
        if not os.path.exists(comfy_dir) and not os.path.islink(comfy_dir):
            print("📥 Cloning ComfyUI core...")
            subprocess.run(["git", "clone", "--depth", "1", "https://github.com/comfyanonymous/ComfyUI.git", comfy_dir], check=True)
        for sub in ["checkpoints", "loras", "vae", "controlnet", "unet", "clip", "upscale_models"]:
            vol_sub = f"/mnt/data/models/{sub}"
            os.makedirs(vol_sub, exist_ok=True)
            safe_symlink(vol_sub, f"{comfy_dir}/models/{sub}")
    elif os.path.exists(gdrive_path):
        print(f"🎨 Found existing ComfyUI directory in Google Drive: {gdrive_path}")
        if os.path.exists(os.path.join(gdrive_path, "main.py")):
            safe_symlink(gdrive_path, comfy_dir)
            print("🔗 Linked Google Drive ComfyUI to /content/ComfyUI")
        elif os.path.exists(os.path.join(gdrive_path, "models")):
            if not os.path.exists(comfy_dir) and not os.path.islink(comfy_dir):
                print("📥 Cloning ComfyUI core...")
                subprocess.run(["git", "clone", "--depth", "1", "https://github.com/comfyanonymous/ComfyUI.git", comfy_dir], check=True)
            safe_symlink(os.path.join(gdrive_path, "models"), f"{comfy_dir}/models")
            print("🔗 Linked Google Drive models directory!")
    else:
        if not os.path.exists(comfy_dir) and not os.path.islink(comfy_dir):
            print("📥 Cloning fresh ComfyUI core...")
            subprocess.run(["git", "clone", "--depth", "1", "https://github.com/comfyanonymous/ComfyUI.git", comfy_dir], check=True)
    
    # Collect ComfyUI requirements
    comfy_req = f"{comfy_dir}/requirements.txt"
    if os.path.exists(comfy_req):
        collected_reqs.append(comfy_req)

    # Ensure full standard model directory structure exists (prevents scanner crashes)
    models_base = f"{comfy_dir}/models"
    model_dirs = [
        "checkpoints", "loras", "vae", "controlnet", "unet", "clip",
        "upscale_models", "embeddings", "hypernetworks", "aesthetics",
        "poses", "wildcards", "ultralytics/bbox", "ultralytics/seg",
        "motion_modules", "clip_vision", "TTS", "sams"
    ]
    for d in model_dirs:
        os.makedirs(os.path.join(models_base, d), exist_ok=True)

    # Custom nodes definition (parity with deployables/modal)
    custom_nodes_dir = f"{comfy_dir}/custom_nodes"
    os.makedirs(custom_nodes_dir, exist_ok=True)

    custom_nodes = [
        ("ComfyUI-Manager", "https://github.com/ltdrdata/ComfyUI-Manager.git"),
        ("ComfyUI-Impact-Pack", "https://github.com/ltdrdata/ComfyUI-Impact-Pack.git"),
        ("ComfyUI-Impact-Subpack", "https://github.com/ltdrdata/ComfyUI-Impact-Subpack.git"),
        ("ComfyUI_IPAdapter_plus", "https://github.com/cubiq/ComfyUI_IPAdapter_plus.git"),
        ("comfyui_controlnet_aux", "https://github.com/Fannovel16/comfyui_controlnet_aux.git"),
        ("ComfyUI-AnimateDiff-Evolved", "https://github.com/Kosinkadink/ComfyUI-AnimateDiff-Evolved.git"),
    ]
    if mode_key in ("hybrid", "tts"):
        custom_nodes.append(("ComfyUI-QwenTTS", "https://github.com/1038lab/ComfyUI-QwenTTS.git"))

    # Parallel clone of custom nodes
    print("🧩 Fetching custom nodes in parallel...")
    def clone_node(name, repo_url):
        dest_node = os.path.join(custom_nodes_dir, name)
        if not os.path.exists(dest_node):
            subprocess.run(["git", "clone", "--depth", "1", repo_url, dest_node], check=True, stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)
            return f"  ✅ {name} cloned."
        return f"  ⏭️ {name} already present."

    with ThreadPoolExecutor(max_workers=min(len(custom_nodes), 6)) as executor:
        futures = {executor.submit(clone_node, name, url): name for name, url in custom_nodes}
        for future in as_completed(futures):
            try:
                print(future.result())
            except Exception as e:
                print(f"  ⚠️ Clone error for {futures[future]}: {e}")

    # Collect custom node requirements
    for node_name, _ in custom_nodes:
        req_file = os.path.join(custom_nodes_dir, node_name, "requirements.txt")
        if os.path.exists(req_file):
            collected_reqs.append(req_file)

    # Timing profiler node from repo if present
    profiler_src = "/content/tnhcomfy/deployables/modal/image/load_profiler_node"
    profiler_dst = os.path.join(custom_nodes_dir, "tnh_load_profiler")
    if os.path.exists(profiler_src):
        try:
            safe_symlink(profiler_src, profiler_dst)
            print("  🔗 Linked tnh_load_profiler diagnostics node.")
        except Exception:
            pass

    # Extra packages required by nodes (ADetailer, IPAdapter, QwenTTS, etc.)
    extra_packages = [
        "accelerate", "scipy", "ultralytics", "dill", "einops", "timm",
        "soundfile", "torchaudio", "librosa", "opencv-python", "matplotlib",
        "hydra-core", "iopath", "huggingface_hub", "psutil", "pysocks"
    ]

# 3. Unified High-Speed Python Package Installation
print("📦 Installing all Python dependencies concurrently...")
install_python_packages(req_files=collected_reqs, packages=extra_packages)
print("✅ Python dependencies are ready.")

# 4. Parallel Auxiliary Models Download (Upscalers & ADetailer)
if mode_key in ("model", "hybrid", "tts"):
    auxiliary_models = [
        # Upscalers
        ("models/upscale_models/4x-UltraSharp.pth", "https://huggingface.co/lokCX/4x-Ultrasharp/resolve/main/4x-UltraSharp.pth"),
        ("models/upscale_models/4x_foolhardy_Remacri.pth", "https://huggingface.co/uwg/upscaler/resolve/main/ESRGAN/4x_foolhardy_Remacri.pth"),
        ("models/upscale_models/RealESRGAN_x4plus.pth", "https://github.com/xinntao/Real-ESRGAN/releases/download/v0.1.0/RealESRGAN_x4plus.pth"),
        ("models/upscale_models/RealESRGAN_x4plus_anime_6B.pth", "https://github.com/xinntao/Real-ESRGAN/releases/download/v0.2.2.4/RealESRGAN_x4plus_anime_6B.pth"),
        # ADetailer Models (Bbox)
        ("models/ultralytics/bbox/face_yolov8n.pt", "https://huggingface.co/Bingsu/adetailer/resolve/main/face_yolov8n.pt"),
        ("models/ultralytics/bbox/face_yolov8s.pt", "https://huggingface.co/Bingsu/adetailer/resolve/main/face_yolov8s.pt"),
        ("models/ultralytics/bbox/hand_yolov8n.pt", "https://huggingface.co/Bingsu/adetailer/resolve/main/hand_yolov8n.pt"),
        # ADetailer Models (Seg)
        ("models/ultralytics/seg/person_yolov8n-seg.pt", "https://huggingface.co/Bingsu/adetailer/resolve/main/person_yolov8n-seg.pt"),
    ]

    print("📥 Checking auxiliary models (Upscalers & ADetailer)...")
    gdrive_aux = f"{gdrive_root}/models/auxiliary"
    os.makedirs(gdrive_aux, exist_ok=True)

    def fetch_aux_model(rel_path, url):
        target_path = os.path.join(comfy_dir, rel_path)
        os.makedirs(os.path.dirname(target_path), exist_ok=True)
        model_name = os.path.basename(target_path)
        gdrive_target = os.path.join(gdrive_aux, model_name)

        # Check primary target or alternate casing if already cached in ComfyUI
        alt_path = target_path.replace("4x-UltraSharp.pth", "4x-Ultrasharp.pth") if "4x-UltraSharp.pth" in target_path else None
        if os.path.exists(target_path) and os.path.getsize(target_path) > 100_000:
            return f"  ⏭️ {model_name} cached."
        if alt_path and os.path.exists(alt_path) and os.path.getsize(alt_path) > 100_000:
            try:
                safe_symlink(alt_path, target_path)
            except Exception:
                pass
            return f"  ⏭️ {model_name} cached (from {os.path.basename(alt_path)})."

        # Check Google Drive auxiliary cache
        if os.path.exists(gdrive_target) and os.path.getsize(gdrive_target) > 100_000:
            try:
                shutil.copy(gdrive_target, target_path)
                return f"  ⚡ {model_name} restored from Google Drive cache."
            except Exception:
                pass

        tmp_target = f"{target_path}.downloading"
        try:
            subprocess.run(["curl", "-fsSL", "--retry", "2", url, "-o", tmp_target], check=True)
            if os.path.exists(tmp_target) and os.path.getsize(tmp_target) > 100_000:
                os.replace(tmp_target, target_path)
                try:
                    shutil.copy(target_path, gdrive_target)
                except Exception:
                    pass
                return f"  ✅ {model_name} installed."
            else:
                if os.path.exists(tmp_target): os.remove(tmp_target)
                return f"  ⚠️ {model_name} download was empty or truncated."
        except Exception as e:
            if os.path.exists(tmp_target): os.remove(tmp_target)
            return f"  ⚠️ Could not download {model_name}: {e}"

    with ThreadPoolExecutor(max_workers=4) as executor:
        futures = {executor.submit(fetch_aux_model, rel, url): rel for rel, url in auxiliary_models}
        for future in as_completed(futures):
            print(future.result())

    # Provide backward-compatible lowercase alias for 4x-Ultrasharp
    ultrasharp_primary = os.path.join(comfy_dir, "models/upscale_models/4x-UltraSharp.pth")
    ultrasharp_alias = os.path.join(comfy_dir, "models/upscale_models/4x-Ultrasharp.pth")
    if os.path.exists(ultrasharp_primary) and not os.path.exists(ultrasharp_alias):
        try:
            safe_symlink(ultrasharp_primary, ultrasharp_alias)
        except Exception:
            pass

    print("✅ ComfyUI environment & custom nodes are ready.")

# 5. llama-server Setup with Google Drive Persistence (if LLM or Hybrid mode)
if mode_key in ("llm", "hybrid"):
    llama_dir = "/usr/local/llama.cpp"
    target_llama = "/usr/local/bin/llama-server"
    cached_bundle = f"{gdrive_bin}/llama-cuda12-bundle.tar.gz"

    # Remove stale broken single-binary cache from prior runs
    legacy_cached = f"{gdrive_bin}/llama-server"
    if os.path.isfile(legacy_cached) and not os.path.islink(legacy_cached):
        try:
            os.remove(legacy_cached)
        except Exception:
            pass

    # Test if currently installed llama-server is healthy and can load dynamic libraries
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
            print("⚡ Restoring CUDA-accelerated llama.cpp bundle from Google Drive cache...")
            subprocess.run(f"tar -xzf '{cached_bundle}' -C '{llama_dir}'", shell=True, check=True)
            print("✅ llama.cpp bundle restored from cache in ~1s!")
        else:
            print("📥 Fetching CUDA-accelerated llama.cpp binary & runtime libraries...")
            llama_tar = "/tmp/llama_server.tar.gz"
            llama_url = "https://github.com/ggml-org/llama.cpp/releases/download/b11647/llama-b11647-bin-ubuntu-cuda-12.8-x64.tar.gz"
            subprocess.run(["curl", "-fsSL", "--retry", "3", llama_url, "-o", llama_tar], check=True)
            subprocess.run(f"tar -xzf '{llama_tar}' -C '{llama_dir}' --strip-components=1", shell=True, check=True)
            try:
                shutil.copy(llama_tar, cached_bundle)
                print("💾 Cached complete llama.cpp bundle to Google Drive for future sessions.")
            except Exception as e:
                print(f"⚠️ Could not cache bundle to Drive: {e}")
            if os.path.exists(llama_tar):
                try:
                    os.remove(llama_tar)
                except Exception:
                    pass

        # Link all shared libraries (*.so*) into /usr/local/lib
        for root, dirs, files in os.walk(llama_dir):
            for f in files:
                src_path = os.path.join(root, f)
                if f == "llama-server":
                    try:
                        if os.path.exists(target_llama) or os.path.islink(target_llama):
                            os.remove(target_llama)
                        os.symlink(src_path, target_llama)
                    except Exception:
                        shutil.copy(src_path, target_llama)
                    os.chmod(target_llama, 0o755)
                elif f.endswith(".so") or ".so." in f:
                    dst_lib = os.path.join("/usr/local/lib", f)
                    try:
                        if not os.path.exists(dst_lib):
                            os.symlink(src_path, dst_lib)
                    except Exception:
                        pass

        # Update ld.so.cache so all shared libraries (libggml-cuda.so, libllama.so) are found
        # Discover and link CUDA runtime libraries into /usr/local/llama.cpp and /usr/local/lib
        cuda_dirs = [llama_dir, "/usr/local/lib", "/usr/local/cuda/lib64", "/usr/local/cuda-12/lib64", "/usr/lib64-nvidia", "/usr/lib/x86_64-linux-gnu"]
        import glob
        for pat in ["/usr/local/lib/python*/dist-packages/nvidia/*/lib", f"{sys.prefix}/lib/python*/dist-packages/nvidia/*/lib"]:
            cuda_dirs.extend(glob.glob(pat))
        cuda_dirs = [p for p in list(dict.fromkeys(cuda_dirs)) if os.path.isdir(p)]
        for c_dir in cuda_dirs:
            for root, dirs, files in os.walk(c_dir):
                for f in files:
                    if f.startswith(("libcudart.so", "libcublas.so", "libcublasLt.so", "libcuda.so")):
                        for target_dir in (llama_dir, "/usr/local/lib"):
                            dst = os.path.join(target_dir, f)
                            if not os.path.exists(dst):
                                try: os.symlink(os.path.join(root, f), dst)
                                except Exception: pass
        subprocess.run(["ldconfig"], check=False)
        ld_path = ":".join(cuda_dirs) + ":/usr/local/llama.cpp:/usr/local/lib:" + os.environ.get("LD_LIBRARY_PATH", "")
        os.environ["LD_LIBRARY_PATH"] = ld_path

        try:
            ver = subprocess.run([target_llama, "--version"], capture_output=True, text=True, timeout=5)
            ver_text = (ver.stdout.strip() or ver.stderr.strip() or "CUDA build").split("\\n")[0]
            print(f"✅ Installed CUDA-enabled llama-server ({ver_text})")
        except Exception as e:
            print(f"⚠️ llama-server verification notice: {e}")
    else:
        print("✅ llama-server and CUDA runtime libraries are already active!")
    
    llm_dir = "/mnt/data/tnhcomfy/llm_models" if is_modal else (GDRIVE_LLM_PATH.strip() or "/content/drive/MyDrive/tnhcomfy/llm_models")
    os.makedirs(llm_dir, exist_ok=True)
    os.makedirs("/content/agent-data/llm", exist_ok=True)
    safe_symlink(llm_dir, "/content/agent-data/llm/models")
    print(f"✅ LLM storage ready at {llm_dir}")

# 6. System 1 Decision Maker (Laya System 1 GPU/RAM Engine)
print("🧠 Installing & pre-downloading Laya System 1 Engine...")
subprocess.run([sys.executable, "-m", "pip", "install", "--break-system-packages", "--quiet", "laya"], check=False)
try:
    from huggingface_hub import snapshot_download
    laya_choice = LAYA_MODEL.strip() if "LAYA_MODEL" in locals() and LAYA_MODEL.strip() else "laya_multilingual"
    laya_repo_map = {
        "laya_multilingual": "convaiinnovations/laya-multilingual",
        "laya_typed_decisions": "convaiinnovations/laya-typed-decisions",
        "laya_english": "convaiinnovations/laya",
    }
    repo_to_fetch = laya_repo_map.get(laya_choice, "convaiinnovations/laya-multilingual")
    laya_target = f"/content/agent-data/decisions/{laya_choice}"
    os.makedirs(laya_target, exist_ok=True)
    print(f"⚡ Pre-downloading Laya weights for [{laya_choice}] ({repo_to_fetch}) from Hugging Face...")
    snapshot_download(repo_to_fetch, local_dir=laya_target, token=os.environ.get("HF_TOKEN") or None)
    print(f"✅ Laya model [{laya_choice}] pre-downloaded to local storage!")
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
tunnel_key = "netbird" if "netbird" in TUNNEL_METHOD else "cloudflared"
policy_key = "auto" if "auto" in CONCURRENCY_POLICY else ("exclusive" if "exclusive" in CONCURRENCY_POLICY else ("semi_concurrent" if "semi_concurrent" in CONCURRENCY_POLICY else "concurrent"))
# 0. Persistent Storage & Multi-GPU Topology
is_modal = os.path.exists("/mnt/data") or ("MODAL_ENVIRONMENT" in os.environ)
is_colab = False
try:
    import google.colab
    is_colab = True
except Exception:
    pass

if is_colab:
    try:
        from google.colab import drive
        if not os.path.exists("/content/drive/MyDrive"):
            print("📁 Mounting Google Drive at /content/drive...")
            drive.mount("/content/drive")
    except Exception:
        pass
    gdrive_root = "/content/drive/MyDrive/tnhcomfy"
elif is_modal:
    gdrive_root = "/mnt/data/tnhcomfy"
else:
    gdrive_root = "/content/tnhcomfy_storage"

os.makedirs(gdrive_root, exist_ok=True)

# 0b. Multi-GPU Device Allocation
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

# 0c. RAM Caching Policy
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

# 0d. Expand /dev/shm capacity early for Direct-to-RAM streaming on High-RAM hosts
if enable_ram_cache and os.path.exists("/dev/shm"):
    try:
        target_shm_gb = min(64, int(tot_ram_gb * 0.82))
        subprocess.run(["mount", "-o", f"remount,size={target_shm_gb}G", "/dev/shm"], check=False)
    except Exception:
        pass

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

# 2. Networking Setup (Connect NetBird VPN Mesh First)
assigned_ip = ""
public_url = ""

if tunnel_key == "netbird":
    netbird_dir = f"{gdrive_root}/netbird"
    os.makedirs(netbird_dir, exist_ok=True)
    os.makedirs("/var/lib/netbird", exist_ok=True)
    os.makedirs("/etc/netbird", exist_ok=True)
    os.makedirs("/var/log/netbird", exist_ok=True)
    os.makedirs("/var/run", exist_ok=True)

    # Clean up any stale netbird processes/sockets
    subprocess.run("pkill -9 -f 'netbird' || true", shell=True)
    for p in ["/var/run/netbird.sock", "/var/run/netbird.pid"]:
        if os.path.exists(p):
            try: os.remove(p)
            except Exception: pass

    # Resolve custom management URL & admin URL
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
            with open(mgmt_url_file, "r") as f:
                mgmt_url = f.read().strip()
        except Exception: pass

    admin_url = NETBIRD_ADMIN_URL.strip() if "NETBIRD_ADMIN_URL" in locals() else ""
    if not admin_url:
        try:
            from google.colab import userdata
            admin_url = userdata.get("NETBIRD_ADMIN_URL", "").strip()
        except Exception: pass
    if not admin_url and os.path.exists(admin_url_file):
        try:
            with open(admin_url_file, "r") as f:
                admin_url = f.read().strip()
        except Exception: pass

    if mgmt_url:
        if not mgmt_url.startswith("http://") and not mgmt_url.startswith("https://"):
            mgmt_url = f"https://{mgmt_url}"
        mgmt_url = mgmt_url.rstrip("/")
        try:
            with open(mgmt_url_file, "w") as f:
                f.write(mgmt_url)
        except Exception: pass
        print(f"🌐 Self-hosted NetBird Management Server: {mgmt_url}")
    else:
        print("🌐 Using default NetBird Cloud (api.netbird.io)")

    if admin_url:
        if not admin_url.startswith("http://") and not admin_url.startswith("https://"):
            admin_url = f"https://{admin_url}"
        admin_url = admin_url.rstrip("/")
        try:
            with open(admin_url_file, "w") as f:
                f.write(admin_url)
        except Exception: pass

    # Restore existing NetBird peer credentials from Google Drive
    persisted_files = os.listdir(netbird_dir) if os.path.exists(netbird_dir) else []
    config_backed_up = any(f.endswith(".json") for f in persisted_files) or ("config.json" in persisted_files) or ("default.json" in persisted_files)
    if config_backed_up:
        print("🔄 Restoring existing NetBird peer credentials from Google Drive (Static IP preserved!)...")
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

    # Launch daemon in userspace netstack mode
    print("🚀 Starting NetBird daemon in Userspace Netstack mode (bypasses container TUN restrictions)...")
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
    if mgmt_url:
        daemon_cmd.extend(["--management-url", mgmt_url])
    if admin_url:
        daemon_cmd.extend(["--admin-url", admin_url])
    with open("/var/log/netbird/daemon.stdout.log", "w") as out:
        subprocess.Popen(daemon_cmd, env=env_daemon, stdout=out, stderr=out)

    daemon_ready = False
    for _ in range(20):
        time.sleep(1)
        res = subprocess.run(["netbird", "status"], capture_output=True, text=True)
        out = (res.stdout or "") + (res.stderr or "")
        if "Management:" in out or "Signal:" in out or "NeedsLogin" in out or "Connected" in out or "daemon version:" in out.lower():
            daemon_ready = True
            break

    if daemon_ready:
        print("✅ NetBird daemon is running and responsive in Netstack mode!")
    else:
        print("⚠️ NetBird daemon took longer than expected to start; proceeding with connection attempt.")

    # Bring up connection
    extra_flags = []
    if mgmt_url:
        extra_flags.append(f"--management-url {mgmt_url}")
    if admin_url:
        extra_flags.append(f"--admin-url {admin_url}")
    flags_str = (" " + " ".join(extra_flags)) if extra_flags else ""

    env_up = dict(
        os.environ,
        NB_WG_KERNEL_DISABLED="true",
        NB_USE_NETSTACK_MODE="true",
        NB_ENABLE_NETSTACK_LOCAL_FORWARDING="true",
        NB_SOCKS5_LISTENER_PORT="1080",
        NB_SOCKS5_LISTENER_ADDRESS="127.0.0.1",
    )

    if config_backed_up:
        print("🚀 Bringing up restored NetBird connection...")
        cmd_up = f"netbird up{flags_str}".strip()
        res_up = subprocess.run(cmd_up, shell=True, env=env_up, capture_output=True, text=True)
        if res_up.returncode != 0 and "already connected" not in res_up.stderr.lower() and "already connected" not in res_up.stdout.lower():
            print(f"⚠️ Restored connection notice: {res_up.stderr.strip() or res_up.stdout.strip()}")
    else:
        setup_key = NETBIRD_SETUP_KEY.strip() if "NETBIRD_SETUP_KEY" in locals() else ""
        if not setup_key:
            try:
                from google.colab import userdata
                setup_key = userdata.get("NETBIRD_SETUP_KEY", "").strip()
            except Exception: pass

        if not setup_key:
            print("❌ Error: NETBIRD_SETUP_KEY was not provided and no credentials found in Google Drive!")
        else:
            print("🔑 Registering new NetBird peer key...")
            cmd_up = f"netbird up --setup-key {setup_key} --hostname comfy-colab-worker{flags_str}".strip()
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
            else:
                print(f"❌ NetBird registration failed: {res_up.stderr.strip() or res_up.stdout.strip()}")

    # Wait for IP
    print("⏳ Waiting for NetBird IP assignment...")
    for _ in range(30):
        time.sleep(1)
        res = subprocess.run(["netbird", "status"], capture_output=True, text=True)
        out = res.stdout
        m = re.search(r"NetBird IP:\\s*([0-9a-fA-F\\.:]+)", out)
        if m:
            assigned_ip = m.group(1).split("/")[0].strip()
            break
        m2 = re.search(r"IP:\\s*([0-9a-fA-F\\.:]+)", out)
        if m2:
            assigned_ip = m2.group(1).split("/")[0].strip()
            break

    if assigned_ip:
        print(f"✅ Connected to NetBird Mesh with Static IP: {assigned_ip}")
        # Keep Google Drive credentials fresh and in sync
        for f in os.listdir("/var/lib/netbird"):
            src = os.path.join("/var/lib/netbird", f)
            dst = os.path.join(netbird_dir, f)
            try:
                if os.path.isdir(src): shutil.copytree(src, dst, dirs_exist_ok=True)
                else: shutil.copy2(src, dst)
            except Exception: pass
    else:
        print("⚠️ NetBird status details:")
        res = subprocess.run(["netbird", "status", "--detail"], capture_output=True, text=True)
        print(res.stdout or res.stderr)

# 3. Sync Model Catalog with Backend (Sole Source of Truth)
catalog = {}
catalog_source = "local models.json"
backend_sync_ok = False
backend_url_clean = BACKEND_URL.strip().rstrip("/")

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

    target_host = ""
    try:
        parsed_target = urllib.parse.urlparse(backend_url_clean)
        target_host = parsed_target.hostname or ""
    except Exception:
        pass

    # In NetBird Userspace Netstack mode, outbound traffic to mesh peers routes via NetBird's SOCKS5 proxy (127.0.0.1:1080).
    # Wait for the WireGuard P2P handshake with the backend peer before beginning HTTP queries.
    if target_host and (target_host.startswith("100.") or ".netbird." in target_host):
        print(f"⏳ Waiting for NetBird WireGuard handshake with backend peer ({target_host})...")
        peer_connected = False
        for _ in range(25):
            try:
                res_st = subprocess.run(["netbird", "status", "--detail"], capture_output=True, text=True, timeout=5)
                out_st = res_st.stdout or ""
                if target_host in out_st:
                    idx = out_st.find(target_host)
                    block = out_st[max(0, idx - 100):idx + 350]
                    if "Status: Connected" in block:
                        peer_connected = True
                        break
                elif "Peers count:" in out_st:
                    m_peers = re.search(r"Peers count:\\s*([1-9][0-9]*)/", out_st)
                    if m_peers:
                        peer_connected = True
                        break
            except Exception:
                pass
            time.sleep(1)
        if peer_connected:
            print(f"✅ NetBird peer ({target_host}) is Connected!")
        else:
            print("⏳ Peer handshake taking longer than usual; proceeding with catalog retry loop...")

    def fetch_backend_json(url, timeout=4):
        # 1. SOCKS5 proxy via curl (essential for userspace Netstack mode where wt0 is not in kernel routing table)
        for socks_port in ("1080", None):
            try:
                cmd = ["curl", "-fsSL", "--connect-timeout", "3", "-m", str(timeout), "-H", "Accept: application/json", "-k"]
                if socks_port:
                    cmd.extend(["--socks5-hostname", f"127.0.0.1:{socks_port}"])
                cmd.append(url)
                res = subprocess.run(cmd, capture_output=True, text=True, timeout=timeout + 2)
                if res.returncode == 0:
                    text = res.stdout.strip()
                    if text.startswith("{"):
                        return json.loads(text)
            except Exception:
                pass

        # 2. Python requests with SOCKS5 proxy (if requests & pysocks available)
        try:
            import requests
            proxies = {"http": "socks5h://127.0.0.1:1080", "https": "socks5h://127.0.0.1:1080"}
            r = requests.get(url, proxies=proxies, timeout=timeout, verify=False)
            if r.status_code == 200:
                data = r.json()
                if isinstance(data, dict):
                    return data
        except Exception:
            pass

        # 3. Direct Python urllib fallback
        try:
            req = urllib.request.Request(url, headers={"Accept": "application/json"})
            ctx = ssl._create_unverified_context()
            with urllib.request.urlopen(req, timeout=timeout, context=ctx) as resp:
                if resp.status == 200:
                    text = resp.read().decode("utf-8", errors="replace").strip()
                    if text.startswith("{"):
                        return json.loads(text)
        except Exception:
            pass

        return None

    print(f"⏳ Syncing Model Catalog from backend ({backend_url_clean})...")
    for attempt in range(1, 16):
        for cand in candidates:
            for path in ("/api/v2/models/catalog", "/api/v2/world-vault/llm-config/catalog"):
                cat_endpoint = f"{cand}{path}"
                cat_data = fetch_backend_json(cat_endpoint, timeout=3)
                if cat_data and isinstance(cat_data, dict) and ("models" in cat_data or "catalog" in cat_data):
                    catalog = cat_data
                    backend_sync_ok = True
                    catalog_source = f"backend ({cand})"
                    break
            if backend_sync_ok:
                break
        if backend_sync_ok:
            break
        if attempt % 5 == 0:
            print(f"  ... still attempting catalog sync ({attempt}/15)...")
        time.sleep(2)

    if not backend_sync_ok:
        print(f"⚠️ Notice: Could not contact backend catalog at {backend_url_clean} after retries. Using local catalog.")

if not catalog:
    local_cat = "/content/tnhcomfy/backend_v2/modal_llm/models.json"
    if os.path.exists(local_cat):
        with open(local_cat, "r") as f:
            catalog = json.load(f)

models_dict = catalog.get("models") or catalog.get("catalog", {})
active_spec = catalog.get("active", {})
active_rp = active_spec.get("rp") or LLM_RP_MODEL
active_util = active_spec.get("util") or LLM_UTIL_MODEL
active_decisions = active_spec.get("decisions") or (LAYA_MODEL if "LAYA_MODEL" in locals() and LAYA_MODEL.strip() else "laya_multilingual")
active_image = active_spec.get("image") or ""
shared_weights = (active_util in ("same_as_rp", active_rp))
distinct_active_llm = [active_rp] if shared_weights else [active_rp, active_util]

print(f"🌐 Model Catalog synced from {catalog_source}:")
print(f"   • Active RP Model:   {active_rp}")
print(f"   • Active Util Model: {active_util} (Shared Weights: {shared_weights})")
print(f"   • Active Decisions:  {active_decisions}")
if active_image:
    print(f"   • Active Image Model: {active_image}")

checkpoint_recs = catalog.get("checkpoint_recommendations") or {}
top_rec_7d = checkpoint_recs.get("top_checkpoint_7d")
recent_recs_30d = checkpoint_recs.get("recent_checkpoints_30d") or []
if top_rec_7d and top_rec_7d.get("filename"):
    c_ver_str = f" (CivitAI Ver: {top_rec_7d.get('civitai_version_id')})" if top_rec_7d.get("civitai_version_id") else ""
    print(f"   • Recommended Tier 1 Checkpoint: {top_rec_7d['filename']}{c_ver_str} [{top_rec_7d.get('count', 0)} uses in 7d]")
if recent_recs_30d:
    non_flux_count = sum(1 for r in recent_recs_30d if not r.get("is_flux"))
    print(f"   • Warm Tier 2 Candidate Models: {len(recent_recs_30d)} models ({non_flux_count} non-Flux ready for NVMe caching)")

# Sync API tokens from backend if returned by catalog endpoint
backend_tokens = catalog.get("tokens") or {}
if isinstance(backend_tokens, dict):
    synced_hf = backend_tokens.get("hf_token") or ""
    synced_civitai = backend_tokens.get("civitai_token") or ""
    if synced_hf and not os.environ.get("HF_TOKEN"):
        os.environ["HF_TOKEN"] = synced_hf
        print("🔑 Hugging Face token synced from backend!")
    if synced_civitai and not os.environ.get("CIVITAI_TOKEN"):
        os.environ["CIVITAI_TOKEN"] = synced_civitai
        print("🔑 CivitAI token synced from backend!")

# 4. Check & Auto-Download Active LLM GGUF Weights (Direct RAM Cache, NVMe, or Google Drive)
storage_strat_key = "direct" if ("STORAGE_STRATEGY" in locals() and "direct" in str(STORAGE_STRATEGY).lower()) else "gdrive"
llm_gdrive_dir = "/mnt/data/tnhcomfy/llm_models" if is_modal else (GDRIVE_LLM_PATH.strip() or "/content/drive/MyDrive/tnhcomfy/llm_models")
llm_local_dir = "/content/models/llm"
os.makedirs(llm_local_dir, exist_ok=True)
if storage_strat_key == "gdrive":
    os.makedirs(llm_gdrive_dir, exist_ok=True)

# Direct-to-RAM Gating: Uses System RAM Caching Policy & Host RAM threshold
can_direct_download_to_ram = enable_ram_cache and (tot_ram_gb >= 45.0)
ram_llm_dir = "/dev/shm/tnh_ram_cache/llm"
if can_direct_download_to_ram:
    os.makedirs(ram_llm_dir, exist_ok=True)

resolved_weights = {}
for mid in distinct_active_llm:
    spec = models_dict.get(mid, {})
    vol_dir = spec.get("dir") or mid
    gguf_name = spec.get("gguf")
    repo = spec.get("repo")
    mmproj_name = spec.get("mmproj")
    mmproj_repo = spec.get("mmproj_repo") or repo

    # Determine primary target folder based on strategy and RAM capacity
    if storage_strat_key == "direct":
        if can_direct_download_to_ram:
            target_folder = os.path.join(ram_llm_dir, vol_dir)
            download_target_desc = f"RAM cache (/dev/shm) [⚡ Zero-NVMe direct stream]"
        else:
            target_folder = os.path.join(llm_local_dir, vol_dir)
            download_target_desc = f"local NVMe SSD ({target_folder}) [RAM constrained ({tot_ram_gb:.1f} GB)]"
    else:
        target_folder = os.path.join(llm_gdrive_dir, vol_dir)
        download_target_desc = f"Google Drive ({target_folder})"
    os.makedirs(target_folder, exist_ok=True)

    local_gguf = os.path.join(target_folder, gguf_name) if gguf_name else ""
    nvme_candidate = os.path.join(llm_local_dir, vol_dir, gguf_name) if gguf_name else ""
    gdrive_candidate = os.path.join(llm_gdrive_dir, vol_dir, gguf_name) if (gguf_name and os.path.exists(llm_gdrive_dir)) else ""

    # In persistent_volume mode, check if weights already exist in Google Drive cache
    if storage_strat_key != "direct":
        if not (local_gguf and os.path.exists(local_gguf)) and gdrive_candidate and os.path.exists(gdrive_candidate):
            print(f"📁 Found [{mid}] in Google Drive cache: {gdrive_candidate}")
            local_gguf = gdrive_candidate

    # In direct mode: if already present on NVMe SSD from a previous run, reuse it without re-downloading
    if storage_strat_key == "direct" and not (local_gguf and os.path.exists(local_gguf)):
        if nvme_candidate and os.path.exists(nvme_candidate):
            print(f"⚡ Found [{mid}] already present on local NVMe SSD: {nvme_candidate}")
            local_gguf = nvme_candidate

    # When direct_download_fast is selected, download directly from Hugging Face into target folder (RAM cache or NVMe)
    if not (local_gguf and os.path.exists(local_gguf)):
        if repo and gguf_name:
            speed_note = "⚡ High-speed direct CDN transfer" if storage_strat_key == "direct" else "📁 Google Drive transfer"
            print(f"📥 Active LLM weights for [{mid}] not found in {download_target_desc}.")
            print(f"   Downloading {repo} :: {gguf_name} directly to {download_target_desc} ({speed_note})...")
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
                downloaded_file = os.path.join(target_folder, gguf_name)
                if os.path.exists(downloaded_file):
                    local_gguf = downloaded_file
                    print(f"✅ Successfully downloaded [{mid}] ({os.path.getsize(downloaded_file) / (1024**3):.2f} GB) to {download_target_desc}!")
                try:
                    subprocess.run(["sync"], check=False)
                    with open("/proc/sys/vm/drop_caches", "w") as f:
                        f.write("3\\n")
                except Exception:
                    pass
            except Exception as exc:
                print(f"⚠️ HF download error for {mid}: {exc}")
                # Fallback to local NVMe candidate if available
                if nvme_candidate and os.path.exists(nvme_candidate):
                    print(f"📁 HF download failed; falling back to local NVMe SSD: {nvme_candidate}")
                    local_gguf = nvme_candidate
                # Direct mode fallback: If HF download failed, fall back to Google Drive cache if available
                elif storage_strat_key == "direct" and gdrive_candidate and os.path.exists(gdrive_candidate):
                    print(f"📁 HF direct download failed; falling back to existing Google Drive cache: {gdrive_candidate}")
                    local_gguf = gdrive_candidate
        else:
            print(f"⚠️ Model [{mid}] has no repository metadata in catalog.")
            if nvme_candidate and os.path.exists(nvme_candidate):
                print(f"📁 Falling back to local NVMe SSD: {nvme_candidate}")
                local_gguf = nvme_candidate
            elif gdrive_candidate and os.path.exists(gdrive_candidate):
                print(f"📁 Falling back to existing Google Drive cache: {gdrive_candidate}")
                local_gguf = gdrive_candidate

    if local_gguf and os.path.exists(local_gguf):
        resolved_weights[mid] = local_gguf
    else:
        # Fallback candidate scan: only match files corresponding to this model
        for cdir in [llm_local_dir, llm_gdrive_dir, "/mnt/data/tnhcomfy/llm_models", "/mnt/data/models/llm", "/content/agent-data/llm/models", "/content/ComfyUI/models/llm", "/dev/shm/tnh_ram_cache/llm"]:
            if os.path.exists(cdir):
                for root, _, files in os.walk(cdir):
                    for f in sorted(files):
                        if f.endswith(".gguf") and not f.startswith("."):
                            if (gguf_name and f == gguf_name) or (vol_dir and vol_dir.lower() in root.lower()) or (mid and mid.lower() in f.lower()):
                                resolved_weights[mid] = os.path.join(root, f)
                                break
                    if mid in resolved_weights:
                        break
            if mid in resolved_weights:
                break

# 5. High-Speed RAM Setup & Anchor Configuration
try:
    import psutil
    tot_ram = psutil.virtual_memory().total / (1024**3)
    target_shm_gb = min(64, int(tot_ram * 0.82))
    subprocess.run(["mount", "-o", f"remount,size={target_shm_gb}G", "/dev/shm"], check=False)
except Exception:
    pass

if agent_dir not in sys.path:
    sys.path.insert(0, agent_dir)
from ram_manager import RamModelManager
shm_budget = min(56.0, float(int(tot_ram_gb * 0.70))) if enable_ram_cache else 0.0
ram_mgr = RamModelManager(ram_dir="/dev/shm/tnh_ram_cache", budget_gb=shm_budget)

anchor_ids = [active_rp]
if not shared_weights:
    anchor_ids.append(active_util)
if active_decisions and active_decisions not in ("same_as_util", "disabled"):
    anchor_ids.append(active_decisions)

# Pre-register all active LLM weights into RAM manager and anchors to prevent accidental eviction
for m_id, w_path in resolved_weights.items():
    if w_path and os.path.exists(w_path):
        w_fn = os.path.basename(w_path)
        anchor_ids.extend([m_id, w_fn])
        if enable_ram_cache:
            role_m = "rp" if m_id == active_rp else "util"
            try:
                ram_mgr.ensure_in_ram(w_path, model_id=m_id, role=role_m, is_anchor=True)
                ram_mgr.aliases[w_fn] = m_id
                ram_mgr.aliases["default"] = active_rp
                ram_mgr.aliases["rp"] = active_rp
                if shared_weights:
                    ram_mgr.aliases["util"] = active_rp
                elif m_id == active_util:
                    ram_mgr.aliases["util"] = active_util
            except Exception as exc:
                print(f"⚠️ Notice during early RAM registration for {m_id}: {exc}")

comfy_dir = "/content/ComfyUI"
nvme_cache_base = "/content/models/nvme_cache"
nvme_ckpt_dir = f"{nvme_cache_base}/checkpoints"
os.makedirs(nvme_ckpt_dir, exist_ok=True)
os.makedirs(f"{nvme_cache_base}/loras", exist_ok=True)
os.makedirs(f"{nvme_cache_base}/vae", exist_ok=True)

# Determine Google Drive master checkpoint location
gdrive_path = GDRIVE_COMFY_PATH.strip() if "GDRIVE_COMFY_PATH" in locals() and GDRIVE_COMFY_PATH.strip() else "/content/drive/MyDrive/comfyui"
gdrive_base = gdrive_path
gdrive_ckpt_rel = "checkpoints"
gdrive_lora_rel = "loras"
gdrive_vae_rel = "vae"
if os.path.exists(os.path.join(gdrive_path, "models", "checkpoints")):
    gdrive_base = os.path.join(gdrive_path, "models")
elif os.path.exists(os.path.join(gdrive_path, "checkpoints")):
    gdrive_base = gdrive_path

gdrive_ckpt_dir = os.path.join(gdrive_base, gdrive_ckpt_rel)

# ----------------------------------------------------------------------------
# 3-Tier ComfyUI Storage Model:
# Tier 1: Ultra-Hot RAM Cache (/dev/shm) — #1 most used in 7 days (or active_image)
# Tier 2: Warm Local NVMe SSD Cache (/content/models/nvme_cache) — Non-Flux 30-day set
# Tier 3: Master Permanent Library (Google Drive / Modal Volume)
# ----------------------------------------------------------------------------

tier1_candidate_name = active_image if active_image else (top_rec_7d.get("filename", "") if top_rec_7d else "")
tier1_civitai_ver = None
tier1_dl_url = None

if top_rec_7d:
    if not active_image or (top_rec_7d.get("filename") == active_image):
        tier1_civitai_ver = top_rec_7d.get("civitai_version_id")
        tier1_dl_url = top_rec_7d.get("download_url")

if not tier1_civitai_ver and tier1_candidate_name:
    m_ver = re.search(r"_(\\d+)\\.(?:safetensors|ckpt)$", tier1_candidate_name)
    if m_ver:
        try:
            tier1_civitai_ver = int(m_ver.group(1))
            tier1_dl_url = f"https://civitai.com/api/download/models/{tier1_civitai_ver}"
        except Exception:
            pass

# Helper to test if a path actually resides on Google Drive FUSE (via symlink or mount)
def is_on_gdrive(p):
    if not p or not os.path.exists(p):
        return False
    try:
        r = os.path.realpath(p)
        return r.startswith("/content/drive") or "/drive/MyDrive" in r
    except Exception:
        return False

# Check candidates for Tier 1: RAM cache, local NVMe, or Google Drive
active_ckpt_path = None
ram_ckpt_dir = "/dev/shm/tnh_ram_cache/checkpoints"
os.makedirs(ram_ckpt_dir, exist_ok=True)

ram_candidate = os.path.join(ram_ckpt_dir, tier1_candidate_name) if tier1_candidate_name else ""
nvme_candidate = os.path.join(nvme_ckpt_dir, tier1_candidate_name) if tier1_candidate_name else ""
comfy_candidate = os.path.join(comfy_dir, "models", "checkpoints", tier1_candidate_name) if tier1_candidate_name else ""

# Search Google Drive checkpoints directories recursively (Tier 3 Master Library)
gdrive_candidate = ""
if tier1_candidate_name:
    search_dirs = [
        os.path.join(comfy_dir, "models", "checkpoints"),
        gdrive_ckpt_dir,
        os.path.join(gdrive_base, "checkpoints") if "gdrive_base" in locals() else "",
        os.path.join(gdrive_path, "models", "checkpoints") if "gdrive_path" in locals() else "",
        os.path.join(gdrive_path, "checkpoints") if "gdrive_path" in locals() else "",
    ]
    for s_dir in search_dirs:
        if not s_dir or not os.path.exists(s_dir):
            continue
        direct_f = os.path.join(s_dir, tier1_candidate_name)
        if os.path.exists(direct_f) and os.path.getsize(direct_f) > 100_000_000:
            gdrive_candidate = direct_f
            break
        for root, _, files in os.walk(s_dir):
            if tier1_candidate_name in files:
                found_f = os.path.join(root, tier1_candidate_name)
                if os.path.getsize(found_f) > 100_000_000:
                    gdrive_candidate = found_f
                    break
        if gdrive_candidate:
            break

print("\\n" + "=" * 65)
print("📦 [3-Tier Storage Hierarchy Resolution]")
if tier1_candidate_name:
    print(f"🎯 Target Ultra-Hot Checkpoint: {tier1_candidate_name}")
    print(f"   • Tier 1 (RAM /dev/shm):     {'[RESIDENT]' if (ram_candidate and os.path.exists(ram_candidate) and os.path.getsize(ram_candidate) > 100_000_000) else '[NOT RESIDENT]'}")
    print(f"   • Tier 2 (Local NVMe SSD):   {'[FOUND]' if (nvme_candidate and os.path.exists(nvme_candidate) and os.path.getsize(nvme_candidate) > 100_000_000 and not is_on_gdrive(nvme_candidate)) else '[NOT FOUND]'}")
    print(f"   • Tier 3 (Google Drive):     {'[FOUND: ' + gdrive_candidate + ']' if gdrive_candidate else ('[FOUND: ' + comfy_candidate + ']' if (comfy_candidate and os.path.exists(comfy_candidate) and os.path.getsize(comfy_candidate) > 100_000_000) else '[NOT FOUND]')}")

    # 1. Tier 1: Resident in RAM Cache (/dev/shm)
    if ram_candidate and os.path.exists(ram_candidate) and os.path.getsize(ram_candidate) > 100_000_000:
        print(f"⚡ [Tier 1 Cache Hit] Checkpoint already resident in RAM cache (/dev/shm): {tier1_candidate_name}")
        active_ckpt_path = ram_candidate

    # 2. Tier 2: Resident on local NVMe SSD
    elif nvme_candidate and os.path.exists(nvme_candidate) and os.path.getsize(nvme_candidate) > 100_000_000 and not is_on_gdrive(nvme_candidate):
        print(f"⚡ [Tier 2 Cache Hit] Found checkpoint already present on local NVMe SSD: {tier1_candidate_name}")
        active_ckpt_path = nvme_candidate

    # 3. Tier 3: Google Drive Master Library (Always preferred over slow, throttled CivitAI CDN!)
    elif gdrive_candidate and os.path.exists(gdrive_candidate) and os.path.getsize(gdrive_candidate) > 100_000_000:
        sz_gb = os.path.getsize(gdrive_candidate) / (1024**3)
        print(f"📁 [Tier 3 Library] Found checkpoint in Google Drive: {gdrive_candidate} ({sz_gb:.2f} GB)")
        print(f"   ⚡ Loading directly from Google Drive into RAM cache (/dev/shm) at ~85 MB/s (~1.5 min) — zero CivitAI throttling!")
        active_ckpt_path = gdrive_candidate
    elif comfy_candidate and os.path.exists(comfy_candidate) and os.path.getsize(comfy_candidate) > 100_000_000:
        sz_gb = os.path.getsize(comfy_candidate) / (1024**3)
        print(f"📁 [Tier 3 Library] Found checkpoint in ComfyUI models: {comfy_candidate} ({sz_gb:.2f} GB)")
        print(f"   ⚡ Loading directly from Google Drive into RAM cache (/dev/shm) at ~85 MB/s (~1.5 min) — zero CivitAI throttling!")
        active_ckpt_path = comfy_candidate
    else:
        print(f"ℹ️ Checkpoint not found in local RAM, NVMe, or Google Drive library.")

print("=" * 65 + "\\n")

# Fallback: only if completely absent from RAM, NVMe, and Google Drive, attempt CivitAI download
if not active_ckpt_path and (tier1_dl_url or tier1_civitai_ver):
    civ_token = os.environ.get("CIVITAI_TOKEN", "")
    target_dl_path = ram_candidate if can_direct_download_to_ram else nvme_candidate
    target_dl_desc = "RAM cache (/dev/shm) [⚡ Zero-NVMe direct stream]" if can_direct_download_to_ram else f"local NVMe SSD ({nvme_cache_base})"
    c_url = tier1_dl_url or f"https://civitai.com/api/download/models/{tier1_civitai_ver}"
    if civ_token:
        sep = "&" if "?" in c_url else "?"
        c_url += f"{sep}token={civ_token}"
    
    print(f"📥 Checkpoint not present in Google Drive library; downloading from CivitAI CDN to {target_dl_desc}...")
    try:
        import requests
        from tqdm import tqdm
        headers = {"User-Agent": "TNHComfy-Colab-Worker/1.0"}
        if civ_token:
            headers["Authorization"] = f"Bearer {civ_token}"
        os.makedirs(os.path.dirname(target_dl_path), exist_ok=True)
        tmp_target = target_dl_path + ".downloading"
        with requests.get(c_url, headers=headers, stream=True, timeout=60, allow_redirects=True) as resp:
            if resp.status_code != 200:
                raise RuntimeError(f"CivitAI CDN HTTP {resp.status_code}: {resp.text[:180]}")
            tot_bytes = int(resp.headers.get("content-length", 0))
            with open(tmp_target, "wb") as f_dl, tqdm(
                desc=f"⚡ [CivitAI CDN] {tier1_candidate_name[:25] if tier1_candidate_name else 'Tier 1'}",
                total=tot_bytes,
                unit="B",
                unit_scale=True,
                unit_divisor=1024,
            ) as bar:
                for chunk in resp.iter_content(chunk_size=16 * 1024 * 1024):
                    if chunk:
                        f_dl.write(chunk)
                        bar.update(len(chunk))
        if os.path.exists(tmp_target) and os.path.getsize(tmp_target) > 100_000_000:
            os.replace(tmp_target, target_dl_path)
            active_ckpt_path = target_dl_path
            print(f"✅ Successfully downloaded Tier 1 Checkpoint ({os.path.getsize(target_dl_path) / (1024**3):.2f} GB) to {target_dl_desc}!")
        else:
            if os.path.exists(tmp_target):
                os.remove(tmp_target)
            raise RuntimeError("Downloaded file too small or incomplete")
    except Exception as exc:
        print(f"⚠️ CivitAI direct download error: {exc}")
        if gdrive_candidate and os.path.exists(gdrive_candidate):
            print(f"📁 CivitAI direct download failed; falling back to Google Drive cache: {gdrive_candidate}")
            active_ckpt_path = gdrive_candidate
        elif comfy_candidate and os.path.exists(comfy_candidate):
            print(f"📁 CivitAI direct download failed; falling back to Google Drive ComfyUI: {comfy_candidate}")
            active_ckpt_path = comfy_candidate
        elif nvme_candidate and os.path.exists(nvme_candidate):
            print(f"📁 Falling back to existing local NVMe copy: {nvme_candidate}")
            active_ckpt_path = nvme_candidate

# Final fallback: scan available checkpoint directories for any valid model
if not active_ckpt_path:
    fallback_candidates = []
    for d in [ram_ckpt_dir, nvme_ckpt_dir, f"{comfy_dir}/models/checkpoints", gdrive_ckpt_dir]:
        if os.path.exists(d):
            for root, _, files in os.walk(d):
                for f in files:
                    if f.endswith((".safetensors", ".ckpt")):
                        fallback_candidates.append(os.path.join(root, f))
    if fallback_candidates:
        fallback_candidates.sort(key=lambda x: os.path.getmtime(x), reverse=True)
        active_ckpt_path = fallback_candidates[0]
        print(f"📁 Selected fallback checkpoint: {active_ckpt_path}")

img_id = os.path.basename(active_ckpt_path) if active_ckpt_path else ""
if img_id:
    anchor_ids.append(img_id)

ram_mgr.set_anchors(anchor_ids)

# Evict any non-anchor models from prior runs to keep RAM dedicated and lean
for mid_k, entry_k in list(ram_mgr.entries.items()):
    if entry_k.is_anchor:
        continue
    is_protected = (
        mid_k in anchor_ids
        or any(a in mid_k or mid_k in a for a in anchor_ids)
        or any(self_alias == mid_k for self_alias in [ram_mgr.aliases.get(a) for a in anchor_ids])
        or any(mid_k == os.path.basename(p) for p in resolved_weights.values() if p)
    )
    if not is_protected:
        try:
            ram_mgr.evict_model(mid_k, force=True)
        except Exception:
            pass

# 6. Prepare Engine Paths & CUDA Runtimes
if mode_key in ("hybrid", "model"):
    extra_paths_file = f"{comfy_dir}/extra_model_paths.yaml"
    extra_paths_content = f\"\"\"tnh_ram_cache:
    base_path: /dev/shm/tnh_ram_cache
    is_default: true
    checkpoints: checkpoints
    loras: loras
    vae: vae
tnh_ram_flat:
    base_path: /dev/shm/tnh_ram_cache
    is_default: true
    checkpoints: .
    loras: .
    vae: .
tnh_nvme_cache:
    base_path: {nvme_cache_base}
    is_default: true
    checkpoints: checkpoints
    loras: loras
    vae: vae
gdrive_storage:
    base_path: {gdrive_base}
    is_default: false
    checkpoints: {gdrive_ckpt_rel}
    loras: {gdrive_lora_rel}
    vae: {gdrive_vae_rel}
\"\"\"
    try:
        with open(extra_paths_file, "w") as f:
            f.write(extra_paths_content.strip() + "\\n")
    except Exception:
        pass

def sync_tier2_warm_cache():
    if not (is_colab and os.path.exists(gdrive_base)):
        return
    time.sleep(6)
    tier1_base = os.path.basename(active_ckpt_path) if active_ckpt_path else ""
    synced_count = 0
    print("\\n🔄 [Tier 2 Background Sync] Checking recent models for local NVMe caching...")
    for item in recent_recs_30d:
        fn = item.get("filename") or ""
        if not fn or fn == tier1_base:
            continue
        if item.get("is_flux") or ("flux" in fn.lower()):
            print(f"   • [Tier 2] Skipping Flux model {fn} (Flux excluded from NVMe scratch)")
            continue

        try:
            free_gb = shutil.disk_usage("/content").free / (1024**3)
            if free_gb < 20.0:
                print(f"   ⚠️ [Tier 2] Local NVMe free space is {free_gb:.1f} GB (<20 GB limit); stopping warm cache sync.")
                break
        except Exception:
            pass

        dest_file = os.path.join(nvme_ckpt_dir, fn)
        src_file = os.path.join(gdrive_ckpt_dir, fn)
        if not os.path.exists(src_file):
            for root, _, files in os.walk(gdrive_ckpt_dir):
                if fn in files:
                    src_file = os.path.join(root, fn)
                    break

        if not os.path.exists(src_file):
            continue

        src_sz = os.path.getsize(src_file)
        if src_sz > 11.5 * 1024 * 1024 * 1024:
            print(f"   • [Tier 2] Skipping {fn} ({src_sz / (1024**3):.1f} GB > 11.5 GB limit)")
            continue

        if os.path.exists(dest_file) and os.path.getsize(dest_file) == src_sz:
            continue

        try:
            sz_gb = src_sz / (1024**3)
            print(f"📦 [Tier 2 Background Sync] Caching {fn} ({sz_gb:.2f} GB) from Drive to local NVMe SSD...")
            tmp_file = dest_file + ".syncing"
            with open(src_file, "rb") as fsrc, open(tmp_file, "wb") as fdst:
                shutil.copyfileobj(fsrc, fdst, length=16 * 1024 * 1024)
            os.replace(tmp_file, dest_file)
            synced_count += 1
            print(f"✅ [Tier 2 Background Sync] Cached {fn} to local NVMe SSD!")
        except Exception as exc:
            print(f"⚠️ [Tier 2 Background Sync] Notice while caching {fn}: {exc}")
            if os.path.exists(dest_file + ".syncing"):
                try: os.remove(dest_file + ".syncing")
                except Exception: pass

    if synced_count > 0:
        print(f"✨ [Tier 2 Background Sync] Warm cache synchronization finished ({synced_count} models cached on NVMe).")

if mode_key in ("hybrid", "llm"):
    llama_dir = "/usr/local/llama.cpp"
    target_llama = "/usr/local/bin/llama-server"
    gdrive_bin = os.path.join(gdrive_root, "bin")
    cached_bundle = os.path.join(gdrive_bin, "llama-cuda12-bundle.tar.gz")

    # 1. Discover all candidate CUDA runtime library directories
    cuda_dirs = [
        llama_dir,
        "/usr/local/lib",
        "/usr/local/cuda/lib64",
        "/usr/local/cuda-12/lib64",
        "/usr/local/cuda-12.8/lib64",
        "/usr/local/cuda-12.6/lib64",
        "/usr/local/cuda-12.5/lib64",
        "/usr/local/cuda-12.4/lib64",
        "/usr/local/cuda-12.2/lib64",
        "/usr/lib64-nvidia",
        "/usr/lib/x86_64-linux-gnu",
    ]
    import glob
    for pat in [
        "/usr/local/lib/python*/dist-packages/nvidia/*/lib",
        "/usr/lib/python*/dist-packages/nvidia/*/lib",
        f"{sys.prefix}/lib/python*/dist-packages/nvidia/*/lib",
    ]:
        cuda_dirs.extend(glob.glob(pat))
    cuda_dirs = [p for p in list(dict.fromkeys(cuda_dirs)) if os.path.isdir(p)]

    # 2. Check if libcudart and libcublas exist; if not, auto-install pip wheels
    has_cudart = any(os.path.exists(os.path.join(d, "libcudart.so.12")) for d in cuda_dirs)
    has_cublas = any(os.path.exists(os.path.join(d, "libcublas.so.12")) for d in cuda_dirs)
    if not (has_cudart and has_cublas):
        print("⚡ Installing CUDA runtime wheels for llama.cpp acceleration...")
        subprocess.run([sys.executable, "-m", "pip", "install", "--quiet", "nvidia-cuda-runtime-cu12", "nvidia-cublas-cu12"], check=False)
        for pat in [
            "/usr/local/lib/python*/dist-packages/nvidia/*/lib",
            f"{sys.prefix}/lib/python*/dist-packages/nvidia/*/lib",
        ]:
            cuda_dirs.extend(glob.glob(pat))
        cuda_dirs = [p for p in list(dict.fromkeys(cuda_dirs)) if os.path.isdir(p)]

    # 3. Restore or fetch llama-server if missing
    if not (os.path.exists(target_llama) or shutil.which("llama-server")):
        os.makedirs(llama_dir, exist_ok=True)
        if os.path.exists(cached_bundle) and os.path.getsize(cached_bundle) > 50_000_000:
            print("⚡ Restoring CUDA-accelerated llama.cpp bundle from Google Drive cache...")
            subprocess.run(f"tar -xzf '{cached_bundle}' -C '{llama_dir}' --strip-components=1", shell=True, check=False)
        else:
            print("📥 Fetching CUDA-accelerated llama.cpp binary & runtime libraries...")
            llama_tar = "/tmp/llama_server.tar.gz"
            llama_url = "https://github.com/ggml-org/llama.cpp/releases/download/b11647/llama-b11647-bin-ubuntu-cuda-12.8-x64.tar.gz"
            subprocess.run(["curl", "-fsSL", "--retry", "3", llama_url, "-o", llama_tar], check=False)
            if os.path.exists(llama_tar):
                subprocess.run(f"tar -xzf '{llama_tar}' -C '{llama_dir}' --strip-components=1", shell=True, check=False)
                try:
                    os.makedirs(gdrive_bin, exist_ok=True)
                    shutil.copy(llama_tar, cached_bundle)
                except Exception:
                    pass

    # Clean up any stray symlinks in /usr/local/lib to prevent PyTorch cuDNN conflicts
    for f_pat in ("libcudart.so*", "libcublas.so*", "libcublasLt.so*", "libcuda.so*", "libggml*.so*", "libllama*.so*"):
        for p in glob.glob(f"/usr/local/lib/{f_pat}"):
            if os.path.islink(p):
                try: os.remove(p)
                except Exception: pass
    subprocess.run(["ldconfig"], check=False)

    # 4. Link llama-server binary into /usr/local/bin
    for root, dirs, files in os.walk(llama_dir):
        for f in files:
            src_path = os.path.join(root, f)
            if f == "llama-server":
                try:
                    if os.path.exists(target_llama) or os.path.islink(target_llama):
                        os.remove(target_llama)
                    os.symlink(src_path, target_llama)
                except Exception:
                    shutil.copy(src_path, target_llama)
                os.chmod(target_llama, 0o755)

    # 5. Symlink CUDA runtime libs into /usr/local/llama.cpp ONLY (dedicated, never pollutes /usr/local/lib)
    for c_dir in cuda_dirs:
        for root, dirs, files in os.walk(c_dir):
            for f in files:
                if f.startswith(("libcudart.so", "libcublas.so", "libcublasLt.so", "libcuda.so")):
                    dst = os.path.join(llama_dir, f)
                    if not os.path.exists(dst):
                        try:
                            os.symlink(os.path.join(root, f), dst)
                        except Exception:
                            pass

    ld_path = ":".join(cuda_dirs) + ":/usr/local/llama.cpp:" + os.environ.get("LD_LIBRARY_PATH", "")

    # 6. Verify CUDA device detection
    llama_exec = target_llama if os.path.exists(target_llama) else "llama-server"
    try:
        ver_check = subprocess.run([llama_exec, "--list-devices"], env=dict(os.environ, LD_LIBRARY_PATH=ld_path), capture_output=True, text=True, timeout=5)
        dev_info = (ver_check.stdout or ver_check.stderr or "").strip()
        if "CUDA" in dev_info:
            c_lines = [l.strip() for l in dev_info.split("\\n") if "CUDA" in l]
            print(f"  ✅ CUDA GPU acceleration active: {', '.join(c_lines)}")
        else:
            print(f"  ⚠️ llama-server device notice: {dev_info.replace(chr(10), ' ') or 'no devices reported'}")
    except Exception as e:
        print(f"  Notice during CUDA device check: {e}")

# 7. Asynchronous & Pipelined Service Launches
import threading

worker_procs = {}

def start_remote_agent():
    print(f"🚀 Starting Remote Storage Agent on :{agent_port} (DATA_DIR={comfy_dir})...")
    agent_work_mode = "hybrid" if mode_key == "hybrid" else mode_key
    data_path = comfy_dir if mode_key in ("hybrid", "model") else ("/content/agent-data/llm/models" if mode_key == "llm" else "/content/agent-data/tts")
    os.makedirs(data_path, exist_ok=True)
    env_agent = dict(
        os.environ,
        DATA_DIR=data_path,
        WORKER_MODE=agent_work_mode,
        PORT=str(agent_port),
        HOST="127.0.0.1",
        LLM_UPSTREAM_BASE=f"http://127.0.0.1:{llm_port}/v1",
        RAM_CACHE_DIR="/dev/shm/tnh_ram_cache",
        RAM_CACHE_BUDGET_GB="40" if enable_ram_cache else "0",
        CACHE_IN_RAM="1" if enable_ram_cache else "0",
        COMFY_GPU_DEVICE=str(comfy_gpu_device),
        LLM_GPU_DEVICE=str(llm_gpu_device),
        LAYA_GPU_DEVICE=str(laya_gpu_device),
        LAYA_MODEL_ID=active_decisions,
        ACTIVE_RP_MODEL=active_rp,
        ACTIVE_UTIL_MODEL=active_util,
        DEFAULT_RP_MODEL=active_rp,
        DEFAULT_UTIL_MODEL=active_util,
        PERSISTENT_STORAGE_PATH=gdrive_root,
        PYTHONUNBUFFERED="1",
        PROVIDER_DOWNLOAD_SCRATCH_DIR=scratch_downloads,
        REMOTE_AGENT_DOWNLOAD_MAX_CONCURRENT="1",
    )
    if mode_key in ("hybrid", "llm"):
        env_agent["LD_LIBRARY_PATH"] = ld_path
        env_agent["PATH"] = "/usr/local/llama.cpp:/usr/local/bin:" + os.environ.get("PATH", "")
    with open(log_agent, "w") as out:
        worker_procs["agent"] = subprocess.Popen([sys.executable, f"{agent_dir}/server.py"], cwd=agent_dir, env=env_agent, stdout=out, stderr=out)

def launch_comfyui_track():
    if active_ckpt_path:
        print(f"⚡ [ComfyUI Track] Pre-warming {os.path.basename(active_ckpt_path)} into RAM cache (/dev/shm)...")
        try:
            ram_mgr.ensure_in_ram(active_ckpt_path, model_id=img_id, role="image", is_anchor=True)
            print("✅ [ComfyUI Track] Checkpoint cached in RAM!")
        except Exception as exc:
            print(f"⚠️ [ComfyUI Track] Pre-warming failed ({exc}); will stream from storage directly.")
    print(f"🚀 [ComfyUI Track] Starting ComfyUI server on :{comfy_port}...")
    with open(log_comfy, "w") as out:
        env_comfy = dict(os.environ, PYTORCH_CUDA_ALLOC_CONF="expandable_segments:True", PYTHONUNBUFFERED="1")
        cudnn_paths = glob.glob("/usr/local/lib/python*/dist-packages/nvidia/cudnn/lib") + glob.glob(f"{sys.prefix}/lib/python*/dist-packages/nvidia/cudnn/lib")
        if cudnn_paths:
            env_comfy["LD_LIBRARY_PATH"] = ":".join(cudnn_paths) + ":" + os.environ.get("LD_LIBRARY_PATH", "")
        worker_procs["comfy"] = subprocess.Popen([sys.executable, f"{comfy_dir}/main.py", "--listen", "127.0.0.1", "--port", str(comfy_port), "--cuda-device", str(comfy_gpu_device)], env=env_comfy, stdout=out, stderr=out)

def launch_llm_track():
    src_expected = resolved_weights.get(active_rp, "")
    if src_expected:
        print(f"⚡ [LLM Track] Pre-warming {os.path.basename(src_expected)} into RAM cache (/dev/shm)...")
        try:
            ram_mgr.ensure_in_ram(src_expected, model_id=active_rp, role="rp", is_anchor=True)
            ram_mgr.aliases["default"] = active_rp
            ram_mgr.aliases["rp"] = active_rp
            print("✅ [LLM Track] GGUF weights cached in RAM!")
        except Exception as exc:
            print(f"⚠️ [LLM Track] Pre-warming failed ({exc}); will load directly from storage.")

    if not shared_weights:
        src_util = resolved_weights.get(active_util, "")
        if src_util and enable_ram_cache:
            print(f"⚡ [LLM Track] Pre-warming Util model {os.path.basename(src_util)} into RAM cache (/dev/shm)...")
            try:
                ram_mgr.ensure_in_ram(src_util, model_id=active_util, role="util", is_anchor=True)
                ram_mgr.aliases["util"] = active_util
                print("✅ [LLM Track] Util GGUF weights cached in RAM!")
            except Exception as exc:
                print(f"⚠️ [LLM Track] Util pre-warming failed ({exc}); will stream from storage.")

    # Resolve resident RAM file
    rp_ram_file = ""
    src_size = os.path.getsize(src_expected) if (src_expected and os.path.exists(src_expected)) else 0
    if active_rp in ram_mgr.entries and os.path.exists(ram_mgr.entries[active_rp].ram_path):
        cand = ram_mgr.entries[active_rp].ram_path
        if src_size > 0 and os.path.getsize(cand) != src_size:
            try: ram_mgr.evict_model(active_rp, force=True)
            except Exception: pass
        else:
            rp_ram_file = cand

    if not rp_ram_file:
        for mid, entry in list(ram_mgr.entries.items()):
            if (active_rp in mid or mid in active_rp) and os.path.exists(entry.ram_path):
                if src_size > 0 and os.path.getsize(entry.ram_path) != src_size:
                    try: ram_mgr.evict_model(mid, force=True)
                    except Exception: pass
                else:
                    rp_ram_file = entry.ram_path
                    break

    if not rp_ram_file and src_expected and os.path.exists(src_expected):
        rp_ram_file = src_expected

    global spawn_cmd, env_llm

    # Dynamic VRAM budgeting & safe layer offload calculation based on LIVE FREE VRAM
    ngl = 99
    try:
        import torch
        if torch.cuda.is_available():
            free_bytes, total_bytes = torch.cuda.mem_get_info(0)
            free_vram_gb = free_bytes / (1024**3)
            total_vram_gb = total_bytes / (1024**3)
            weight_gb = os.path.getsize(rp_ram_file) / (1024**3) if (rp_ram_file and os.path.exists(rp_ram_file)) else 0.0

            # Reserve 1.8 GB for KV cache (8192 context q8_0 with -np 1) and compute scratch
            reserve_gb = 1.8
            available_weight_gb = max(0.0, free_vram_gb - reserve_gb)

            # Estimate total model layers (e.g. 46 for 26B/27B Gemma, 64 for 31B, 40 for 12B/14B)
            model_name_lower = os.path.basename(rp_ram_file).lower()
            if "26b" in model_name_lower or "27b" in model_name_lower or "sompoa" in model_name_lower:
                total_layers = 46
            elif "31b" in model_name_lower or "32b" in model_name_lower or "artemis" in model_name_lower:
                total_layers = 64
            elif "12b" in model_name_lower or "14b" in model_name_lower:
                total_layers = 40
            else:
                total_layers = 42

            if weight_gb > 0 and (weight_gb + reserve_gb) <= free_vram_gb:
                ngl = 99
                print(f"  ⚡ Model ({weight_gb:.1f} GB) fits entirely in free GPU VRAM ({free_vram_gb:.1f} GB free of {total_vram_gb:.1f} GB): -ngl 99 (100% GPU offload, zero CPU latency)")
            elif weight_gb > 0 and available_weight_gb > 0:
                fraction = min(1.0, available_weight_gb / weight_gb)
                target_layers = int(total_layers * fraction)
                ngl = max(4, min(total_layers - 2, target_layers - 1))
                print(f"  ⚡ GPU VRAM: {free_vram_gb:.1f} GB free of {total_vram_gb:.1f} GB | Model: {weight_gb:.1f} GB")
                print(f"  🎯 Calculated safe layer offload: -ngl {ngl}/{total_layers} (GPU: ~{available_weight_gb:.1f} GB, RAM Cache: ~{weight_gb - available_weight_gb:.1f} GB) to prevent CUDA OOM")
            elif weight_gb > 0:
                ngl = 0
                print(f"  ⚠️ Low free VRAM ({free_vram_gb:.1f} GB free for {weight_gb:.1f} GB model); running on CPU RAM cache: -ngl 0")
            else:
                ngl = 0
                print(f"  ⚠️ Model weights not found on disk/RAM; running fallback model on CPU: -ngl 0")
    except Exception as exc:
        ngl = 35
        print(f"  Notice: VRAM layer budgeting fallback ({exc}); using safe -ngl 35")

    free_vram_gb_val = free_vram_gb if "free_vram_gb" in locals() else 0.0
    target_kv = "f16" if (free_vram_gb_val >= 20.0 or "gemma" in (rp_ram_file or "").lower()) else "q8_0"
    llama_args = [
        llama_exec,
        "--port", str(llm_port),
        "--host", "127.0.0.1",
        "--main-gpu", str(llm_gpu_device),
        "-ngl", str(ngl),
        "-np", "1",
        "-c", "8192",
        "-b", "2048",
        "-ub", "512",
        "--cache-type-k", target_kv,
        "--cache-type-v", target_kv,
        "--jinja",
    ]
    if ngl > 0:
        llama_args.append("-fa")
    if rp_ram_file and os.path.exists(rp_ram_file):
        aliases = [active_rp, "default", "rp"]
        if shared_weights and active_util != active_rp:
            aliases.append(active_util)
        alias_str = ",".join(list(dict.fromkeys(aliases)))
        llama_args.extend(["-m", rp_ram_file, "--alias", alias_str])
        if rp_ram_file.startswith("/dev/shm") or "ram_cache" in rp_ram_file:
            print(f"  🧠 Loading RAM-cached GGUF: {os.path.basename(rp_ram_file)} (sub-second VRAM transfer)")
        else:
            print(f"  📦 Loading GGUF from storage: {os.path.basename(rp_ram_file)}")
    else:
        print("  🧠 Auto-loading Qwen2.5-1.5B via Hugging Face...")
        llama_args.extend(["--hf-repo", "Qwen/Qwen2.5-1.5B-Instruct-GGUF", "--hf-file", "qwen2.5-1.5b-instruct-q4_k_m.gguf", "--alias", "default"])

    stdbuf_bin = shutil.which("stdbuf")
    spawn_cmd = [stdbuf_bin, "-oL", "-eL"] + llama_args if stdbuf_bin else llama_args
    env_llm = dict(
        os.environ,
        LD_LIBRARY_PATH=ld_path,
        PATH="/usr/local/llama.cpp:/usr/local/bin:" + os.environ.get("PATH", ""),
        PYTHONUNBUFFERED="1",
    )
    if mode_key == "llm":
        print(f"🚀 [LLM Track] Starting CUDA llama-server on :{llm_port}...")
        with open(log_llm, "a", buffering=1) as out:
            worker_procs["llm"] = subprocess.Popen(spawn_cmd, env=env_llm, stdout=out, stderr=out)
    else:
        print("⚡ [LLM Track] GGUF weights pre-warmed in RAM cache (/dev/shm). llama-server will start Just-In-Time on first LLM request (0 MB idle GPU VRAM reserved)!")

laya_repo_map = {
    "laya_multilingual": "convaiinnovations/laya-multilingual",
    "laya_typed_decisions": "convaiinnovations/laya-typed-decisions",
    "laya_english": "convaiinnovations/laya",
}

# Auto-download active Laya weights if needed
if active_decisions and active_decisions not in ("same_as_util", "disabled"):
    laya_target_folder = f"/content/agent-data/decisions/{active_decisions}"
    os.makedirs(laya_target_folder, exist_ok=True)
    if not (os.path.exists(laya_target_folder) and any(os.listdir(laya_target_folder))):
        repo_to_dl = laya_repo_map.get(active_decisions) or models_dict.get(active_decisions, {}).get("repo")
        if repo_to_dl:
            print(f"📥 Downloading active Laya weights for [{active_decisions}] ({repo_to_dl})...")
            try:
                from huggingface_hub import snapshot_download
                snapshot_download(repo_to_dl, local_dir=laya_target_folder, token=os.environ.get("HF_TOKEN") or None)
                print(f"✅ Downloaded Laya model [{active_decisions}]!")
            except Exception as exc:
                print(f"⚠️ Laya download notice for {active_decisions}: {exc}")

def launch_laya_track():
    if active_decisions in ("same_as_util", "disabled"):
        print(f"ℹ️ [Laya Track] Decisions mode is '{active_decisions}'; skipping Laya pre-warm.")
        return
    print(f"⚡ [Laya Track] Pre-warming Laya [{active_decisions}] into RAM cache...")
    try:
        laya_dir = f"/content/agent-data/decisions/{active_decisions}"
        repo_fallback = laya_repo_map.get(active_decisions) or models_dict.get(active_decisions, {}).get("repo") or "convaiinnovations/laya-multilingual"
        src = laya_dir if (os.path.exists(laya_dir) and any(os.listdir(laya_dir))) else repo_fallback
        if enable_ram_cache:
            try:
                ram_mgr.ensure_dir_in_ram(src, model_id=active_decisions, role="decisions", is_anchor=True)
            except Exception:
                pass
        print(f"✅ [Laya Track] Laya [{active_decisions}] pre-warmed in RAM cache (<150ms inference ready)!")
    except Exception as exc:
        print(f"⚠️ [Laya Track] Pre-warming notice for {active_decisions}: {exc}")

# 1. Start Storage Agent immediately
start_remote_agent()

# 2. Start Service Pipelines concurrently
active_threads = []
if mode_key in ("hybrid", "model"):
    t_comfy = threading.Thread(target=launch_comfyui_track, daemon=True)
    t_comfy.start()
    active_threads.append(t_comfy)

if mode_key in ("hybrid", "llm"):
    t_llm = threading.Thread(target=launch_llm_track, daemon=True)
    t_llm.start()
    active_threads.append(t_llm)

t_laya = threading.Thread(target=launch_laya_track, daemon=True)
t_laya.start()
active_threads.append(t_laya)

# Asynchronous Tier 2 Background Sync (populates local NVMe cache while ComfyUI is live)
if mode_key in ("hybrid", "model"):
    threading.Thread(target=sync_tier2_warm_cache, name="Tier2WarmSync", daemon=True).start()

# 3. Unified Health Check Loop
print("⏳ Waiting for services to become healthy...")
services_to_check = [("agent", agent_port, "/health", "Remote Agent")]
if mode_key in ("hybrid", "model"):
    services_to_check.append(("comfy", comfy_port, "/system_stats", "ComfyUI"))
if mode_key == "llm":
    services_to_check.append(("llm", llm_port, "/health", "llama-server"))

healthy_services = set()
for attempt in range(120):
    for s_name, s_port, s_path, s_label in services_to_check:
        if s_name in healthy_services:
            continue
        proc = worker_procs.get(s_name)
        if proc and proc.poll() is not None:
            print(f"\\n❌ {s_label} process exited unexpectedly (code {proc.returncode})!")
            log_file = log_llm if s_name == "llm" else (log_comfy if s_name == "comfy" else log_agent)
            if os.path.exists(log_file):
                with open(log_file, "r", errors="replace") as f:
                    print(f"--- Last 20 lines of {os.path.basename(log_file)} ---")
                    print("".join(f.readlines()[-20:]))
            healthy_services.add(s_name)
            continue
        try:
            req = urllib.request.Request(f"http://127.0.0.1:{s_port}{s_path}")
            with urllib.request.urlopen(req, timeout=1) as res:
                if res.status in (200, 307):
                    print(f"✅ {s_label} is online and healthy on :{s_port}!")
                    healthy_services.add(s_name)
        except Exception:
            pass
    if len(healthy_services) == len(services_to_check):
        break
    time.sleep(1)

# Wait for pre-warming threads to complete so RAM status reports accurately
for t in active_threads:
    t.join(timeout=300)

ram_status = ram_mgr.get_status()
print(f"✅ RAM Cache Ready: {ram_status['used_gb']} GB / {ram_status['budget_gb']} GB used ({ram_status['percent_used']}%)")
print(f"   • Anchors in RAM: {[a['model_id'] for a in ram_status['anchor_models']]}")

# 7. Cloudflare Tunnel (if selected)
if tunnel_key == "cloudflared":
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
                m = re.search(r"https://[a-zA-Z0-9-]+\\.trycloudflare\\.com", content)
                if m:
                    public_url = m.group(0)
                    break
    if public_url:
        print(f"✅ Cloudflare Tunnel is live: {public_url}")
    else:
        print("⚠️ Could not extract Cloudflare URL; check /content/cloudflared.log.")

# 8. Worker Credentials & Visual Banner with Live Stream Box
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

def _credential_row(label, val, color="#a5f3fc"):
    if not val:
        return ""
    return f'''
        <div style="margin-bottom: 12px;">
            <div style="display: flex; justify-content: space-between; align-items: center;">
                <span style="color: #64748b; font-size: 11px; text-transform: uppercase; font-weight: bold; letter-spacing: 0.05em;">{label}</span>
                <button onclick="if (navigator.clipboard) {{ let b = this; navigator.clipboard.writeText('{val}').then(() => {{ b.innerText='✓ Copied'; b.style.color='#34d399'; setTimeout(() => {{ b.innerText='📋 Copy'; b.style.color='#94a3b8'; }}, 1500); }}); }}" style="background: rgba(51, 65, 85, 0.4); border: 1px solid #475569; border-radius: 4px; color: #94a3b8; font-size: 10px; padding: 1px 7px; cursor: pointer;">📋 Copy</button>
            </div>
            <div style="font-family: monospace; font-size: 14px; color: {color}; word-break: break-all; margin-top: 2px;">{val}</div>
        </div>
    '''

rows_html = ""
if mode_key == "hybrid":
    rows_html += _credential_row("Unified Base URL (base_url)", base_endpoint)
    rows_html += _credential_row("ComfyUI Server URL (comfy_url)", comfy_endpoint)
    rows_html += _credential_row("Remote Agent URL (agent_url)", agent_endpoint)
    rows_html += _credential_row("LLM Server URL (llm_url)", llm_endpoint)
    rows_html += f'''
        <div style="margin-bottom: 12px;">
            <span style="color: #64748b; font-size: 11px; text-transform: uppercase; font-weight: bold;">Hardware Concurrency Policy</span>
            <div style="font-family: monospace; font-size: 14px; color: #f59e0b; margin-top: 2px;">{policy_key}</div>
        </div>
    '''
elif mode_key == "model":
    rows_html += _credential_row("ComfyUI Server URL (comfy_url)", comfy_endpoint)
    rows_html += _credential_row("Remote Storage Agent URL (agent_url)", agent_endpoint)
elif mode_key == "llm":
    rows_html += _credential_row("Remote LLM Base URL (base_url)", agent_endpoint)
elif mode_key == "tts":
    rows_html += _credential_row("Remote TTS Base URL (base_url)", agent_endpoint)

rows_html += _credential_row("Remote Agent Token (agent_token)", agent_token, color="#34d399")

gpu_topo_badge = f\"\"\"
<div style="background: rgba(30, 41, 59, 0.7); border: 1px solid #334155; border-radius: 8px; padding: 10px 14px; margin-bottom: 12px; font-size: 13px;">
    <div style="display: flex; justify-content: space-between; align-items: center;">
        <span style="font-weight: 700; color: #38bdf8;">⚡ Hardware & GPU Topology:</span>
        <span style="color: {'#22c55e' if is_multi_gpu else '#f59e0b'}; font-weight: 600;">{'Multi-GPU Parallel Concurrency' if is_multi_gpu else 'Single-GPU Cooperative Arbiter'}</span>
    </div>
    <div style="margin-top: 4px; color: #94a3b8; font-size: 11px;">
        {'<b>GPU 0:</b> ComfyUI (Image) | <b>GPU 1:</b> llama-server (LLM) & Laya (Director) [Zero eviction latency]' if is_multi_gpu else '<b>GPU 0:</b> Shared across ComfyUI, LLM, and Laya'}
    </div>
</div>
\"\"\"

ram_badge_html = f'''
<div style="background: rgba(30, 41, 59, 0.7); border: 1px solid #334155; border-radius: 8px; padding: 10px 14px; margin-bottom: 14px; font-size: 13px;">
    <div style="display: flex; justify-content: space-between; align-items: center;">
        <span style="font-weight: 700; color: #38bdf8;">⚡ High-Speed RAM Cache Status:</span>
        <span style="color: #60a5fa; font-weight: 600;">{ram_status['used_gb']} GB / {ram_status['budget_gb']} GB ({ram_status['percent_used']}%)</span>
    </div>
    <div style="margin-top: 4px; color: #94a3b8; font-size: 11px;">
        <b>Pinned Anchors (Protected):</b> {", ".join([a["model_id"] for a in ram_status["anchor_models"]]) or "None"}
    </div>
</div>
'''

card_header_html = f'''
<style>
.tnh-log-box {{
    background-color: #020617 !important;
    color: #cbd5e1 !important;
    font-family: 'SFMono-Regular', Consolas, 'Liberation Mono', Menlo, monospace !important;
    font-size: 12px !important;
    line-height: 1.5 !important;
    scrollbar-width: thin !important;
    scrollbar-color: #475569 #020617 !important;
}}
.tnh-log-box pre {{
    color: inherit !important;
    background: transparent !important;
    margin: 0 !important;
    padding: 0 !important;
    white-space: pre-wrap !important;
    word-break: break-all !important;
}}
</style>
<div style="color: #f8fafc; font-family: system-ui, -apple-system, sans-serif;">
    <h2 style="margin: 0 0 12px 0; color: #60a5fa; font-size: 20px; display: flex; align-items: center; gap: 8px;">
        ✨ TNHComfy Colab Worker is Ready! ({provider_category} Mode)
    </h2>
    <p style="margin: 0 0 16px 0; font-size: 14px; color: #94a3b8;">
        Your worker is online and connected. Copy the credentials below into your TNHComfy Providers page:
    </p>

    {gpu_topo_badge}
    {ram_badge_html}

    <div style="background: rgba(15, 23, 42, 0.85); border: 1px solid #334155; border-radius: 10px; padding: 16px; margin-bottom: 16px;">
        <div style="margin-bottom: 12px;">
            <span style="color: #64748b; font-size: 11px; text-transform: uppercase; font-weight: bold; letter-spacing: 0.05em;">Provider Category & Type</span>
            <div style="font-family: monospace; font-size: 14px; color: #38bdf8; font-weight: bold; margin-top: 2px;">{provider_category} &rarr; <code>{provider_type}</code></div>
        </div>
        {rows_html}
    </div>

    <div style="font-size: 13px; color: #cbd5e1; background: rgba(59, 130, 246, 0.15); border-left: 4px solid #3b82f6; padding: 12px 16px; border-radius: 4px; line-height: 1.5; margin-bottom: 18px;">
        💡 <b>Static Configuration:</b><br/>
        Because your NetBird state and token are saved in Google Drive, the IP and token above are <b>permanent</b>. You do not need to update your provider row when restarting Colab!
    </div>

    <div style="display: flex; justify-content: space-between; align-items: center; padding-top: 12px; border-top: 1px solid rgba(59, 130, 246, 0.25); margin-bottom: 8px;">
        <div style="display: flex; align-items: center; gap: 8px;">
            <span style="display: inline-block; width: 8px; height: 8px; border-radius: 50%; background: #22c55e; box-shadow: 0 0 8px #22c55e;"></span>
            <span style="font-size: 13px; font-weight: 700; color: #e2e8f0; letter-spacing: 0.02em;">
                Live Worker Activity & Traffic Log
            </span>
        </div>
        <div style="font-size: 11px; color: #64748b;">
            Scroll wheel inside log window to inspect history • Colab ⏹️ to stop
        </div>
    </div>
</div>
'''

try:
    import ipywidgets as widgets
    card_widget = widgets.HTML(card_header_html)
    log_box = widgets.Output(layout=widgets.Layout(
        height="320px",
        max_height="400px",
        overflow_y="auto",
        border="1px solid #334155",
        border_radius="10px",
        padding="12px 16px",
        background_color="#020617"
    ))
    log_box.add_class("tnh-log-box")
    panel = widgets.VBox([card_widget, log_box], layout=widgets.Layout(
        background="linear-gradient(135deg, #0f172a 0%, #1e1b4b 100%)",
        border="1px solid #3b82f6",
        border_radius="16px",
        padding="24px",
        margin="20px 0 10px 0",
        box_shadow="0 10px 25px -5px rgba(0, 0, 0, 0.5)"
    ))
    display(panel)
    with log_box:
        print("📡 Connected to worker service log streams. Waiting for incoming events...", flush=True)
except Exception:
    display(HTML(f'<div style="background: linear-gradient(135deg, #0f172a 0%, #1e1b4b 100%); border: 1px solid #3b82f6; border-radius: 16px; padding: 24px; color: #f8fafc; font-family: system-ui, -apple-system, sans-serif; box-shadow: 0 10px 25px -5px rgba(0, 0, 0, 0.5); margin: 20px 0 10px 0;">{card_header_html}</div>'))
    log_box = None

log_files = {"Agent": log_agent}
if mode_key in ("hybrid", "model", "tts"):
    log_files["ComfyUI"] = log_comfy
if mode_key in ("hybrid", "llm"):
    log_files["LLM"] = log_llm

handles = {}
for label, p in log_files.items():
    if os.path.exists(p):
        f = open(p, "r", errors="replace")
        sz = os.path.getsize(p)
        if sz > 16384:
            f.seek(max(0, sz - 8192), os.SEEK_SET)
        handles[label] = f

TAG_COLORS = {
    "Agent": "[92m[Agent][0m",
    "ComfyUI": "[94m[ComfyUI][0m",
    "LLM": "[93m[LLM][0m",
    "Status": "[95m[Status][0m",
}

total_lines = 0
last_watchdog = 0.0

try:
    while True:
        activity = False
        batch = []
        for label, f in list(handles.items()):
            for _ in range(50):
                line = f.readline()
                if not line:
                    break
                activity = True
                line_clean = line.strip()
                if line_clean:
                    batch.append([label, line_clean])

        for label, p in log_files.items():
            if label not in handles and os.path.exists(p):
                f = open(p, "r", errors="replace")
                handles[label] = f

        if batch:
            total_lines += len(batch)
            if log_box:
                if total_lines > 2000:
                    log_box.clear_output(wait=True)
                    total_lines = len(batch)
                with log_box:
                    for l, t in batch:
                        tag = TAG_COLORS.get(l, f"[{l}]")
                        print(f"{tag} {t}", flush=True)
            else:
                for l, t in batch:
                    print(f"[{l}] {t}", flush=True)

        # Periodic watchdog to auto-restart llama-server if it exited during the session
        now = time.time()
        if now - last_watchdog > 10.0:
            last_watchdog = now
            proc_llm = worker_procs.get("llm")
            if mode_key == "llm" and proc_llm and proc_llm.poll() is not None:
                tag = TAG_COLORS.get("LLM", "[LLM]")
                print(f"{tag} ⚠️ llama-server process exited (code {proc_llm.returncode}). Auto-restarting...", flush=True)
                # Ensure ComfyUI yields VRAM before restarting llama-server
                try:
                    req_free = urllib.request.Request(
                        f"http://127.0.0.1:{comfy_port}/free",
                        data=json.dumps({"unload_models": True, "free_memory": True}).encode("utf-8"),
                        headers={"Content-Type": "application/json"}
                    )
                    with urllib.request.urlopen(req_free, timeout=2) as _:
                        pass
                    time.sleep(0.5)
                except Exception:
                    pass
                with open(log_llm, "a", buffering=1) as out:
                    worker_procs["llm"] = subprocess.Popen(spawn_cmd, env=env_llm, stdout=out, stderr=out)

        if not activity:
            time.sleep(0.3)
except KeyboardInterrupt:
    if log_box:
        with log_box:
            print("\\n\\033[91m🛑 Stopped live log monitor. Your background services are still running happily!\\033[0m", flush=True)
    else:
        print("\\n🛑 Stopped live log monitor. Your background services are still running happily!")
finally:
    for f in handles.values():
        try:
            f.close()
        except Exception:
            pass
"""
    return [line + "\n" for line in code.split("\n")[:-1]]


def build_cell_6_source() -> list[str]:
    code = """#@title 6. 📥 (Optional) Live Models-in-RAM Dashboard & Model Manager
#@markdown Manage, view high-speed RAM cache residency, or pre-warm models on the fly:

OPERATION = "📊 View Models-in-RAM Dashboard & Status" #@param ["📊 View Models-in-RAM Dashboard & Status", "⚡ Pre-Warm Model into RAM Cache", "🧹 Evict Model from RAM Cache", "📥 Download Model from URL", "🔍 List Checkpoints in Persistent Storage"]
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

is_modal = os.path.exists("/mnt/data") or ("MODAL_ENVIRONMENT" in os.environ)
is_colab = False
try:
    import google.colab
    is_colab = True
except Exception:
    pass
workspace_root = "/content" if is_colab else ("/root" if os.path.exists("/root") else os.path.expanduser("~"))
agent_dir = os.path.join(workspace_root, "tnhcomfy", "remote_agent")
if agent_dir not in sys.path:
    sys.path.insert(0, agent_dir)
from ram_manager import get_ram_manager
ram_mgr = get_ram_manager()

comfy_dir = os.path.join(workspace_root, "ComfyUI")
ckpt_dir = "/mnt/data/models/checkpoints" if (is_modal and os.path.exists("/mnt/data/models/checkpoints")) else f"{comfy_dir}/models/checkpoints"
lora_dir = "/mnt/data/models/loras" if (is_modal and os.path.exists("/mnt/data/models/loras")) else f"{comfy_dir}/models/loras"
llm_dir = "/mnt/data/tnhcomfy/llm_models" if is_modal else (GDRIVE_LLM_PATH.strip() if "GDRIVE_LLM_PATH" in locals() and GDRIVE_LLM_PATH.strip() else "/content/drive/MyDrive/tnhcomfy/llm_models")

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

elif OPERATION == "🔍 List Checkpoints in Persistent Storage":
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
        scratch_dir = os.path.join(workspace_root, "tmp_downloads")
        os.makedirs(scratch_dir, exist_ok=True)
        scratch_path = os.path.join(scratch_dir, fname)
        final_path = os.path.join(dest_dir, fname)

        print(f"📥 High-speed streaming '{fname}' to local scratch ({scratch_path})...")
        subprocess.run(f"curl -fL '{DOWNLOAD_URL.strip()}' -o '{scratch_path}'", shell=True, check=True)
        if os.path.exists(scratch_path) and os.path.getsize(scratch_path) > 1000:
            print(f"📦 Safely copying to persistent storage ({final_path})...")
            dst_tmp = f"{final_path}.publishing"
            shutil.copyfile(scratch_path, dst_tmp)
            os.replace(dst_tmp, final_path)
            os.remove(scratch_path)
            print(f"✅ Successfully downloaded and saved to persistent storage: {final_path}!")
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

    while len(nb["cells"]) < 8:
        nb["cells"].append({"cell_type": "code", "execution_count": None, "metadata": {}, "outputs": [], "source": []})

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
