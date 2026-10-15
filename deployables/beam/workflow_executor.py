"""Shared ComfyUI workflow execution helpers for the Beam deployable.

The inlined twin of this file lives at the top of
`deployables/modal/image/modal_app.py`; the two must stay in step, as they did
when they were `image_worker/comfy/workflow_executor.py` and the inlined copy.
"""

import asyncio
import json
import logging
import os
import httpx
import base64
import uuid
import urllib.parse
from typing import Any, AsyncGenerator, Dict, List, Optional

# `provider_worker_core`, not `provider_core`: get_http_client moved there in
# acc86aa3 (see deployables/provider_worker_core/__init__.py). Both packages are
# resolved by the sys.path bootstrap in the file that imports this one.
from provider_worker_core.http_client import get_http_client
from provider_core.utils import get_safe_path


IMAGE_FETCH_FILESYSTEM = "filesystem"
IMAGE_FETCH_VIEW_API = "view_api"


def _get_websockets_module():
    import websockets

    return websockets


def _log(logger: logging.Logger | None, level: int, message: str) -> None:
    if logger is not None:
        logger.log(level, message)


def _normalize_server_url(server_address: str) -> str:
    """Ensure a ComfyUI server address carries an explicit scheme."""
    if not server_address.startswith("http://") and not server_address.startswith("https://"):
        server_address = f"http://{server_address}"
    return server_address


def _comfy_auth_headers() -> dict[str, str]:
    api_key = os.getenv("COMFYUI_API_KEY", "").strip()
    return {"Authorization": f"Bearer {api_key}"} if api_key else {}


async def _connect_with_retry(
    ws_url: str,
    *,
    max_retries: int,
    initial_retry_delay_seconds: float,
    logger: logging.Logger | None,
):
    websockets = _get_websockets_module()
    retry_delay = initial_retry_delay_seconds

    for attempt in range(max_retries):
        try:
            auth_headers = _comfy_auth_headers()
            if not auth_headers:
                return await websockets.connect(ws_url), websockets
            try:
                return await websockets.connect(
                    ws_url,
                    additional_headers=auth_headers,
                ), websockets
            except TypeError:
                return await websockets.connect(
                    ws_url,
                    extra_headers=auth_headers,
                ), websockets
        except Exception as error:  # pragma: no cover - provider runtime dependent
            if attempt >= max_retries - 1:
                raise
            _log(
                logger,
                logging.WARNING,
                f"Workflow websocket connect failed (attempt {attempt + 1}/{max_retries}): {error}",
            )
            await asyncio.sleep(retry_delay)
            retry_delay *= 2

    raise RuntimeError("Workflow websocket connection retries exhausted")


async def _queue_prompt(
    server_address: str,
    workflow_json: Dict[str, Any],
    client_id: str,
) -> tuple[str | None, Dict[str, Any] | None]:
    if not server_address.startswith("http://") and not server_address.startswith("https://"):
        server_address = f"http://{server_address}"
    endpoint = f"{server_address}/prompt"
    payload = {"prompt": workflow_json, "client_id": client_id}

    try:
        client = get_http_client()
        response = await client.post(
            endpoint,
            json=payload,
            headers=_comfy_auth_headers(),
            timeout=10.0,
        )
        response.raise_for_status()
        response_data = response.json()
    except httpx.HTTPStatusError as error:
        body = error.response.text
        message = body or str(error)
        return None, {"status": "error", "message": f"ComfyUI rejected workflow: {message}"}
    except Exception as error:
        return None, {"status": "error", "message": f"ComfyUI rejected workflow: {error}"}

    prompt_id = response_data.get("prompt_id")
    if not prompt_id:
        return None, {"status": "error", "message": "ComfyUI did not return a prompt_id"}

    if "error" in response_data:
        return None, {"status": "error", "message": response_data["error"]}

    node_errors = response_data.get("node_errors")
    if node_errors:
        return None, {"status": "error", "message": str(node_errors)}

    return prompt_id, None


