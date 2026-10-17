"""Read the model registry, and know how to launch llama.cpp from it.

The registry is `backend_v2/modal_llm/models.json`, and it is deliberately ONE
file read by both sides: the Modal app (`deployables/modal/llm/app.py`) launches
llama-server from it, and the backend (`services/llm_router.py`) resolves
job-kind -> role -> model from the same text. That is what keeps the two from
disagreeing about which model serves `rp` — a second copy of the list in either
place is the drift the registry exists to prevent.

So this worker reads that file too, and it is what makes a `remote_llm` provider
genuinely the same thing as `modal_llm` rather than a lookalike:

  * Modal: one container, one llama-server per role, on adjacent loopback ports,
    reachable only through the Modal SDK.
  * Remote: one container, one llama-server per role, on adjacent loopback
    ports, reachable through the sidecar's authenticated `/v1/chat/completions`.

No HTTP surface on Modal's side at all — plain `@modal.method()` rather than
`modal.web_server()`, because a `web_server` leaves unauthenticated public URLs
where llama-server's API key is the only thing between the internet and the
model. The sidecar's token check is the same protection for the remote transport,
which is why the proxy exists rather than publishing the ports.

`LLM_UPSTREAM_BASE` still works, and is now the OPT-OUT: set it to front a
llama.cpp or vLLM you already run, leave it unset to let this worker serve the
weights it manages. The default is what makes the managed tree the served tree,
which is the whole parity claim.
"""

from __future__ import annotations

import json
import os
import subprocess
import time
import urllib.request
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any, Dict, List, Optional

#: Where the registry lives inside a built image. The Dockerfile adds the
#: backend's `modal_llm/` directory here, so there is exactly one file.
BUNDLED_REGISTRY = Path("/app/modal_llm/models.json")

#: The paths tried in order. Bundled first, then beside this file, then beside
#: the repo root, then the operator's explicit override.
#
#: Beside-this-file covers a bare `python3 server.py` on a GPU box; the repo-root
#: candidate covers running from a checkout without a build step; the env var
#: wins everything so an operator can point at their own edit.
_CANDIDATES = (
    Path(os.getenv("LLM_REGISTRY_PATH", "")) if os.getenv("LLM_REGISTRY_PATH") else None,
    BUNDLED_REGISTRY,
    Path(__file__).resolve().parent / "models.json",
    Path(__file__).resolve().parent.parent / "backend_v2" / "modal_llm" / "models.json",
)

PORT = 8080

#: Base port for the first llama-server. Adjacent, fixed and never published, so
#: there is nothing to configure — the same scheme the Modal app uses.
SERVER_PORT_BASE = 8081

#: How long a model gets to load. The Modal app's measured figure is ~18s for a
#: 23.5 GB GGUF off a volume; 600 leaves room for a slower first pull.
MODEL_LOAD_TIMEOUT_SECONDS = 600


