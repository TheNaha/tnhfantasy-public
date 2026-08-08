import modal
import os
import json
import logging
import time
import asyncio
from typing import List, Dict, Any, Optional
from datetime import datetime, timezone

from provider_core.utils import get_safe_path
from provider_core.downloads import download_model_to_path
from provider_core.validation import (
    MIN_MODEL_SIZE,
    VALID_FILE_HEADERS,
    validate_downloaded_file,
)

logging.basicConfig(
    level=logging.INFO,
    format='%(levelname)s %(name)s: %(message)s'
)
logger = logging.getLogger("modal_app_vllm")

app = modal.App(os.getenv("MODAL_APP_NAME", "vllm-modal-stack"))
vol = modal.Volume.from_name(os.getenv("MODAL_VOLUME_NAME", "comfy-llm-models"), create_if_missing=True)

image = (
    modal.Image.debian_slim(python_version="3.11")
    .pip_install(
        "vllm",
        "fastapi",
        "uvicorn",
        "huggingface_hub",
        "hf-transfer",
        "aiofiles",
        "requests",
    )
    .env({"HF_HUB_ENABLE_HF_TRANSFER": "1"})
)

DOWNLOAD_TIMEOUT = int(os.environ.get("MODAL_DOWNLOAD_TIMEOUT", "3600"))
DOWNLOAD_MAX_CONTAINERS = int(os.environ.get("MODAL_DOWNLOAD_MAX_CONTAINERS", "2"))
STORAGE_MAX_CONTAINERS = int(os.environ.get("MODAL_STORAGE_MAX_CONTAINERS", "10"))
VALIDATE_TIMEOUT = int(os.environ.get("MODAL_VALIDATE_TIMEOUT", "600"))
VALIDATE_MAX_CONTAINERS = int(os.environ.get("MODAL_VALIDATE_MAX_CONTAINERS", "2"))


async def list_models_with_metadata_internal(base_path: str, directory: str, compute_hashes: bool = False) -> list[Dict[str, Any]]:
    import aiofiles
    try:
        target_dir = get_safe_path(base_path, directory)
    except Exception:
        return []
    if not os.path.exists(target_dir):
        return []

    def _scan():
        entries, entry_set = [], set()
        try:
            for e in os.scandir(target_dir):
                if e.is_file():
                    entry_set.add(e.name)
                    if not e.name.endswith(('.json', '.preview.png', '.sha256')):
                        entries.append((e.name, e.stat().st_size))
        except Exception:
            pass
        return entries, entry_set

    entries, entry_set = await asyncio.to_thread(_scan)

    async def _proc(name: str, size: int):
        fpath = f"{directory}/{name}" if directory else name
        res = {"name": name, "path": fpath, "type": "file", "size": size, "sha256": None}
        if f"{os.path.splitext(name)[0]}.preview.png" in entry_set:
            res["preview"] = f"/api/view/{directory}/{os.path.splitext(name)[0]}.preview.png"
        meta_name = f"{os.path.splitext(name)[0]}.json"
        if meta_name in entry_set:
            res["metadata_url"] = f"/api/view/{directory}/{meta_name}"
            try:
                async with aiofiles.open(os.path.join(target_dir, meta_name), 'r') as f:
                    res["metadata"] = json.loads(await f.read())
            except Exception:
                pass
        return res

    return await asyncio.gather(*[_proc(n, s) for n, s in entries])


