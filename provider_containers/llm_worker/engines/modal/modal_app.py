import modal
import os
import json
import logging
import time
import asyncio
from typing import List, Dict, Any, Optional

from provider_core.utils import get_safe_path, is_model_file, is_transient_artifact
from provider_core.model_scan import scan_model_directory
from provider_core.downloads import (
    download_model_to_path,
    pending_download_paths,
    pipeline_artifacts,
)
from provider_core.validation import (
    validate_downloaded_file,
)

logging.basicConfig(
    level=logging.INFO,
    format='%(levelname)s %(name)s: %(message)s'
)
logger = logging.getLogger("modal_app_vllm")



def safe_vol_reload():
    try:
        vol.reload()
    except Exception as e:
        logger.warning(f"vol.reload failed: {e}")

async def safe_vol_reload_aio():
    try:
        await vol.reload.aio()
    except Exception as e:
        logger.warning(f"vol.reload.aio failed: {e}")

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


async def list_models_with_metadata_internal(base_path: str, directory: str) -> list[Dict[str, Any]]:
    import aiofiles
    # `get_safe_path` raises on an empty path and the router defaults
    # `directory=""`, so a bodyless `GET /list-models` raised and a bare
    # `except: return []` turned that into "no models". `models_utils.py`
    # already handles it; the copies had drifted.
    try:
        target_dir = get_safe_path(base_path, directory) if directory else base_path
    except Exception:
        return []
    if not os.path.exists(target_dir):
        return []

    def _scan():
        # Raises on a failed scandir or stat. This was `except: pass`, which made
        # "the volume could not be read" indistinguishable from "no models here",
        # and reconciliation then re-downloaded the directory. `is_model_file` is
        # the shared predicate — see the note at its former call site — applied by
        # `provider_core/model_scan.py`, so the image twin and this one cannot
        # drift on which suffixes count as models.
        return scan_model_directory(target_dir)

    entries, entry_set = await asyncio.to_thread(_scan)

    async def _proc(name: str, size: int):
        fpath = f"{directory}/{name}" if directory else name
        # `sha256` is a declared field of every listing entry and stays None; see
        # the image twin for why the `compute_hashes` flag is gone rather than
        # accepted and ignored.
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
        sampling: Optional[Dict[str, Any]] = None,
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

        # Engine defaults; caller-provided sampling overrides win when present.
        # Keys arrive as max_output_tokens (contract name) and map to vLLM's
        # max_tokens; penalties pass straight through.
        params = {
            "temperature": 0.8,
            "top_p": 0.95,
            "max_tokens": 1024,
        }
        if sampling:
            key_map = {"max_output_tokens": "max_tokens"}
            for key, value in sampling.items():
                if value is not None:
                    params[key_map.get(key, key)] = value
        sampling_params = SamplingParams(**params)

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
                yield {
                    "event": "delta",
                    "text": delta,
                }

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
                yield {
                    "event": "completed",
                    "outputs": [output_dict]
                }
                return

        output_dict = {"role": "assistant", "content": full_text}
        if tool_calls:
            output_dict["tool_calls"] = tool_calls
        yield {
            "event": "completed",
            "outputs": [output_dict]
        }


@app.function(
    image=image,
    volumes={"/mnt/data": vol},
    timeout=DOWNLOAD_TIMEOUT,
    max_containers=DOWNLOAD_MAX_CONTAINERS,
)
@modal.concurrent(max_inputs=1, target_inputs=1)
def download_model(url: str, path: str, token: str = None, preview_url: str = None, metadata: dict = None):
    """Download model with shared validation pipeline and progress tracking."""
    safe_vol_reload()
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
            # The same value as the function timeout above, used as the HTTP
            # read timeout. `requests.get` with no timeout blocks forever on a
            # peer that accepts the connection and then stops sending.
            request_timeout_seconds=DOWNLOAD_TIMEOUT,
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
        await safe_vol_reload_aio()
    except Exception:
        safe_vol_reload()
    return await list_models_with_metadata_internal("/mnt/data", directory)


