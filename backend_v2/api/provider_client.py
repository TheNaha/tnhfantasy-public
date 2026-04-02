import json

from infrastructure.http_client import get_streaming_client
from infrastructure.logging import get_logger

logger = get_logger("provider_client")


class ProviderCallError(Exception):
    """Raised when a provider call fails and may be retried."""

    def __init__(self, message: str, provider_id: str, is_retryable: bool = True):
        super().__init__(message)
        self.provider_id = provider_id
        self.is_retryable = is_retryable


class JobTimeoutError(Exception):
    """Raised when a job exceeds its timeout."""


class JobCancelledError(Exception):
    """Raised when the worker confirms job cancellation."""

    def __init__(self, message: str, provider_id: str = ""):
        super().__init__(message)
        self.provider_id = provider_id


def extract_worker_error_message(update: dict) -> str:
    """Normalize worker error payloads from different providers."""
    detail = update.get("detail")
    if isinstance(detail, dict):
        return detail.get("message") or detail.get("error") or json.dumps(detail)

    return (
        update.get("message")
        or update.get("error")
        or detail
        or "Unknown worker error"
    )


def format_worker_http_error(status_code: int, error_text: str) -> str:
    """Produce a readable error for non-200 worker responses."""
    if not error_text:
        return f"Worker returned {status_code}"

    try:
        payload = json.loads(error_text)
    except json.JSONDecodeError:
        return f"Worker returned {status_code}: {error_text}"

    if isinstance(payload, dict):
        return f"Worker returned {status_code}: {extract_worker_error_message(payload)}"
    return f"Worker returned {status_code}: {payload}"


def validate_success_payload(update: dict) -> None:
    """Validate terminal success payloads before backend-side finalization."""
    if not isinstance(update, dict):
        raise ValueError("success payload must be an object")

    if update.get("status") != "success":
        return

    images = update.get("images")
    if images is None:
        return

    if not isinstance(images, list):
        raise ValueError("success payload images must be a list")

    for index, image in enumerate(images):
        if not isinstance(image, dict):
            raise ValueError(f"success payload images[{index}] must be an object")

        filename = image.get("filename")
        if not filename:
            raise ValueError(f"success payload images[{index}] missing filename")

        if image.get("_base64_encoded"):
            encoded_data = image.get("data")
            if not isinstance(encoded_data, str) or not encoded_data:
                raise ValueError(
                    f"success payload images[{index}] missing base64 data for encoded image"
                )


async def call_provider(
    worker_url: str,
    workflow: dict,
    job_id: str,
    job_service,
    total_nodes: int,
    timeout: float,
    use_snapshot: bool = False,
    provider_id: str = "",
) -> dict:
    """
    Call the provider worker with the workflow.
    Returns the final result on success, raises ProviderCallError on failure.
    """
    import httpx

    async with get_streaming_client(timeout=timeout) as client:
        try:
            async with client.stream(
                "POST",
                f"{worker_url}/inference",
                json={"workflow": workflow, "use_snapshot": use_snapshot, "job_id": job_id},
                timeout=timeout,
            ) as response:

                if response.status_code == 200:
                    final_result = None
                    buffer = ""
                    executed_nodes = set()

                    async def handle_update(update: dict) -> None:
                        nonlocal final_result

                        status = update.get("status")

                        if status == "progress":
                            val = update.get("value", 0)
                            max_val = update.get("max", 1)
                            percent = int((val / max_val) * 100) if max_val > 0 else 0
                            overall = int((len(executed_nodes) / total_nodes) * 100) if total_nodes > 0 else 0
                            await job_service.update_job(
                                job_id,
                                progress=percent,
                                overall_progress=overall,
                                message=f"Rendering: {percent}%",
                            )
                        elif status == "executing":
                            node_id = update.get("node")
                            if node_id:
                                executed_nodes.add(node_id)

                            overall = int((len(executed_nodes) / total_nodes) * 100) if total_nodes > 0 else 0
                            await job_service.update_job(
                                job_id,
                                overall_progress=overall,
                                message=f"Executing node {len(executed_nodes)}/{total_nodes}...",
                            )
                        elif status == "execution_cached":
                            nodes = update.get("nodes", [])
                            for node in nodes:
                                executed_nodes.add(node)

                            overall = int((len(executed_nodes) / total_nodes) * 100) if total_nodes > 0 else 0
                            await job_service.update_job(
                                job_id,
                                overall_progress=overall,
                                message=f"Restored {len(nodes)} cached nodes...",
                            )
                        elif status == "queued":
                            await job_service.update_job(job_id, message="Queued in ComfyUI...")
                        elif status == "success":
                            try:
                                validate_success_payload(update)
                            except ValueError as error:
                                raise ProviderCallError(
                                    f"Invalid success payload: {error}",
                                    provider_id=provider_id,
                                    is_retryable=False,
                                ) from error
                            final_result = update
                        elif status == "error":
                            error_message = extract_worker_error_message(update)
                            raise ProviderCallError(
                                error_message,
                                provider_id=provider_id,
                                is_retryable=bool(update.get("retryable", False)),
                            )
                        elif status == "cancelled":
                            raise JobCancelledError(
                                update.get("message") or "Job cancelled by user",
                                provider_id=provider_id,
                            )

                    async def process_line(raw_line: str, source: str) -> None:
                        line = raw_line.strip()
                        if not line:
                            return

                        try:
                            update = json.loads(line)
                        except json.JSONDecodeError as error:
                            logger.warning(
                                "job_parse_error",
                                job_id=job_id,
                                source=source,
                                line_length=len(line),
                                error=str(error),
                            )
                            return

                        await handle_update(update)

                    async for chunk in response.aiter_bytes():
                        buffer += chunk.decode("utf-8")

                        while "\n" in buffer:
                            line, buffer = buffer.split("\n", 1)
                            await process_line(line, source="stream")

                    # Some workers can end streams without a trailing newline.
                    # Parse any remaining buffered JSON so terminal payloads aren't lost.
                    if buffer.strip():
                        await process_line(buffer, source="stream_tail")

                    if final_result:
                        return final_result

                    raise ProviderCallError(
                        "No success response received from worker",
                        provider_id=provider_id,
                        is_retryable=True,
                    )

                error_text = await response.aread()
                raise ProviderCallError(
                    format_worker_http_error(response.status_code, error_text.decode()),
                    provider_id=provider_id,
                    is_retryable=response.status_code >= 500,
                )

        except httpx.TimeoutException:
            raise JobTimeoutError(f"Job timed out after {timeout}s")
        except httpx.ConnectError as error:
            raise ProviderCallError(
                f"Failed to connect to worker: {error}",
                provider_id=provider_id,
                is_retryable=True,
            )
        except httpx.HTTPError as error:
            is_retryable = not isinstance(error, httpx.LocalProtocolError)
            raise ProviderCallError(
                f"HTTP error: {error}",
                provider_id=provider_id,
                is_retryable=is_retryable,
            )