async def _get_history(server_address: str, prompt_id: str) -> tuple[Dict[str, Any] | None, str | None]:
    if not server_address.startswith("http://") and not server_address.startswith("https://"):
        server_address = f"http://{server_address}"
    endpoint = f"{server_address}/history/{prompt_id}"
    try:
        client = get_http_client()
        response = await client.get(
            endpoint,
            headers=_comfy_auth_headers(),
            timeout=10.0,
        )
        response.raise_for_status()
        history = response.json()
    except Exception as error:
        return None, f"Failed to fetch history: {error}"

    if prompt_id not in history:
        return None, "Prompt not found in history"

    return history[prompt_id], None


def _collect_images_from_filesystem(
    history_data: Dict[str, Any],
    *,
    output_dir: str,
    temp_dir: str,
    logger: logging.Logger | None,
) -> List[Dict[str, Any]]:
    images_output: List[Dict[str, Any]] = []

    for node_output in history_data.get("outputs", {}).values():
        for image in node_output.get("images", []):
            filename = image.get("filename")
            if not filename:
                continue

            subfolder = image.get("subfolder") or ""
            folder_type = image.get("type", "output")
            base_dir = output_dir if folder_type == "output" else temp_dir
            
            try:
                if subfolder:
                    filepath = get_safe_path(base_dir, os.path.join(subfolder, filename))
                else:
                    filepath = get_safe_path(base_dir, filename)
            except ValueError as error:
                _log(logger, logging.ERROR, f"Invalid path for output image {filename}: {error}")
                continue

            try:
                with open(filepath, "rb") as file_obj:
                    data = file_obj.read()
                    b64_data = base64.b64encode(data).decode('utf-8')
                    images_output.append(
                        {
                            "filename": filename,
                            "data": b64_data,
                            "_base64_encoded": True,
                            "type": folder_type,
                            "subfolder": subfolder,
                        }
                    )
            except Exception as error:
                _log(logger, logging.ERROR, f"Failed to read output image {filepath}: {error}")

    return images_output


async def _collect_images_via_view_api(
    history_data: Dict[str, Any],
    *,
    server_address: str,
    view_timeout_seconds: float,
    logger: logging.Logger | None,
) -> List[Dict[str, Any]]:
    if not server_address.startswith("http://") and not server_address.startswith("https://"):
        server_address = f"http://{server_address}"
    client = get_http_client()

    # Collect the descriptors first, then fetch them concurrently.
    #
    # This was `await client.get(url)` per image inside the loop, so an SDXL batch
    # of 4 was 4 sequential round trips against a shared 10-connection pool — the
    # pool had the headroom and the loop did not use it. Each fetch is independent
    # and its failure is already isolated (logged, image skipped), so `gather` with
    # per-future handling preserves both properties. Order is preserved because the
    # results are gathered into a list positionally, which is what the downstream
    # artifact order and the existing tests depend on.
    requested: List[Dict[str, Any]] = []
    for node_output in history_data.get("outputs", {}).values():
        for image in node_output.get("images", []):
            filename = image.get("filename")
            if not filename:
                continue
            subfolder = image.get("subfolder") or ""
            requested.append({
                "filename": filename,
                "subfolder": subfolder,
                "type": image.get("type", "output"),
            })

    if not requested:
        return []

    async def _fetch(descriptor: Dict[str, Any]) -> Optional[Dict[str, Any]]:
        filename = descriptor["filename"]
        subfolder = descriptor["subfolder"]
        folder_type = descriptor["type"]
        url = f"{server_address}/view?filename={urllib.parse.quote(filename)}&subfolder={urllib.parse.quote(subfolder)}&type={urllib.parse.quote(folder_type)}"
        try:
            response = await client.get(
                url,
                headers=_comfy_auth_headers(),
                timeout=view_timeout_seconds,
            )
            response.raise_for_status()
            data = response.content
            b64_data = base64.b64encode(data).decode('utf-8')
            return {
                "filename": filename,
                "data": b64_data,
                "_base64_encoded": True,
                "type": folder_type,
                "subfolder": subfolder,
            }
        except Exception as error:
            _log(logger, logging.ERROR, f"Failed to fetch image via /view ({filename}): {error}")
            return None

    fetched = await asyncio.gather(*[_fetch(descriptor) for descriptor in requested])
    return [entry for entry in fetched if entry is not None]


