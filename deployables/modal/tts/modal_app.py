"""
TTS worker — a ComfyUI container that speaks.

A SEPARATE Modal app from the image worker, and the separation is the point
rather than tidiness.

Measured on Modal L4 against `comfy-modal-stack`, cold, from the container entry
hook to ComfyUI answering /ready:

    container_enter        t=0.00
    comfy-cli spawn        t=0.00    (returns immediately; it forks)
    ComfyUI ready          t=44.15

Modal's own reported cold time for the same request was 57.66s, so roughly 13.5s
is provisioning and image pull and ~44s is in-container — of which ~42s is
ComfyUI's own boot. That 42s is what this app is designed to shrink, because
almost all of it is image-specific:

  * `ultralytics`, which this image does not carry. It is a heavy import
    (torch, opencv, scipy) and the image worker needs it for ADetailer.
  * the `models/` tree. ComfyUI enumerates model files at boot, and the image
    worker's `models` is symlinked to `/mnt/data/models` — a Modal VOLUME, i.e.
    network storage, with 531 files in it as of this writing. Enumerating that
    costs real time on every cold start. This app's volume holds one TTS model
    directory.

The original claim that "custom node discovery dominates" was wrong and is
recorded in `docs/audit-2026-09-29.md`; the mechanism is the heavy import plus
the volume scan, not the node count. The image has 8 node packs, not 60+.

What is deliberately NOT here: ultralytics, the impact pack, animatediff,
controlnet_aux, and the image model tree. Keeping them out is the whole point;
adding a TTS node pack to the image worker would have made every image job's
cold start slower to serve a feature most sessions never use.

Two apps can share one volume, so downloaded TTS models are visible to the
FileStorage functions here and to the image worker alike.
"""

import asyncio
import json
import logging
import os
import subprocess
import sys
import threading
import time
from pathlib import Path
from typing import Any, Dict, List, Optional

import modal

# `provider_core` used to be a sibling package: `provider_containers/` held this
# app in `tts_worker/engines/modal/` and the library in `provider_core/`, so
# `import provider_core` worked wherever the app happened to sit inside that
# tree, and nothing in the file said so. The container layout is gone (see
# deployables/README.md), `provider_core` now lives under `remote_agent/`, and
# that positional assumption is what made the source un-deployable: it could not
# move without breaking this import, and the import could not be satisfied
# without the source. Resolve the repo root explicitly instead of counting
# parents, and fall through to nothing when the marker is missing — inside the
# container this module is uploaded to /root/modal_app.py, where there is no
# repo at all, and sys.path[0] is already the directory holding
# /root/provider_core (see tts_image.add_local_dir below).
_HERE = Path(__file__).resolve().parent
# This file is 3 levels below the repo root: tts -> modal -> deployables
# -> repo root.
_REPO_ROOT = next(
    (p for p in _HERE.parents if (p / "remote_agent" / "provider_core").is_dir()),
    None,
)
if _REPO_ROOT is not None:
    # `remote_agent/` makes the shared provider_core importable;
    # `deployables/` makes provider_worker_core (the modules the 2026-10-08
    # slimming deleted, which this app still imports) importable.
    for _parent in ("remote_agent", "deployables"):
        _sys_path_entry = _REPO_ROOT / _parent
        if _sys_path_entry.is_dir() and str(_sys_path_entry) not in sys.path:
            sys.path.insert(0, str(_sys_path_entry))

# comfy_lifecycle was one of the worker-only provider_core modules deleted in
# acc86aa3 and is restored at deployables/provider_worker_core/. It must also be
# inside the image, or this import fails on every TTSWorker method.
from provider_worker_core.comfy_lifecycle import free_comfy_vram, restart_comfy_process

logger = logging.getLogger(__name__)
logging.basicConfig(level=logging.INFO)

# ---------------------------------------------------------------- configuration

