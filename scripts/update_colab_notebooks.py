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
#@markdown #### ⚡ Model Storage & Download Strategy:
#@markdown - `direct_download_fast` (Recommended): Download directly from Hugging Face CDN into local NVMe SSD / RAM (~150-250 MB/s, ~2 min for 20GB). Bypasses Google Drive FUSE throttling!
#@markdown - `gdrive_persistent`: Download & cache models in Google Drive across reconnects (~25-40 MB/s FUSE read).
STORAGE_STRATEGY = "direct_download_fast (recommended: 150+ MB/s from HF)" #@param ["direct_download_fast (recommended: 150+ MB/s from HF)", "gdrive_persistent (Google Drive FUSE)"]

#@markdown ---
#@markdown #### 🎨 Image / Hybrid Mode — Google Drive ComfyUI:
#@markdown Path to your ComfyUI folder copied from Modal (default is /content/drive/MyDrive/comfyui):
GDRIVE_COMFY_PATH = "/content/drive/MyDrive/comfyui" #@param {type:"string"}

#@markdown ---
#@markdown #### 💬 LLM / Hybrid Mode — Curated Models from models.json:
LLM_RP_MODEL = "artemis_31b_q4" #@param ["artemis_31b_q4", "artemis_31b", "sompoa_26b_a4b", "goetia_26b_a4b", "styletune_v2_26b_a4b", "dark_thoughts_v2_31b", "split_untied_31b", "weirdcompound_24b", "gemma3_12b_heretic", "writers_31b_v2", "gemma4_31b_heretic", "magnum_diamond_24b"]
LLM_UTIL_MODEL = "same_as_rp" #@param ["same_as_rp", "artemis_31b_q4", "artemis_31b", "sompoa_26b_a4b", "gemma3_12b_heretic_util", "gemma4_26b_a4b_heretic_util", "gemma4_31b_heretic_util", "mistral_small_32_it", "qwen2.5_14b"]
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
print(f"• Storage Strategy: {STORAGE_STRATEGY}")
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

    # 0. Ensure Google Drive is mounted for persistence if running Cell 4 directly
    if "from google.colab import drive" not in content:
        content = content.replace(
            "import os\nimport sys",
            """import os\nimport sys\n\ntry:\n    from google.colab import drive\n    if not os.path.exists("/content/drive/MyDrive"):\n        print("📁 Mounting Google Drive at /content/drive...")\n        drive.mount("/content/drive")\nexcept Exception:\n    pass""",
        )

    # 1. Ensure huggingface_hub, psutil, and pysocks are in extra_packages
    if '"pysocks"' not in content:
        if '"hydra-core", "iopath", "huggingface_hub", "psutil"' in content:
            content = content.replace(
                '"hydra-core", "iopath", "huggingface_hub", "psutil"',
                '"hydra-core", "iopath", "huggingface_hub", "psutil", "pysocks"',
            )
        elif '"hydra-core", "iopath"' in content:
            content = content.replace(
                '"hydra-core", "iopath"',
                '"hydra-core", "iopath", "huggingface_hub", "psutil", "pysocks"',
            )

    # 2. Add RAM cache directory setup and ComfyUI extra_model_paths.yaml before "Environment setup complete!"
    ram_cache_setup = """
# 5. Initialize High-Speed System RAM Cache & Expand /dev/shm
try:
    import psutil
    tot_ram = psutil.virtual_memory().total / (1024**3)
    target_shm_gb = min(44, int(tot_ram * 0.82))
    subprocess.run(["mount", "-o", f"remount,size={target_shm_gb}G", "/dev/shm"], check=False)
    print(f"⚡ Expanded /dev/shm filesystem capacity to {target_shm_gb} GB.")
except Exception:
    pass

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
    is_default: true
    checkpoints: checkpoints
    loras: loras
    vae: vae
tnh_ram_flat:
    base_path: {ram_cache_dir}
    is_default: true
    checkpoints: .
    loras: .
    vae: .
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

    # 3. Enhance CUDA runtime linking and device detection in Cell 4
    old_ld = 'subprocess.run(["ldconfig"], check=False)\n        os.environ["LD_LIBRARY_PATH"] = f"{llama_dir}:/usr/local/lib:" + os.environ.get("LD_LIBRARY_PATH", "")'
    new_ld = '''# Clean up any stray symlinks in /usr/local/lib to prevent PyTorch cuDNN conflicts
        for f_pat in ("libcudart.so*", "libcublas.so*", "libcublasLt.so*", "libcuda.so*", "libggml*.so*", "libllama*.so*"):
            for p in glob.glob(f"/usr/local/lib/{f_pat}"):
                if os.path.islink(p):
                    try: os.remove(p)
                    except Exception: pass
        subprocess.run(["ldconfig"], check=False)
        # Discover and link CUDA runtime libraries into /usr/local/llama.cpp ONLY
        cuda_dirs = [llama_dir, "/usr/local/cuda/lib64", "/usr/local/cuda-12/lib64", "/usr/lib64-nvidia", "/usr/lib/x86_64-linux-gnu"]
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
        ld_path = ":".join(cuda_dirs) + ":/usr/local/llama.cpp:" + os.environ.get("LD_LIBRARY_PATH", "")'''
    if old_ld in content:
        content = content.replace(old_ld, new_ld)

    return [line + "\n" for line in content.split("\n")[:-1]]


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
# 0. Ensure Google Drive is mounted for persistence
try:
    from google.colab import drive
    if not os.path.exists("/content/drive/MyDrive"):
        print("📁 Mounting Google Drive at /content/drive...")
        drive.mount("/content/drive")
except Exception:
    pass

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
active_image = active_spec.get("image") or ""
shared_weights = (active_util in ("same_as_rp", active_rp))
distinct_active_llm = [active_rp] if shared_weights else [active_rp, active_util]

print(f"🌐 Model Catalog synced from {catalog_source}:")
print(f"   • Active RP Model:   {active_rp}")
print(f"   • Active Util Model: {active_util} (Shared Weights: {shared_weights})")
if active_image:
    print(f"   • Active Image Model: {active_image}")

# 4. Check & Auto-Download Active LLM GGUF Weights (Direct NVMe or Google Drive)
storage_strat_key = "direct" if ("STORAGE_STRATEGY" in locals() and "direct" in str(STORAGE_STRATEGY).lower()) else "gdrive"
llm_gdrive_dir = GDRIVE_LLM_PATH.strip() or "/content/drive/MyDrive/tnhcomfy/llm_models"
llm_local_dir = "/content/models/llm"
os.makedirs(llm_local_dir, exist_ok=True)
if storage_strat_key == "gdrive":
    os.makedirs(llm_gdrive_dir, exist_ok=True)

resolved_weights = {}
for mid in distinct_active_llm:
    spec = models_dict.get(mid, {})
    vol_dir = spec.get("dir") or mid
    gguf_name = spec.get("gguf")
    repo = spec.get("repo")
    mmproj_name = spec.get("mmproj")
    mmproj_repo = spec.get("mmproj_repo") or repo

    # Determine primary target folder based on strategy
    if storage_strat_key == "direct":
        target_folder = os.path.join(llm_local_dir, vol_dir)
        download_target_desc = f"local NVMe SSD ({target_folder})"
    else:
        target_folder = os.path.join(llm_gdrive_dir, vol_dir)
        download_target_desc = f"Google Drive ({target_folder})"
    os.makedirs(target_folder, exist_ok=True)

    local_gguf = os.path.join(target_folder, gguf_name) if gguf_name else ""

    # Check if file exists in either target folder or existing Google Drive cache
    gdrive_candidate = os.path.join(llm_gdrive_dir, vol_dir, gguf_name) if (gguf_name and os.path.exists(llm_gdrive_dir)) else ""
    if not (local_gguf and os.path.exists(local_gguf)) and gdrive_candidate and os.path.exists(gdrive_candidate):
        print(f"📁 Found [{mid}] in Google Drive cache: {gdrive_candidate}")
        local_gguf = gdrive_candidate

    if not (local_gguf and os.path.exists(local_gguf)):
        if repo and gguf_name:
            speed_note = "⚡ High-speed direct CDN transfer" if storage_strat_key == "direct" else "📁 Google Drive transfer"
            print(f"📥 Active LLM weights for [{mid}] not found locally or in Drive.")
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
        else:
            print(f"⚠️ Model [{mid}] has no repository metadata in catalog.")

    if local_gguf and os.path.exists(local_gguf):
        resolved_weights[mid] = local_gguf
    else:
        # Fallback candidate scan
        for cdir in [llm_local_dir, llm_gdrive_dir, "/content/agent-data/llm/models", "/content/ComfyUI/models/llm", "/dev/shm/tnh_ram_cache/llm"]:
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

# 5. High-Speed RAM Setup & Anchor Configuration
try:
    import psutil
    tot_ram = psutil.virtual_memory().total / (1024**3)
    target_shm_gb = min(44, int(tot_ram * 0.82))
    subprocess.run(["mount", "-o", f"remount,size={target_shm_gb}G", "/dev/shm"], check=False)
except Exception:
    pass

if agent_dir not in sys.path:
    sys.path.insert(0, agent_dir)
from ram_manager import RamModelManager
ram_mgr = RamModelManager(ram_dir="/dev/shm/tnh_ram_cache", budget_gb=40.0)

anchor_ids = [active_rp]
if not shared_weights:
    anchor_ids.append(active_util)
if active_image:
    anchor_ids.append(active_image)

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

img_id = os.path.basename(active_ckpt_path) if active_ckpt_path else ""
if img_id:
    anchor_ids.append(img_id)

ram_mgr.set_anchors(anchor_ids)

# Evict any non-anchor models from prior runs to keep RAM dedicated and lean
for mid in list(ram_mgr.entries.keys()):
    if mid not in anchor_ids:
        try:
            ram_mgr.evict_model(mid, force=True)
        except Exception:
            pass

# 6. Prepare Engine Paths & CUDA Runtimes
if mode_key in ("hybrid", "model"):
    extra_paths_file = f"{comfy_dir}/extra_model_paths.yaml"
    extra_paths_content = \"\"\"tnh_ram_cache:
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
\"\"\"
    try:
        with open(extra_paths_file, "w") as f:
            f.write(extra_paths_content.strip() + "\\n")
    except Exception:
        pass

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
        RAM_CACHE_BUDGET_GB="40",
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
        worker_procs["comfy"] = subprocess.Popen([sys.executable, f"{comfy_dir}/main.py", "--listen", "127.0.0.1", "--port", str(comfy_port)], env=env_comfy, stdout=out, stderr=out)

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

            # Reserve 2.5 GB for KV cache (8192 context q8_0) and compute scratch
            reserve_gb = 2.5
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
                fraction = min(0.95, available_weight_gb / weight_gb)
                target_layers = int(total_layers * fraction)
                ngl = max(4, min(total_layers - 2, target_layers - 1))
                print(f"  ⚡ GPU VRAM: {free_vram_gb:.1f} GB free of {total_vram_gb:.1f} GB | Model: {weight_gb:.1f} GB")
                print(f"  🎯 Calculated safe layer offload: -ngl {ngl}/{total_layers} (GPU: ~{available_weight_gb:.1f} GB, RAM Cache: ~{weight_gb - available_weight_gb:.1f} GB) to prevent CUDA OOM")
            else:
                ngl = 0
                print(f"  ⚠️ Very low free VRAM ({free_vram_gb:.1f} GB free); running on CPU RAM cache: -ngl 0")
    except Exception as exc:
        ngl = 35
        print(f"  Notice: VRAM layer budgeting fallback ({exc}); using safe -ngl 35")

    llama_args = [
        llama_exec,
        "--port", str(llm_port),
        "--host", "127.0.0.1",
        "-ngl", str(ngl),
        "-c", "8192",
        "--cache-type-k", "q8_0",
        "--cache-type-v", "q8_0",
        "--jinja",
    ]
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

def launch_laya_track():
    print("⚡ [Laya Track] Pre-warming Laya System 1 on GPU (CUDA)...")
    try:
        import laya
        laya_dir = "/content/agent-data/decisions/laya_multilingual"
        src = laya_dir if (os.path.exists(laya_dir) and os.listdir(laya_dir)) else "convaiinnovations/laya-multilingual"
        try:
            ram_mgr.ensure_dir_in_ram(src, model_id="laya_multilingual", role="decisions", is_anchor=True)
        except Exception:
            pass
        hf_tok = os.environ.get("HF_TOKEN") or None
        test_agent = laya.load(src, device="cuda", token=hf_tok)
        actual_dev = getattr(test_agent, "device", "cuda")
        print(f"✅ [Laya Track] Laya pre-warmed on {str(actual_dev).upper()} (<100ms inference ready)!")
    except Exception as exc:
        print(f"⚠️ [Laya Track] Pre-warming notice: {exc}")

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
    "Agent": "\033[92m[Agent]\033[0m",
    "ComfyUI": "\033[94m[ComfyUI]\033[0m",
    "LLM": "\033[93m[LLM]\033[0m",
    "Status": "\033[95m[Status]\033[0m",
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
            if mode_key in ("hybrid", "llm") and proc_llm and proc_llm.poll() is not None:
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