@dataclass(frozen=True)
class Model:
    """One registry entry, resolved."""

    id: str
    role: str
    repo: str
    gguf: str
    mmproj: Optional[str] = None
    mmproj_repo: Optional[str] = None
    dir: Optional[str] = None
    ctx: int = 32768
    parallel: int = 1
    kv: Optional[str] = None
    gpu: str = "L40S"
    sampler: Dict[str, Any] = field(default_factory=dict)
    extra_args: List[str] = field(default_factory=list)
    enabled: bool = True
    #: Declared and carried, though a self-hosted box neither scales to zero nor
    #: imposes a startup budget: the fields exist so this parser accepts the
    #: SAME models.json the Modal app reads. Dropping them here would mean
    #: editing the registry to add them back for the remote transport, which is
    #: the drift the shared file exists to prevent.
    idle: int = 300
    startup: int = 600
    note: Optional[str] = None

    @property
    def volume_dir(self) -> str:
        """The folder holding this model's weights.

        A `util` twin sharing an `rp` entry's weights declares no `dir` and falls
        back to the id it shares with — that is how one download serves two
        servers, and why the launcher launches by DISTINCT model rather than by
        role.
        """
        return self.dir or self.id

    @property
    def has_vision(self) -> bool:
        return bool(self.mmproj)

    def llama_args(self, models_dir: str, ram_path: Optional[str] = None) -> List[str]:
        """The llama-server flags this model needs, in order.

        Order is not cosmetic: `-m` must precede the model path, and the KV-cache
        flags must not appear twice when a model declares `extra_args`. The same
        rule `modal_llm/registry.py:llama_args` documents, mirrored here because
        the sidecar cannot import from backend_v2.
        """
        model_path = ram_path or f"{models_dir}/{self.volume_dir}/{self.gguf}"
        ngl = 99
        try:
            import torch
            if torch.cuda.is_available() and os.path.exists(model_path):
                total_vram_gb = torch.cuda.get_device_properties(0).total_memory / (1024**3)
                weight_gb = os.path.getsize(model_path) / (1024**3)
                # Reserve 5.0 GB for KV cache, CUDA driver/runtime, and compute scratch buffers
                safe_budget_gb = max(0.0, total_vram_gb - 5.0)
                if weight_gb > safe_budget_gb > 0:
                    ngl = max(20, min(56, int(64 * (safe_budget_gb / weight_gb))))
        except Exception:
            ngl = 50

        args = [
            "-m", model_path,
            "--alias", self.id,
            "-ngl", str(ngl),
            "-c", str(min(self.ctx * self.parallel, 8192)),
            "--parallel", str(self.parallel),
            "--jinja",
        ]
        if self.mmproj:
            args += ["--mmproj", f"{models_dir}/{self.volume_dir}/{self.mmproj}"]
        if self.kv:
            args += ["--cache-type-k", self.kv, "--cache-type-v", self.kv]
        args += list(self.extra_args)
        return args


@dataclass(frozen=True)
class Registry:
    """The parsed registry: models plus per-role fallback order."""

    models: Dict[str, Model]
    fallback: Dict[str, List[str]]

    def role_order(self, role: str) -> List[str]:
        return [m for m in self.fallback.get(role, []) if m in self.enabled_ids()]

    def enabled_ids(self) -> List[str]:
        return [mid for mid, m in self.models.items() if m.enabled]

    def enabled_for(self, role: str) -> List[Model]:
        return [self.models[mid] for mid in self.role_order(role) if mid in self.models]

    def get(self, model_id: str) -> Model:
        try:
            return self.models[model_id]
        except KeyError:
            raise KeyError(
                f"model {model_id!r} is not in the registry; known ids: "
                f"{sorted(self.models)}"
            ) from None

    def primary(self, role: str) -> Model:
        ordered = self.enabled_for(role)
        if not ordered:
            raise LookupError(f"role {role!r} has no enabled model in the registry")
        return ordered[0]

    @property
    def roles(self) -> List[str]:
        return sorted(self.fallback)

    def distinct_primaries(self) -> List[Model]:
        """One Model per distinct weight set across every role's primary.

        A role per model, not a role per server: when `rp` and `util` resolve to
        the same weights — which is the whole point of the shared-model setting —
        one server serves both and the second is never started. Launching the
        same GGUF twice would double the VRAM for no gain. This is the rule
        `ChatLLM.start` documents, applied here.
        """
        distinct: List[Model] = []
        for role in self.roles:
            model = self.primary(role)
            if model.id not in {m.id for m in distinct}:
                distinct.append(model)
        return distinct


def _registry_candidates() -> List[Path]:
    return [c for c in _CANDIDATES if c is not None]


def resolve_registry_path() -> Optional[Path]:
    """The models.json that exists, preferring the bundled one."""
    for candidate in _registry_candidates():
        try:
            if candidate.is_file():
                return candidate
        except OSError:
            continue
    return None