# Distinct app name. The image worker is `comfy-modal-stack`; sharing the name
# would make `modal.Cls.from_name` ambiguous and merge the two deployment
# histories. Deploying this file creates/updates this app independently.
TTS_APP_NAME = os.getenv("MODAL_TTS_APP_NAME", "comfy-modal-tts")

VOLUME_NAME = os.getenv("MODAL_VOLUME_NAME", "comfy-storage")

GPU_TYPE = os.getenv("MODAL_TTS_GPU_TYPE", os.getenv("MODAL_GPU_TYPE", "L4"))
CPU = int(os.getenv("MODAL_TTS_CPU", os.getenv("MODAL_GPU_CPU", "2")))

# A TTS container's whole reason to exist is to be warm. The image worker's 40s
# is right for jobs measured in minutes; this one runs a few seconds of speech at
# a time and a batch of voices, so paying a 44s cold start per message would
# dominate. It still scales to zero, so an idle TTS app costs nothing.
SCALEDOWN = int(os.getenv("MODAL_TTS_SCALEDOWN", "300"))

# One by default, matching the image worker, because the cost is per
# container-second. Raise it for concurrent narration.
MAX_CONTAINERS = int(os.getenv("MODAL_TTS_MAX_CONTAINERS", "1"))

# Runs before the ComfyUI process is replaced. 10 is the image worker's cadence
# (`COMFYUI_MAX_RUNS_BEFORE_RESTART`); speech jobs are seconds long rather than
# minutes, so the same count buys far more wall-clock per unit of accumulated
# state here.
MAX_RUNS_BEFORE_RESTART = int(os.getenv("MODAL_TTS_MAX_RUNS_BEFORE_RESTART", "10"))

# A batched voice-design run and a long narration batch both legitimately take
# minutes on a cold container, so this is generous relative to the image
# worker's 600s.
TIMEOUT = int(os.getenv("MODAL_TTS_TIMEOUT", "1800"))

HEALTHCHECK_TIMEOUT = float(os.getenv("MODAL_TTS_HEALTHCHECK_TIMEOUT", "180"))
PORT = int(os.getenv("MODAL_TTS_PORT", "8199"))

# Where ComfyUI looks for the TTS model. One small directory, versus 531 files
# on the image worker's volume — the scan is a measurable part of its 42s boot.
TTS_MODEL_DIR = os.getenv("MODAL_TTS_MODEL_DIR", "/mnt/data/models/TTS")

# Qwen3-TTS is chosen over XTTS for one reason that matters here: its "Voice
# Design" node creates a voice from a natural-language description, which is what
# makes a cast's voices obtainable with no reference audio and no expertise. It
# also has 9 preset timbres, a reusable voice library, and style control. See
# docs/audit-2026-09-29.md.
QWEN_TTS_NODE_PACK = "https://github.com/1038lab/ComfyUI-QwenTTS.git"


# ------------------------------------------------------------------ utilities


def _wait_for_ready(port: int, timeout_seconds: float, label: str) -> None:
    """Poll ComfyUI's /system_stats until it answers, or give up.

    Same shape as the image worker's `_wait_for_comfy_ready`, kept separate
    rather than imported: this app must not depend on the image worker's module
    graph, because the two images differ and a shared import would drag the
    image stack's imports into the TTS container — which is the cost this
    separation exists to avoid.
    """
    import urllib.error
    import urllib.request

    deadline = time.time() + max(timeout_seconds, 1.0)
    last_error: Optional[str] = None
    while time.time() < deadline:
        try:
            with urllib.request.urlopen(
                f"http://127.0.0.1:{port}/system_stats", timeout=3
            ) as resp:
                if resp.status == 200:
                    logger.info("[tts] %s ready", label)
                    return
        except Exception as exc:  # noqa: BLE001 - any failure means "not yet"
            last_error = str(exc)
        time.sleep(1.0)
    raise RuntimeError(
        f"[{label}] ComfyUI did not become ready within {timeout_seconds}s. "
        f"Last error: {last_error}"
    )


