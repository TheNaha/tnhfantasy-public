"""
In-process execution engine for self-hosted Hybrid workers.

A hybrid worker runs ComfyUI (Image/TTS), the storage agent sidecar, and
llama-server (LLM) concurrently on a single GPU node (e.g. Google Colab Pro,
a local multi-modal GPU rig, or a dedicated instance).

Key Architectural Pillars:
1. Unified Node Identity: Single provider entry in the backend routing to
   ComfyUI (:8188), Agent (:8001), and LLM (:8003).
2. Hardware Capability Marker & Concurrency Policy:
   - "exclusive": Mutual exclusion lock on GPU tasks. ComfyUI yields VRAM
     via its /free endpoint after generation before LLM executes (ideal for
     L4 24GB / T4 16GB).
   - "semi_concurrent": Concurrent RP chat and ComfyUI, with mutual exclusion
     for secondary models (ideal for A100 40GB).
   - "concurrent": Full unconstrained parallel execution (ideal for A100 80GB).
   - "auto": Auto-detects policy from the worker's reported VRAM via /info.
3. Dual-Modality Dispatch: Transparently routes image graph workflows to
   DirectComfyEngine and chat completion requests to RemoteLLMEngine.
"""

from __future__ import annotations

import asyncio
import os
import urllib.parse
from typing import Any, AsyncIterator, Dict, List, Optional

from infrastructure.logging import get_logger
from services.engines.base import InProcessEngine
from services.engines.direct_comfy_engine import DirectComfyEngine
from services.engines.worker_transport_engines import RemoteLLMEngine

logger = get_logger("hybrid_engine")