@app.cls(image=image, gpu="A100", volumes={"/mnt/data": vol}, timeout=3600)
class VLLMEngine:
    @modal.enter()
    def setup(self):
        self.engine = None
        self.current_model = None
        logger.info("[VLLMEngine] Initialized")

    @modal.method()
    async def generate(
        self,
        model_id: str,
        messages: List[Dict[str, Any]],
        tools: Optional[List[Dict[str, Any]]] = None,
        timeout_seconds: Optional[float] = None,
    ):
        import uuid

        model_path = f"/mnt/data/{model_id}"

        if self.current_model != model_path:
            from vllm import AsyncLLMEngine, AsyncEngineArgs
            engine_args = AsyncEngineArgs(
                model=model_path,
                tensor_parallel_size=1,
                max_model_len=8192,
            )
            self.engine = AsyncLLMEngine.from_engine_args(engine_args)
            self.current_model = model_path
            logger.info(f"[VLLMEngine] Loaded model: {model_path}")

        from vllm.sampling_params import SamplingParams

        sampling_params = SamplingParams(
            temperature=0.8,
            top_p=0.95,
            max_tokens=1024,
        )

        request_id = str(uuid.uuid4())

        tokenizer = await self.engine.get_tokenizer()
        prompt = tokenizer.apply_chat_template(messages, add_generation_prompt=True)

        last_text_len = 0
        full_text = ""
        tool_calls: list[Dict[str, Any]] = []

        async for request_output in self.engine.generate(prompt, sampling_params, request_id):
            output = request_output.outputs[0]
            new_text = output.text

            if len(new_text) > last_text_len:
                delta = new_text[last_text_len:]
                full_text = new_text
                last_text_len = len(new_text)
                yield json.dumps({
                    "type": "progress",
                    "progress": 0,
                    "message": delta,
                })

            if output.tool_calls:
                for tc in output.tool_calls:
                    idx = next(
                        (i for i, t in enumerate(tool_calls) if t["id"] == tc.id),
                        None,
                    )
                    if idx is None:
                        tool_calls.append({
                            "id": tc.id,
                            "type": "function",
                            "function": {
                                "name": tc.function.name,
                                "arguments": "",
                            }
                        })
                    else:
                        tool_calls[idx]["function"]["arguments"] += tc.function.arguments

            if request_output.finished:
                output_dict: Dict[str, Any] = {"role": "assistant", "content": full_text}
                if tool_calls:
                    output_dict["tool_calls"] = tool_calls
                yield json.dumps({
                    "type": "completed",
                    "outputs": [output_dict]
                })
                return

        output_dict = {"role": "assistant", "content": full_text}
        if tool_calls:
            output_dict["tool_calls"] = tool_calls
        yield json.dumps({
            "type": "completed",
            "outputs": [output_dict]
        })


@app.function(
    image=image,
    volumes={"/mnt/data": vol},
    timeout=DOWNLOAD_TIMEOUT,
    max_containers=DOWNLOAD_MAX_CONTAINERS,
)
@modal.concurrent(max_inputs=1, target_inputs=1)
def download_model(url: str, path: str, token: str = None, preview_url: str = None, metadata: dict = None):
    """Download model with shared validation pipeline and progress tracking."""
    vol.reload()
    base_path = "/mnt/data"
    try:
        full_path = get_safe_path(base_path, path)
    except Exception as e:
        logger.error(f"[Download] Path traversal blocked: {e}")
        return {"status": "error", "message": "Invalid path"}

    progress_dir = "/mnt/data/downloads"
    os.makedirs(progress_dir, exist_ok=True)
    safe_name = os.path.basename(path)
    progress_file = os.path.join(progress_dir, f"{safe_name}.json")

    def update_progress(status, percent=0, speed="", eta="", downloaded="", total="", message=""):
        try:
            with open(progress_file, "w") as f:
                json.dump({
                    "filename": safe_name,
                    "status": status,
                    "percent": percent,
                    "speed": speed,
                    "eta": eta,
                    "downloaded": downloaded,
                    "total": total,
                    "message": message,
                    "updated_at": time.time()
                }, f)
            vol.commit()
        except Exception as e:
            logger.info(f"[Download] Failed to write progress: {e}")

    last_progress_update = 0.0

    def progress_callback(payload: Dict[str, Any]):
        nonlocal last_progress_update
        status = payload.get("status")

        if status == "starting":
            update_progress("starting", 0)
            return

        if status == "downloading":
            now = time.time()
            if now - last_progress_update < 0.5:
                return

            total_bytes = payload.get("total_bytes", 0) or 0
            downloaded_bytes = payload.get("downloaded_bytes", 0) or 0
            speed_mbps = payload.get("speed_mbps", 0.0) or 0.0
            eta_seconds = int(payload.get("eta_seconds", 0) or 0)
            percent = int(payload.get("percent", 0) or 0)

            downloaded_str = f"{downloaded_bytes / (1024 ** 2):.2f} MB"
            total_str = f"{total_bytes / (1024 ** 2):.2f} MB" if total_bytes > 0 else "Unknown"
            speed_str = f"{speed_mbps:.2f} MB/s"

            update_progress(
                "downloading",
                percent,
                speed_str,
                f"{eta_seconds}s",
                downloaded_str,
                total_str,
            )
            last_progress_update = now
            return

        if status == "success":
            update_progress("success", 100, message="Download complete")
            return

        if status == "message":
            update_progress("error", message=payload.get("message", "Download failed"))

    try:
        result = download_model_to_path(
            url=url,
            full_path=full_path,
            path=path,
            token=token,
            hf_token=os.environ.get("HF_TOKEN"),
            civitai_token=os.environ.get("CIVITAI_TOKEN"),
            preview_url=preview_url,
            metadata=metadata,
            log=logger.info,
            log_prefix="Download",
            progress_callback=progress_callback,
        )

        if result.get("status") == "success":
            vol.commit()
            time.sleep(5)

        return result
    finally:
        if os.path.exists(progress_file):
            try:
                os.remove(progress_file)
                vol.commit()
            except Exception:
                pass