def _start_comfy(port: int) -> None:
    """Launch ComfyUI detached and wait for it."""
    logger.info("[tts] starting ComfyUI on port %s", port)
    subprocess.Popen(
        ["comfy", "launch", "--", "--port", str(port), "--cpu" if GPU_TYPE == "cpu" else "--listen",
         "0.0.0.0", "--port", str(port)],
        stdout=subprocess.DEVNULL,
        stderr=subprocess.DEVNULL,
        start_new_session=True,
    )
    _wait_for_ready(port, HEALTHCHECK_TIMEOUT, "ComfyUIStable")


def safe_vol_reload():
    try:
        vol.reload()
    except Exception as e:
        logger.warning("vol.reload failed: %s", e)


async def safe_vol_reload_aio():
    try:
        await vol.reload.aio()
    except Exception as e:
        logger.warning("vol.reload.aio failed: %s", e)


def _resolve_package_local_path(*relative: str) -> Path:
    """Resolve a package directory for Modal image packaging, by repo-relative path.

    This replaces a walk up `Path(__file__).parent` looking for a sibling named
    `provider_core`. The walk could only succeed while this file sat inside the
    deleted `provider_containers/` tree, and it is the reason the deploy context
    had to be the repo root. A path relative to the repo root says where the
    source is instead of guessing how deep it happens to be nested.

    The sibling fallback is for the container, where `_REPO_ROOT` is None and
    the image definition below has already been built from a real path: this
    module is uploaded to /root/modal_app.py and the packages are copied beside
    it, so `sys.path[0]` already resolves them. What comes back here is only
    what keeps the import from raising.
    """
    package_name = relative[-1]
    candidates = []
    if _REPO_ROOT is not None:
        candidates.append(_REPO_ROOT.joinpath(*relative))
    candidates += [_HERE / package_name, Path("/") / package_name]
    for candidate in candidates:
        if candidate.is_dir():
            return candidate
    raise RuntimeError(
        f"package directory not found for Modal image build: {package_name}"
    )


PROVIDER_CORE_LOCAL_PATH = _resolve_package_local_path("remote_agent", "provider_core")
PROVIDER_WORKER_CORE_LOCAL_PATH = _resolve_package_local_path("deployables", "provider_worker_core")


# ----------------------------------------------------------------------- image

# Modelled on the image worker's image so the two are recognisable, minus
# everything the image worker needs and this does not.
tts_image = (
    modal.Image.debian_slim(python_version="3.12")
    .apt_install("git", "libgl1-mesa-glx", "libglib2.0-0", "procps", "ffmpeg")
    .uv_pip_install(
        "comfy-cli", "fastapi", "websockets", "uvicorn", "requests",
        "safetensors", "py-spy", "httpx", "aiofiles", "psutil",
    )
    .run_commands(
        "comfy --skip-prompt install --fast-deps --nvidia --cuda-version 12.8",
        gpu=GPU_TYPE,
    )
    .uv_pip_install("torch", "torchaudio", "soundfile", "librosa")
    .run_commands(
        # The Qwen3-TTS node pack. It installs its own requirements on first use
        # via comfy-cli, which is why the install is a node install rather than a
        # pinned pip set: the pack moves, and a pinned version would silently
        # age out of step with the model it loads.
        f"comfy node install --fast-deps {QWEN_TTS_NODE_PACK.split('.git')[0]}",
        # Models live on the volume; a stale local copy would be scanned at boot
        # for nothing.
        "rm -rf /root/comfy/ComfyUI/models /root/comfy/ComfyUI/output /root/comfy/ComfyUI/input",
        "ln -s /mnt/data/models /root/comfy/ComfyUI/models",
        "ln -s /mnt/data/output /root/comfy/ComfyUI/output",
        "ln -s /mnt/data/input /root/comfy/ComfyUI/input",
        "mkdir -p /mnt/data/models/TTS",
        "comfy --help",
        gpu=GPU_TYPE,
    )
    # `get_safe_path` is the path-confinement gate every storage route in this
    # repo uses, and it lives in provider_core. The Modal image is a separate
    # artifact built here, so the package has to be packaged into it explicitly
    # or the import above fails inside the remote container. Both packages land
    # in /root, the directory Modal uploads this module to, so `sys.path[0]`
    # resolves them without a PYTHONPATH entry.
    .add_local_dir(
        local_path=PROVIDER_CORE_LOCAL_PATH,
        remote_path="/root/provider_core",
        copy=True,
    )
    .add_local_dir(
        local_path=PROVIDER_WORKER_CORE_LOCAL_PATH,
        remote_path="/root/provider_worker_core",
        copy=True,
    )
)

