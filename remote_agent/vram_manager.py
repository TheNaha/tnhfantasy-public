"""Dynamic VRAM Arbiter and Lifecycle Manager for Hybrid/Colab Workers.

Coordinates GPU VRAM between ComfyUI (:8188), llama-server (:8003), and
System 1 Decision Evaluator (Laya) on a single physical GPU node.

Retention / Eviction Priority Hierarchy:
1. HIGHEST PRIORITY (Keep in VRAM): Laya (System 1 Decision Engine).
   Small (~0.5 - 1.2 GB), evaluated on every interaction for instant (<100ms)
   director decisions. Kept resident in CUDA unless ComfyUI + llama-server VRAM
   clearance is STILL insufficient.
2. MEDIUM PRIORITY: llama-server (LLM Engine).
   Started Just-In-Time (JIT) on demand from the /dev/shm RAM cache (~8-9s boot).
   Stopped or yielded during image generation on VRAM-constrained GPUs (T4/L4).
3. LOWEST PRIORITY (Evicted First): ComfyUI cached models.
   Unloaded in <500ms via POST http://127.0.0.1:8188/free before LLM or decision
   evaluation without terminating the ComfyUI process.
"""

from __future__ import annotations

import gc
import json
import logging
import os
import shutil
import subprocess
import sys
import threading
import time
import urllib.request
from typing import Any, Dict, List, Optional, Tuple

logger = logging.getLogger("vram_manager")


