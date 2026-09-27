import os
import asyncio
import base64
import hmac
import json
from typing import Any, Dict, List, Optional

from fastapi import FastAPI, HTTPException, Request, Query, Depends
from fastapi.responses import FileResponse, Response
from pydantic import BaseModel, Field

from provider_core.http_client import get_file_size_cap
from provider_core.responses import failed, from_upstream, ok
from provider_core.utils import get_safe_path, is_transient_artifact
from provider_core.downloads import download_model_to_path, pending_download_paths
from provider_core.reconciliation import determine_download_token
from provider_core.validation import validate_downloaded_file
from provider_core.models import MODEL_DIRECTORIES

app = FastAPI(title="TNHComfy Remote Agent")

DATA_DIR = os.getenv("DATA_DIR", "./data")  # STORAGE ROOT (not `models/`)
TOKEN = os.getenv("REMOTE_AGENT_TOKEN", "").strip()
ALLOW_INSECURE = os.getenv("REMOTE_AGENT_ALLOW_INSECURE", "").lower() in {"1", "true", "yes"}
if not TOKEN and not ALLOW_INSECURE:
    raise RuntimeError("REMOTE_AGENT_TOKEN must be set unless REMOTE_AGENT_ALLOW_INSECURE=1")
HF_TOKEN = os.getenv("HF_TOKEN", "")
CIVITAI_TOKEN = os.getenv("CIVITAI_TOKEN", "")
DOWNLOAD_TIMEOUT = int(os.getenv("DOWNLOAD_TIMEOUT", "1800"))

# The default bind was 0.0.0.0 (here, agentctl.sh:71, and
# remote_agent/docker-compose.yml publishing 8001 on all interfaces), and
# REMOTE_AGENT_ALLOW_INSECURE makes `verify_token` return True unconditionally —
# so the flag did not just "skip auth on a dev box", it opened
# /delete-model, /delete-file, /upload-file and /download-model to anyone who
# could route to the port, with write access to the ComfyUI models mount. The flag
# still works exactly as documented (local dev, single user, loopback); it just
# refuses to be a remote write API by default.
_LOOPBACK_HOSTS = frozenset({"127.0.0.1", "::1", "localhost", ""})


def _resolve_bind_host() -> str:
    """Clamp the insecure bind to loopback unless the operator already chose it.

    Deliberately no "unless they set HOST explicitly" escape: the default was
    0.0.0.0 in three places (here, `agentctl.sh:71`, and the compose that publishes
    8001 on all interfaces), so an explicit-looking HOST is usually just the
    default being echoed back. An operator who genuinely needs the agent reachable
    from another machine sets REMOTE_AGENT_TOKEN; there is no reason to hand out
    an unauthenticated *writer* to get that.
    """
    host = os.getenv("HOST", "0.0.0.0").strip()
    if not ALLOW_INSECURE or host in _LOOPBACK_HOSTS:
        return host
    return "127.0.0.1"


def _warn_insecure_bind() -> None:
    if not ALLOW_INSECURE:
        return
    requested = os.getenv("HOST", "0.0.0.0").strip() or "0.0.0.0"
    print(
        "WARNING: REMOTE_AGENT_ALLOW_INSECURE is set. The agent has NO "
        "authentication: /delete-model, /delete-file, /upload-file and "
        "/download-model will accept any caller that can reach it, and DATA_DIR is "
        f"read-write. HOST={requested!r} -> binding {_resolve_bind_host()!r}. "
        "Set REMOTE_AGENT_TOKEN to open it up; this flag is for local dev only.",
        flush=True,
    )

# Concurrent /setup seeds. Below the 8 default seed URLs, and well below the
# default executor's worker count, so a rig where several model hosts are slow
# cannot occupy every thread the single-process agent has.
SEED_MAX_CONCURRENT = int(os.getenv("REMOTE_AGENT_SEED_MAX_CONCURRENT", "3"))