def load(path: Optional[Path] = None) -> Optional[Registry]:
    """Parse the registry, or return None when there is nothing to serve.

    None rather than an error, because `WORKER_MODE=llm` with no registry is a
    legitimate configuration — the operator is fronting an existing `LLM_UPSTREAM`
    and wants no local model. An empty registry is a different state and is
    reported, not swallowed.
    """
    registry_path = Path(path) if path else resolve_registry_path()
    if registry_path is None or not registry_path.is_file():
        return None

    raw = json.loads(registry_path.read_text(encoding="utf-8"))
    models_raw: Dict[str, Any] = raw.get("models") or {}
    if not models_raw:
        raise ValueError(f"{registry_path} declares no models")

    defaults: Dict[str, Any] = {
        "mmproj": None, "mmproj_repo": None, "dir": None, "ctx": 32768,
        "parallel": 1, "kv": None, "sampler": {}, "extra_args": [], "enabled": True,
    }
    meta_keys = {"role", "enabled", "_note", "_comment"}

    models: Dict[str, Model] = {}
    for model_id, spec in models_raw.items():
        merged = {**defaults, **{k: v for k, v in spec.items() if k not in meta_keys}}
        role = spec.get("role")
        if not role:
            raise ValueError(f"model {model_id!r} declares no role")
        merged.pop("role", None)
        models[model_id] = Model(id=model_id, role=role, **merged)

    fallback: Dict[str, List[str]] = {}
    for role, spec in (raw.get("roles") or {}).items():
        order = [m for m in list(spec.get("fallback") or []) if m in models]
        if order:
            fallback[role] = order
    return Registry(models=models, fallback=fallback)


class LaunchedServer:
    """A running llama-server plus the handle needed to notice it died.

    Keeping the `Popen` matters: without it a container whose model process exits
    after becoming healthy answers every subsequent call with a connection error
    until it scales down, which reads as "the model is broken" rather than "the
    process is gone". Same reason as `deployables/modal/llm/app.py:_LaunchedServer`.
    """

    def __init__(self, process, port: int, model_id: str):
        self.process = process
        self.port = port
        self.model_id = model_id

    @property
    def alive(self) -> bool:
        return self.process.poll() is None