class HybridRemoteEngine(InProcessEngine):
    """Unified engine coordinating ComfyUI, Agent Storage, and LLM on a single node."""

    worker_mode = "hybrid"
    manages_model_files = True
    supports_discovery_reconcile = True

    def __init__(
        self,
        provider_id: str,
        base_url: str = "http://localhost",
        agent_token: str = "",
        comfy_url: Optional[str] = None,
        agent_url: Optional[str] = None,
        llm_url: Optional[str] = None,
        comfy_port: int = 8188,
        agent_port: int = 8001,
        llm_port: int = 8003,
        concurrency_policy: str = "auto",
        hf_token: Optional[str] = None,
        civitai_token: Optional[str] = None,
        default_model: str = "default",
        default_rp_model: str = "rp",
        default_util_model: str = "util",
        **kwargs: Any,
    ) -> None:
        super().__init__(provider_id)
        self.base_url = (base_url or "").strip().rstrip("/")
        self.agent_token = (agent_token or "").strip()
        self.concurrency_policy = (concurrency_policy or "auto").strip().lower()
        self.hf_token = hf_token or os.getenv("HF_TOKEN", "")
        self.civitai_token = civitai_token or os.getenv("CIVITAI_TOKEN", "")

        # Resolve endpoint URLs
        parsed = urllib.parse.urlparse(self.base_url)
        scheme = parsed.scheme or "http"
        host = parsed.hostname or self.base_url.replace("http://", "").replace("https://", "").split(":")[0]

        self.comfy_url = (comfy_url or f"{scheme}://{host}:{comfy_port}").rstrip("/")
        self.agent_url = (agent_url or f"{scheme}://{host}:{agent_port}").rstrip("/")
        self.llm_url = (llm_url or f"{scheme}://{host}:{llm_port}").rstrip("/")

        # Child delegate engines
        self.image_engine = DirectComfyEngine(
            provider_id=f"{provider_id}_image",
            comfy_url=self.comfy_url,
            agent_url=self.agent_url,
            agent_token=self.agent_token,
            hf_token=self.hf_token,
            civitai_token=self.civitai_token,
        )

        self.llm_engine = RemoteLLMEngine(
            provider_id=f"{provider_id}_llm",
            agent_url=self.llm_url,
            agent_token=self.agent_token,
            default_model=default_model,
            default_rp_model=default_rp_model,
            default_util_model=default_util_model,
        )

        # GPU concurrency coordinator
        self._gpu_lock = asyncio.Lock()
        self._resolved_policy: Optional[str] = None
        self._detected_gpu: Optional[Dict[str, Any]] = None

    # ----------------------------------------------------------------------
    # Hardware Capability Marker & Policy Resolution
    # ----------------------------------------------------------------------

    async def _resolve_policy(self) -> str:
        """Resolve concurrency policy, probing remote worker's GPU if set to auto."""
        if self.concurrency_policy in ("exclusive", "semi_concurrent", "concurrent"):
            return self.concurrency_policy
        if self._resolved_policy is not None:
            return self._resolved_policy

        # Auto-detect from agent /info
        try:
            client = self.image_engine.get_agent_client()
            resp = await client.get("/info", timeout=5.0)
            if resp.status_code == 200:
                data = resp.json() or {}
                gpu = data.get("gpu") or {}
                self._detected_gpu = gpu
                vram_mb = gpu.get("vram_total_mb") or 0
                if vram_mb >= 70000:
                    self._resolved_policy = "concurrent"
                elif vram_mb >= 35000:
                    self._resolved_policy = "semi_concurrent"
                else:
                    self._resolved_policy = "exclusive"
                logger.info(
                    "hybrid_policy_auto_detected",
                    provider_id=self.provider_id,
                    gpu=gpu.get("name"),
                    vram_mb=vram_mb,
                    policy=self._resolved_policy,
                )
                return self._resolved_policy
        except Exception as exc:
            logger.warning(
                "hybrid_policy_auto_detection_failed",
                provider_id=self.provider_id,
                error=str(exc),
            )

        # Conservative fallback: exclusive mode (prevents OOM on budget GPUs like L4/T4)
        self._resolved_policy = "exclusive"
        return self._resolved_policy

    async def _free_comfy_vram(self) -> None:
        """Tell ComfyUI to unload models and free CUDA VRAM cache."""
        try:
            client = self.image_engine.get_http_client()
            await client.post(
                f"{self.comfy_url}/free",
                json={"unload_models": True, "free_memory": True},
                timeout=5.0,
            )
            logger.debug("hybrid_comfy_vram_freed", provider_id=self.provider_id)
        except Exception as exc:
            logger.debug("hybrid_comfy_vram_free_ignored", provider_id=self.provider_id, error=str(exc))

    # ----------------------------------------------------------------------
    # Execution & Routing
    # ----------------------------------------------------------------------

    @staticmethod
    def _is_image_workflow(workflow: Dict[str, Any]) -> bool:
        """Determine if a workflow payload is an image generation graph."""
        if not isinstance(workflow, dict):
            return False
        # ComfyUI prompt graphs have node ID keys mapping to {"class_type": ...}
        # or contain "prompt"
        if "prompt" in workflow or "extra_data" in workflow:
            return True
        # If any value is a node dict with 'class_type'
        for val in workflow.values():
            if isinstance(val, dict) and "class_type" in val:
                return True
        return False

    async def inference(
        self,
        workflow: Dict[str, Any],
        job_id: Optional[str] = None,
        use_snapshot: bool = True,
        timeout: float = 3600.0,
    ) -> AsyncIterator[Dict[str, Any]]:
        """Dispatch inference to the proper engine under GPU policy coordination."""
        policy = await self._resolve_policy()
        is_image = self._is_image_workflow(workflow)

        if policy == "exclusive":
            # Strict mutual exclusion for single-GPU budget nodes (e.g. L4, T4)
            async with self._gpu_lock:
                if is_image:
                    try:
                        async for event in self.image_engine.inference(
                            workflow, job_id=job_id, use_snapshot=use_snapshot, timeout=timeout
                        ):
                            yield event
                    finally:
                        # Yield VRAM immediately back to system/LLM
                        await self._free_comfy_vram()
                else:
                    async for event in self.llm_engine.inference(
                        workflow, job_id=job_id, use_snapshot=use_snapshot, timeout=timeout
                    ):
                        yield event

        elif policy == "semi_concurrent":
            # A100-40GB profile: RP and ComfyUI co-exist, but Util or heavy swaps lock
            is_util = isinstance(workflow, dict) and workflow.get("model") == "util"
            if is_util:
                async with self._gpu_lock:
                    async for event in self.llm_engine.inference(
                        workflow, job_id=job_id, use_snapshot=use_snapshot, timeout=timeout
                    ):
                        yield event
            else:
                if is_image:
                    async for event in self.image_engine.inference(
                        workflow, job_id=job_id, use_snapshot=use_snapshot, timeout=timeout
                    ):
                        yield event
                else:
                    async for event in self.llm_engine.inference(
                        workflow, job_id=job_id, use_snapshot=use_snapshot, timeout=timeout
                    ):
                        yield event

        else:
            # Concurrent mode (A100-80GB / H100): parallel pass-through
            if is_image:
                async for event in self.image_engine.inference(
                    workflow, job_id=job_id, use_snapshot=use_snapshot, timeout=timeout
                ):
                    yield event
            else:
                async for event in self.llm_engine.inference(
                    workflow, job_id=job_id, use_snapshot=use_snapshot, timeout=timeout
                ):
                    yield event

    async def cancel_job(self, job_id: str) -> bool:
        """Cancel an in-flight job on whichever engine holds it."""
        cancelled_image = await self.image_engine.cancel_job(job_id)
        cancelled_llm = await self.llm_engine.cancel_job(job_id)
        return cancelled_image or cancelled_llm

    # ----------------------------------------------------------------------
    # Diagnostics & Health
    # ----------------------------------------------------------------------

    async def check_health(self) -> Dict[str, Any]:
        """Aggregate health probing ComfyUI, Agent, and LLM."""
        policy = await self._resolve_policy()
        image_health = await self.image_engine.check_health()
        llm_health = await self.llm_engine.check_health()

        image_ok = image_health.get("status") in ("healthy", "ok")
        llm_ok = llm_health.get("status") in ("healthy", "ok")

        is_healthy = image_ok or llm_ok
        status = "healthy" if (image_ok and llm_ok) else ("degraded" if is_healthy else "unhealthy")

        return {
            "status": status,
            "engine": "remote_hybrid",
            "concurrency_policy": policy,
            "detected_gpu": self._detected_gpu,
            "components": {
                "comfyui": image_health,
                "llm": llm_health,
            },
        }

    async def health(self) -> Dict[str, Any]:
        return await self.check_health()

    # ----------------------------------------------------------------------
    # Storage & Model Operations (Delegated to Sidecar Agent)
    # ----------------------------------------------------------------------

    async def list_models(self, directory: str = "") -> List[Dict[str, Any]]:
        if directory in ("llm", "models/llm"):
            return await self.llm_engine.list_models(directory)
        if not directory:
            img_models = await self.image_engine.list_models("")
            try:
                llm_models = await self.llm_engine.list_models("")
            except Exception:
                llm_models = []
            return img_models + llm_models
        return await self.image_engine.list_models(directory)

    async def get_storage_stats(self) -> Dict[str, Any]:
        return await self.image_engine.get_storage_stats()

    async def get_object_info(self) -> Dict[str, Any]:
        return await self.image_engine.get_object_info()

    async def list_models_with_metadata(self, directory: str = "") -> List[Dict[str, Any]]:
        return await self.image_engine.list_models_with_metadata(directory)

    async def validate_models(self, directories: Optional[List[str]] = None, delete_invalid: bool = False) -> Dict[str, Any]:
        return await self.image_engine.validate_models(directories=directories, delete_invalid=delete_invalid)

    async def validate_all_models(self, delete_invalid: bool = False) -> Dict[str, Any]:
        return await self.image_engine.validate_all_models(delete_invalid=delete_invalid)

    async def download_file(self, download_url: str, storage_path: str, token: Optional[str] = None, timeout: float = 1800.0) -> Dict[str, Any]:
        return await self.image_engine.download_file(download_url, storage_path, token=token, timeout=timeout)

    async def delete_model(self, path: str) -> bool:
        return await self.image_engine.delete_model(path)

    async def delete_file(self, path: str) -> bool:
        return await self.image_engine.delete_file(path)

    async def get_file_stream(self, path: str) -> AsyncIterator[bytes]:
        async for chunk in self.image_engine.get_file_stream(path):
            yield chunk

    async def setup_models(self) -> bool:
        return await self.image_engine.setup_models()

    async def close(self) -> None:
        await self.image_engine.close()
        await self.llm_engine.close()
