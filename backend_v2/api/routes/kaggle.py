"""
Kaggle Worker Routes

Provides:
1. Worker script served at /api/kaggle/worker.py
2. Setup code generator for Kaggle notebooks
"""

from fastapi import APIRouter
from fastapi.responses import PlainTextResponse

router = APIRouter(prefix="/api/kaggle", tags=["kaggle"])


# ============================================================================
# Worker Script (served to Kaggle notebooks)
# ============================================================================

WORKER_SCRIPT = '''
"""
Kaggle Worker for ComfyUI Backend
Auto-generated script - do not edit directly.
"""

import asyncio
import json
import os
import subprocess
import sys
import time
from pathlib import Path

# Install dependencies if needed
def install_deps():
    deps = ["websockets", "aiohttp"]
    for dep in deps:
        try:
            __import__(dep)
        except ImportError:
            subprocess.check_call([sys.executable, "-m", "pip", "install", dep, "-q"])

install_deps()

import websockets
import aiohttp


class KaggleWorker:
    """
    Worker that connects to ComfyUI backend and processes jobs.
    Designed for Kaggle notebooks with GPU access.
    """
    
    def __init__(self, backend_url: str, token: str, provider_id: str = "kaggle"):
        self.backend_url = backend_url.rstrip("/")
        self.token = token
        self.provider_id = provider_id
        self.ws = None
        self.comfy_process = None
        self.comfy_port = 8188
        self.running = False
        
        # Kaggle paths
        self.models_input = Path("/kaggle/input/comfy-models")
        self.working_dir = Path("/kaggle/working")
        self.comfy_dir = self.working_dir / "ComfyUI"
    
    def setup_comfyui(self):
        """Install and setup ComfyUI."""
        print("[Worker] Setting up ComfyUI...")
        
        if not self.comfy_dir.exists():
            subprocess.run([
                "git", "clone", "--depth=1",
                "https://github.com/comfyanonymous/ComfyUI.git",
                str(self.comfy_dir)
            ], check=True)
        
        # Install requirements
        subprocess.run([
            sys.executable, "-m", "pip", "install", "-r",
            str(self.comfy_dir / "requirements.txt"), "-q"
        ], check=True)
        
        # Setup model symlinks from Kaggle dataset
        self.setup_model_links()
        
        print("[Worker] ComfyUI setup complete")
    
    def setup_model_links(self):
        """Symlink models from Kaggle dataset to ComfyUI."""
        if not self.models_input.exists():
            print("[Worker] Warning: No model dataset found at /kaggle/input/comfy-models")
            return
        
        models_dir = self.comfy_dir / "models"
        
        for subdir in ["checkpoints", "loras", "vae", "controlnet", "upscale_models"]:
            src = self.models_input / subdir
            dst = models_dir / subdir
            
            if src.exists():
                # Remove existing dir and symlink
                if dst.is_symlink():
                    dst.unlink()
                elif dst.exists():
                    import shutil
                    shutil.rmtree(dst)
                
                dst.symlink_to(src)
                print(f"[Worker] Linked {subdir}: {src} -> {dst}")
    
    def start_comfyui(self):
        """Start ComfyUI server."""
        print("[Worker] Starting ComfyUI server...")
        
        self.comfy_process = subprocess.Popen([
            sys.executable, "main.py",
            "--listen", "127.0.0.1",
            "--port", str(self.comfy_port),
            "--disable-auto-launch"
        ], cwd=str(self.comfy_dir))
        
        # Wait for startup
        import urllib.request
        for _ in range(60):
            try:
                urllib.request.urlopen(f"http://127.0.0.1:{self.comfy_port}/")
                print("[Worker] ComfyUI server ready")
                return True
            except Exception as e:
                print(f"[Worker] Error: {e}")
                time.sleep(1)
        
        print("[Worker] ComfyUI failed to start")
        return False
    
    async def connect(self):
        """Connect to backend WebSocket."""
        ws_url = self.backend_url.replace("http://", "ws://").replace("https://", "wss://")
        ws_url = f"{ws_url}/ws/worker/{self.provider_id}?token={self.token}"
        
        print(f"[Worker] Connecting to {ws_url}")
        self.ws = await websockets.connect(ws_url)
        
        # Wait for welcome
        msg = await self.ws.recv()
        data = json.loads(msg)
        if data.get("type") == "connected":
            print(f"[Worker] Connected: {data.get('message')}")
            return True
        
        return False
    
    async def heartbeat_loop(self):
        """Send periodic heartbeats."""
        while self.running:
            try:
                await self.ws.send(json.dumps({"type": "heartbeat"}))
                await asyncio.sleep(30)
            except Exception as e:
                print(f"[Worker] Error: {e}")
                break
    
    async def process_job(self, job_data: dict):
        """Execute a ComfyUI job."""
        job_id = job_data.get("id")
        workflow = job_data.get("workflow", {})
        
        print(f"[Worker] Processing job: {job_id}")
        
        try:
            await self.ws.send(json.dumps({
                "type": "job_started",
                "job_id": job_id
            }))
            
            # Send workflow to ComfyUI and poll for completion using a single session
            async with aiohttp.ClientSession() as session:
                async with session.post(
                    f"http://127.0.0.1:{self.comfy_port}/prompt",
                    json={"prompt": workflow}
                ) as resp:
                    result = await resp.json()
                    prompt_id = result.get("prompt_id")
            
                # Poll for completion (outside post response context, inside session context)
                outputs = await self.wait_for_completion(session, prompt_id)
            
            await self.ws.send(json.dumps({
                "type": "job_completed",
                "job_id": job_id,
                "result": {"outputs": outputs}
            }))
            
            print(f"[Worker] Job completed: {job_id}")
            
        except Exception as e:
            print(f"[Worker] Job failed: {e}")
            await self.ws.send(json.dumps({
                "type": "job_failed",
                "job_id": job_id,
                "error": str(e)
            }))
    
    async def wait_for_completion(self, session, prompt_id: str, timeout: int = 300):
        """Wait for ComfyUI to complete the prompt."""
        start = time.time()
        while time.time() - start < timeout:
            try:
                async with session.get(
                    f"http://127.0.0.1:{self.comfy_port}/history/{prompt_id}"
                ) as resp:
                    data = await resp.json()
                    if prompt_id in data:
                        outputs = data[prompt_id].get("outputs", {})
                        # Extract image filenames
                        images = []
                        for node_output in outputs.values():
                            for img in node_output.get("images", []):
                                images.append(img.get("filename"))
                        return images
            except Exception as e:
                print(f"[Worker] Error: {e}")
                pass
            await asyncio.sleep(1)
        
        raise TimeoutError("Job timed out")
    
    async def message_loop(self):
        """Main message handling loop."""
        while self.running:
            try:
                msg = await asyncio.wait_for(self.ws.recv(), timeout=60)
                data = json.loads(msg)
                
                if data.get("type") == "job":
                    await self.process_job(data.get("data", {}))
                elif data.get("type") == "heartbeat_ack":
                    pass  # Expected
                    
            except asyncio.TimeoutError:
                continue
            except websockets.ConnectionClosed:
                print("[Worker] Connection closed")
                break
            except Exception as e:
                print(f"[Worker] Error: {e}")
    
    def run(self):
        """Main entry point - setup and run worker."""
        print("[Worker] Kaggle Worker starting...")
        
        # Setup ComfyUI
        self.setup_comfyui()
        
        # Start ComfyUI server
        if not self.start_comfyui():
            print("[Worker] Failed to start ComfyUI")
            return
        
        # Run async event loop
        self.running = True
        asyncio.get_event_loop().run_until_complete(self._async_run())
    
    async def _async_run(self):
        """Async main loop."""
        if not await self.connect():
            print("[Worker] Failed to connect")
            return
        
        # Start heartbeat
        heartbeat_task = asyncio.create_task(self.heartbeat_loop())
        
        try:
            await self.message_loop()
        finally:
            self.running = False
            heartbeat_task.cancel()
            if self.comfy_process:
                self.comfy_process.terminate()


# Export for easy access
__all__ = ["KaggleWorker"]
'''


