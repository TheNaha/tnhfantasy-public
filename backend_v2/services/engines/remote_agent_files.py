"""The remote-agent file protocol, once, for every engine that fronts the sidecar.

`remote_comfy`, `remote_llm` and `remote_tts` all talk to the same binary — the
`remote_agent` sidecar — and all three need the same model-file surface:
`/list-models`, `/download-model`, `/delete-model`, `/validate-models`,
`/get-file`, `/upload-file`, `/delete-file`, `/setup`.

The sidecar registers those routes unconditionally, in every `WORKER_MODE`. What
made the LLM and TTS providers NOT 1-to-1 with `modal_llm` and `modal_tts` was
therefore never the sidecar — it was that `RemoteLLMEngine` and `RemoteTTSEngine`
never called them. `RemoteLLMEngine` overrode only `__init__`, so it inherited
`OpenAICompatLLMEngine`'s inference set and nothing else, and reported
`manages_model_files: False`; `RemoteTTSEngine` reimplemented its own client and
the same handful.

So the protocol lives here, and the three engines mix it in. The image engine
keeps its ComfyUI-specific parts (WebSocket generation, node-to-directory
mapping) — those are genuinely different — and delegates the file half to this.

`manages_model_files` is deliberately `True` on the mixin, which is what makes
the registry's parity claim real: a `remote_llm` provider now owns a models tree
it can list, download into, validate and delete from, exactly like `modal_llm`.
"""

from __future__ import annotations

import os
from typing import Any, AsyncIterator, Dict, List

import httpx

from infrastructure.logging import get_logger

from .base import (
    clamp_timeout,
    encoded_upload_over_cap,
    is_auth_error,
    normalize_validation_result,
)

logger = get_logger("engines.remote_agent_files")


def _envelope_succeeded(resp) -> bool:
    """Did the agent say yes, in its body as well as its status line?

    `remote_agent` answers failures as HTTP 200 carrying
    `{"status": "error", ...}` or `{"success": false, "code": 404}` — that is
    what its `failed()`/`from_upstream()` helpers produce, and the whole point
    of an envelope is to carry a status the transport could not. Reading only
    `status_code == 200` reported a 404 delete as success and a failed download
    as installed, which reconciliation then recorded as "0 invalid cleaned" and
    "downloads_completed" respectively. `DirectComfyEngine.delete_file` and
    `.download_file` already read the envelope; this brings the shared mixin
    into line with them.
    """
    if resp.status_code != 200:
        return False
    try:
        body = resp.json()
    except Exception:
        # Not a JSON body at all — the status line is all there is.
        return True
    if not isinstance(body, dict):
        return True
    if body.get("success") is False:
        return False
    return body.get("status") != "error"

#: The header the sidecar validates. Bearer rather than a bespoke
#: `X-Service-Token` because `remote_agent/provider_core/auth.py` already does
#: the constant-time comparison on `Authorization`; a second scheme would mean a
#: container change for no gain.
SERVICE_TOKEN_HEADER = "Authorization"

#: Per-mode storage-root variables, mirroring the sidecar's `MODE_DATA_ENV`.
#: Used only to *report* which root a provider resolved to, so a misconfigured
#: mount is visible in `get_info` instead of as a confusing 403 later.
MODE_ROOT_ENV = {
    "model": "DATA_DIR",
    "llm": "LLM_DATA_DIR",
    "tts": "TTS_DATA_DIR",
}