@app.function(
    image=image,
    volumes={"/mnt/data": vol},
    scaledown_window=15,
    max_containers=STORAGE_MAX_CONTAINERS,
    timeout=3600,
)
@modal.concurrent(max_inputs=20, target_inputs=10)
async def list_models_with_metadata(directory: str):
    try:
        await vol.reload.aio()
    except Exception:
        vol.reload()
    return await list_models_with_metadata_internal("/mnt/data", directory, compute_hashes=False)


@app.function(
    image=image,
    volumes={"/mnt/data": vol},
    timeout=VALIDATE_TIMEOUT,
    max_containers=VALIDATE_MAX_CONTAINERS,
)
@modal.concurrent(max_inputs=10, target_inputs=5)
async def validate_models(directories: list[str], delete_invalid: bool = False):
    try:
        await vol.reload.aio()
    except Exception:
        vol.reload()

    if isinstance(directories, str):
        directories = [directories]

    validation_results = {
        "total_valid": 0,
        "total_invalid": 0,
        "total_partial": 0,
        "by_directory": {}
    }

    VALID_HEADERS = VALID_FILE_HEADERS
    MIN_SIZE = MIN_MODEL_SIZE

    def validate_single_file_in_dir(directory: str, name: str) -> Optional[Dict[str, Any]]:
        full_dir = get_safe_path("/mnt/data", directory) if directory else "/mnt/data"
        filepath = os.path.join(full_dir, name)
        if not os.path.exists(filepath):
            return None
        size = os.path.getsize(filepath)
        if size < MIN_SIZE:
            return {"name": name, "path": f"{directory}/{name}" if directory else name, "status": "invalid", "reason": f"File too small ({size} bytes)"}
        try:
            with open(filepath, "rb") as f:
                header = f.read(32)
            for header_sig, expected in VALID_HEADERS.items():
                if header[:len(expected)] == expected:
                    return {"name": name, "path": f"{directory}/{name}" if directory else name, "status": "valid", "size": size}
            return {"name": name, "path": f"{directory}/{name}" if directory else name, "status": "invalid", "reason": "Unknown file format"}
        except Exception as e:
            return {"name": name, "path": f"{directory}/{name}" if directory else name, "status": "invalid", "reason": str(e)}

    def validate_directory(dir_path: str) -> Dict[str, Any]:
        result = {"valid": [], "invalid": [], "partial": []}
        try:
            full_dir = get_safe_path("/mnt/data", dir_path)
        except Exception:
            return result
        if not os.path.exists(full_dir):
            return result
        names = []
        for f in os.listdir(full_dir):
            if f.endswith(('.json', '.preview.png', '.sha256')):
                continue
            names.append(f)
        for name in names:
            info = validate_single_file_in_dir(dir_path, name)
            if info is None:
                continue
            if info["status"] == "valid":
                result["valid"].append(info)
            elif info["status"] == "invalid":
                if "too small" in info.get("reason", "").lower():
                    result["partial"].append(info)
                else:
                    result["invalid"].append(info)
                    if delete_invalid:
                        try:
                            os.remove(os.path.join(full_dir, name))
                        except Exception:
                            pass
        return result

    for directory in directories:
        dir_result = validate_directory(directory)
        valid_count = len(dir_result["valid"])
        invalid_count = len(dir_result["invalid"])
        partial_count = len(dir_result["partial"])
        validation_results["total_valid"] += valid_count
        validation_results["total_invalid"] += invalid_count
        validation_results["total_partial"] += partial_count
        validation_results["by_directory"][directory] = {
            "valid": dir_result["valid"],
            "invalid": dir_result["invalid"],
            "partial": dir_result["partial"],
        }

    return validation_results