tts_app = modal.App(TTS_APP_NAME, image=tts_image)
vol = modal.Volume.from_name(VOLUME_NAME, create_if_missing=True)


# ---------------------------------------------------------------------- worker


@tts_app.cls(
    image=tts_image,
    volumes={"/mnt/data": vol},
    cpu=CPU,
    gpu=GPU_TYPE,
    timeout=TIMEOUT,
    scaledown_window=SCALEDOWN,
    max_containers=MAX_CONTAINERS,
    min_containers=0,
)
class TTSWorker:
    """ComfyUI configured for speech.

    Deliberately mirrors the image worker's container contract — the same
    `/free` endpoint, the same restart-after-N-runs, the same crash log — so the
    backend can treat it as a ComfyUI provider with no special-casing beyond the
    task type. The divergences are documented where they occur.
    """

    port: int = PORT
    _server: Optional[Any] = None
    _server_thread: Optional[threading.Thread] = None
    _is_running: bool = False
    _completed_runs: int = 0

    @modal.enter()
    def launch_server(self):
        # Cold-start telemetry, matching the image worker's format so the two
        # are directly comparable in the logs. See the module docstring for the
        # measured baseline this is meant to move.
        _t0 = time.time()
        logger.info("[tts] container_enter t=0.00")
        try:
            _start_comfy(self.port)
        except Exception:
            # The image worker leaves ComfyUI to start in the background and
            # waits separately; here a failure to launch is fatal for the
            # container, and swallowing it would just move the error to the first
            # job as a confusing graph failure.
            logger.exception("[tts] ComfyUI failed to start")
            raise
        logger.info("[tts] comfy_ready t=%.2f", time.time() - _t0)
        self._completed_runs = 0

    @modal.method()
    async def run(self, workflow_json: Dict[str, Any]):
        """Execute one TTS workflow, streaming NDJSON progress.

        Same envelope as the image worker's `run`: a workflow in, `TaskEvent`
        lines out. That is what lets `provider_core` treat both identically, and
        it is why the provider's `capabilities` had to grow a list — this app is
        the same kind of machine serving a different task type.
        """
        # Refresh the volume replica, so an uploaded voice reference written by
        # another container since this one started is visible to ComfyUI. The
        # image worker has done this since the beginning; without it a cloned
        # voice resolves against the state the container booted with and the
        # graph fails on a file it can see is there.
        await safe_vol_reload_aio()

        if MAX_CONTAINERS >= 1 and self._completed_runs >= MAX_RUNS_BEFORE_RESTART:
            # Matches the image worker's restart cadence. A ComfyUI container
            # accumulates state across runs and eventually stalls; a restart is
            # cheaper than a timeout and cheaper than debugging a hung graph.
            logger.info("[tts] restarting ComfyUI after %s runs", self._completed_runs)
            await asyncio.to_thread(self._restart)
            self._completed_runs = 0

        async for update in self._execute(workflow_json):
            yield update
        self._completed_runs += 1

        # Per-run VRAM cleanup, on the same terms as the image worker: the
        # request has to reach the ComfyUI subprocess, because the VRAM this
        # container has to give back is the subprocess's, not this function's.
        await asyncio.to_thread(free_comfy_vram, self.port, "TTSWorker", logger.info)

    async def _execute(self, workflow_json: Dict[str, Any]):
        import urllib.request

        # Submit the graph.
        body = json.dumps(
            {
                "prompt": workflow_json.get("prompt", workflow_json),
                "client_id": "tts-worker",
            }
        ).encode()
        req = urllib.request.Request(
            f"http://127.0.0.1:{self.port}/prompt",
            data=body,
            headers={"Content-Type": "application/json"},
            method="POST",
        )
        try:
            with urllib.request.urlopen(req, timeout=60) as resp:
                queued = json.loads(resp.read())
        except Exception as exc:  # noqa: BLE001
            yield {
                "status": "error",
                "message": f"ComfyUI rejected the workflow: {exc}",
                "retryable": False,
            }
            return

        prompt_id = queued.get("prompt_id")
        if not prompt_id:
            yield {
                "status": "error",
                "message": f"ComfyUI returned no prompt_id: {queued}",
                "retryable": False,
            }
            return

        # Poll for completion. ComfyUI's history endpoint is the reliable one;
        # the websocket would be faster but adds a client dependency to an
        # app whose whole point is a small image.
        deadline = time.time() + TIMEOUT
        while time.time() < deadline:
            try:
                with urllib.request.urlopen(
                    f"http://127.0.0.1:{self.port}/history/{prompt_id}", timeout=10
                ) as resp:
                    history = json.loads(resp.read())
            except Exception:
                history = {}
            entry = history.get(prompt_id)
            if entry:
                outputs = self._collect_outputs(entry)
                yield {"status": "success", "prompt_id": prompt_id, "outputs": outputs}
                return
            yield {"status": "running", "prompt_id": prompt_id}
            await asyncio.sleep(1.0)

        yield {
            "status": "error",
            "message": f"Timed out after {TIMEOUT}s",
            "retryable": True,
        }

    @staticmethod
    def _collect_outputs(entry: Dict[str, Any]) -> List[Dict[str, Any]]:
        """Pull the produced audio files out of a ComfyUI history entry."""
        collected: List[Dict[str, Any]] = []
        for node_output in (entry.get("outputs") or {}).values():
            for kind in ("audio", "gifs", "images"):
                for item in node_output.get(kind, []) or []:
                    if isinstance(item, dict) and item.get("filename"):
                        collected.append(
                            {
                                "filename": item["filename"],
                                "subfolder": item.get("subfolder", ""),
                                "type": item.get("type", "output"),
                            }
                        )
        return collected

    def _restart(self) -> None:
        """Replace the ComfyUI process inside this container.

        The actual recycle mechanism is a process kill, not a Modal container
        recycle: `MAX_CONTAINERS` is 1, so Modal has no second container to evict
        and nothing to wait for. What previously stood here called `/free` and
        logged "requesting container recycle" — it recycled nothing, and the
        log line said otherwise, which is worse than having no function at all.
        """
        restart_comfy_process(
            self.port,
            "TTSWorker",
            start=lambda: _start_comfy(self.port),
            wait_for_ready=lambda: _wait_for_ready(
                self.port, HEALTHCHECK_TIMEOUT, "ComfyUIStable"
            ),
            log=logger.info,
            timeout_seconds=HEALTHCHECK_TIMEOUT,
        )

    @modal.method()
    def list_voices(self) -> List[Dict[str, Any]]:
        return [
            {"id": "friendly", "name": "Friendly", "type": "preset", "language": "en", "description": "Warm, approachable tone"},
            {"id": "professional", "name": "Professional", "type": "preset", "language": "en", "description": "Clear, authoritative delivery"},
            {"id": "cheerful", "name": "Cheerful", "type": "preset", "language": "en", "description": "Bright, energetic tone"},
            {"id": "calm", "name": "Calm", "type": "preset", "language": "en", "description": "Relaxed, soothing presence"},
            {"id": "deep", "name": "Deep", "type": "preset", "language": "en", "description": "Rich, resonant bass"},
            {"id": "bright", "name": "Bright", "type": "preset", "language": "en", "description": "Crisp, clear high register"},
            {"id": "storyteller", "name": "Storyteller", "type": "preset", "language": "en", "description": "Expressive, narrative style"},
            {"id": "whisper", "name": "Whisper", "type": "preset", "language": "en", "description": "Intimate, hushed delivery"},
            {"id": "dramatic", "name": "Dramatic", "type": "preset", "language": "en", "description": "Theatrical, emotional range"},
        ]


