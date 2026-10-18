"""Launch TNHComfy Worker or Interactive Jupyter Notebook on Modal with GPU and comfy-storage.

Usage:
    # 1. Interactive Jupyter Lab with Web URL (to open TNHComfy_Colab_Worker.ipynb):
    modal run scripts/launch_modal_worker.py::jupyter --gpu A10G

    # 2. Multi-GPU worker (GPU 0: ComfyUI, GPU 1: llama-server + Laya):
    modal run scripts/launch_modal_worker.py::jupyter --gpu 2xA10G

    # 3. Headless background worker:
    modal run scripts/launch_modal_worker.py::worker --gpu T4

Default Volume:
    Mounted at /mnt/data with volume name 'comfy-storage' (shared with Modal image worker).
"""

import os
import subprocess
import sys
import modal

APP_NAME = os.getenv("MODAL_APP_NAME", "tnhcomfy-worker")
VOLUME_NAME = os.getenv("MODAL_VOLUME_NAME", "comfy-storage")

app = modal.App(APP_NAME)
vol = modal.Volume.from_name(VOLUME_NAME, create_if_missing=True)

# Container image with PyTorch CUDA, git, curl, NetBird, and core worker dependencies
worker_image = (
    modal.Image.debian_slim(python_version="3.11")
    .apt_install(
        "git",
        "curl",
        "wget",
        "tar",
        "procps",
        "build-essential",
        "libgl1",
        "libglib2.0-0",
        "pciutils",
    )
    .pip_install(
        "torch",
        "torchvision",
        "torchaudio",
        "--index-url",
        "https://download.pytorch.org/whl/cu124",
    )
    .pip_install(
        "fastapi",
        "uvicorn",
        "pydantic",
        "httpx",
        "websockets",
        "psutil",
        "pysocks",
        "huggingface_hub",
        "laya",
        "jupyterlab",
        "ipywidgets",
    )
    .run_commands(
        "curl -fsSL https://pkgs.netbird.io/install.sh | sh",
        "mkdir -p /root/tnhcomfy",
    )
)


@app.function(
    image=worker_image,
    volumes={"/mnt/data": vol},
    gpu="A10G",
    timeout=3600 * 8,
    max_containers=1,
)
@modal.web_server(port=8888, startup_timeout=60)
def jupyter():
    """Launch Jupyter Lab web interface to run TNHComfy_Colab_Worker.ipynb on Modal."""
    # Ensure persistent directories on comfy-storage volume exist
    for sub in [
        "/mnt/data/tnhcomfy",
        "/mnt/data/tnhcomfy/bin",
        "/mnt/data/tnhcomfy/llm_models",
        "/mnt/data/models",
        "/mnt/data/models/checkpoints",
        "/mnt/data/models/loras",
        "/mnt/data/models/vae",
        "/mnt/data/output",
        "/mnt/data/input",
    ]:
        os.makedirs(sub, exist_ok=True)

    # Launch Jupyter Lab without authentication on port 8888 (Modal provides authentication)
    cmd = [
        "jupyter",
        "lab",
        "--ip=0.0.0.0",
        "--port=8888",
        "--no-browser",
        "--allow-root",
        "--NotebookApp.token=''",
        "--NotebookApp.password=''",
        "--ServerApp.disable_check_xsrf=True",
    ]
    subprocess.Popen(cmd, cwd="/root")


@app.function(
    image=worker_image,
    volumes={"/mnt/data": vol},
    gpu="A10G",
    timeout=3600 * 12,
    max_containers=1,
)
def worker(token: str = "", netbird_setup_key: str = "", backend_url: str = ""):
    """Run headless worker directly inside Modal container."""
    print("⚡ Starting TNHComfy Worker on Modal...")
    repo_dir = "/root/tnhcomfy"
    if not os.path.exists(repo_dir):
        subprocess.run(["git", "clone", "--depth", "1", "https://github.com/TheNaha/TNHComfy.git", repo_dir], check=True)

    sys.path.insert(0, f"{repo_dir}/remote_agent")
    env = dict(
        os.environ,
        DATA_DIR="/mnt/data/models",
        WORKER_MODE="hybrid",
        PORT="8001",
        HOST="0.0.0.0",
        PERSISTENT_STORAGE_PATH="/mnt/data/tnhcomfy",
        CACHE_IN_RAM="0",  # Low-RAM direct NVMe volume streaming
    )
    if token:
        env["REMOTE_AGENT_TOKEN"] = token
    if netbird_setup_key:
        env["NETBIRD_SETUP_KEY"] = netbird_setup_key
    if backend_url:
        env["BACKEND_URL"] = backend_url

    subprocess.run([sys.executable, f"{repo_dir}/remote_agent/server.py"], env=env)


if __name__ == "__main__":
    print(__doc__)