@app.function(
    image=image,
    volumes={"/mnt/data": vol},
    timeout=VALIDATE_TIMEOUT,
    max_containers=VALIDATE_MAX_CONTAINERS,
)
@modal.concurrent(max_inputs=10, target_inputs=5)
async def validate_models(directories: list[str], delete_invalid: bool = False):
    try:
        await safe_vol_reload_aio()
    except Exception:
        safe_vol_reload()

    if isinstance(directories, str):
        directories = [directories]

    validation_results = {
        "total_valid": 0,
        "total_invalid": 0,
        "total_partial": 0,
        # Present-and-zero, not absent-until-needed: the image twin and the remote
        # agent both report it, and a key that only exists once something failed
        # makes "no key" indistinguishable from "this engine does not report it".
        "total_indeterminate": 0,
        "by_directory": {}
    }

    def validate_single_file_in_dir(directory: str, name: str) -> Optional[Dict[str, Any]]:
        """Classify one file via the shared validator.

        This used to be a third hand-rolled copy of the magic-byte check, and it
        unpacked `VALID_FILE_HEADERS` backwards: the table maps magic *bytes* to
        a format *name*, so `for header_sig, expected in ...` bound `expected` to
        a str and compared a bytes slice against it. `bytes != str` in Python 3,
        so the branch never matched, every file over `MIN_MODEL_SIZE` was
        reported "Unknown file format", and `validate_directory` deleted it —
        and reconciliation calls this with `delete_invalid=True` on every tick.

        `provider_core/validation.py` owns this rule and the image engine's twin
        already calls it. See `tests/test_llm_modal_validate.py`.
        """
        full_dir = get_safe_path("/mnt/data", directory) if directory else "/mnt/data"
        filepath = os.path.join(full_dir, name)
        # `isfile`, not `exists`. `exists` is true for a DIRECTORY, and
        # `LLMModal.setup_models` creates `/mnt/data/models` with subdirectories
        # that `list_directory` walks one level at a time — so every directory
        # under the model tree was classified "invalid" on every tick, counted in
        # `total_invalid`, reported to the backend, and then handed to
        # `os.remove`, which raised IsADirectoryError into a bare `except: pass`.
        # The image twin at `image_worker/engines/modal/modal_app.py:1093` has
        # always checked `isfile` first.
        if not os.path.isfile(filepath):
            return None
        label = f"{directory}/{name}" if directory else name
        try:
            validation = validate_downloaded_file(
                filepath, unknown_header_log_prefix="llm_modal/validate_models"
            )
        except Exception as e:
            # A validator that itself raised tells us nothing about the file.
            # Reporting "invalid" here let the caller's `delete_invalid` remove a
            # model on an infrastructure error.
            return {
                "name": name,
                "path": label,
                "status": "indeterminate",
                "reason": str(e),
            }
        try:
            size = os.path.getsize(filepath)
        except OSError as e:
            return {
                "name": name,
                "path": label,
                "status": "indeterminate",
                "reason": f"Could not stat file: {e}",
            }
        if validation["valid"]:
            return {"name": name, "path": label, "status": "valid", "size": size}
        return {
            "name": name,
            "path": label,
            "status": "invalid",
            "size": size,
            "reason": validation.get("error", "Invalid file"),
            # Carried through so the caller can refuse to delete on a failed
            # read. See `provider_core/validation.py`.
            "indeterminate": bool(validation.get("indeterminate")),
        }

    def validate_directory(dir_path: str) -> Dict[str, Any]:
        result = {"valid": [], "invalid": [], "partial": []}
        try:
            full_dir = get_safe_path("/mnt/data", dir_path)
        except Exception:
            return result
        if not os.path.exists(full_dir):
            return result
        # Classify transient artifacts *before* the is_model_file filter, which
        # excludes `.lock` and `.downloading` by name and returned first. That
        # ordering is why `total_partial` was permanently 0 for this engine, so
        # step 0 of reconciliation — the only step that reads it — could never
        # see a partial download.
        #
        # Reported, never deleted. Reconciliation runs with delete_invalid=True,
        # and unlinking an in-flight temp leaves its writer holding a live
        # descriptor: it finishes the transfer and then fails at os.replace,
        # which reconciliation reports as a failed download. Unlinking a `.lock`
        # is worse — it removes the flock a concurrent downloader holds, so a
        # second downloader takes a *different* lock and the interleaving
        # corruption the lock exists to prevent happens again. provider_core/
        # utils.py records that having happened. Abandoned partials are reclaimed
        # by FileStorage.delete_file via pending_download_paths, which is the
        # only place that can tell an in-flight attempt from a dead one.
        #
        # `os.listdir` is guarded because the loop over it had none: one EIO on
        # the directory raised out of `validate_directory`, out of the
        # 16-directory loop below, out of `validate_models`, and became a Modal
        # 500 — which `llm_worker/engines/modal/client.py::validate_models` turns
        # into `failed(...)`, and reconciliation's `except Exception` logs as
        # "⚠ Validation step failed". Step 0 then ran against nothing at all, so
        # the 15 healthy directories in the same sweep were never counted. The
        # failure is reported per directory instead, which is what
        # `remote_agent/server.py::validate_models` has always done with
        # `return_exceptions=True`.
        try:
            names = os.listdir(full_dir)
        except OSError as exc:
            return {"error": f"Could not list directory: {exc}"}

        for name in names:
            full_path = os.path.join(full_dir, name)
            if is_transient_artifact(name):
                if os.path.isfile(full_path):
                    label = f"{dir_path}/{name}" if dir_path else name
                    try:
                        size = os.path.getsize(full_path)
                    except OSError as exc:
                        # Was unguarded, and reproduced: an ENOSPC on a volume with
                        # no space for the next attempt's temp file raised
                        # `OSError: [Errno 28] No space left on device` out of the
                        # whole 16-directory sweep, so step 0 produced no counts
                        # for any of them. A stat that failed says nothing about the
                        # artifact, and it is never deleted here in any case — so it
                        # is reported, in the bucket whose whole purpose is "we
                        # could not determine this", and the sweep continues.
                        result.setdefault("indeterminate", []).append({
                            "name": name,
                            "path": label,
                            "size": None,
                            "reason": f"Could not stat file: {exc}",
                            "indeterminate": True,
                        })
                        continue
                    result["partial"].append({
                        "name": name,
                        "path": label,
                        "size": size,
                        "reason": "Incomplete download (temp file)",
                    })
                continue
            if not is_model_file(name):
                continue
            info = validate_single_file_in_dir(dir_path, name)
            if info is None:
                continue
            if info["status"] == "valid":
                result["valid"].append(info)
            elif info["status"] == "indeterminate":
                # The read failed (EIO, ENOMEM, a gcsfuse stall). That is not a
                # verdict on the file, and the sweep below runs unattended with
                # `delete_invalid=True` every 2h, so treating it as invalid meant
                # one transient read error destroyed a healthy multi-GB model.
                # Reported, kept, and re-read on the next tick.
                result.setdefault("indeterminate", []).append(info)
            elif info["status"] == "invalid":
                # A file under the size floor is a truncated transfer, not a
                # corrupt model. It is classified and reported, and left on
                # disk: deciding it is abandoned is pending_download_paths' job.
                if "too small" in info.get("reason", "").lower():
                    result["partial"].append(info)
                elif info.get("indeterminate"):
                    # A content check that could not complete. Same reasoning as
                    # above: no deletion on a guess.
                    result.setdefault("indeterminate", []).append(info)
                else:
                    result["invalid"].append(info)
                    if delete_invalid:
                        try:
                            os.remove(full_path)
                        except Exception:
                            pass
        return result

    for directory in directories:
        try:
            dir_result = validate_directory(directory)
        except Exception as exc:
            # The outer guard, for anything `validate_directory` does not expect.
            # One directory raising used to discard the other 15: the counts the
            # rest of the system reads came from whichever engine answered, and
            # this one answered "nothing to report". Recorded against its own
            # directory so the rest of the answer survives.
            validation_results["by_directory"][directory] = {
                "error": f"{type(exc).__name__}: {exc}"
            }
            continue
        if "error" in dir_result:
            # A directory that could not be read. Same treatment as a raise, and
            # deliberately NOT folded into the four counts: `total_indeterminate`
            # means "a file was seen and could not be judged", which is a
            # different statement from "this directory was never opened".
            validation_results["by_directory"][directory] = dict(dir_result)
            continue
        valid_count = len(dir_result["valid"])
        invalid_count = len(dir_result["invalid"])
        partial_count = len(dir_result["partial"])
        indeterminate_count = len(dir_result.get("indeterminate", []))
        validation_results["total_valid"] += valid_count
        validation_results["total_invalid"] += invalid_count
        validation_results["total_partial"] += partial_count
        validation_results["total_indeterminate"] += indeterminate_count
        validation_results["by_directory"][directory] = {
            "valid": dir_result["valid"],
            "invalid": dir_result["invalid"],
            "partial": dir_result["partial"],
            "indeterminate": dir_result.get("indeterminate", []),
        }

    return validation_results


