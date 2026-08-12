import os
import asyncio
import base64
import json
from typing import Any, Dict, List, Optional

from fastapi import FastAPI, HTTPException, Request, Query, Depends
from fastapi.responses import Response
from pydantic import BaseModel

from provider_core.utils import get_safe_path
from provider_core.downloads import download_model_to_path
from provider_core.reconciliation import determine_download_token
from provider_core.validation import validate_downloaded_file
from provider_core.models import MODEL_DIRECTORIES

app = FastAPI(title="TNHComfy Remote Agent")

DATA_DIR = os.getenv("DATA_DIR", "./data")  # STORAGE ROOT (not `models/`)
TOKEN = os.getenv("REMOTE_AGENT_TOKEN", "")
HF_TOKEN = os.getenv("HF_TOKEN", "")
CIVITAI_TOKEN = os.getenv("CIVITAI_TOKEN", "")
DOWNLOAD_TIMEOUT = int(os.getenv("DOWNLOAD_TIMEOUT", "1800"))

_SIDECAR_EXTENSIONS = (".json", ".preview.png", ".sha256", ".downloading")


def _ensure_data_dir() -> str:
    os.makedirs(DATA_DIR, exist_ok=True)
    return DATA_DIR


async def verify_token(request: Request):
    if TOKEN:
        auth_header = request.headers.get("Authorization")
        if not auth_header or not auth_header.startswith("Bearer ") or auth_header.split(" ", 1)[1] != TOKEN:
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
    content_base64: str
    directory: str


class ValidateModelsRequest(BaseModel):
    directory: str | List[str]
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
    return {"status": "healthy", "data_dir": DATA_DIR}


@app.post("/setup", dependencies=[Depends(verify_token)])
async def setup():
    _ensure_data_dir()
    directories = (
        ["output", "input", "downloads"]
        + [f"models/{d}" if d.startswith("models/") else f"models/{d}" for d in MODEL_DIRECTORIES]
    )
    # MODEL_DIRECTORIES are already "models/<kind>"; normalize.
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

    async def _seed(url: str, path: str):
        full_path = _data_path(path)
        if os.path.exists(full_path) and os.path.getsize(full_path) > 0:
            return
        token = determine_download_token(url, HF_TOKEN, CIVITAI_TOKEN)
        try:
            await asyncio.to_thread(
                download_model_to_path,
                url=url, full_path=full_path, path=path, token=token,
                hf_token=HF_TOKEN, civitai_token=CIVITAI_TOKEN,
                log=print, log_prefix="Setup",
            )
        except Exception as e:
            print(f"[setup] failed to seed {path}: {e}")

    await asyncio.gather(*[_seed(u, p) for u, p in zip(default_models, default_paths)])
    return {"status": "success", "message": "Setup complete", "directories": directories}


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
            return {"status": "error", "message": str(e)}

    result = await asyncio.to_thread(_do)
    if os.path.exists(progress_file):
        try:
            os.remove(progress_file)
        except Exception:
            pass
    return result if isinstance(result, dict) else {"status": "error", "message": "Download failed"}


def _validate_dir(target_dir: str, delete_invalid: bool) -> Dict[str, Any]:
    if not os.path.isdir(target_dir):
        return {"valid": [], "invalid": [], "partial": [], "total_valid": 0, "total_invalid": 0, "total_partial": 0}

    valid, invalid, partial = [], [], []
    entries = list(os.walk(target_dir))
    for root, _, filenames in entries:
        for name in filenames:
            if name.startswith("."):
                continue
            if name.endswith(".downloading"):
                rel_path = os.path.relpath(os.path.join(root, name), DATA_DIR).replace("\\", "/")
                size = os.path.getsize(os.path.join(root, name))
                partial.append({"name": name, "path": rel_path, "size": size, "issue": "Incomplete download (temp file)"})
                if delete_invalid:
                    try:
                        os.remove(os.path.join(root, name))
                    except Exception:
                        pass
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
                else:
                    continue
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

    return {"status": "success", "files": await asyncio.to_thread(_walk)}


@app.post("/delete-model", dependencies=[Depends(verify_token)])
@app.post("/delete-file", dependencies=[Depends(verify_token)])
async def delete_model(req: DeleteModelRequest):
    full_path = _data_path(req.path)
    if not os.path.exists(full_path):
        return {"success": False, "message": "File not found"}

    def _do_remove(path: str):
        if os.path.exists(path):
            os.remove(path)

    _do_remove(full_path)
    base, _ = os.path.splitext(full_path)
    for ext in (".json", ".preview.png", ".sha256"):
        _do_remove(base + ext)
    _do_remove(full_path + ".sha256")
    _do_remove(full_path + ".downloading")
    return {"success": True}


@app.get("/get-file/{path:path}", dependencies=[Depends(verify_token)])
async def get_file(path: str, type: str = Query(default="output"), subfolder: str = Query(default="")):
    full_path = _data_path(os.path.join(subfolder, path) if subfolder else path)
    if not os.path.exists(full_path):
        raise HTTPException(status_code=404, detail=f"File not found: {path}")
    with open(full_path, "rb") as f:
        content = f.read()
    return Response(content=content, media_type="application/octet-stream")


@app.post("/upload-file", dependencies=[Depends(verify_token)])
async def upload_file(req: UploadFileRequest):
    content = base64.b64decode(req.content_base64)
    target_dir = _data_path(req.directory)
    os.makedirs(target_dir, exist_ok=True)
    path = os.path.join(target_dir, req.filename)
    with open(path, "wb") as f:
        f.write(content)
    rel_path = os.path.join(req.directory, req.filename).replace("\\", "/")
    return {"status": "success", "path": rel_path, "size": len(content)}


@app.post("/validate-models", dependencies=[Depends(verify_token)])
async def validate_models(req: ValidateModelsRequest):
    dirs = [req.directory] if isinstance(req.directory, str) else req.directory
    payloads = await asyncio.gather(*[asyncio.to_thread(_validate_dir, _data_path(d), req.delete_invalid) for d in dirs])
    results = {"valid": [], "invalid": [], "partial": [], "total_valid": 0, "total_invalid": 0, "total_partial": 0, "by_directory": {}}
    for directory, payload in zip(dirs, payloads):
        results["by_directory"][directory] = payload
        for k in ("valid", "invalid", "partial"):
            results[k].extend(payload.get(k, []))
        results["total_valid"] += payload["total_valid"]
        results["total_invalid"] += payload["total_invalid"]
        results["total_partial"] += payload["total_partial"]
    results["total"] = results["total_valid"] + results["total_invalid"] + results["total_partial"]
    return results


@app.post("/validate-all-models", dependencies=[Depends(verify_token)])
async def validate_all_models(req: Dict = {}):
    return await validate_models(ValidateModelsRequest(directory=list(MODEL_DIRECTORIES), delete_invalid=req.get("delete_invalid", False)))


if __name__ == "__main__":
    import uvicorn
    port = int(os.getenv("PORT", "8001"))
    host = os.getenv("HOST", "0.0.0.0")
    uvicorn.run(app, host=host, port=port)