async def execute_comfy_workflow(
    workflow_json: Dict[str, Any],
    port: int = 8188,
    *,
    comfy_api_url: str | None = None,
    image_fetch_mode: str = IMAGE_FETCH_FILESYSTEM,
    output_dir: str = "/root/comfy/ComfyUI/output",
    temp_dir: str = "/root/comfy/ComfyUI/temp",
    history_delay_seconds: float = 0.0,
    view_timeout_seconds: float = 30.0,
    stall_timeout_seconds: float = 300.0,
    max_retries: int = 5,
    initial_retry_delay_seconds: float = 1.0,
    logger: logging.Logger | None = None,
) -> AsyncGenerator[Dict[str, Any], None]:
    """Execute a ComfyUI workflow and yield provider stream updates."""
    if image_fetch_mode not in {IMAGE_FETCH_FILESYSTEM, IMAGE_FETCH_VIEW_API}:
        raise ValueError(f"Unsupported image fetch mode: {image_fetch_mode}")

    client_id = str(uuid.uuid4())
    if comfy_api_url:
        import urllib.parse
        parsed = urllib.parse.urlparse(comfy_api_url)
        # Handle ws:// vs wss:// based on http:// vs https://
        ws_scheme = "wss" if parsed.scheme == "https" else "ws"
        ws_url = f"{ws_scheme}://{parsed.netloc}/ws?clientId={client_id}"
        # For HTTP endpoints (like /prompt or /history), _queue_prompt and _get_history
        # currently take server_address as host:port and prepend http://.
        # Let's pass the full base URL string if they support it, or modify them to support it.
        # Actually, let's just make server_address the full base url and change how _queue_prompt uses it.
        server_address = comfy_api_url
    else:
        server_address = f"http://127.0.0.1:{port}"
        ws_url = f"ws://127.0.0.1:{port}/ws?clientId={client_id}"

    _log(logger, logging.INFO, f"Connecting to ComfyUI websocket: {ws_url}")
    websocket, websockets = await _connect_with_retry(
        ws_url,
        max_retries=max_retries,
        initial_retry_delay_seconds=initial_retry_delay_seconds,
        logger=logger,
    )

    prompt_id: str | None = None
    try:
        prompt_id, queue_error = await _queue_prompt(server_address, workflow_json, client_id)
        if queue_error:
            yield queue_error
            return

        yield {"status": "queued", "prompt_id": prompt_id}

        effective_stall_timeout_seconds = max(float(stall_timeout_seconds), 1.0)
        last_prompt_node: str | None = None

        while True:
            try:
                message = await asyncio.wait_for(
                    websocket.recv(),
                    timeout=effective_stall_timeout_seconds,
                )
            except asyncio.TimeoutError:
                # ComfyUI occasionally deadlocks mid-run on long-lived containers.
                # Probe history once before failing the request as stalled.
                history_probe, _history_probe_error = await _get_history(server_address, prompt_id)
                if history_probe is not None:
                    _log(
                        logger,
                        logging.WARNING,
                        (
                            "Workflow websocket stalled but history is available; "
                            "continuing with collected outputs"
                        ),
                    )
                    break

                stalled_message = (
                    f"Workflow stalled after {int(effective_stall_timeout_seconds)}s "
                    f"without websocket updates"
                )
                if last_prompt_node:
                    stalled_message += f" (last node: {last_prompt_node})"

                _log(logger, logging.ERROR, stalled_message)
                yield {
                    "status": "error",
                    "message": stalled_message,
                    "code": 408,
                    "retryable": True,
                    "details": {
                        "reason": "workflow_stalled",
                        "prompt_id": prompt_id,
                        "last_node": last_prompt_node,
                        "stall_timeout_seconds": int(effective_stall_timeout_seconds),
                    },
                }
                return
            except websockets.exceptions.ConnectionClosed as error:
                _log(logger, logging.ERROR, f"Workflow websocket closed unexpectedly: {error}")
                try:
                    client = get_http_client()
                    await client.post(
                        f"{_normalize_server_url(server_address)}/interrupt",
                        headers=_comfy_auth_headers(),
                        timeout=5.0,
                    )
                except Exception as e:
                    _log(logger, logging.ERROR, f"Failed to send interrupt after connection closed: {e}")

                yield {
                    "status": "error",
                    "message": f"WebSocket connection closed: {error}",
                    "code": 1006,
                    "retryable": True,
                    "details": {
                        "reason": "websocket_closed",
                        "prompt_id": prompt_id,
                    },
                }
                return
            except Exception as error:
                _log(logger, logging.ERROR, f"Workflow websocket error: {error}")
                yield {
                    "status": "error",
                    "message": f"WebSocket error: {error}",
                    "code": 500,
                    "retryable": False,
                    "details": {
                        "reason": "websocket_error",
                        "prompt_id": prompt_id,
                    },
                }
                return

            if not isinstance(message, str):
                continue

            try:
                payload = json.loads(message)
            except json.JSONDecodeError:
                _log(logger, logging.WARNING, "Ignoring non-JSON websocket payload")
                continue

            msg_type = payload.get("type")
            msg_data = payload.get("data", {})
            msg_prompt_id = msg_data.get("prompt_id")

            if msg_type == "executing":
                node = msg_data.get("node")
                if node is None and msg_prompt_id == prompt_id:
                    break
                if msg_prompt_id == prompt_id:
                    last_prompt_node = str(node) if node is not None else None
                    yield {"status": "executing", "node": node, "prompt_id": prompt_id}
            elif msg_type == "execution_cached":
                if msg_prompt_id == prompt_id:
                    yield {
                        "status": "execution_cached",
                        "nodes": msg_data.get("nodes", []),
                        "prompt_id": prompt_id,
                    }
            elif msg_type == "progress":
                if msg_prompt_id is None or msg_prompt_id == prompt_id:
                    yield {
                        "status": "progress",
                        "value": msg_data.get("value", 0),
                        "max": msg_data.get("max", 0),
                        "prompt_id": prompt_id,
                    }
            elif msg_type == "execution_error":
                yield {"status": "error", "message": str(msg_data)}
                return
    except asyncio.CancelledError:
        _log(logger, logging.INFO, "Workflow execution cancelled. Interrupting ComfyUI.")
        try:
            client = get_http_client()
            await client.post(
                f"{_normalize_server_url(server_address)}/interrupt",
                headers=_comfy_auth_headers(),
                timeout=5.0,
            )
        except Exception as e:
            _log(logger, logging.ERROR, f"Failed to send interrupt: {e}")
        raise
    finally:
        await websocket.close()

    if not prompt_id:
        yield {"status": "error", "message": "Missing prompt_id"}
        return

    if history_delay_seconds > 0:
        await asyncio.sleep(history_delay_seconds)

    history_data, history_error = await _get_history(server_address, prompt_id)
    if history_error:
        yield {"status": "error", "message": history_error}
        return

    if image_fetch_mode == IMAGE_FETCH_VIEW_API:
        images_output = await _collect_images_via_view_api(
            history_data,
            server_address=server_address,
            view_timeout_seconds=view_timeout_seconds,
            logger=logger,
        )
    else:
        images_output = _collect_images_from_filesystem(
            history_data,
            output_dir=output_dir,
            temp_dir=temp_dir,
            logger=logger,
        )

    yield {"status": "success", "images": images_output}