# -------------------------------------------------------------------- storage
#
# Namespace: every path here is relative to the volume root, `/mnt/data` — the
# same convention the image worker's FileStorage uses, and the one the backend's
# `provider_registry` assumes when it passes a path through to `/get-file`
# unencoded. It is also the only choice that can round-trip: ComfyUI's
# `output`/`input` directories are symlinks into `/mnt/data`, so an audio file
# the app produced at `output/<subfolder>/x.wav` is addressable as exactly the
# `{subfolder, filename}` the app reported, and an uploaded reference at
# `input/<name>` lands where ComfyUI will look for it. Resolving against the
# backend's own `settings.output_dir` instead (which is what a bare
# `os.path.join("/mnt/data", path)` appeared to do) puts uploads in
# `/mnt/data/<rel_path>` where no ComfyUI node will ever read them.


@tts_app.cls(
    image=tts_image,
    volumes={"/mnt/data": vol},
    cpu=1.0,
    timeout=300,
    scaledown_window=60,
    max_containers=1,
)
class TTSFileStorage:
    """Volume reads and writes for the TTS client.

    A class rather than the `modal.Volume` handle because the client runs in a
    different container: `Volume` exposes only container-local methods
    (`read_file`, `remove_file`) and has no `stat` and no `write_file` at all, so
    every route built on the handle was calling something that does not exist.
    Modal methods, like the image worker's, do have `.remote`.
    """

    @staticmethod
    def _resolve(path: str) -> str:
        from provider_core.utils import get_safe_path

        return get_safe_path("/mnt/data", path)

    @modal.method()
    def file_size(self, path: str) -> int:
        safe_vol_reload()
        full_path = self._resolve(path)
        if not os.path.isfile(full_path):
            raise FileNotFoundError(f"File not found: {path}")
        return os.path.getsize(full_path)

    @modal.method()
    def read_file(self, path: str) -> bytes:
        safe_vol_reload()
        full_path = self._resolve(path)
        if not os.path.isfile(full_path):
            raise FileNotFoundError(f"File not found: {path}")
        with open(full_path, "rb") as handle:
            return handle.read()

    @modal.method()
    def put_file(self, path: str, content: bytes) -> int:
        full_path = self._resolve(path)
        os.makedirs(os.path.dirname(full_path) or "/mnt/data", exist_ok=True)
        with open(full_path, "wb") as handle:
            handle.write(content)
        vol.commit()
        return len(content)

    @modal.method()
    def delete_file(self, path: str) -> bool:
        safe_vol_reload()
        full_path = self._resolve(path)
        if not os.path.isfile(full_path):
            return False
        os.remove(full_path)
        vol.commit()
        return True


# -------------------------------------------------------------------- storage


@tts_app.function(
    volumes={"/mnt/data": vol},
    cpu=1.0,
    timeout=600,
    scaledown_window=5,
    max_containers=1,
)
def ensure_tts_model_dir() -> Dict[str, Any]:
    """Make sure the TTS model directory exists on the volume.

    A separate function rather than a class method because it must run on a CPU
    container: a GPU container for a `mkdir` is the most expensive no-op
    available.
    """
    os.makedirs(TTS_MODEL_DIR, exist_ok=True)
    return {"dir": TTS_MODEL_DIR, "exists": os.path.isdir(TTS_MODEL_DIR)}


if __name__ == "__main__":
    # `modal deploy deployables/modal/tts/modal_app.py` is what the backend's
    # deploy target runs; this block is only for `modal run` during development.
    with tts_app.run():
        pass