class RemoteAgentFileMixin:
    """Model-file operations against the remote_agent sidecar.

    A mixin rather than a base class because the three engines have different
    *inference* shapes — one speaks ComfyUI's WebSocket, one OpenAI chat
    completions, one a plain `/synthesize` — and only the file half is shared.
    Multiple inheritance keeps each engine's inference identity while giving all
    three the same storage surface.

    The consumer declares `agent_url`, `agent_token` and `_agent_http`;
    everything else is here. `_agent_http` deliberately does NOT collide with
    the `_http` an `OpenAICompatLLMEngine` parent caches — see
    `get_agent_client`.
    """

    #: True for all three: the sidecar owns a storage root in every mode.
    manages_model_files: bool = True

    #: Which directories this engine considers a models tree. ``None`` means
    # "whatever the agent answers for any directory" — the generic
    # reconciler's six.
    #:
    #: A narrower tuple is a deliberate claim about the container's storage
    #: shape, exactly as ``ModalLlamaCPPEngine._MODEL_DIRS = ("models",)`` is: that
    #: app stores ONE tree, and asking the agent for ``checkpoints`` or ``loras``
    # against a plain weights directory is a category error. Without this the
    #: remote engine is the only one that answers the wrong question with a
    #: straight face — ``modal_llm`` returns ``[]`` and ``modal_tts`` returns
    #: ``[]``, while the generic reconciler fans out over the image
    #: ``MODEL_DIRECTORIES`` and this mixin would happily walk all six.
    _MODEL_DIRS: tuple[str, ...] | None = None

    def _directory_allowed(self, directory: str) -> bool:
        """Is `directory` a models tree this engine recognises?

        The rule is ``ModalLlamaCPPEngine.list_models``'s, verbatim, so the two
        engines answer the same way for the same input.
        """
        if self._MODEL_DIRS is None:
            return True
        return directory in self._MODEL_DIRS or directory.startswith("models/")

    def _narrow_dirs(self, directories) -> list[str]:
        """Keep only the directories this engine recognises.

        Empty-input and every-filtered-out both fall back to the recognised set,
        which is what ``ModalLlamaCPPEngine._vllm_dirs`` does.
        """
        wanted = list(directories or [])
        if not wanted:
            return list(self._MODEL_DIRS) if self._MODEL_DIRS is not None else []
        kept = [d for d in wanted if self._directory_allowed(d)]
        return kept or (list(self._MODEL_DIRS) if self._MODEL_DIRS is not None else wanted)

    # ------------------------------------------------------------------
    # The HTTP client, once.
    # ------------------------------------------------------------------

    def get_agent_client(self) -> httpx.AsyncClient:
        """The agent-scoped client: base URL plus the bearer token.

        Same shape `DirectComfyEngine` used, so a provider row written for the
        image sidecar points at the LLM or TTS container with no renaming.

        The attribute is `_agent_http`, NOT `_http`, and that distinction is
        load-bearing. `RemoteLLMEngine` mixes this class in ahead of
        `OpenAICompatLLMEngine`, and that base class caches its own client on
        `_http` (`llm_engine.get_http_client`) with a DIFFERENT base URL — the
        `/v1`-suffixed one it needs for `/v1/chat/completions`. Sharing the
        attribute meant whichever parent ran first won permanently: a health
        check before the first completion left inference posting to
        `/chat/completions` (404), and a completion first left the file routes
        asking for `/v1/health` (404). `RemoteTTSEngine` had already worked
        around this by aliasing `get_http_client` at the subclass; this is the
        same fix applied where it belongs. `DirectComfyEngine` uses
        `_agent_http` for the same reason.
        """
        client = getattr(self, "_agent_http", None)
        if client is None or client.is_closed:
            self._agent_http = httpx.AsyncClient(
                base_url=self.agent_url,
                timeout=clamp_timeout(600.0, default=600.0),
                headers={
                    "Content-Type": "application/json",
                    SERVICE_TOKEN_HEADER: f"Bearer {self.agent_token}",
                },
            )
        return self._agent_http

    @property
    def _has_agent(self) -> bool:
        return bool(getattr(self, "agent_url", "").strip())

    def _agent_unavailable(self) -> Dict[str, Any]:
        """The `get_info` shape when no agent URL is configured.

        A remote engine with no `agent_url` cannot do storage work at all, and
        saying so is better than an httpx exception at the first list.
        """
        return {
            "provider_id": self.provider_id,
            "agent_configured": False,
            "error": "No remote agent URL configured",
        }

    # ------------------------------------------------------------------
    # The engine contract.
    # ------------------------------------------------------------------

    async def check_health(self) -> Dict[str, Any]:
        """Probe `/health`, then report the container's topology alongside it.

        The topology is the point. `/topology` (the sidecar's `/info`) answers
        with the resolved storage root and, for an LLM worker, where it proxies
        inference to. `api/routes/providers/crud.py` passes this whole dict
        through as the provider's diagnostics payload, so both settings surface
        next to the health verdict.

        That matters because `modal_llm` serves from the same tree it manages
        and a `remote_llm` provider does not: it manages a root AND proxies to
        `LLM_UPSTREAM_BASE`, which can be a different tree on a different
        machine. An operator looking at a populated models tree would reasonably
        assume it is the one being served. `/topology` makes that checkable.
        """
        import time

        t0 = time.monotonic()
        topology = await self.topology()
        if not self._has_agent:
            return {
                "status": "unhealthy",
                "provider_id": self.provider_id,
                "ready": False,
                "agent_configured": False,
                "error": "No remote agent URL configured",
                "topology": topology,
            }
        try:
            client = self.get_agent_client()
            resp = await client.get("/health", timeout=5.0)
            ok = resp.status_code == 200
        except Exception as exc:
            return {
                "status": "unhealthy",
                "provider_id": self.provider_id,
                "ready": False,
                "agent_configured": True,
                "agent_reachable": False,
                "latency_ms": round((time.monotonic() - t0) * 1000, 2),
                "error": f"Remote agent unreachable: {type(exc).__name__}: {exc}",
                "topology": topology,
            }
        return {
            "status": "healthy" if ok else "unhealthy",
            "provider_id": self.provider_id,
            "ready": ok,
            "agent_configured": True,
            "agent_reachable": ok,
            "latency_ms": round((time.monotonic() - t0) * 1000, 2),
            "topology": topology,
            **({} if ok else {"error": f"Agent /health returned HTTP {resp.status_code}"}),
        }

    async def topology(self) -> Dict[str, Any]:
        """The container's deployment topology, from its own `/info`.

        Reads the agent rather than the environment, because the resolved root
        exists only there. This engine used to report the NAME of the variable
        that decides the root, which is always right and never useful; the agent
        knows the path, so it is the one to ask.

        A failure to reach `/info` returns the variable-name fallback rather than
        raising: health probing is a diagnostics path, and a second failure mode
        alongside an unreachable container helps nobody.
        """
        base = self.storage_root_info()
        if not self._has_agent:
            return {**base, "agent_configured": False}
        try:
            client = self.get_agent_client()
            resp = await client.get("/info", timeout=5.0)
            if resp.status_code != 200:
                return {**base, "agent_configured": True, "info_error": f"HTTP {resp.status_code}"}
            payload = resp.json()
        except Exception as exc:
            return {**base, "agent_configured": True, "info_error": f"{type(exc).__name__}: {exc}"}
        if not isinstance(payload, dict):
            return {**base, "agent_configured": True}
        return {**base, **payload, "agent_configured": True}

    async def list_models(self, directory: str) -> List[Dict[str, Any]]:
        if not self._directory_allowed(directory):
            # Not a models tree this engine recognises. `[]`, not an error and
            # not the agent's own answer: a directory outside the narrowed set is
            # a question about storage this container does not have.
            return []
        client = self.get_agent_client()
        try:
            resp = await client.post(
                "/list-models",
                json={"directory": directory, "recursive": True},
                timeout=clamp_timeout(120.0, default=120.0),
            )
            if resp.status_code != 200:
                return []
            payload = resp.json()
        except Exception:
            return []
        entries = payload.get("models") or payload.get("files") or []
        return [e for e in entries if isinstance(e, dict)]

    async def get_object_info(self) -> Dict[str, Any]:
        return {"provider_id": self.provider_id, "objects": {}}

    async def get_storage_stats(self) -> Dict[str, Any]:
        """Model counts by directory, from the agent's own listing.

        Walks `_MODEL_DIRS` when the engine narrows, and all of
        `MODEL_DIRECTORIES` when it does not — so `remote_llm` reports one
        number for the tree it actually has rather than five empty ones, which
        is what `modal_llm` reports.
        """
        from .base import MODEL_DIRECTORIES

        if self._MODEL_DIRS is not None:
            directory_set = list(self._MODEL_DIRS)
        else:
            directory_set = list(MODEL_DIRECTORIES)

        by_directory: Dict[str, int] = {}
        total = 0
        for directory in directory_set:
            try:
                entries = await self.list_models(directory)
            except Exception as exc:
                logger.warning(
                    "remote_agent_list_failed",
                    provider_id=self.provider_id,
                    directory=directory,
                    error=str(exc),
                )
                entries = []
            count = len([e for e in entries if e.get("name")])
            by_directory[directory] = count
            total += count
        return {
            "provider_id": self.provider_id,
            "total": total,
            "by_directory": by_directory,
        }

    async def setup_models(self) -> bool:
        """Initialise the storage root, delegating to the agent's `/setup`.

        Real rather than the base's `False`, which is what puts `remote_llm` and
        `remote_tts` in the registry's `_SUPPORTS_SETUP` set and makes the
        provider page's setup action work for them.
        """
        if not self._has_agent:
            return False
        client = self.get_agent_client()
        try:
            resp = await client.post("/setup", json={}, timeout=clamp_timeout(300.0, default=300.0))
        except Exception as exc:
            logger.warning(
                "remote_agent_setup_failed", provider_id=self.provider_id, error=str(exc)
            )
            return False
        return resp.status_code == 200

    async def upload_file(self, filename: str, content_base64: str, directory: str = "") -> bool:
        if not self._has_agent:
            return False
        if encoded_upload_over_cap(len(content_base64)):
            return False
        client = self.get_agent_client()
        try:
            resp = await client.post(
                "/upload-file",
                # `content_base64`, not `content`. The agent's
                # `UploadFileRequest` requires `content_base64`, and pydantic
                # rejects the whole body when it is missing — a 422 that this
                # function was collapsing to `False`, indistinguishable from
                # "this provider cannot upload". Every agent upload failed.
                json={
                    "content_base64": content_base64,
                    "directory": directory,
                    "filename": filename,
                },
                timeout=clamp_timeout(1800.0, default=1800.0),
            )
        except Exception as exc:
            logger.warning(
                "remote_agent_upload_failed", provider_id=self.provider_id, error=str(exc)
            )
            return False
        return _envelope_succeeded(resp)

    async def delete_file(self, path: str) -> bool:
        if not self._has_agent:
            return False
        client = self.get_agent_client()
        try:
            resp = await client.post(
                "/delete-file", json={"path": path}, timeout=clamp_timeout(120.0, default=120.0)
            )
        except Exception as exc:
            logger.warning(
                "remote_agent_delete_failed", provider_id=self.provider_id, error=str(exc)
            )
            return False
        return _envelope_succeeded(resp)

    async def download_file(
        self,
        download_url: str,
        storage_path: str,
        token: str | None = None,
        timeout: float = 3600.0,
    ) -> Dict[str, Any]:
        """Download one model into the agent's storage, awaiting completion.

        The agent owns the byte transfer, so a 20 GB checkpoint streams on the GPU
        box rather than through the backend process — the same reason the Modal
        and Beam engines do their downloading on the worker.
        """
        if not self._has_agent:
            raise NotImplementedError("No remote agent URL configured")
        client = self.get_agent_client()
        try:
            resp = await client.post(
                "/download-model",
                json={
                    "url": download_url,
                    "filename": os.path.basename(storage_path),
                    "path": storage_path,
                    "directory": os.path.dirname(storage_path),
                    "token": token,
                },
                timeout=clamp_timeout(timeout, default=3600.0),
            )
        except Exception as exc:
            if is_auth_error(exc):
                raise
            return {"status": "failed", "error": str(exc)}
        if resp.status_code != 200:
            return {"status": "failed", "error": f"HTTP {resp.status_code}: {resp.text[:200]}"}
        try:
            body = resp.json()
        except Exception:
            return {"status": "completed"}
        # The agent reports a failed transfer INSIDE a 200 — its
        # `from_upstream` envelope carries `{"status": "error", "message": ...}`
        # for a 404/403/timeout on the upstream URL. Handing that back
        # unchanged is not enough on its own: `in_process_reconciliation`
        # ignores this return value entirely and unconditionally increments
        # `downloads_completed`, sets the model to `ready` and raises
        # `MODEL_SYNC_COMPLETED`. So a gated HuggingFace URL marked a model
        # installed and dropped it out of the pending queue. Normalising the
        # envelope to `failed` here is what lets the caller see it.
        if isinstance(body, dict) and body.get("status") == "error":
            return {
                "status": "failed",
                "error": str(body.get("message") or body.get("error") or "upstream refused"),
            }
        return body

    async def validate_models(self, directories: List[str]) -> Dict[str, Any]:
        """Ask the agent to hash-check what it holds.

        The normalisation is the shared one, so a `remote_llm` provider's
        validation payload has the same shape a `modal_llm` one does.
        """
        if not self._has_agent:
            raise NotImplementedError("No remote agent URL configured")
        client = self.get_agent_client()
        try:
            resp = await client.post(
                "/validate-models",
                json={
                    # `directory`, not `directories`. The agent's
                    # `ValidateModelsRequest` takes a singular
                    # `directory: str | list[str]`, so sending the plural was a
                    # 422 for the whole request. This is the key the deployed
                    # agent accepts; the plural one it never has.
                    "directory": self._narrow_dirs(directories),
                    "delete_invalid": False,
                },
                timeout=clamp_timeout(3600.0, default=3600.0),
            )
        except Exception as exc:
            if is_auth_error(exc):
                raise
            raise
        if resp.status_code != 200:
            # NOT a clean sweep. Falling through to
            # `normalize_validation_result({}, ...)` fabricated
            # `total_invalid: 0`, which reconciliation records as "0 invalid
            # cleaned" — so a corrupt-checkpoint sweep silently reported success
            # forever. An upstream that cannot be asked has told us nothing,
            # and the honest answer is an indeterminate result, not zero.
            return normalize_validation_result(
                {
                    "status": "error",
                    "total_indeterminate": len(self._narrow_dirs(directories)),
                    "error": f"HTTP {resp.status_code}: {resp.text[:200]}",
                },
                directories,
            )
        try:
            payload = resp.json()
        except Exception:
            payload = {}
        return normalize_validation_result(payload, directories)

    async def get_file_stream(self, path: str) -> AsyncIterator[bytes]:
        """Stream a file out of the agent's storage root.

        `%2F` rather than a raw slash: the sidecar's route is `/get-file/{path:path}`,
        and a path with a separator in it is collapsed by the router before it
        reaches the handler, so the encoded form is what actually round-trips.
        """
        if not self._has_agent:
            raise NotImplementedError("No remote agent URL configured")
        client = self.get_agent_client()
        from urllib.parse import quote

        encoded = quote(path, safe="")
        try:
            async with client.stream(
                "GET",
                f"/get-file/{encoded}",
                timeout=clamp_timeout(600.0, default=600.0),
            ) as resp:
                if resp.status_code != 200:
                    raise RuntimeError(f"Agent returned HTTP {resp.status_code}")
                async for chunk in resp.aiter_bytes():
                    if chunk:
                        yield chunk
        except Exception as exc:
            if is_auth_error(exc):
                raise
            raise

    # ------------------------------------------------------------------
    # Reporting, including the resolved storage root.
    # ------------------------------------------------------------------

    def storage_root_info(self) -> Dict[str, Any]:
        """Which variable names the storage root, without pretending to read it.

        The sidecar resolves its root from `LLM_DATA_DIR` / `TTS_DATA_DIR` /
        `DATA_DIR` depending on `WORKER_MODE` — a container-side decision, so the
        backend process has no way to observe the value and MUST NOT try.

        This used to call `os.getenv(env)`. That reads the *backend's* own
        environment, which has none of those variables set, so it reported
        `storage_root_configured: False` for a correctly configured container and
        `True` only when the operator happened to have `DATA_DIR` exported in the
        backend's shell — a coincidence, not a signal. Reporting the name of the
        variable that wins is the honest half and is always correct.
        """
        mode = getattr(self, "worker_mode", None) or "model"
        return {
            "worker_mode": mode,
            "storage_root_env": MODE_ROOT_ENV.get(mode, "DATA_DIR"),
        }

    async def get_info(self) -> Dict[str, Any]:
        base: Dict[str, Any] = {
            "provider_id": self.provider_id,
            "agent_configured": self._has_agent,
        }
        if self._has_agent:
            base["agent_url"] = self.agent_url.rstrip("/")
            base.update(self.storage_root_info())
        return base