class VRAMManager:
    """Coordinates GPU VRAM between ComfyUI, llama-server, and Laya."""

    def __init__(
        self,
        comfy_url: Optional[str] = None,
        llm_url: Optional[str] = None,
        llm_port: int = 8003,
        idle_timeout_seconds: float = 600.0,
    ) -> None:
        self.comfy_url = (comfy_url or os.getenv("COMFY_URL", "http://127.0.0.1:8188")).rstrip("/")
        self.llm_url = (llm_url or os.getenv("LLM_URL", f"http://127.0.0.1:{llm_port}")).rstrip("/")
        self.llm_port = int(os.getenv("LLM_PORT", str(llm_port)))
        self.idle_timeout_seconds = float(os.getenv("LLM_IDLE_TIMEOUT_SECONDS", str(idle_timeout_seconds)))

        self.active_workload: str = "idle"  # "idle" | "image" | "llm" | "decisions"
        self.last_llm_activity: float = time.time()
        self.last_image_activity: float = 0.0

        # Managed llama-server process handle
        self.llama_proc: Optional[subprocess.Popen] = None
        self.llama_model_id: Optional[str] = None
        self.llama_managed: bool = False

        # Laya model cache: (repo_or_path, device) -> model instance
        self.laya_cache: Dict[Tuple[str, str], Any] = {}
        self.current_laya_device: str = "cpu"

        self._lock = threading.RLock()

    # ----------------------------------------------------------------------
    # GPU VRAM Telemetry & Inspection
    # ----------------------------------------------------------------------

    def get_vram_info(self) -> Dict[str, Any]:
        """Query precise live GPU device memory, current usage, and component status."""
        total_mb = 0
        free_mb = 0
        used_mb = 0
        name = "Unknown"
        cuda_available = False

        # 1. Primary: PyTorch CUDA Driver
        try:
            import torch

            if torch.cuda.is_available():
                cuda_available = True
                name = torch.cuda.get_device_name(0)
                # mem_get_info returns (free_bytes, total_bytes) on device 0
                free_bytes, total_bytes = torch.cuda.mem_get_info(0)
                total_mb = int(total_bytes / (1024 * 1024))
                free_mb = int(free_bytes / (1024 * 1024))
                used_mb = max(0, total_mb - free_mb)
        except Exception:
            pass

        # 2. Fallback: nvidia-smi CLI
        if not cuda_available:
            try:
                res = subprocess.run(
                    ["nvidia-smi", "--query-gpu=name,memory.total,memory.used,memory.free", "--format=csv,noheader,nounits"],
                    capture_output=True,
                    text=True,
                    timeout=2.0,
                    check=False,
                )
                if res.returncode == 0 and res.stdout.strip():
                    parts = [p.strip() for p in res.stdout.strip().splitlines()[0].split(",")]
                    name = parts[0]
                    total_mb = int(parts[1]) if len(parts) > 1 else 0
                    used_mb = int(parts[2]) if len(parts) > 2 else 0
                    free_mb = int(parts[3]) if len(parts) > 3 else max(0, total_mb - used_mb)
                    cuda_available = True
            except Exception:
                pass

        llama_alive = self.is_llama_running()

        return {
            "available": cuda_available,
            "device_name": name,
            "vram_total_mb": total_mb,
            "vram_used_mb": used_mb,
            "vram_free_mb": free_mb,
            "active_workload": self.active_workload,
            "llama_running": llama_alive,
            "llama_model_id": self.llama_model_id if llama_alive else None,
            "llama_managed": self.llama_managed,
            "laya_device": self.current_laya_device,
            "laya_loaded_count": len(self.laya_cache),
            "idle_timeout_seconds": self.idle_timeout_seconds,
            "last_llm_activity_ago_s": round(time.time() - self.last_llm_activity, 1),
        }

    # ----------------------------------------------------------------------
    # Component Eviction Controls
    # ----------------------------------------------------------------------

    def free_comfy_vram(self, timeout: float = 2.5) -> bool:
        """Instruct ComfyUI to purge its cached diffusion models from GPU VRAM."""
        try:
            req = urllib.request.Request(
                f"{self.comfy_url}/free",
                data=json.dumps({"unload_models": True, "free_memory": True}).encode("utf-8"),
                headers={"Content-Type": "application/json"},
            )
            with urllib.request.urlopen(req, timeout=timeout) as resp:
                if resp.status == 200:
                    logger.info("comfy_vram_freed")
                    return True
        except Exception as exc:
            logger.debug(f"comfy_vram_free_ignored: {exc}")
        return False

    def is_llama_running(self) -> bool:
        """Check if llama-server process is actively alive and healthy."""
        with self._lock:
            if self.llama_proc is not None:
                if self.llama_proc.poll() is None:
                    return True
                self.llama_proc = None
                self.llama_model_id = None
                self.llama_managed = False

        # If not tracked by Popen, test HTTP port directly (unmanaged/external case)
        try:
            req = urllib.request.Request(f"http://127.0.0.1:{self.llm_port}/health")
            with urllib.request.urlopen(req, timeout=0.8) as resp:
                return resp.status == 200
        except Exception:
            return False

    def stop_llama(self, timeout: float = 3.0) -> bool:
        """Gracefully terminate running llama-server process to recover 10-18GB VRAM."""
        with self._lock:
            # 1. Managed Popen process
            if self.llama_proc is not None:
                try:
                    logger.info("stopping_managed_llama_server", extra={"model_id": self.llama_model_id})
                    self.llama_proc.terminate()
                    t0 = time.time()
                    while time.time() - t0 < timeout:
                        if self.llama_proc.poll() is not None:
                            break
                        time.sleep(0.1)
                    if self.llama_proc.poll() is None:
                        logger.warning("force_killing_managed_llama_server")
                        self.llama_proc.kill()
                        self.llama_proc.wait(timeout=1.0)
                except Exception as exc:
                    logger.warning(f"error_stopping_llama_proc: {exc}")
                finally:
                    self.llama_proc = None
                    self.llama_model_id = None
                    self.llama_managed = False

            # 2. Check if an orphaned llama-server is listening on the port
            try:
                # Send pkill to any orphaned llama-server on Linux
                subprocess.run(["pkill", "-f", f"llama-server.*{self.llm_port}"], check=False, stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)
            except Exception:
                pass

            # 3. Flush torch CUDA cache if available in this process
            try:
                import torch

                if torch.cuda.is_available():
                    torch.cuda.empty_cache()
            except Exception:
                pass

            return True

    def unload_laya_cuda(self) -> bool:
        """LAST RESORT: Unload Laya models from CUDA memory and return to CPU."""
        with self._lock:
            cuda_keys = [k for k in self.laya_cache if k[1].startswith("cuda")]
            if not cuda_keys:
                return False

            logger.info("unloading_laya_cuda_models", extra={"count": len(cuda_keys)})
            for k in cuda_keys:
                del self.laya_cache[k]

            self.current_laya_device = "cpu"
            gc.collect()

            try:
                import torch

                if torch.cuda.is_available():
                    torch.cuda.empty_cache()
            except Exception:
                pass

            return True

    # ----------------------------------------------------------------------
    # Laya Device Selection & Management
    # ----------------------------------------------------------------------

    def get_laya_device(self, required_headroom_mb: int = 1200) -> str:
        """Determine optimal device for Laya: CUDA if VRAM permits, else CPU."""
        info = self.get_vram_info()
        if not info["available"]:
            return "cpu"

        # If already plenty of free VRAM (>= 1.2 GB), run on CUDA for <100ms latency
        if info["vram_free_mb"] >= required_headroom_mb:
            return "cuda:0"

        # Try freeing ComfyUI VRAM first
        if self.free_comfy_vram():
            time.sleep(0.1)
            refreshed = self.get_vram_info()
            if refreshed["vram_free_mb"] >= required_headroom_mb:
                return "cuda:0"

        # If VRAM is still below required headroom (e.g. llama-server active),
        # fallback to CPU gracefully so we never crash or interrupt ongoing generation
        return "cpu"

    def get_or_load_laya(
        self,
        model_id: str,
        repo_or_path: str,
        preferred_device: Optional[str] = None,
    ) -> Tuple[Any, str]:
        """Load and cache Laya model on CUDA (with automatic fallback to CPU)."""
        import laya  # type: ignore

        device = preferred_device or self.get_laya_device()
        cache_key = (repo_or_path, device)

        with self._lock:
            # Check existing cache
            if cache_key in self.laya_cache:
                self.current_laya_device = device
                return self.laya_cache[cache_key], device

            # Attempt to load on chosen device
            try:
                logger.info("loading_laya_model", extra={"model_id": model_id, "device": device, "source": repo_or_path})
                model = laya.load(repo_or_path, device=device)
                self.laya_cache[cache_key] = model
                self.current_laya_device = device
                return model, device
            except Exception as exc:
                if "cuda" in device.lower():
                    logger.warning(
                        "laya_cuda_load_failed_falling_back_to_cpu",
                        extra={"error": str(exc), "model_id": model_id},
                    )
                    # Safe fallback to CPU
                    cpu_key = (repo_or_path, "cpu")
                    if cpu_key in self.laya_cache:
                        self.current_laya_device = "cpu"
                        return self.laya_cache[cpu_key], "cpu"
                    model = laya.load(repo_or_path, device="cpu")
                    self.laya_cache[cpu_key] = model
                    self.current_laya_device = "cpu"
                    return model, "cpu"
                raise

    # ----------------------------------------------------------------------
    # Workload Preparation & Priority Arbiter
    # ----------------------------------------------------------------------

    def prepare_for_workload(
        self,
        workload: str,
        model_id: Optional[str] = None,
        min_free_vram_mb: int = 0,
    ) -> Dict[str, Any]:
        """Enforce strict VRAM retention/eviction hierarchy before execution."""
        workload = (workload or "idle").strip().lower()

        with self._lock:
            info = self.get_vram_info()
            total_mb = info["vram_total_mb"]
            free_mb = info["vram_free_mb"]

            # ==============================================================
            # CASE A: IMAGE WORKLOAD (ComfyUI)
            # ==============================================================
            if workload == "image":
                self.active_workload = "image"
                self.last_image_activity = time.time()

                # On huge GPUs (e.g. A100 80GB), both image & LLM fit concurrently
                if total_mb >= 70000:
                    return {
                        "status": "ready",
                        "workload": "image",
                        "policy": "concurrent",
                        "vram": self.get_vram_info(),
                    }

                # On constrained GPUs (T4 16GB, L4 24GB, A10 24GB, A100 40GB):
                # Target free VRAM needed for clean diffusion generation
                target_free = min_free_vram_mb if min_free_vram_mb > 0 else 10000

                actions_taken: List[str] = []

                # EVICTION STEP 1: Stop llama-server to reclaim 10-18GB VRAM
                if free_mb < target_free and self.is_llama_running():
                    self.stop_llama()
                    actions_taken.append("stopped_llama_server")
                    time.sleep(0.2)
                    info = self.get_vram_info()
                    free_mb = info["vram_free_mb"]

                # EVICTION STEP 2 (LAST RESORT): If free VRAM is STILL below target,
                # ONLY THEN touch Laya to squeeze out the final ~1GB VRAM
                if free_mb < target_free and any(k[1].startswith("cuda") for k in self.laya_cache):
                    self.unload_laya_cuda()
                    actions_taken.append("unloaded_laya_cuda")
                    time.sleep(0.1)
                    info = self.get_vram_info()
                else:
                    # Laya is kept running on CUDA!
                    actions_taken.append("preserved_laya_cuda")

                return {
                    "status": "ready",
                    "workload": "image",
                    "actions_taken": actions_taken,
                    "vram": self.get_vram_info(),
                }

            # ==============================================================
            # CASE B: LLM WORKLOAD (llama-server)
            # ==============================================================
            elif workload == "llm":
                self.active_workload = "llm"
                self.last_llm_activity = time.time()

                actions_taken = []

                # EVICTION STEP 1: Flush ComfyUI models from VRAM
                if self.free_comfy_vram():
                    actions_taken.append("freed_comfy_vram")

                # Note: Laya is PRESERVED on CUDA! We do not touch Laya here.
                actions_taken.append("preserved_laya_cuda")

                # Ensure llama-server is alive and serving the target model
                if not self.is_llama_running() or (model_id and self.llama_model_id and self.llama_model_id != model_id):
                    started = self.ensure_llama_running(model_id=model_id)
                    actions_taken.append(f"started_llama_server:{model_id}" if started else "llama_launch_failed")

                return {
                    "status": "ready",
                    "workload": "llm",
                    "actions_taken": actions_taken,
                    "vram": self.get_vram_info(),
                }

            # ==============================================================
            # CASE C: DECISIONS WORKLOAD (System 1 Laya)
            # ==============================================================
            elif workload in ("decisions", "decision"):
                self.active_workload = "decisions"
                actions_taken = []

                # Check if we can keep or promote Laya on CUDA
                dev = self.get_laya_device()
                actions_taken.append(f"selected_laya_device:{dev}")

                return {
                    "status": "ready",
                    "workload": "decisions",
                    "actions_taken": actions_taken,
                    "target_device": dev,
                    "vram": self.get_vram_info(),
                }

            # ==============================================================
            # CASE D: IDLE / FLUSH
            # ==============================================================
            else:
                self.active_workload = "idle"
                self.free_comfy_vram()
                return {
                    "status": "ready",
                    "workload": "idle",
                    "vram": self.get_vram_info(),
                }

    # ----------------------------------------------------------------------
    # JIT llama-server Lifecycle Management
    # ----------------------------------------------------------------------

    def ensure_llama_running(self, model_id: Optional[str] = None, timeout: float = 60.0) -> bool:
        """Start llama-server Just-In-Time from RAM cache if not already running."""
        with self._lock:
            # If already running with matching model, return immediately
            if self.is_llama_running():
                if not model_id or not self.llama_model_id or self.llama_model_id == model_id:
                    self.last_llm_activity = time.time()
                    return True
                # Different model requested -> stop current and hot-switch
                self.stop_llama()

            # Locate llama-server binary
            binary = self._find_llama_binary()
            if not binary:
                logger.warning("llama_binary_not_found")
                return False

            # Resolve model weights path (prefer RAM cache /dev/shm)
            model_path, resolved_mid = self._resolve_model_path(model_id)
            if not model_path or not os.path.exists(model_path):
                logger.warning(f"model_path_not_found: {model_path} (mid={model_id})")
                return False

            # Calculate safe layer offload (-ngl) reserving VRAM for Laya (~1.2GB) & KV cache (~2GB)
            ngl = 99
            info = self.get_vram_info()
            total_vram_gb = info["vram_total_mb"] / 1024.0
            weight_gb = os.path.getsize(model_path) / (1024**3)

            # Reserve 4.0 GB for Laya (1.2GB) + KV cache (1.5GB) + CUDA driver overhead (1.3GB)
            safe_budget_gb = max(0.0, total_vram_gb - 4.0)
            if weight_gb > safe_budget_gb > 0:
                fraction = safe_budget_gb / weight_gb
                ngl = max(20, min(56, int(64 * fraction)))
                logger.info(
                    "calculated_safe_ngl_offload",
                    extra={"ngl": ngl, "safe_budget_gb": safe_budget_gb, "weight_gb": weight_gb},
                )

            # Build command
            cmd = [
                binary,
                "-m", model_path,
                "--host", "127.0.0.1",
                "--port", str(self.llm_port),
                "-ngl", str(ngl),
                "-c", "8192",
                "--cache-type-k", "q8_0",
                "--cache-type-v", "q8_0",
                "--jinja",
            ]
            if resolved_mid:
                cmd.extend(["--alias", resolved_mid])

            # Prepare CUDA library environment
            env = self._build_cuda_env()

            logger.info("launching_jit_llama_server", extra={"cmd": " ".join(cmd[:6]), "model": resolved_mid})
            try:
                proc = subprocess.Popen(cmd, env=env)
                self.llama_proc = proc
                self.llama_model_id = resolved_mid or model_id or "default"
                self.llama_managed = True
                self.last_llm_activity = time.time()

                # Poll until ready
                t0 = time.time()
                while time.time() - t0 < timeout:
                    if proc.poll() is not None:
                        logger.error(f"llama-server exited unexpectedly code {proc.returncode}")
                        self.llama_proc = None
                        self.llama_model_id = None
                        self.llama_managed = False
                        return False

                    try:
                        req = urllib.request.Request(f"http://127.0.0.1:{self.llm_port}/health")
                        with urllib.request.urlopen(req, timeout=1.0) as resp:
                            if resp.status == 200:
                                elapsed = round(time.time() - t0, 1)
                                logger.info(f"llama-server ready in {elapsed}s on port {self.llm_port}!")
                                return True
                    except Exception:
                        pass
                    time.sleep(0.5)

                logger.error(f"llama-server did not become healthy within {timeout}s")
                self.stop_llama()
                return False

            except Exception as exc:
                logger.error(f"failed_to_spawn_llama_server: {exc}")
                self.llama_proc = None
                self.llama_model_id = None
                self.llama_managed = False
                return False

    def _find_llama_binary(self) -> Optional[str]:
        """Locate llama-server binary in common directories or system PATH."""
        candidates = [
            "/usr/local/bin/llama-server",
            "/app/llama-server",
            "/usr/local/llama.cpp/llama-server",
            shutil.which("llama-server"),
        ]
        for c in candidates:
            if c and os.path.exists(c) and os.access(c, os.X_OK):
                return c
        return None

    def _resolve_model_path(self, model_id: Optional[str] = None) -> Tuple[Optional[str], Optional[str]]:
        """Resolve weight file path from RAM cache or disk storage."""
        # 1. Check RAM Manager entries
        try:
            from ram_manager import get_ram_manager

            mgr = get_ram_manager()
            if model_id and mgr.is_cached(model_id):
                return mgr.entries[mgr.aliases.get(model_id, model_id)].ram_path, model_id

            # If no model_id specified, pick first cached LLM model
            for mid, entry in mgr.entries.items():
                if entry.role in ("rp", "util", "llm") or mid.endswith(".gguf"):
                    return entry.ram_path, mid
        except Exception:
            pass

        # 2. Check /dev/shm/tnh_ram_cache directly
        ram_dir = os.getenv("RAM_CACHE_DIR", "/dev/shm/tnh_ram_cache")
        if os.path.exists(ram_dir):
            for root, _, files in os.walk(ram_dir):
                for f in files:
                    if f.endswith(".gguf") and not f.startswith("."):
                        if not model_id or model_id.lower() in f.lower():
                            return os.path.join(root, f), model_id or f

        # 3. Check DATA_ROOT storage
        data_root = os.getenv("DATA_DIR", "/content/models/llm")
        if os.path.exists(data_root):
            for root, _, files in os.walk(data_root):
                for f in files:
                    if f.endswith(".gguf") and not f.startswith("."):
                        if not model_id or model_id.lower() in f.lower():
                            return os.path.join(root, f), model_id or f

        return None, model_id

    def _build_cuda_env(self) -> Dict[str, str]:
        """Construct process environment with discovered CUDA libraries."""
        cuda_dirs = [
            "/usr/local/llama.cpp",
            "/usr/local/lib",
            "/usr/local/cuda/lib64",
            "/usr/local/cuda-12/lib64",
            "/usr/lib64-nvidia",
            "/usr/lib/x86_64-linux-gnu",
        ]
        import glob

        for pat in [
            "/usr/local/lib/python*/dist-packages/nvidia/*/lib",
            f"{sys.prefix}/lib/python*/dist-packages/nvidia/*/lib",
        ]:
            cuda_dirs.extend(glob.glob(pat))

        cuda_dirs = [p for p in list(dict.fromkeys(cuda_dirs)) if os.path.isdir(p)]
        ld_path = ":".join(cuda_dirs) + ":/usr/local/llama.cpp:/usr/local/lib:" + os.environ.get("LD_LIBRARY_PATH", "")
        env = dict(os.environ, LD_LIBRARY_PATH=ld_path, PYTHONUNBUFFERED="1")
        env["PATH"] = "/usr/local/llama.cpp:/usr/local/bin:" + os.environ.get("PATH", "")
        return env


# ---------------------------------------------------------------------------
# Global Singleton
# ---------------------------------------------------------------------------
_VRAM_MANAGER_INSTANCE: Optional[VRAMManager] = None
_VRAM_MANAGER_LOCK = threading.Lock()


def get_vram_manager() -> VRAMManager:
    """Return the process-wide VRAMManager singleton."""
    global _VRAM_MANAGER_INSTANCE
    with _VRAM_MANAGER_LOCK:
        if _VRAM_MANAGER_INSTANCE is None:
            _VRAM_MANAGER_INSTANCE = VRAMManager()
        return _VRAM_MANAGER_INSTANCE