class FileStorage:
    """
    File storage operations for Modal volume (LLM worker).
    """

    @modal.method()
    def read_file(self, path: str) -> bytes:
        vol.reload()
        full_path = get_safe_path("/mnt/data", path)
        logger.info(f"[FileStorage] Reading file: {full_path}")

        if not os.path.exists(full_path):
            raise FileNotFoundError(f"File not found: {path}")

        with open(full_path, "rb") as f:
            return f.read()

    @modal.method()
    async def delete_file(self, path: str) -> bool:
        vol.reload()
        full_path = get_safe_path("/mnt/data", path)
        logger.info(f"[FileStorage] Deleting file: {full_path}")

        if not os.path.exists(full_path) and not os.path.exists(full_path + ".downloading"):
            return False

        try:
            if os.path.exists(full_path):
                if os.path.isdir(full_path):
                    import shutil
                    await asyncio.to_thread(shutil.rmtree, full_path)
                else:
                    await asyncio.to_thread(os.remove, full_path)

            if os.path.exists(full_path + ".downloading"):
                await asyncio.to_thread(os.remove, full_path + ".downloading")

            if not path.endswith((".json", ".preview.png", ".sha256")):
                base_path, _ = os.path.splitext(full_path)
                side_files = [
                    base_path + ".json",
                    base_path + ".preview.png",
                    full_path + ".sha256",
                ]
                for side_file in side_files:
                    if os.path.exists(side_file):
                        await asyncio.to_thread(os.remove, side_file)

            await asyncio.to_thread(vol.commit)
            return True
        except Exception as e:
            logger.info(f"[FileStorage] Error deleting file: {e}")
            return False

    @modal.method()
    def list_directory(self, directory: str) -> list[dict]:
        vol.reload()
        full_path = get_safe_path("/mnt/data", directory)
        logger.info(f"[FileStorage] Listing directory: {full_path}")

        if not os.path.exists(full_path):
            return []

        files = []
        for root, dirs, filenames in os.walk(full_path):
            for filename in filenames:
                if filename.endswith(".sha256") or filename.endswith(".json") or filename.endswith(".preview.png"):
                    continue
                filepath = os.path.join(root, filename)
                rel_path = os.path.relpath(filepath, "/mnt/data")
                files.append(rel_path)

        return files

    @modal.method()
    def file_exists(self, path: str) -> bool:
        vol.reload()
        full_path = get_safe_path("/mnt/data", path)
        return os.path.exists(full_path)

    @modal.method()
    def get_file_size(self, path: str) -> int:
        vol.reload()
        full_path = get_safe_path("/mnt/data", path)
        if os.path.exists(full_path):
            return os.path.getsize(full_path)
        return 0

    @modal.method()
    def put_file(self, path: str, content: bytes) -> bool:
        from pathlib import Path

        full_path = Path(get_safe_path("/mnt/data", path))
        full_path.parent.mkdir(parents=True, exist_ok=True)

        with open(full_path, "wb") as f:
            f.write(content)

        vol.commit()
        logger.info(f"[FileStorage] Saved {len(content)} bytes to {full_path}")
        return True


@app.function(
    image=image,
    volumes={"/mnt/data": vol},
    timeout=600,
    scaledown_window=5,
    max_containers=1,
)
@modal.concurrent(max_inputs=10, target_inputs=5)
def setup_models():
    vol.reload()
    for d in ["/mnt/data/models", "/mnt/data/downloads", "/mnt/data/output"]:
        os.makedirs(d, exist_ok=True)
        logger.debug(f"[Setup] Ensured directory: {d}")

    logger.info("Setup complete. Volume ready.")
    return {"status": "success", "message": "Setup complete"}