@app.cls(
    image=image,
    volumes={"/mnt/data": vol},
    timeout=300,
    max_containers=1,
    scaledown_window=5
)
class FileStorage:
    """
    File storage operations for Modal volume (LLM worker).

    The `@app.cls` decorator is load-bearing, not decoration: the client resolves
    this class by name with `modal.Cls.from_name(MODAL_APP_NAME, "FileStorage")`
    (llm_worker/engines/modal/client.py:39-42). A bare Python class is never
    registered with the app, so `Cls.from_name` raised on every call and every
    file operation on this provider 500'd — get_file, delete_file, delete_model,
    upload_file and get_storage_stats all go through here. The image twin had the
    decorator the whole time; the fix simply was not ported.
    """

    @modal.method()
    def read_file(self, path: str) -> bytes:
        """Read file contents from the volume.

        Kept for small files. `read_file_range` exists because a modal method
        serialises its return value across the RPC boundary, so a 7 GB GGUF is
        7 GB in the container and 7 GB in the caller before anyone can do
        anything with it. Callers should prefer the ranged pair.
        """
        safe_vol_reload()
        full_path = get_safe_path("/mnt/data", path)
        logger.info(f"[FileStorage] Reading file: {full_path}")

        if not os.path.exists(full_path):
            raise FileNotFoundError(f"File not found: {path}")

        with open(full_path, "rb") as f:
            return f.read()

    @modal.method()
    def file_size(self, path: str) -> int:
        """Size of a file in the volume, in bytes. Raises FileNotFoundError."""
        safe_vol_reload()
        full_path = get_safe_path("/mnt/data", path)
        if not os.path.exists(full_path):
            raise FileNotFoundError(f"File not found: {path}")
        return os.path.getsize(full_path)

    @modal.method()
    def read_file_range(self, path: str, offset: int, length: int) -> bytes:
        """Read at most `length` bytes starting at `offset`.

        A short read at the end of the file returns whatever is there, so callers
        treat an empty result as end-of-file. `offset` is validated rather than
        trusted: a negative offset would be interpreted as an absolute seek.
        """
        if offset < 0 or length < 0:
            raise ValueError("offset and length must be non-negative")
        if length == 0:
            return b""

        safe_vol_reload()
        full_path = get_safe_path("/mnt/data", path)
        if not os.path.exists(full_path):
            raise FileNotFoundError(f"File not found: {path}")

        with open(full_path, "rb") as f:
            f.seek(offset)
            return f.read(length)

    @modal.method()
    async def delete_file(self, path: str) -> bool:
        safe_vol_reload()
        full_path = get_safe_path("/mnt/data", path)
        logger.info(f"[FileStorage] Deleting file: {full_path}")

        if not os.path.exists(full_path) and not list(pending_download_paths(full_path)):
            return False

        try:
            if os.path.exists(full_path):
                if os.path.isdir(full_path):
                    import shutil
                    await asyncio.to_thread(shutil.rmtree, full_path)
                else:
                    await asyncio.to_thread(os.remove, full_path)

            # pending_download_paths, not a fixed `.downloading` probe: the
            # per-attempt temp is `<path>.<pid>.<hex>.downloading` and a parked
            # resume slot is `<path>.resume.<identity>.downloading`, so the old
            # probe matched nothing and a crash-interrupted download survived
            # delete-model forever. image_worker/engines/modal/modal_app.py had
            # the sweep; this twin did not.
            for stale in pipeline_artifacts(full_path):
                await asyncio.to_thread(os.remove, stale)

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
        safe_vol_reload()
        full_path = get_safe_path("/mnt/data", directory)
        logger.info(f"[FileStorage] Listing directory: {full_path}")

        if not os.path.exists(full_path):
            return []

        files = []
        for root, dirs, filenames in os.walk(full_path):
            for filename in filenames:
                if not is_model_file(filename):
                    continue
                filepath = os.path.join(root, filename)
                rel_path = os.path.relpath(filepath, "/mnt/data")
                files.append(rel_path)

        return files

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
    safe_vol_reload()
    for d in ["/mnt/data/models", "/mnt/data/downloads", "/mnt/data/output"]:
        os.makedirs(d, exist_ok=True)
        logger.debug(f"[Setup] Ensured directory: {d}")

    logger.info("Setup complete. Volume ready.")
    return {"status": "success", "message": "Setup complete"}