# Ceiling on every `asyncio.to_thread` in this file.
#
# `asyncio.to_thread` uses the default executor, whose worker count is bounded
# (and is NOT SEED_MAX_CONCURRENT — that semaphore only covered /setup). So the
# 16 unbounded fan-out of /validate-models, plus a /get-file walk, plus a
# download, could occupy every thread the single-process agent has and queue
# everything else behind it — which is the same failure /setup already had and
# already fixed. Sized like the default executor's worker count rather than
# smaller: the point is not to make the work smaller, it is to stop an unbounded
# number of *pending* work items from ever reaching the executor.
THREAD_MAX_CONCURRENT = int(os.getenv("REMOTE_AGENT_THREAD_MAX_CONCURRENT", "32"))
_thread_semaphore: Optional[asyncio.Semaphore] = None


# Ceiling on one /upload-file body, in decoded bytes. 512 MiB is generous for the
# route's real traffic (input images, masks) and still finite. The JSON field is
# checked at the encoded length (4/3 of this plus slack for the rest of the
# document), because that is what Pydantic has in hand.
UPLOAD_MAX_BYTES = int(os.getenv("REMOTE_AGENT_UPLOAD_MAX_BYTES", str(512 * 1024 * 1024)))
UPLOAD_MAX_BYTES_ENCODED = (UPLOAD_MAX_BYTES // 3) * 4 + 4096


async def _bounded_to_thread(fn, /, *args, **kwargs):
    """`asyncio.to_thread` behind a process-wide admission gate.

    The gate is taken around the `await`, not inside the thread body: holding it
    in the body would bound nothing, because the coroutine has already handed the
    work to the executor by then (the same reasoning the seed semaphore above
    documents).

    The semaphore is created lazily rather than at import, because an
    `asyncio.Semaphore` binds to the loop that is running when it is first
    awaited, and this module is imported before uvicorn has a loop.
    """
    global _thread_semaphore
    if _thread_semaphore is None:
        _thread_semaphore = asyncio.Semaphore(THREAD_MAX_CONCURRENT)
    async with _thread_semaphore:
        return await asyncio.to_thread(fn, *args, **kwargs)

_SIDECAR_EXTENSIONS = (".json", ".preview.png", ".sha256", ".downloading", ".lock")
# Deliberately NOT provider_core.utils.SIDECAR_SUFFIXES. The shared tuple also
# excludes .txt/.yaml/.yml, which are reported as models here; narrowing it would
# silently stop listing files an operator can see in the directory. The
# pipeline-owned suffixes are NOT duplicated in that tuple on purpose: they come
# from is_transient_artifact, which is the single source of truth for them.


def _ensure_data_dir() -> str:
    os.makedirs(DATA_DIR, exist_ok=True)
    return DATA_DIR


async def verify_token(request: Request):
    if TOKEN:
        auth_header = request.headers.get("Authorization")
        provided = auth_header.split(" ", 1)[1] if auth_header and auth_header.startswith("Bearer ") else ""
        # compare_digest, not `!=`: a plain string compare short-circuits on the
        # first differing byte, which leaks the length of the shared prefix of a
        # guessed token. Every other gate in this repo (provider_core/router.py)
        # uses hmac.compare_digest.
        if not provided or not hmac.compare_digest(provided, TOKEN):
            raise HTTPException(status_code=401, detail="Unauthorized")
    return True


class DownloadRequest(BaseModel):
    url: str
    path: str
    token: Optional[str] = None
    preview_url: Optional[str] = None
    metadata: Optional[Dict[str, Any]] = None
    info: Optional[Dict[str, Any]] = None


class ListModelsRequest(BaseModel):
    directory: str


class DeleteModelRequest(BaseModel):
    path: str


class UploadFileRequest(BaseModel):
    filename: str
    # Bounded in the model, not in the handler. `content_base64` is a JSON string
    # field, so FastAPI/Pydantic had already parsed the entire body into memory
    # before the first line of `upload_file` ran — `base64.b64decode` then made a
    # second copy. The limit is therefore on the *encoded* length, and the
    # Content-Length check below rejects the body before that parse happens at all.
    content_base64: str = Field(..., max_length=UPLOAD_MAX_BYTES_ENCODED)
    directory: str


class ValidateModelsRequest(BaseModel):
    directory: str | List[str]
    delete_invalid: bool = False


class ValidateAllModelsRequest(BaseModel):
    delete_invalid: bool = False


def _data_path(requested_path: str) -> str:
    try:
        return get_safe_path(DATA_DIR, requested_path)
    except ValueError:
        raise HTTPException(status_code=403, detail="Access denied: path outside allowed directory")


def _is_sidecar(name: str) -> bool:
    return name.lower().endswith(_SIDECAR_EXTENSIONS)


@app.get("/health")
async def health():
    return {"status": "healthy"}


@app.post("/setup", dependencies=[Depends(verify_token)])
async def setup():
    _ensure_data_dir()
    # The first comprehension that used to sit here was dead: line 106 overwrote
    # it, and it would have produced "models/models/checkpoints" for any entry
    # that already carried the prefix. MODEL_DIRECTORIES are all "models/<kind>".
    directories = ["output", "input", "downloads"] + list(MODEL_DIRECTORIES)
    # Seed default upscaler + ADetailer models (mirrors Modal/Beam setup).
    default_models = [
        "https://huggingface.co/lokCX/4x-Ultrasharp/resolve/main/4x-Ultrasharp.pth",
        "https://huggingface.co/Facehugger/4x-foolhardy-Remacri/resolve/main/4x_foolhardy_Remacri.pth",
        "https://github.com/xinntao/Real-ESRGAN/releases/download/v0.1.0/RealESRGAN_x4plus.pth",
        "https://github.com/xinntao/Real-ESRGAN/releases/download/v0.2.2.4/RealESRGAN_x4plus_anime_6B.pth",
        "https://huggingface.co/Bingsu/adetailer/resolve/main/face_yolov8n.pt",
        "https://huggingface.co/Bingsu/adetailer/resolve/main/face_yolov8s.pt",
        "https://huggingface.co/Bingsu/adetailer/resolve/main/hand_yolov8n.pt",
        "https://huggingface.co/Bingsu/adetailer/resolve/main/person_yolov8n-seg.pt",
    ]
    default_paths = [
        "models/upscale_models/4x-Ultrasharp.pth",
        "models/upscale_models/4x_foolhardy_Remacri.pth",
        "models/upscale_models/RealESRGAN_x4plus.pth",
        "models/upscale_models/RealESRGAN_x4plus_anime_6B.pth",
        "models/ultralytics/bbox/face_yolov8n.pt",
        "models/ultralytics/bbox/face_yolov8s.pt",
        "models/ultralytics/bbox/hand_yolov8n.pt",
        "models/ultralytics/seg/person_yolov8n-seg.pt",
    ]
    for d in directories:
        os.makedirs(os.path.join(DATA_DIR, d), exist_ok=True)

    # Bounded, and with a real HTTP timeout.
    #
    # This used to `asyncio.gather` all 8 seeds with no semaphore and no
    # `request_timeout_seconds`. Both halves mattered: `asyncio.to_thread` uses
    # the default executor, whose worker count is bounded, so 8 stalled peers
    # pinned every thread in the process and every later `to_thread` — including
    # /validate-models and /get-file — queued behind them, stopping a
    # single-process agent outright. And with no HTTP timeout, one `requests.get`
    # that connected and then went quiet blocks its thread forever.
    seed_semaphore = asyncio.Semaphore(SEED_MAX_CONCURRENT)

    async def _seed(url: str, path: str):
        full_path = _data_path(path)
        if os.path.exists(full_path) and os.path.getsize(full_path) > 0:
            return
        token = determine_download_token(url, HF_TOKEN, CIVITAI_TOKEN)

        def _do() -> None:
            download_model_to_path(
                url=url, full_path=full_path, path=path, token=token,
                hf_token=HF_TOKEN, civitai_token=CIVITAI_TOKEN,
                log=print, log_prefix="Setup",
                # Same value /download-model passes (below). A seed that cannot
                # finish inside it gives up instead of holding a thread open
                # indefinitely.
                request_timeout_seconds=DOWNLOAD_TIMEOUT,
            )

        # The semaphore wraps the `await`, not the `to_thread` body: holding it
        # here is what keeps the queued seeds in the coroutine rather than
        # occupying executor threads.
        async with seed_semaphore:
            try:
                await _bounded_to_thread(_do)
            except Exception as e:
                print(f"[setup] failed to seed {path}: {e}")

    await asyncio.gather(*[_seed(u, p) for u, p in zip(default_models, default_paths)])
    return ok("Setup complete", directories=directories)


@app.post("/download-model", dependencies=[Depends(verify_token)])
async def download_model(req: DownloadRequest):
    full_path = _data_path(req.path)
    os.makedirs(os.path.dirname(full_path), exist_ok=True)

    # download_model_to_path resolves HF/CivitAI tokens internally
    # (build_authenticated_download_request), writes a `.downloading` temp file,
    # validates the file (magic bytes / min size), then atomically renames —
    # matching the Modal/Beam storage function semantics.
    token = req.token or determine_download_token(req.url, HF_TOKEN, CIVITAI_TOKEN)

    progress_dir = os.path.join(DATA_DIR, "downloads")
    os.makedirs(progress_dir, exist_ok=True)
    safe_name = os.path.basename(full_path)
    progress_file = os.path.join(progress_dir, f"{safe_name}.json")

    def progress_callback(payload: Dict[str, Any]):
        try:
            with open(progress_file, "w") as f:
                json.dump(payload, f)
        except Exception:
            pass

    def _do():
        try:
            return download_model_to_path(
                url=req.url, full_path=full_path, path=req.path,
                token=token, hf_token=HF_TOKEN, civitai_token=CIVITAI_TOKEN,
                preview_url=req.preview_url, metadata=req.metadata,
                log=print, log_prefix="Download",
                progress_callback=progress_callback,
                request_timeout_seconds=DOWNLOAD_TIMEOUT,
            )
        except Exception as e:
            return failed(str(e))

    result = await _bounded_to_thread(_do)
    if os.path.exists(progress_file):
        try:
            os.remove(progress_file)
        except Exception:
            pass
    # `from_upstream`, not a bare pass-through: `download_model_to_path` answers
    # `{"status": "error", ...}` for a real failure, and forwarding that verbatim is
    # one of the dialects the shared response module exists to remove. A non-dict
    # return is a failure too, rather than an AttributeError three frames up.
    if not isinstance(result, dict):
        return failed("Download failed")
    return from_upstream(result)


def _validate_dir(target_dir: str, delete_invalid: bool) -> Dict[str, Any]:
    if not os.path.isdir(target_dir):
        return {"valid": [], "invalid": [], "partial": [], "total_valid": 0, "total_invalid": 0, "total_partial": 0}

    valid, invalid, partial = [], [], []
    entries = list(os.walk(target_dir))
    for root, _, filenames in entries:
        for name in filenames:
            if name.startswith("."):
                continue
            if is_transient_artifact(name):
                # The shared predicate, so a new pipeline-owned suffix is picked up
                # here without a per-engine exclusion list that can drift. Both are
                # "partial": the per-attempt temp and the parked resume slot are a
                # download that has not finished, and a `.lock` is a 0-byte file
                # whose held flock is what makes the download safe.
                #
                # Reported, never deleted: reconciliation runs with delete_invalid
                # true, and removing an in-flight temp file leaves the writer with
                # a live descriptor whose os.replace then fails. The abandoned ones
                # are swept by /delete-model and /delete-file via
                # pending_download_paths, which is the only place that can tell an
                # in-flight attempt from a dead one.
                rel_path = os.path.relpath(os.path.join(root, name), DATA_DIR).replace("\\", "/")
                size = os.path.getsize(os.path.join(root, name))
                partial.append({"name": name, "path": rel_path, "size": size, "issue": "Incomplete download (temp file)"})
                continue
            if _is_sidecar(name):
                continue
            full_path = os.path.join(root, name)
            rel_path = os.path.relpath(full_path, DATA_DIR).replace("\\", "/")
            size = os.path.getsize(full_path)
            validation = validate_downloaded_file(full_path)
            model_info = {"name": name, "path": rel_path, "size": size, "size_mb": round(size / (1024 ** 2), 1), "format": validation.get("format", "unknown")}
            if not validation["valid"]:
                model_info["issues"] = validation.get("errors", [validation.get("error", "validation failed")])
                invalid.append(model_info)
                if delete_invalid:
                    try: os.remove(full_path)
                    except Exception: pass
                # Was `else: continue` as the last statement of the loop body, so
                # it was unreachable and `valid.append` below was the only thing
                # that ran when the file *was* valid.
            else:
                valid.append(model_info)

    return {
        "total_valid": len(valid), "total_invalid": len(invalid), "total_partial": len(partial),
        "valid": valid, "invalid": invalid, "partial": partial, "total": len(valid) + len(invalid) + len(partial),
    }


@app.post("/list-models", dependencies=[Depends(verify_token)])
async def list_models(req: ListModelsRequest):
    target_dir = _data_path(req.directory) if req.directory else DATA_DIR

    def _walk():
        files = []
        if os.path.exists(target_dir):
            for root, _, filenames in os.walk(target_dir):
                for filename in filenames:
                    if filename.startswith(".") or _is_sidecar(filename):
                        continue
                    full_path = os.path.join(root, filename)
                    rel_path = os.path.relpath(full_path, DATA_DIR).replace("\\", "/")
                    files.append({"name": filename, "path": rel_path, "type": "file", "size": os.path.getsize(full_path)})
        return files

    listed = await _bounded_to_thread(_walk)
    return ok(f"Listed {len(listed)} models", files=listed)


@app.post("/delete-model", dependencies=[Depends(verify_token)])
@app.post("/delete-file", dependencies=[Depends(verify_token)])
async def delete_model(req: DeleteModelRequest):
    full_path = _data_path(req.path)
    if not os.path.exists(full_path) and not list(pending_download_paths(full_path)):
        return failed("File not found", code=404)

    def _do_remove(path: str):
        if os.path.isdir(path):
            import shutil
            shutil.rmtree(path)
        elif os.path.exists(path):
            os.remove(path)

    try:
        _do_remove(full_path)
        base, _ = os.path.splitext(full_path)
        for ext in (".json", ".preview.png", ".sha256"):
            _do_remove(base + ext)
        _do_remove(full_path + ".sha256")
        # pending_download_paths, not a fixed `.downloading` probe. The per-attempt
        # temp is `<path>.<pid>.<hex>.downloading` and a parked resume slot is
        # `<path>.resume.<identity>.downloading` (downloads.py _unique_temp_path /
        # _resume_slot_path), so the old probe matched nothing: a crash-interrupted
        # 7 GB download survived delete-model forever. It also never got cleaned up
        # by /validate-*-models, which reports every `.downloading` as `partial` and
        # deliberately does not delete one — so `total_partial` was permanently
        # non-zero, and step 0 of reconciliation (which runs with delete_invalid)
        # could never reach zero. Modal (modal_app.py) and Beam (beam_app.py) both
        # used the shared helper; this file never referenced it at all.
        for stale in pending_download_paths(full_path):
            _do_remove(stale)
    except OSError as exc:
        # Was unhandled: `_do_remove` called os.remove on a directory, which
        # raises IsADirectoryError, so a DELETE of a directory was a 500 while
        # Modal and Beam rmtree the same request and answer 200.
        return failed(f"Delete failed: {exc}")
    return ok(f"Deleted {req.path}")


@app.get("/get-file/{path:path}", dependencies=[Depends(verify_token)])
async def get_file(path: str, type: str = Query(default="output"), subfolder: str = Query(default="")):
    """Stream a file from DATA_DIR.

    This read the whole file with `f.read()` inside an `async def` and returned it
    in a single Response. On a single-process `uvicorn.run` that blocks every other
    request on the agent for the duration, and a 7 GB checkpoint is three copies
    of RAM between here and whoever asked for it.

    `FileResponse` reads in chunks on Starlette's own threadpool, so the event loop
    stays free and peak memory is one chunk. The `type` parameter is accepted and
    ignored: it was never used here, and `_data_path` already confines the result
    to DATA_DIR.

    The size cap is the same backstop beam_app's /get-file uses
    (`provider_core.http_client.get_file_size_cap`, overridable with
    `PROVIDER_GET_FILE_MAX_BYTES`): a wrong `path` must not turn into an
    out-of-memory kill of the agent, and a weights file is not what this route is
    for.
    """
    full_path = _data_path(os.path.join(subfolder, path) if subfolder else path)
    if not os.path.exists(full_path) or not os.path.isfile(full_path):
        raise HTTPException(status_code=404, detail=f"File not found: {path}")

    max_bytes = get_file_size_cap()
    size = os.path.getsize(full_path)
    if max_bytes >= 0 and size > max_bytes:
        raise HTTPException(
            status_code=413,
            detail=f"{path} is {size} bytes, over the {max_bytes} byte get-file limit",
        )

    return FileResponse(full_path, media_type="application/octet-stream", filename=os.path.basename(full_path))


@app.post("/upload-file", dependencies=[Depends(verify_token)])
async def upload_file(req: UploadFileRequest, http_request: Request):
    # The pydantic bound above rejects an over-long *field*, but the body was
    # already read to parse it. Content-Length is declared before that read, so
    # this is the check that actually stops an oversized upload: it answers 413
    # without ever materialising the payload. A missing or unparseable
    # Content-Length is not a reason to fail — chunked bodies are legal — so it
    # falls through to the model's own limit.
    declared = http_request.headers.get("content-length")
    if declared is not None:
        try:
            if int(declared) > UPLOAD_MAX_BYTES_ENCODED:
                raise HTTPException(
                    status_code=413,
                    detail=f"Upload body of {declared} bytes is over the {UPLOAD_MAX_BYTES_ENCODED} byte limit",
                )
        except ValueError:
            pass
    content = base64.b64decode(req.content_base64)
    target_dir = _data_path(req.directory)
    os.makedirs(target_dir, exist_ok=True)
    path = _data_path(os.path.join(req.directory, req.filename))
    with open(path, "wb") as f:
        f.write(content)
    rel_path = os.path.relpath(path, DATA_DIR).replace("\\", "/")
    return ok("File uploaded", path=rel_path, size=len(content))


@app.post("/validate-models", dependencies=[Depends(verify_token)])
async def validate_models(req: ValidateModelsRequest):
    dirs = [req.directory] if isinstance(req.directory, str) else req.directory
    # Bounded: this used to be 16 unbounded `asyncio.to_thread` calls, which is
    # the fan-out the comment above /setup warns about — enough of them, or
    # enough concurrent requests, to take every executor thread the single-process
    # agent has and stop the rig answering anything at all.
    payloads = await asyncio.gather(*[
        _bounded_to_thread(_validate_dir, _data_path(d), req.delete_invalid)
        for d in dirs
    ])
    results = {"valid": [], "invalid": [], "partial": [], "total_valid": 0, "total_invalid": 0, "total_partial": 0, "by_directory": {}}
    for directory, payload in zip(dirs, payloads):
        results["by_directory"][directory] = payload
        for k in ("valid", "invalid", "partial"):
            results[k].extend(payload.get(k, []))
        results["total_valid"] += payload["total_valid"]
        results["total_invalid"] += payload["total_invalid"]
        results["total_partial"] += payload["total_partial"]
    results["total"] = results["total_valid"] + results["total_invalid"] + results["total_partial"]
    # The envelope, not a bare `{valid, invalid, partial, ...}`: the worker adopts
    # this body verbatim through `from_upstream`, and a body carrying neither
    # `status` nor `success` is the dialect the envelope exists to make impossible.
    return ok(
        f"Validated {results['total']} files across {len(dirs)} directories",
        result=results,
        **results,
    )


@app.post("/validate-all-models", dependencies=[Depends(verify_token)])
async def validate_all_models(req: Optional[ValidateAllModelsRequest] = None):
    # Was `req: Dict = {}`: a mutable default as a FastAPI body parameter, so
    # every request without a body shared (and could mutate) one dict. The body
    # stays optional so `POST` with no payload still works.
    delete_invalid = req.delete_invalid if req is not None else False
    return await validate_models(ValidateModelsRequest(directory=list(MODEL_DIRECTORIES), delete_invalid=delete_invalid))


if __name__ == "__main__":
    import uvicorn
    port = int(os.getenv("PORT", "8001"))
    _warn_insecure_bind()
    uvicorn.run(app, host=_resolve_bind_host(), port=port)
