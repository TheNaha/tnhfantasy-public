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


async def call_provider(
    worker_url: str,
    workflow: dict,
    job_id: str,
    job_service,
    total_nodes: int,
    timeout: float,
    use_snapshot: bool = False,
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

                    async for chunk in response.aiter_bytes():
                        buffer += chunk.decode("utf-8")

                        while "\n" in buffer:
                            line, buffer = buffer.split("\n", 1)
                            if not line.strip():
                                continue

                            try:
                                update = json.loads(line)
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
                                    final_result = update
                                elif status == "error":
                                    error_message = extract_worker_error_message(update)
                                    raise ProviderCallError(
                                        error_message,
                                        provider_id="",
                                        is_retryable=bool(update.get("retryable", False)),
                                    )
                            except json.JSONDecodeError as error:
                                logger.warning(
                                    "job_parse_error",
                                    job_id=job_id,
                                    line_length=len(line),
                                    error=str(error),
                                )

                    if final_result:
                        return final_result

                    raise ProviderCallError(
                        "No success response received from worker",
                        provider_id="",
                        is_retryable=True,
                    )

                error_text = await response.aread()
                raise ProviderCallError(
                    format_worker_http_error(response.status_code, error_text.decode()),
                    provider_id="",
                    is_retryable=response.status_code >= 500,
                )

        except httpx.TimeoutException:
            raise JobTimeoutError(f"Job timed out after {timeout}s")
        except httpx.ConnectError as error:
            raise ProviderCallError(f"Failed to connect to worker: {error}", provider_id="", is_retryable=True)
        except httpx.HTTPError as error:
            raise ProviderCallError(f"HTTP error: {error}", provider_id="", is_retryable=True)