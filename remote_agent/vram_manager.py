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
from pathlib import Path
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

        self.active_workload: str = "idle"  # "idle" | "image" | "llm" | "decisions" | "tts"
        self.last_llm_activity: float = time.time()
        self.last_image_activity: float = 0.0

        #: True when something ELSE already serves the LLM: the local llama
        #: stack in `llm` mode (which serves the registry's models on :8081+),
        #: or an explicit `LLM_UPSTREAM_BASE` (a server the operator runs).
        #:
        #: The JIT launcher must stay out of the way in both cases. It used to
        #: run anyway, so the agent started a SECOND llama-server with the same
        #: 19.5 GB of weights on the same 24 GB card — and in `llm` mode the
        #: stack had already loaded them once. Two copies of a 19.5 GB model
        #: on a 24 GB card is an OOM, and the copy that lost was whichever
        #: the arbiter started.
        self.llm_served_externally: bool = False

        # Multi-GPU Device Allocation
        self.comfy_gpu_device = int(os.getenv("COMFY_GPU_DEVICE", "0"))
        device_count = self._get_cuda_device_count()
        default_llm_gpu = 1 if (device_count >= 2) else 0
        self.llm_gpu_device = int(os.getenv("LLM_GPU_DEVICE", str(default_llm_gpu)))
        self.laya_gpu_device = int(os.getenv("LAYA_GPU_DEVICE", str(self.llm_gpu_device)))
        # Two DISTINCT DEVICE INDICES are what makes this a multi-GPU node:
        # ComfyUI and the LLM on different cards do not contend for VRAM.
        #
        # But the indices must also EXIST. `remote_agent/.env.example`
        # suggests `LLM_GPU_DEVICE=1`, and on a single-GPU L4 that made the
        # arbiter believe it had two GPUs and DISABLE every eviction path —
        # so ComfyUI's checkpoint and a 19.5 GB llama-server were told to
        # coexist on a 24 GB card.
        #
        # `device_count == 0` means the count could not be determined (no
        # CUDA, or a container without the driver), and the configured
        # indices are taken at face value. A real single-GPU box reports 1,
        # and then `LLM_GPU_DEVICE=1` — a device that does not exist — is
        # correctly NOT multi-GPU, so the eviction paths stay armed.
        self.is_multi_gpu = (self.comfy_gpu_device != self.llm_gpu_device) and (
            device_count == 0
            or max(self.comfy_gpu_device, self.llm_gpu_device) < device_count
        )

        # RAM Caching Policy: "1" (default) or "0" (low-RAM direct volume streaming)
        cache_ram_env = os.getenv("CACHE_IN_RAM", "auto").strip().lower()
        if cache_ram_env in ("0", "false", "no", "off", "disable", "disabled"):
            self.cache_in_ram = False
        elif cache_ram_env in ("1", "true", "yes", "on", "enable", "enabled"):
            self.cache_in_ram = True
        else:
            # Auto: disable RAM caching if host has < 20 GB RAM to prevent container OOM
            self.cache_in_ram = self._detect_ram_capacity_gb() >= 20.0

        # Managed llama-server process handle
        self.llama_proc: Optional[subprocess.Popen] = None
        self.llama_model_id: Optional[str] = None
        self.llama_managed: bool = False
        self.current_kv_type: str = "q8_0"
        self.current_ctx_size: int = 8192

        # Laya model cache: (repo_or_path, device) -> model instance
        self.laya_cache: Dict[Tuple[str, str], Any] = {}
        self.current_laya_device: str = "cpu"

        # Concurrency & Workload Lease Queue
        self._lock = threading.RLock()
        self._condition = threading.Condition(self._lock)
        self.active_lease: Optional[str] = None
        self.in_flight_count: int = 0
        self.waiting_queue: List[str] = []

    @staticmethod
    def _get_cuda_device_count() -> int:
        """How many CUDA devices this box has. **0 means UNKNOWN.**

        It used to return 1 as a fallback when CUDA was unavailable, and "1"
        is indistinguishable from "one real GPU" — so a caller could not tell
        a single-GPU L4 from a box where the count could not be determined.
        That mattered: the multi-GPU decision is "are ComfyUI and the LLM on
        different cards", and a box whose count is unknown has to be judged
        on the CONFIGURED indices, not on a count that was never measured.

        A real single-GPU box reports 1, which is what makes the single-GPU
        rule work: `LLM_GPU_DEVICE=1` on a one-card L4 asks for a device
        that does not exist, and the arbiter must not believe it.
        """
        try:
            import torch

            if torch.cuda.is_available():
                return torch.cuda.device_count()
        except Exception:
            pass
        return 0

    @staticmethod
    def _detect_ram_capacity_gb() -> float:
        """Total system RAM in GB.

        `psutil` is NOT in `requirements.txt`, so the `import psutil` branch
        essentially never ran and this returned a hardcoded 32.0 — meaning
        the "auto" RAM-cache policy believed every machine had 32 GB and
        enabled caching even on a 4 GB one, where the copy then took the
        container down. `/proc/meminfo` is the same source `psutil` reads, so
        use it directly.
        """
        try:
            import psutil

            return psutil.virtual_memory().total / (1024**3)
        except Exception:
            pass
        try:
            with open("/proc/meminfo", "r") as f:
                for line in f:
                    if line.startswith("MemTotal:"):
                        return int(line.split()[1]) * 1024 / (1024**3)
        except Exception:
            pass
        # Unknown. Assume the SMALLER common case so the policy errs towards
        # not filling a machine's RAM.
        return 8.0

    @staticmethod
    def _detect_shm_capacity_bytes() -> int:
        """The real capacity of the RAM cache's backing store.

        `/dev/shm` is tmpfs: RAM-BACKED, and in a container its size is set by
        `shm_size` in the compose file — Docker's default is 64 MB, and
        `remount` needs CAP_SYS_ADMIN, which the agent does not have. So the
        agent's "RAM cache" is very often a 64 MB filesystem, and every
        multi-GB model silently fails to stage.

        The capacity has to be MEASURED, not assumed, and it has to be
        REPORTED: a cache that cannot hold the model is a configuration
        problem the operator can fix, and it is invisible without this.
        """
        try:
            path = os.getenv("RAM_CACHE_DIR", "/dev/shm/tnh_ram_cache")
            probe = Path(path)
            while not probe.exists() and probe.parent != probe:
                probe = probe.parent
            usage = shutil.disk_usage(probe)
            return int(usage.total)
        except Exception:
            return 0

    # ----------------------------------------------------------------------
    # GPU VRAM Telemetry & Inspection
    # ----------------------------------------------------------------------

    def get_vram_info(self, device_idx: Optional[int] = None) -> Dict[str, Any]:
        """Query precise live GPU device memory, current usage, and component status."""
        total_mb = 0
        free_mb = 0
        used_mb = 0
        name = "Unknown"
        cuda_available = False
        device_count = 0
        devices: List[Dict[str, Any]] = []

        target_device = device_idx if device_idx is not None else (self.llm_gpu_device if self.is_multi_gpu else 0)

        # 1. Primary: PyTorch CUDA Driver
        try:
            import torch

            if torch.cuda.is_available():
                cuda_available = True
                device_count = torch.cuda.device_count()
                target_device = min(target_device, max(0, device_count - 1))
                name = torch.cuda.get_device_name(target_device)
                free_bytes, total_bytes = torch.cuda.mem_get_info(target_device)
                total_mb = int(total_bytes / (1024 * 1024))
                free_mb = int(free_bytes / (1024 * 1024))
                used_mb = max(0, total_mb - free_mb)

                for idx in range(device_count):
                    f_b, t_b = torch.cuda.mem_get_info(idx)
                    t_m = int(t_b / (1024 * 1024))
                    f_m = int(f_b / (1024 * 1024))
                    devices.append({
                        "index": idx,
                        "name": torch.cuda.get_device_name(idx),
                        "vram_total_mb": t_m,
                        "vram_used_mb": max(0, t_m - f_m),
                        "vram_free_mb": f_m,
                    })
        except Exception:
            pass

        # 2. Fallback: nvidia-smi CLI
        if not cuda_available:
            try:
                res = subprocess.run(
                    ["nvidia-smi", "--query-gpu=index,name,memory.total,memory.used,memory.free", "--format=csv,noheader,nounits"],
                    capture_output=True,
                    text=True,
                    timeout=2.0,
                    check=False,
                )
                if res.returncode == 0 and res.stdout.strip():
                    lines = [line.strip() for line in res.stdout.strip().splitlines() if line.strip()]
                    device_count = len(lines)
                    for l in lines:
                        parts = [p.strip() for p in l.split(",")]
                        idx = int(parts[0]) if len(parts) > 0 and parts[0].isdigit() else len(devices)
                        d_name = parts[1] if len(parts) > 1 else "GPU"
                        t_m = int(parts[2]) if len(parts) > 2 else 0
                        u_m = int(parts[3]) if len(parts) > 3 else 0
                        f_m = int(parts[4]) if len(parts) > 4 else max(0, t_m - u_m)
                        devices.append({
                            "index": idx,
                            "name": d_name,
                            "vram_total_mb": t_m,
                            "vram_used_mb": u_m,
                            "vram_free_mb": f_m,
                        })
                    if devices:
                        sel = devices[min(target_device, len(devices) - 1)]
                        name = sel["name"]
                        total_mb = sel["vram_total_mb"]
                        used_mb = sel["vram_used_mb"]
                        free_mb = sel["vram_free_mb"]
                        cuda_available = True
            except Exception:
                pass

        llama_alive = self.is_llama_running()

        return {
            "available": cuda_available,
            "device_name": name,
            "target_device": target_device,
            "device_count": device_count,
            "devices": devices,
            "is_multi_gpu": self.is_multi_gpu,
            "comfy_gpu_device": self.comfy_gpu_device,
            "llm_gpu_device": self.llm_gpu_device,
            "laya_gpu_device": self.laya_gpu_device,
            "cache_in_ram": self.cache_in_ram,
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
            "active_lease": self.active_lease,
            "in_flight_count": self.in_flight_count,
            "queue_depth": len(self.waiting_queue),
            "waiting_workloads": list(self.waiting_queue),
            "comfy_generating": self.is_comfy_generating(),
        }

    # ----------------------------------------------------------------------
    # Component Eviction Controls & Execution Inspection
    # ----------------------------------------------------------------------

    def is_comfy_generating(self, timeout: float = 2.0) -> bool:
        """Is ComfyUI executing or queuing a prompt?

        The failure modes are distinguished, because they mean OPPOSITE
        things, and treating them the same is expensive:

        * ComfyUI REFUSES the connection -> it is not running -> it is
          definitely not generating -> False. A worker that serves only the
          LLM has no ComfyUI at all, and answering "busy" here would put a
          60-second drain in front of every one of its requests.
        * ComfyUI ACCEPTS the connection but does not ANSWER in time -> it is
          running and busy -> True. Freeing its VRAM now would kill a live
          generation.
        * ComfyUI answers with an HTTP error -> it is running, and it is not
          generating -> False.

        The old version answered False for every failure, so a timeout on a
        loaded ComfyUI freed its VRAM under a live generation. The version
        that answered True for every failure stalled every request on a
        worker with no ComfyUI - and made the test suite 60 seconds slower
        per affected test. Neither is right; this distinguishes them.
        """
        try:
            req = urllib.request.Request(f"{self.comfy_url}/queue")
            with urllib.request.urlopen(req, timeout=timeout) as resp:
                if resp.status == 200:
                    data = json.loads(resp.read().decode("utf-8"))
                    running = data.get("queue_running") or []
                    pending = data.get("queue_pending") or []
                    return bool(running or pending)
                # It answered, with something that is not a queue.
                return False
        except urllib.error.HTTPError:
            # It answered, with an error. It is running; it is not generating.
            return False
        except urllib.error.URLError as exc:
            reason = getattr(exc, "reason", exc)
            if isinstance(reason, ConnectionRefusedError):
                # Not running at all.
                return False
            # A timeout or a reset: it is running and we cannot tell, so
            # assume busy.
            logger.debug("comfy_generating_probe_uncertain", extra={"error": str(exc)})
            return True
        except Exception as exc:
            logger.debug("comfy_generating_probe_failed", extra={"error": str(exc)})
            return True

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

    def _wait_for_vram_release(self, target_free_mb: int, timeout: float = 5.0) -> int:
        """Poll until free VRAM reaches `target_free_mb`, or the deadline passes.

        Returns the free VRAM actually observed.

        This replaces the fixed `time.sleep(0.1..0.4)` calls that stood in for
        "wait for the GPU". A fixed sleep is a guess: on a busy card the
        memory can take seconds to come back, and the caller proceeds to
        allocate against a number that is still wrong. Polling is cheap
        (a `mem_get_info` call) and it is the difference between "the swap
        worked" and "the swap raced".
        """
        deadline = time.time() + timeout
        free_mb = 0
        while True:
            info = self.get_vram_info()
            free_mb = int(info.get("vram_free_mb", 0))
            if free_mb >= target_free_mb or time.time() >= deadline:
                return free_mb
            time.sleep(0.15)

    def stop_llama(self, timeout: float = 3.0) -> bool:
        """Gracefully terminate running llama-server process to recover 10-18GB VRAM.

        Returns True only if the server is actually gone. The old version
        returned True unconditionally, including when the kill had timed out
        and the child was still holding 19 GB — so the caller could not tell
        that the VRAM it was about to allocate was still occupied.
        """
        with self._lock:
            freed = False

            # 1. Managed Popen process
            if self.llama_proc is not None:
                try:
                    logger.info("stopping_managed_llama_server", extra={"model_id": self.llama_model_id})
                    self.llama_proc.terminate()
                    t0 = time.time()
                    while time.time() - t0 < timeout:
                        if self.llama_proc.poll() is not None:
                            freed = True
                            break
                        time.sleep(0.1)
                    if self.llama_proc.poll() is None:
                        logger.warning("force_killing_managed_llama_server")
                        self.llama_proc.kill()
                        try:
                            self.llama_proc.wait(timeout=5.0)
                            freed = True
                        except Exception as exc:
                            # The child did not die. It may still be holding
                            # 19 GB of VRAM, and the caller must know that
                            # rather than being told "stopped".
                            logger.error(
                                "llama_server_kill_timed_out",
                                extra={"pid": self.llama_proc.pid, "error": str(exc)},
                            )
                except Exception as exc:
                    logger.warning(f"error_stopping_llama_proc: {exc}")
                finally:
                    self.llama_proc = None
                    self.llama_model_id = None
                    self.llama_managed = False

            # 2. Check if an orphaned llama-server is listening on the port
            #
            # `pkill` is asynchronous: it sends SIGTERM and returns. llama.cpp
            # handles SIGTERM DEFERRED — the handler sets a flag that the main
            # loop notices between token batches — so a server mid-prefill can
            # take seconds to honour it. `pkill -f` also matches the WHOLE
            # command line as a regex, so `llama-server.*8003` would also
            # match a server on port 18003.
            try:
                subprocess.run(
                    ["pkill", "-TERM", "-f", rf"llama-server.*--port[ =]{self.llm_port}\b"],
                    check=False,
                    stdout=subprocess.DEVNULL,
                    stderr=subprocess.DEVNULL,
                    timeout=5,
                )
            except FileNotFoundError:
                # `procps` is not in the slim image. Orphans then survive
                # every stop and keep the card allocated.
                logger.warning("pkill_unavailable_cannot_reap_orphan_llama_servers")
            except Exception as exc:
                logger.warning("orphan_llama_pkill_failed", extra={"error": str(exc)})

            # 3. Flush torch CUDA cache if available in this process.
            # This frees the AGENT's own cached blocks, not the llama-server's
            # — it is a no-op for the actual problem, but it is not harmful.
            try:
                import torch

                if torch.cuda.is_available():
                    torch.cuda.empty_cache()
            except Exception:
                pass

            return freed or not self.is_llama_running()

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
        target_dev_idx = self.laya_gpu_device
        cuda_target_str = f"cuda:{target_dev_idx}"

        info = self.get_vram_info(device_idx=target_dev_idx)
        if not info["available"]:
            return "cpu"

        # If llama-server is actively running on the same GPU, Laya runs on CPU
        # to ensure the LLM has 100% unimpeded VRAM and prevent OOM
        if not self.is_multi_gpu and self.is_llama_running():
            return "cpu"

        # If already plenty of free VRAM (>= required headroom), run on CUDA for <100ms latency
        if info["vram_free_mb"] >= required_headroom_mb:
            return cuda_target_str

        # If single-GPU and ComfyUI is on same GPU, try freeing ComfyUI VRAM first.
        #
        # GATED ON THE DRAIN. Every other eviction in this file waits for
        # ComfyUI to finish what it is generating; this one did not, and the
        # Director runs on EVERY chat turn — so a chat arriving while ComfyUI
        # was sampling could unload the diffusion model out from under the
        # running generation.
        if not self.is_multi_gpu or (self.comfy_gpu_device == target_dev_idx):
            if self.is_comfy_generating():
                logger.debug("laya_device_skipped_comfy_free_comfyui_busy")
            elif self.free_comfy_vram():
                self._wait_for_vram_release(
                    info["vram_free_mb"] + required_headroom_mb, timeout=3.0
                )
                refreshed = self.get_vram_info(device_idx=target_dev_idx)
                if refreshed["vram_free_mb"] >= required_headroom_mb:
                    return cuda_target_str

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
                model = self.laya_cache[cache_key]
                model_dev = getattr(model, "device", None)
                actual_dev = str(model_dev) if model_dev is not None else device
                resolved_dev = "cuda" if "cuda" in actual_dev.lower() else "cpu"
                self.current_laya_device = resolved_dev
                return model, resolved_dev

            # Attempt to load on chosen device
            try:
                logger.info("loading_laya_model", extra={"model_id": model_id, "device": device, "source": repo_or_path})
                hf_token = os.getenv("HF_TOKEN") or None
                model = laya.load(repo_or_path, device=device, token=hf_token)
                model_dev = getattr(model, "device", None)
                actual_dev = str(model_dev) if model_dev is not None else device
                resolved_dev = "cuda" if "cuda" in actual_dev.lower() else "cpu"
                self.laya_cache[cache_key] = model
                self.current_laya_device = resolved_dev
                return model, resolved_dev
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
                    hf_token = os.getenv("HF_TOKEN") or None
                    model = laya.load(repo_or_path, device="cpu", token=hf_token)
                    self.laya_cache[cpu_key] = model
                    self.current_laya_device = "cpu"
                    return model, "cpu"
                raise

    # ----------------------------------------------------------------------
    # Workload Lease & Concurrency Queue
    # ----------------------------------------------------------------------

    def _lease_conflicts(self, workload: str) -> bool:
        """Would taking `workload` now cut across work already in flight?

        Shared by `acquire_lease` (which waits, then takes) and
        `_wait_for_drain` (which only waits), so the two can never disagree
        about what counts as a conflict.
        """
        if workload in ("image", "tts"):
            # Conflict if LLM inference is actively in-flight
            return (self.active_lease == "llm" and self.in_flight_count > 0)
        if workload == "llm":
            # Conflict if ComfyUI is actively sampling or an image/tts lease is held
            if self.is_comfy_generating():
                return True
            if self.active_lease in ("image", "tts") and self.in_flight_count > 0:
                # Auto-reconcile: if ComfyUI is completely idle, image/tts lease is finished
                if not self.is_comfy_generating():
                    self.active_lease = None
                    self.in_flight_count = 0
                    return False
                return True
        return False

    def _wait_for_drain(self, workload: str, timeout: float = 60.0) -> bool:
        """Wait for a conflicting workload to finish, WITHOUT taking a lease.

        `acquire_lease` both waits and takes, which is right for a caller
        that is about to do the work. `prepare_for_workload` is not that
        caller — the route (or the backend, over HTTP) takes the lease
        itself — so using `acquire_lease` here took a lease that nobody
        released.

        The counts were: prepare (+1), route acquire (+1), route release
        (-1). `in_flight_count` therefore settled at 1 permanently after the
        first chat request, `active_lease` was never cleared again, and every
        later image request saw a conflict, blocked for the full 60 s
        timeout, and then proceeded anyway — killing the llama-server that
        might have been streaming an answer.

        Returns True if the drain completed, False on timeout.
        """
        workload = (workload or "idle").strip().lower()
        if workload not in ("image", "llm", "decisions", "tts"):
            return True
        if self.is_multi_gpu or workload == "decisions":
            return True

        start_time = time.time()
        with self._lock:
            if not self._lease_conflicts(workload):
                return True
            logger.info(
                "workload_drain_waiting",
                extra={
                    "requested": workload,
                    "active_lease": self.active_lease,
                    "in_flight": self.in_flight_count,
                },
            )
            while self._lease_conflicts(workload):
                remaining = timeout - (time.time() - start_time)
                if remaining <= 0:
                    logger.warning(
                        "workload_drain_timeout",
                        extra={"requested": workload, "timeout": timeout},
                    )
                    return False
                self._condition.wait(timeout=min(remaining, 1.0))
            return True

    def acquire_lease(self, workload: str, timeout: float = 60.0) -> bool:
        """Acquire an active workload lease, waiting if another conflicting workload is in-flight.

        Guarantees that:
        1. An active LLM inference stream is NEVER terminated or evicted mid-stream.
        2. An active ComfyUI diffusion generation is NEVER interrupted by an LLM launch.
        3. Multi-GPU nodes bypass contention since ComfyUI and LLM reside on separate GPUs.
        """
        workload = (workload or "idle").strip().lower()
        if workload not in ("image", "llm", "decisions", "tts"):
            return True

        if self.is_multi_gpu or workload == "decisions":
            with self._lock:
                if self.active_lease != workload and self.in_flight_count == 0:
                    self.active_lease = workload
                self.in_flight_count += 1
                return True

        start_time = time.time()
        with self._lock:
            if self._lease_conflicts(workload):
                self.waiting_queue.append(workload)
                logger.info(
                    "workload_queued_waiting_for_lease",
                    extra={
                        "requested": workload,
                        "active_lease": self.active_lease,
                        "in_flight": self.in_flight_count,
                        "queue_depth": len(self.waiting_queue),
                    },
                )
                try:
                    while self._lease_conflicts(workload):
                        elapsed = time.time() - start_time
                        remaining = timeout - elapsed
                        if remaining <= 0:
                            logger.warning(
                                "workload_lease_timeout",
                                extra={"requested": workload, "timeout": timeout},
                            )
                            return False
                        self._condition.wait(timeout=min(remaining, 1.0))
                finally:
                    if workload in self.waiting_queue:
                        self.waiting_queue.remove(workload)

            self.active_lease = workload
            self.in_flight_count += 1
            logger.debug(
                "workload_lease_acquired",
                extra={"workload": workload, "in_flight": self.in_flight_count},
            )
            return True

    def release_lease(self, workload: str) -> None:
        """Release an active workload lease and notify waiting queue."""
        workload = (workload or "idle").strip().lower()
        with self._lock:
            self.in_flight_count = max(0, self.in_flight_count - 1)
            if self.in_flight_count == 0:
                self.active_lease = None
                self._condition.notify_all()
            logger.debug(
                "workload_lease_released",
                extra={"workload": workload, "in_flight": self.in_flight_count, "active_lease": self.active_lease},
            )

    # ----------------------------------------------------------------------
    # Workload Preparation & Priority Arbiter
    # ----------------------------------------------------------------------

    def prepare_for_workload(
        self,
        workload: str,
        model_id: Optional[str] = None,
        min_free_vram_mb: int = 0,
        kv_cache_type: Optional[str] = None,
        context_tokens: Optional[int] = None,
        timeout: float = 60.0,
    ) -> Dict[str, Any]:
        """Enforce strict VRAM retention/eviction hierarchy before execution."""
        workload = (workload or "idle").strip().lower()

        with self._lock:
            info = self.get_vram_info()
            total_mb = info["vram_total_mb"]
            free_mb = info["vram_free_mb"]

            # ==============================================================
            # CASE A: IMAGE OR TTS WORKLOAD (ComfyUI)
            # ==============================================================
            if workload in ("image", "tts"):
                self.active_workload = workload
                if workload == "image":
                    self.last_image_activity = time.time()

                # The lease is taken HERE, and released by whoever does the
                # work — the route, or the backend over HTTP. Exactly one
                # acquire, exactly one release.
                if not self.acquire_lease(workload, timeout=timeout):
                    logger.warning(
                        f"{workload}_lease_timeout",
                        extra={"timeout": timeout, "active_lease": self.active_lease},
                    )

                # Multi-GPU optimization: ComfyUI (GPU 0) and LLM (GPU 1) run concurrently without eviction!
                if self.is_multi_gpu:
                    return {
                        "status": "ready",
                        "workload": workload,
                        "policy": "multi_gpu_concurrent",
                        "actions_taken": ["bypassed_llama_eviction_multi_gpu"],
                        "vram": self.get_vram_info(device_idx=self.comfy_gpu_device),
                    }

                # On huge GPUs (e.g. A100 80GB), both image/tts & LLM fit concurrently
                if total_mb >= 70000:
                    return {
                        "status": "ready",
                        "workload": workload,
                        "policy": "concurrent",
                        "actions_taken": [],
                        "vram": self.get_vram_info(),
                    }

                # On constrained GPUs (T4 16GB, L4 24GB, A10 24GB, A100 40GB):
                # Target free VRAM needed for clean diffusion or speech generation
                # TTS (Qwen3-TTS) requires ~6GB while heavy diffusion models require ~10GB
                default_target = 6000 if workload == "tts" else 10000
                target_free = min_free_vram_mb if min_free_vram_mb > 0 else default_target

                actions_taken: List[str] = []

                # COOPERATIVE DRAIN: Wait for any active LLM inference stream to finish!
                if not self._wait_for_drain(workload, timeout=timeout):
                    actions_taken.append("llm_drain_timeout")
                else:
                    actions_taken.append("waited_for_llm_drain")

                # EVICTION STEP 1: Stop llama-server to reclaim 10-18GB VRAM
                if free_mb < target_free and self.is_llama_running():
                    self.stop_llama()
                    actions_taken.append("stopped_llama_server")
                    free_mb = self._wait_for_vram_release(target_free, timeout=8.0)
                    info = self.get_vram_info()
                    free_mb = info["vram_free_mb"]

                # EVICTION STEP 2 (LAST RESORT): If free VRAM is STILL below target,
                # ONLY THEN touch Laya to squeeze out the final ~1GB VRAM
                if free_mb < target_free and any(k[1].startswith("cuda") for k in self.laya_cache):
                    self.unload_laya_cuda()
                    actions_taken.append("unloaded_laya_cuda")
                    free_mb = self._wait_for_vram_release(target_free, timeout=3.0)
                    info = self.get_vram_info()
                    free_mb = info["vram_free_mb"]
                else:
                    # Laya is kept running on CUDA!
                    actions_taken.append("preserved_laya_cuda")

                if not info.get("available", True):
                    status = "ready"
                else:
                    status = "ready" if free_mb >= target_free else "insufficient_vram"
                if status != "ready":
                    actions_taken.append(f"insufficient_vram:{free_mb}_of_{target_free}")

                return {
                    "status": status,
                    "workload": workload,
                    "actions_taken": actions_taken,
                    "vram": self.get_vram_info(),
                    "free_mb": free_mb,
                    "target_free_mb": target_free,
                }

            # ==============================================================
            # CASE B: LLM WORKLOAD (llama-server)
            # ==============================================================
            elif workload == "llm":
                self.active_workload = "llm"
                self.last_llm_activity = time.time()

                actions_taken = []

                # The lease is taken HERE and released by whoever does the
                # work. Exactly one acquire, exactly one release — see the
                # image branch for why.
                if not self.acquire_lease("llm", timeout=timeout):
                    logger.warning(
                        "llm_lease_timeout",
                        extra={"timeout": timeout, "active_lease": self.active_lease},
                    )

                if self.is_multi_gpu:
                    # Multi-GPU: Skip ComfyUI eviction completely! ComfyUI models stay resident on GPU 0.
                    actions_taken.append("bypassed_comfy_eviction_multi_gpu")
                else:
                    # COOPERATIVE DRAIN: Wait if ComfyUI is actively generating or image lease is held.
                    # Wait only — the caller holds the lease for the duration
                    # of the work.
                    if not self._wait_for_drain("llm", timeout=timeout):
                        actions_taken.append("comfy_drain_timeout")
                    else:
                        actions_taken.append("waited_for_comfy_drain")

                    # EVICTION STEP 1: Flush ComfyUI models from VRAM
                    #
                    # Only when it is actually needed, OR when the model's
                    # size is unknown — an unknown size is not a reason to
                    # skip the free, it is a reason to assume the worst.
                    #
                    # It used to run on EVERY chat request, which unloaded
                    # the diffusion model from VRAM whether or not the LLM
                    # needed the room — so every chat cost the NEXT image
                    # request a full checkpoint reload.
                    model_path_hint, _ = self._resolve_model_path(model_id)
                    weight_hint_mb = (
                        int(os.path.getsize(model_path_hint) / (1024 * 1024))
                        if (model_path_hint and os.path.exists(model_path_hint))
                        else 0
                    )
                    hint_ctx = int(context_tokens or self.current_ctx_size or 8192)
                    hint_kv = (kv_cache_type or self.current_kv_type or "q8_0")
                    needed_mb = weight_hint_mb + self._kv_reserve_mb(model_path_hint, hint_ctx, hint_kv)
                    if (weight_hint_mb == 0 or free_mb < needed_mb) and self.free_comfy_vram():
                        actions_taken.append("freed_comfy_vram")
                        self._wait_for_vram_release(free_mb + 1500, timeout=3.0)

                info = self.get_vram_info(device_idx=self.llm_gpu_device)
                free_mb = info["vram_free_mb"]

                # EVICTION STEP 2: Priority check for Laya
                # The rule: "keep laya models running. ComfyUI is cleared first; if comfyui vram clear
                # isn't enough, then it touches the laya one."
                # Check if unloading Laya would allow the LLM model to fit 100% on GPU, OR if free VRAM is critically low (< 4 GB)
                laya_loaded_cuda = any(k[1].startswith("cuda") for k in self.laya_cache)
                if laya_loaded_cuda and info.get("available", False):
                    model_path, _ = self._resolve_model_path(model_id)
                    weight_mb = (
                        int(os.path.getsize(model_path) / (1024 * 1024))
                        if (model_path and os.path.exists(model_path))
                        else 0
                    )
                    # The same computed reserve the offload decision uses —
                    # a flat 1800 here was calibrated for an 8k context at
                    # q8_0 while the registry ships `ctx: 32768`.
                    reserve_mb = self._kv_reserve_mb(
                        model_path, hint_ctx, hint_kv
                    )
                    needed_for_full_mb = weight_mb + reserve_mb

                    # Laya on CUDA typically frees ~1200 - 1800 MB
                    estimated_laya_vram = 1500
                    potential_free_mb = free_mb + estimated_laya_vram

                    if weight_mb > 0 and (free_mb < needed_for_full_mb <= potential_free_mb or (not self.is_multi_gpu and free_mb < needed_for_full_mb)):
                        # Demoting Laya to CPU will allow the LLM to fit 100% on GPU!
                        self.unload_laya_cuda()
                        actions_taken.append("unloaded_laya_to_allow_full_llm_gpu_fit")
                        time.sleep(0.1)
                    elif 0 < free_mb < 2000:
                        # Free VRAM is critically constrained (< 2 GB), demote Laya as safety measure
                        self.unload_laya_cuda()
                        actions_taken.append("unloaded_laya_low_vram_safety")
                        time.sleep(0.1)
                    else:
                        # Laya is PRESERVED on CUDA! (Instant <100ms director decisions)
                        actions_taken.append("preserved_laya_cuda")
                else:
                    actions_taken.append("preserved_laya_cuda")

                # Ensure llama-server is alive and serving the target model & configuration.
                #
                # Skipped when the LLM is served by something else — the local
                # stack in `llm` mode, or an operator's own server behind
                # `LLM_UPSTREAM_BASE`. Starting a second one with the same
                # weights on the same card is an OOM, and the copy is entirely
                # wasted because the requests go to the other port.
                if self.llm_served_externally:
                    actions_taken.append("llm_served_externally_no_jit_launch")
                else:
                    need_restart = (
                        not self.is_llama_running()
                        or (model_id and self.llama_model_id and self.llama_model_id != model_id)
                        or (kv_cache_type and self.current_kv_type != kv_cache_type)
                        or (context_tokens and self.current_ctx_size != context_tokens)
                    )
                    if need_restart:
                        started = self.ensure_llama_running(
                            model_id=model_id,
                            kv_cache_type=kv_cache_type,
                            context_tokens=context_tokens,
                        )
                        actions_taken.append(f"started_llama_server:{model_id}" if started else "llama_launch_failed")
                        if not started:
                        # The status was "ready" here even when the launch
                        # failed, so the caller proxied to a dead port and
                        # reported "Upstream LLM server unreachable" with
                        # `retryable: False` — telling the backend the
                        # provider was permanently broken rather than that
                        # the model had not finished loading.
                            return {
                                "status": "llm_launch_failed",
                                "workload": "llm",
                                "actions_taken": actions_taken,
                                "vram": self.get_vram_info(device_idx=self.llm_gpu_device),
                            }

                return {
                    "status": "ready",
                    "workload": "llm",
                    "actions_taken": actions_taken,
                    "vram": self.get_vram_info(device_idx=self.llm_gpu_device),
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
                    "vram": self.get_vram_info(device_idx=self.laya_gpu_device),
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

    def ensure_llama_running(
        self,
        model_id: Optional[str] = None,
        kv_cache_type: Optional[str] = None,
        context_tokens: Optional[int] = None,
        timeout: float = 600.0,
    ) -> bool:
        """Start llama-server Just-In-Time from RAM cache if not already running."""
        with self._lock:
            # Resolve target KV cache precision and context window
            env_kv = (os.getenv("CACHE_KV_TYPE") or "").strip().lower()
            target_kv = (kv_cache_type or env_kv).strip().lower()
            target_ctx = int(context_tokens or os.getenv("LLAMA_CTX_SIZE") or 8192)

            # Resolve model weights path (prefer RAM cache /dev/shm)
            model_path, resolved_mid = self._resolve_model_path(model_id)
            if not model_path or not os.path.exists(model_path):
                logger.warning(f"model_path_not_found: {model_path} (mid={model_id})")
                return False

            # If already running with matching model and configuration, return immediately
            #
            # `config_matches` compares only what the CALLER explicitly asked
            # for. It used to compare the auto-derived KV type as well, and
            # that value is a function of the FREE VRAM at the moment of the
            # call — which swings by ~10 GB depending on whether ComfyUI
            # currently holds a checkpoint. So a chat request (ComfyUI idle ->
            # f16) and an image request (ComfyUI resident -> q8_0) each
            # decided the running server was misconfigured, and tore down a
            # 20 GB model for a full reload. Alternating between a chat and an
            # image cost a process kill plus a 19.5 GB GGUF load every time.
            #
            # The running server's own KV type is the right answer. Only an
            # EXPLICIT request may override it.
            is_generic = (not model_id) or (str(model_id).strip().lower() in {"default", "auto", "rp", "llm", "primary", "base"})
            if self.is_llama_running():
                model_matches = is_generic or (
                    self.llama_model_id
                    and (
                        self.llama_model_id == model_id
                        or self.llama_model_id == resolved_mid
                        # The registry id and the resolved id are the same
                        # model; the raw request id is often the long
                        # registry name while the RAM cache resolves it to a
                        # short one.
                        or str(self.llama_model_id).lower() in str(model_id or "").lower()
                    )
                )
                config_matches = True
                if kv_cache_type:
                    config_matches = config_matches and self.current_kv_type == kv_cache_type
                if context_tokens:
                    config_matches = config_matches and self.current_ctx_size == context_tokens
                if model_matches and config_matches:
                    self.last_llm_activity = time.time()
                    return True
                # Different model or config requested -> stop current and hot-switch
                self.stop_llama()

            # The KV type is only chosen when we are actually going to START a
            # server, so it cannot flip-flop on a running one.
            if not target_kv:
                info = self.get_vram_info(device_idx=self.llm_gpu_device)
                free_mb = info.get("vram_free_mb", 0)
                is_gemma = "gemma" in model_path.lower() or (model_id and "gemma" in str(model_id).lower())
                # Gemma 3 experiences severe prefill stalls with quantized KV in llama.cpp; use f16.
                # High-VRAM GPUs (>= 20GB free) should use f16 for peak prompt eval speed and 0 dequant latency.
                if is_gemma or free_mb >= 20000:
                    target_kv = "f16"
                else:
                    target_kv = "q8_0"

            # Locate llama-server binary
            binary = self._find_llama_binary()
            if not binary:
                logger.warning("llama_binary_not_found")
                return False

            # Calculate safe dynamic layer offload (-ngl) based on LIVE free VRAM
            ngl, ngl_meta = self.calculate_safe_ngl(
                model_path,
                context_tokens=target_ctx,
                kv_cache_type=target_kv,
            )
            logger.info("llama_safe_ngl_determined", extra=ngl_meta)

            # Build command
            cmd = [
                binary,
                "-m", model_path,
                "--host", "127.0.0.1",
                "--port", str(self.llm_port),
                "--main-gpu", str(self.llm_gpu_device),
                "-ngl", str(ngl),
                "-np", "1",
                "-c", str(target_ctx),
                "-b", "2048",
                "-ub", "512",
                "--cache-type-k", target_kv,
                "--cache-type-v", target_kv,
                "--jinja",
            ]
            if ngl > 0:
                cmd.append("-fa")
            if target_ctx > 32768:
                cmd.extend(["--rope-scaling", "yarn", "--rope-scale", "2.0", "--yarn-orig-ctx", "32768"])

            # Setup aliases
            aliases = []
            is_util_model = ("util" in (resolved_mid or "").lower()) or (model_id and "util" in str(model_id).lower())
            if is_util_model:
                aliases.extend(["util", "utility"])
            else:
                aliases.extend(["default", "rp"])
            if resolved_mid and resolved_mid not in aliases:
                aliases.append(resolved_mid)
            if model_id and str(model_id).strip().lower() not in {"default", "auto", "rp", "llm", "util"}:
                aliases.append(str(model_id).strip())
            cmd.extend(["--alias", ",".join(list(dict.fromkeys(aliases)))])

            # Prepare CUDA library environment
            env = self._build_cuda_env()

            logger.info("launching_jit_llama_server", extra={"cmd": " ".join(cmd[:8]), "model": resolved_mid, "gpu": self.llm_gpu_device})
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
                                self.current_kv_type = target_kv
                                self.current_ctx_size = target_ctx
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
        """Resolve weight file path from RAM cache or disk storage with robust multi-tier fallback."""
        raw_mid = str(model_id).strip() if model_id else ""
        mid_lower = raw_mid.lower()

        is_util = mid_lower in ("util", "utility", "tool", "agentic", "caption") or "util" in mid_lower
        is_rp = mid_lower in ("rp", "roleplay", "chat", "chat_reply", "story")
        is_generic = (not raw_mid) or mid_lower in ("default", "auto", "rp", "llm", "primary", "base", "model")

        env_rp = os.getenv("ACTIVE_RP_MODEL") or os.getenv("DEFAULT_RP_MODEL") or "artemis_31b_q4"
        env_util = os.getenv("ACTIVE_UTIL_MODEL") or os.getenv("DEFAULT_UTIL_MODEL") or "gemma3_12b_heretic_util"

        clean_mid = None
        if not is_generic and not is_util:
            clean_mid = raw_mid
        elif is_util:
            clean_mid = env_util
        else:
            clean_mid = env_rp

        disk_dirs = [
            os.getenv("PERSISTENT_STORAGE_PATH", ""),
            "/mnt/data/tnhfantasy/llm_models",
            "/mnt/data/models/llm",
            "/mnt/data/llm_models",
            "/mnt/data/models",
            "/vol/llm_models",
            "/vol/models/llm",
            os.getenv("DATA_DIR", "/content/models/llm"),
            "/content/models/llm",
            os.getenv("GDRIVE_LLM_PATH", "/content/drive/MyDrive/tnhfantasy/llm_models"),
            "/content/drive/MyDrive/tnhfantasy/llm_models",
            "/content/agent-data/llm/models",
            "/content/ComfyUI/models/llm",
        ]

        # Low-RAM / Modal direct volume streaming mode: bypass /dev/shm copy when cache_in_ram is disabled
        if not self.cache_in_ram:
            direct_candidates: List[str] = []
            for d_dir in disk_dirs:
                if d_dir and os.path.exists(d_dir):
                    for root, _, files in os.walk(d_dir):
                        for f in sorted(files):
                            if f.endswith(".gguf") and not f.startswith("."):
                                full_p = os.path.join(root, f)
                                if clean_mid and clean_mid.lower() in f.lower():
                                    return full_p, clean_mid or f
                                if full_p not in direct_candidates:
                                    direct_candidates.append(full_p)
            if is_generic and direct_candidates:
                target_hint = env_util if is_util else env_rp
                for cand in direct_candidates:
                    if target_hint.lower() in cand.lower():
                        stem = os.path.splitext(os.path.basename(cand))[0]
                        return cand, stem or target_hint
                first_p = direct_candidates[0]
                stem = os.path.splitext(os.path.basename(first_p))[0]
                return first_p, stem or "default"

        # 1. Check RAM Manager entries
        try:
            from ram_manager import get_ram_manager

            mgr = get_ram_manager()
            # If empty or specific mid not cached, attempt a rescan of ram_dir
            if not mgr.entries or (clean_mid and not mgr.is_cached(clean_mid)):
                mgr._rescan_ram_dir()

            # 1a. Direct hit or alias hit
            target_id = mgr.aliases.get(clean_mid, clean_mid)
            if target_id in mgr.entries:
                return mgr.entries[target_id].ram_path, clean_mid or target_id

            # Also check alias if raw_mid was requested directly (e.g. "util", "rp", "default")
            if raw_mid and raw_mid in mgr.aliases:
                alias_id = mgr.aliases[raw_mid]
                if alias_id in mgr.entries:
                    return mgr.entries[alias_id].ram_path, alias_id

            # 1b. Substring match for requested clean_mid
            if clean_mid:
                for mid, entry in mgr.entries.items():
                    if clean_mid.lower() in mid.lower() or clean_mid.lower() in entry.ram_path.lower():
                        return entry.ram_path, mid

            # 1c. Target role match (rp vs util)
            target_role = "util" if is_util else "rp"
            for mid, entry in mgr.entries.items():
                if entry.role == target_role:
                    return entry.ram_path, mid

            # 1d. Fallback for generic / default / rp: prefer non-util GGUFs first!
            if is_generic or is_rp:
                for mid, entry in mgr.entries.items():
                    if (entry.role in ("rp", "llm") or mid.endswith(".gguf") or entry.ram_path.endswith(".gguf")) and entry.role != "util" and "util" not in mid.lower():
                        return entry.ram_path, mid

            # 1e. Fallback to any LLM model
            for mid, entry in mgr.entries.items():
                if entry.role in ("rp", "util", "llm") or mid.endswith(".gguf") or entry.ram_path.endswith(".gguf"):
                    return entry.ram_path, mid
        except Exception as exc:
            logger.debug(f"ram_manager_resolve_skipped: {exc}")

        # 2. Check RAM directories (/dev/shm/tnh_ram_cache, /dev/shm)
        ram_dirs = [
            os.getenv("RAM_CACHE_DIR", "/dev/shm/tnh_ram_cache"),
            "/dev/shm/tnh_ram_cache",
            "/dev/shm",
        ]
        ram_ggufs: List[str] = []
        for r_dir in ram_dirs:
            if os.path.exists(r_dir):
                for root, _, files in os.walk(r_dir):
                    for f in sorted(files):
                        if f.endswith(".gguf") and not f.startswith("."):
                            full_path = os.path.join(root, f)
                            if full_path not in ram_ggufs:
                                ram_ggufs.append(full_path)
                            if clean_mid and clean_mid.lower() in f.lower():
                                return full_path, clean_mid or f

        if ram_ggufs:
            if is_util:
                for p in ram_ggufs:
                    if "util" in p.lower() or "gemma" in p.lower():
                        stem = os.path.splitext(os.path.basename(p))[0]
                        return p, stem or env_util
            else:
                for p in ram_ggufs:
                    if "artemis" in p.lower() or ("util" not in p.lower() and "gemma" not in p.lower()):
                        stem = os.path.splitext(os.path.basename(p))[0]
                        return p, stem or env_rp
            first_p = ram_ggufs[0]
            stem = os.path.splitext(os.path.basename(first_p))[0]
            return first_p, stem or "default"

        # 3. Check disk storage locations
        disk_ggufs: List[str] = []
        for d_dir in disk_dirs:
            if d_dir and os.path.exists(d_dir):
                for root, _, files in os.walk(d_dir):
                    for f in sorted(files):
                        if f.endswith(".gguf") and not f.startswith("."):
                            full_path = os.path.join(root, f)
                            if full_path not in disk_ggufs:
                                disk_ggufs.append(full_path)
                            if clean_mid and clean_mid.lower() in f.lower():
                                return full_path, clean_mid or f

        if disk_ggufs:
            if is_util:
                for p in disk_ggufs:
                    if "util" in p.lower() or "gemma" in p.lower():
                        stem = os.path.splitext(os.path.basename(p))[0]
                        return p, stem or env_util
            else:
                for p in disk_ggufs:
                    if "artemis" in p.lower() or ("util" not in p.lower() and "gemma" not in p.lower()):
                        stem = os.path.splitext(os.path.basename(p))[0]
                        return p, stem or env_rp
            first_p = disk_ggufs[0]
            stem = os.path.splitext(os.path.basename(first_p))[0]
            return first_p, stem or "default"

        # 4. Ultimate graceful fallback: if any GGUF exists anywhere, use it!
        all_candidates = ram_ggufs + disk_ggufs
        if all_candidates:
            fallback_p = all_candidates[0]
            stem = os.path.splitext(os.path.basename(fallback_p))[0]
            logger.warning(
                f"Requested model '{model_id}' not found; gracefully falling back to available weights: {fallback_p}"
            )
            return fallback_p, stem or "default"

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

    def _get_gguf_layer_count(self, model_path: str) -> Optional[int]:
        """Extract exact layer count (<arch>.block_count) from GGUF binary header."""
        try:
            import struct

            with open(model_path, "rb") as f:
                header = f.read(262144)  # Read first 256 KB
                if len(header) < 24 or header[:4] != b"GGUF":
                    return None
                version = struct.unpack("<I", header[4:8])[0]
                if version not in (2, 3):
                    return None

                idx = 0
                while True:
                    idx = header.find(b".block_count", idx)
                    if idx == -1:
                        break
                    key_end = idx + len(b".block_count")
                    if key_end + 8 <= len(header):
                        val_type = struct.unpack("<I", header[key_end : key_end + 4])[0]
                        count = None
                        if val_type == 4:  # UINT32
                            count = struct.unpack("<I", header[key_end + 4 : key_end + 8])[0]
                        elif val_type == 5:  # INT32
                            count = struct.unpack("<i", header[key_end + 4 : key_end + 8])[0]
                        elif val_type in (10, 11) and key_end + 12 <= len(header):  # UINT64 / INT64
                            count = struct.unpack("<Q", header[key_end + 4 : key_end + 12])[0]

                        if count is not None and 8 <= count <= 256:
                            return int(count)
                    idx += 1
        except Exception as exc:
            logger.debug(f"gguf_layer_count_read_failed: {exc}")
        return None

    def _gguf_kv_geometry(self, model_path: str) -> Dict[str, int]:
        """Read the KV-cache geometry from a GGUF header.

        The KV cache is the largest thing in VRAM that is NOT the weights,
        and its size is fully determined by the context window, the KV
        precision, and the model's attention shape. All three are in the GGUF
        metadata, so the reserve for it can be computed instead of guessed.

        Returns `{}` when the header cannot be read; the caller falls back to
        a conservative estimate.
        """
        out: Dict[str, int] = {}
        try:
            import struct

            with open(model_path, "rb") as f:
                header = f.read(262144)  # Read first 256 KB
            if len(header) < 24 or header[:4] != b"GGUF":
                return out
            version = struct.unpack("<I", header[4:8])[0]
            if version not in (2, 3):
                return out

            def _read_int(suffix: str, exclude: str = "") -> Optional[int]:
                needle = suffix.encode()
                idx = 0
                while True:
                    idx = header.find(needle, idx)
                    if idx == -1:
                        return None
                    key_end = idx + len(suffix)
                    # `.head_count` is a prefix of `.head_count_kv`; without
                    # this guard the KV head count would be read as the head
                    # count, and the reserve would be wrong in the direction
                    # that causes an OOM.
                    if exclude and header[key_end:key_end + len(exclude)] == exclude.encode():
                        idx += 1
                        continue
                    if key_end + 8 <= len(header):
                        val_type = struct.unpack("<I", header[key_end:key_end + 4])[0]
                        value = None
                        if val_type == 4:  # UINT32
                            value = struct.unpack("<I", header[key_end + 4:key_end + 8])[0]
                        elif val_type == 5:  # INT32
                            value = struct.unpack("<i", header[key_end + 4:key_end + 8])[0]
                        elif val_type in (10, 11) and key_end + 12 <= len(header):  # UINT64 / INT64
                            value = struct.unpack("<Q", header[key_end + 4:key_end + 12])[0]
                        if value is not None and 0 < value < (1 << 20):
                            return int(value)
                    idx += 1

            for key, suffix, exclude in (
                ("n_layers", ".block_count", ""),
                ("n_heads", ".head_count", "_kv"),
                ("n_kv_heads", ".head_count_kv", ""),
                ("hidden_size", ".embedding_length", ""),
                # The authoritative head dimension. It is NOT always
                # hidden_size / n_heads: Qwen3-32B has hidden 5120 and 64
                # heads (80 each) but a head dimension of 128, and Gemma-3
                # carries its own. Using the ratio would understate the KV
                # cache by more than half.
                ("head_dim", ".key_length", ""),
            ):
                value = _read_int(suffix, exclude)
                if value is not None:
                    out[key] = value
            return out
        except Exception as exc:
            logger.debug(f"gguf_kv_geometry_read_failed: {exc}")
            return {}

    def _kv_reserve_mb(self, model_path: Optional[str], ctx: int, kv_type: str) -> int:
        """The VRAM to hold back for the KV cache and llama.cpp's compute buffers.

        This used to be the literal 1800 MB, which is the right order of
        magnitude for an 8k context at q8_0 and roughly 4.7x too small for the
        32k context at f16 that the SAME file selects. The KV cache is
        allocated AFTER the weights, so an under-sized reserve means the model
        loads fine and then the context allocation takes the card over — the
        OOM lands in the child process, where the agent's log shows only
        "llama-server exited unexpectedly code 1".

        Returns megabytes.
        """
        geometry = self._gguf_kv_geometry(model_path) if model_path else {}
        n_layers = geometry.get("n_layers") or 0
        n_kv_heads = geometry.get("n_kv_heads") or 0
        n_heads = geometry.get("n_heads") or 0
        hidden_size = geometry.get("hidden_size") or 0
        head_dim = geometry.get("head_dim") or 0

        # f16 is two bytes per element; q8_0 is one (plus a small metadata
        # overhead that the extra compute allowance covers).
        bytes_per_element = 2 if (kv_type or "").strip().lower() == "f16" else 1

        kv_bytes_per_token = 0
        if n_layers and n_kv_heads and head_dim:
            # K and V, for every layer, at the model's head dimension.
            kv_bytes_per_token = (
                2 * n_layers * n_kv_heads * head_dim * bytes_per_element
            )
        elif n_layers and n_kv_heads and hidden_size and n_heads:
            # No key_length in the header: fall back to the ratio. It is an
            # UNDER-estimate for the models where head_dim != hidden/n_heads,
            # so the compute allowance below covers the difference.
            kv_bytes_per_token = (
                2 * n_layers * n_kv_heads * (hidden_size // n_heads) * bytes_per_element
            )
        elif n_kv_heads:
            kv_bytes_per_token = 2 * n_kv_heads * 128 * bytes_per_element

        if kv_bytes_per_token:
            kv_mb = int((kv_bytes_per_token * max(1, ctx)) / (1024 * 1024))
        else:
            # No geometry available. Fall back to a conservative per-token
            # estimate rather than the old flat 1800, which was calibrated
            # for a quarter of the context this worker actually runs.
            kv_mb = int((256 * 1024 * max(1, ctx)) / (1024 * 1024))

        # llama.cpp's compute and graph buffers (-b 2048 -ub 512) plus the
        # context activation buffers. These scale with the model, not with
        # the context, so they are a roughly constant allowance.
        compute_mb = 1000
        return int(kv_mb + compute_mb)

    def _estimate_layer_count(self, model_path: str, weight_mb: int) -> int:
        """Estimate layer count from model file name or weight size if header read is unavailable.

        This is a LAST RESORT — `_get_gguf_layer_count` reads the real
        number out of the GGUF header and is used first. The name heuristics
        below were wrong for two of the families this worker ships (the
        26/27B group has 62 layers, not 46, and the 12B has 48, not 40), and
        the error direction matters: an UNDER-count produces
        `total_layers * fraction` too small, so the model is offloaded further
        than it needs to be and the missing layers run on the CPU — which is
        the "the layers got loaded on ram instead" complaint, silently and
        permanently for that server's lifetime.
        """
        name = os.path.basename(model_path).lower()
        if "26b" in name or "27b" in name or "sompoa" in name or "goetia" in name or "styletune" in name:
            return 62
        if "31b" in name or "32b" in name or "artemis" in name:
            return 64
        if "70b" in name or "72b" in name:
            return 80
        if "12b" in name or "13b" in name or "14b" in name:
            return 48
        if "24b" in name:
            return 40
        if "7b" in name or "8b" in name or "9b" in name:
            return 32
        if weight_mb > 15000:
            return 62
        if weight_mb > 8000:
            return 48
        return 32

    def calculate_safe_ngl(
        self,
        model_path: str,
        free_mb: Optional[int] = None,
        context_tokens: Optional[int] = None,
        kv_cache_type: Optional[str] = None,
    ) -> Tuple[int, Dict[str, Any]]:
        """Calculate safe GPU layer offload count (-ngl) based on LIVE free VRAM to prevent CUDA OOM."""
        if not os.path.exists(model_path):
            return 0, {"error": "model_not_found"}

        weight_mb = int(os.path.getsize(model_path) / (1024 * 1024))
        info = self.get_vram_info(device_idx=self.llm_gpu_device)
        if not info["available"]:
            return 0, {"ngl": 0, "reason": "cuda_unavailable", "weight_mb": weight_mb}

        actual_free_mb = free_mb if free_mb is not None else info["vram_free_mb"]

        # Reserve for the KV cache and llama.cpp's compute buffers.
        #
        # This used to be the literal 1800 MB, which is the right order of
        # magnitude for an 8k context at q8_0 and roughly 4.7x too small for
        # the 32k context at f16 that this same file selects — and the
        # registry ships `ctx: 32768` for every prose model. The KV cache is
        # allocated AFTER the weights, so an under-sized reserve means the
        # model loads fine and the CONTEXT allocation then takes the card
        # over. The OOM then lands in the child process, where the agent's
        # log shows only "llama-server exited unexpectedly code 1".
        ctx = int(context_tokens or self.current_ctx_size or 8192)
        kv_type = kv_cache_type or self.current_kv_type or "q8_0"
        reserve_mb = self._kv_reserve_mb(model_path, ctx, kv_type)

        total_layers = self._get_gguf_layer_count(model_path) or self._estimate_layer_count(model_path, weight_mb)

        # If GPU free VRAM is critically low (< 3000 MB), cannot safely offload layers
        if actual_free_mb < 3000:
            return 0, {
                "ngl": 0,
                "mode": "cpu_only",
                "reason": "insufficient_free_vram",
                "free_mb": actual_free_mb,
                "weight_mb": weight_mb,
                "reserve_mb": reserve_mb,
                "total_layers": total_layers,
            }

        # Case 1: Entire model + KV cache fits within free VRAM
        if weight_mb + reserve_mb <= actual_free_mb:
            return 99, {
                "ngl": 99,
                "mode": "full_gpu",
                "free_mb": actual_free_mb,
                "weight_mb": weight_mb,
                "reserve_mb": reserve_mb,
                "total_layers": total_layers,
                "context_tokens": ctx,
                "kv_cache_type": kv_type,
            }

        # Case 2: Partial offload needed
        available_weight_mb = max(0, actual_free_mb - reserve_mb)
        fraction = max(0.0, min(1.0, available_weight_mb / weight_mb))
        target_layers = int(total_layers * fraction)

        # Leave at least 2 layers on CPU to guarantee we never overflow free
        # VRAM when partial offload is required.
        #
        # The floor was `max(4, ...)`, which OVERRODE the budget: when the
        # arithmetic allowed 3 layers, 4 were forced onto the GPU — about
        # 1.2 GB against a 1.2 GB budget with nothing left for the KV cache,
        # so the server allocated and died. And for a model with 6 or fewer
        # layers it put ALL of them on the GPU, defeating the "leave two on
        # the CPU" rule entirely.
        safe_ngl = max(0, min(total_layers - 2, target_layers - 1))

        return safe_ngl, {
            "ngl": safe_ngl,
            "mode": "partial_offload",
            "free_mb": actual_free_mb,
            "weight_mb": weight_mb,
            "reserve_mb": reserve_mb,
            "available_weight_mb": available_weight_mb,
            "fraction": round(fraction, 3),
            "total_layers": total_layers,
            "context_tokens": ctx,
            "kv_cache_type": kv_type,
        }


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