@router.get("/worker.py", response_class=PlainTextResponse)
async def get_worker_script():
    """
    Serve the Kaggle worker script.
    
    Usage in Kaggle:
    ```python
    exec(__import__('urllib.request').urlopen('http://backend/api/kaggle/worker.py').read())
    KaggleWorker("http://backend", "token").run()
    ```
    """
    return WORKER_SCRIPT


@router.get("/setup-code")
async def get_setup_code(
    backend_url: str,
    token: str,
    tailscale_authkey: str = "",
    provider_id: str = "kaggle"
):
    """
    Generate setup code for a Kaggle notebook.
    
    Returns copyable cells for the user.
    """
    cells = []
    
    # Cell 1: Tailscale setup (if authkey provided)
    if tailscale_authkey:
        cells.append({
            "name": "Setup Tailscale",
            "code": f'''# Install and connect Tailscale
!curl -fsSL https://tailscale.com/install.sh | sh
!tailscaled --state=mem: &
!sleep 3
!tailscale up --authkey={tailscale_authkey} --ephemeral --hostname=kaggle-worker-${{RANDOM}}
print("Tailscale connected!")'''
        })
    
    # Cell 2: Run worker
    cells.append({
        "name": "Run Worker",
        "code": f'''# Connect to ComfyUI backend
BACKEND = "{backend_url}"
exec(__import__('urllib.request').urlopen(f'{{BACKEND}}/api/kaggle/worker.py').read())

worker = KaggleWorker(
    backend_url=BACKEND,
    token="{token}",
    provider_id="{provider_id}"
)
worker.run()'''
    })
    
    return {"cells": cells}