class LlamaStack:
    """One llama-server per distinct primary, and the routing between them.

    The model id the backend sends in the payload is what picks the port: the
    registry's `--alias` means llama-server answers `/v1/chat/completions` for
    that name, so routing by id is exact and a request for a model this worker
    does not hold is a clear non-retryable error rather than a silent fallback to
    whatever happens to be loaded.
    """

    def __init__(self, models_dir: str):
        self.models_dir = models_dir
        self.servers: Dict[str, LaunchedServer] = {}
        self.unavailable: Dict[str, str] = {}

    # ------------------------------------------------------------------
    def launch(self, registry: Registry) -> Dict[str, int]:
        """Start one llama-server per distinct primary, in registry order.

        Blocking is required: a `Popen` that returned would let the caller move
        on while the model is still loading, and the first request would arrive
        at a server that is not up yet. The wait is where the load is paid — on
        the worker's own clock, before the first call rather than inside it.
        """
        started: Dict[str, int] = {}
        for index, model in enumerate(registry.distinct_primaries()):
            port = SERVER_PORT_BASE + index
            if not self._weights_present(model):
                self.unavailable[model.id] = (
                    f"{model.id!r} has no weights in {self.models_dir}/{model.volume_dir}; "
                    "use /download-model to fetch them"
                )
                continue
            self._spawn(model, port)
            started[model.id] = port
        return started

    def _spawn(self, model: Model, port: int) -> None:
        # Loopback only: nothing outside the container can reach these ports, and
        # the proxy is what the token check protects.
        #
        # `/app/llama-server` first, because that is where the llama.cpp image
        # puts it — it is NOT on PATH there, so the plain name exits 127 and the
        # launcher reports "exited 127" with nothing pointing at the cause. The
        # PATH lookup covers a bare `python3 server.py` on a rig that has its own
        # llama-server installed.
        binary = self._llama_binary()
        ram_path = None
        try:
            from ram_manager import get_ram_manager
            mgr = get_ram_manager()
            if mgr.is_cached(model.id):
                ram_path = mgr.entries[model.id].ram_path
            else:
                disk_path = f"{self.models_dir}/{model.volume_dir}/{model.gguf}"
                if os.path.isfile(disk_path):
                    ram_path = str(mgr.ensure_in_ram(disk_path, model_id=model.id, role=model.role, is_anchor=True))
        except Exception as exc:
            print(f"[{model.id}] RAM pre-warming notice: {exc}", flush=True)

        cmd = [binary] + model.llama_args(self.models_dir, ram_path=ram_path) + [
            "--host", "127.0.0.1",
            "--port", str(port),
        ]
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

        print(f"[{model.id}] launching on :{port}", flush=True)
        process = subprocess.Popen(cmd, env=env)
        launched_at = time.time()
        deadline = launched_at + MODEL_LOAD_TIMEOUT_SECONDS
        while time.time() < deadline:
            if process.poll() is not None:
                raise RuntimeError(
                    f"llama-server exited {process.returncode} for {model.id} "
                    f"after {time.time() - launched_at:.1f}s"
                )
            try:
                with urllib.request.urlopen(
                    f"http://127.0.0.1:{port}/health", timeout=2
                ) as response:
                    if response.status == 200:
                        self.servers[model.id] = LaunchedServer(process, port, model.id)
                        print(
                            f"[{model.id}] healthy on :{port} after "
                            f"{time.time() - launched_at:.1f}s",
                            flush=True,
                        )
                        return
            except Exception:
                pass
            time.sleep(1)
        process.terminate()
        raise RuntimeError(
            f"llama-server for {model.id} did not become healthy within "
            f"{MODEL_LOAD_TIMEOUT_SECONDS}s"
        )

    # ------------------------------------------------------------------
    #: Where the llama.cpp image puts llama-server. The Modal app uses the same
    #: path (`/app/llama-server`), so the two transports launch the same binary.
    _LLAMA_SERVER_PATHS = ("/app/llama-server", "llama-server")

    def _llama_binary(self) -> str:
        import shutil

        for path in self._LLAMA_SERVER_PATHS:
            if os.path.isabs(path):
                if os.access(path, os.X_OK):
                    return path
            elif shutil.which(path):
                return path
        return "llama-server"

    def _weights_present(self, model: Model) -> bool:
        """Is the model's GGUF (and projector) on disk?"""
        from pathlib import Path as _Path

        for pattern in filter(None, [model.gguf, model.mmproj]):
            try:
                hits = sorted(_Path(self.models_dir, model.volume_dir).glob(pattern))
            except OSError:
                return False
            if len(hits) != 1:
                return False
        return True

    def resolve(self, model_id: str) -> int:
        """The port serving `model_id`, or a clear non-retryable error.

        Not retryable on purpose: an unknown or unserved model is a configuration
        state, so a caller should fail rather than back off.
        """
        server = self.servers.get(model_id)
        if server is None or not server.alive:
            reason = self.unavailable.get(model_id)
            if reason:
                raise RuntimeError(reason)
            raise RuntimeError(
                f"{model_id!r} is not served by this worker; it serves "
                f"{sorted(self.servers)}"
            )
        return server.port

    def health(self, registry: Registry) -> Dict[str, Any]:
        """Per-role reachability, including the roles not loaded.

        A role with no weights answers `not_downloaded` with its reason rather
        than raising, so a caller polling health sees an actionable state instead
        of a crash-loop it has to infer from retries.
        """
        out: Dict[str, Any] = {"servers": {}, "roles": {}}
        for model_id, server in self.servers.items():
            out["servers"][model_id] = {
                "port": server.port,
                "alive": server.alive,
            }
        for role in registry.roles:
            model = registry.primary(role)
            if model.id in self.unavailable:
                out["roles"][role] = {
                    "status": "not_downloaded",
                    "model_id": model.id,
                    "reason": self.unavailable[model.id],
                }
                continue
            server = self.servers.get(model.id)
            if server is None:
                out["roles"][role] = {"status": "unknown", "model_id": model.id}
                continue
            try:
                with urllib.request.urlopen(
                    f"http://127.0.0.1:{server.port}/health", timeout=5
                ) as response:
                    out["roles"][role] = {
                        "status": "ok" if response.status == 200 else "unhealthy",
                        "model_id": model.id,
                        "port": server.port,
                    }
            except Exception as exc:
                out["roles"][role] = {
                    "status": "unhealthy",
                    "model_id": model.id,
                    "reason": str(exc),
                }
        return out
