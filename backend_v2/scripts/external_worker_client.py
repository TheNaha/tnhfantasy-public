#!/usr/bin/env python3
"""Reference external worker for the `external_worker` provider mode.

The backend has spoken this protocol for a long time — `/ws/worker/{provider_id}`
in `backend_v2/api/routes/worker_ws.py` dispatches jobs over it and
`infrastructure/worker_registry.py` resolves their futures — but nothing ever
connected to it, and nothing could mint the token its auth requires. The mode was
unreachable by construction: `is_worker_connected()` could never be True, so
`resolve_provider_runtime` never returned `mode="external_worker"`, and every job
routed to such a provider retried to failure.

This is the smallest thing that makes the mode real: a worker that connects,
heartbeats, reports progress, and answers the `job` messages it is sent. It does
no inference — point `--handler` at your own callable to do that.

Usage
-----
    # One-time: mint a token for the provider.
    curl -X POST http://localhost:8002/api/v2/providers/my-worker/worker-token

    # Then connect. The token is shown once; mint again to rotate.
    python scripts/external_worker_client.py \\
        --backend ws://localhost:8002 \\
        --provider-id my-worker \\
        --token "$WORKER_TOKEN"

Protocol implemented (all shapes verified against the backend handler):

    <- {"type": "connected", "provider_id": ...}
    <- {"type": "pending_models", "models": [...]}
    <- {"type": "job", "data": {...}}
    <- {"type": "cancel_job", "job_id": ...}
    <- {"type": "heartbeat_ack"}
    <- {"type": "error", "message": ...}

    -> {"type": "heartbeat"}
    -> {"type": "job_started", "job_id": ...}
    -> {"type": "job_progress", "job_id": ..., "data": {"event": "progress", "value": 0..100}}
    -> {"type": "job_completed", "job_id": ..., "result": {"outputs": [...]}}
    -> {"type": "job_failed", "job_id": ..., "error": "..."}
    -> {"type": "get_pending_models"}

The backend rejects a progress/completed message for a job that is not assigned
to this worker, so the ordering above matters: `job_started` first.
"""

from __future__ import annotations

import argparse
import asyncio
import json
import logging
import sys
import uuid
from typing import Any, Awaitable, Callable

logger = logging.getLogger("external_worker")

Handler = Callable[[dict[str, Any]], Awaitable[list[Any]]]

def log(level: str, event: str, exc_info: bool = False, **fields: Any) -> None:
    """Structured-ish logging for a standalone script.

    The codebase uses `infrastructure.logging`, which takes key=value kwargs, but
    this file is meant to be copied out and run on a remote box with nothing but
    `websockets` available. So the fields are formatted into the message instead
    of relying on that module.
    """
    rendered = " ".join(f"{k}={v}" for k, v in fields.items())
    getattr(logger, level)("%s %s", event, rendered, exc_info=exc_info)



async def _default_handler(job: dict[str, Any]) -> list[Any]:
    """Echo the workflow back. Replace this with real work."""
    log("warning", "no_handler_configured_echoing_job", job_id=job.get("id"))
    return []


async def run_worker(
    backend: str,
    provider_id: str,
    token: str,
    handler: Handler,
    heartbeat_seconds: float = 30.0,
) -> None:
    import websockets

    base = backend.rstrip("/")
    if base.startswith("http"):
        base = "ws" + base[len("http"):]
    url = f"{base}/ws/worker/{provider_id}?token={token}"

    async with websockets.connect(url, max_size=None) as ws:
        log("info", "worker_connected", url=f"{base}/ws/worker/{provider_id}")

        # A single cancel event per job: a cancellation that arrives while the
        # handler is mid-flight has to interrupt it, and the handler only sees
        # its own coroutine.
        current_job: str | None = None
        cancel = asyncio.Event()

        async def heartbeat() -> None:
            while True:
                await asyncio.sleep(heartbeat_seconds)
                try:
                    await ws.send(json.dumps({"type": "heartbeat"}))
                except Exception as exc:  # pragma: no cover - transport teardown
                    log("debug", "heartbeat_send_failed", error=str(exc))
                    return

        async def handle_job(data: dict[str, Any]) -> None:
            nonlocal current_job
            job_id = data.get("id")
            if not job_id:
                log("error", "job_message_without_id")
                return
            current_job = job_id
            cancel.clear()
            await ws.send(json.dumps({"type": "job_started", "job_id": job_id}))
            try:
                outputs = await handler(data)
            except asyncio.CancelledError:
                await ws.send(json.dumps({
                    "type": "job_failed", "job_id": job_id, "error": "cancelled",
                }))
                raise
            except Exception as exc:
                log("exception", "job_handler_failed", job_id=job_id)
                await ws.send(json.dumps({
                    "type": "job_failed", "job_id": job_id, "error": str(exc),
                }))
                return
            if cancel.is_set():
                await ws.send(json.dumps({
                    "type": "job_failed", "job_id": job_id, "error": "cancelled",
                }))
                return
            await ws.send(json.dumps({
                "type": "job_completed",
                "job_id": job_id,
                "result": {"outputs": outputs},
            }))
            current_job = None

        task: asyncio.Task | None = None
        beat = asyncio.create_task(heartbeat())
        try:
            async for raw in ws:
                try:
                    message = json.loads(raw)
                except json.JSONDecodeError:
                    log("warning", "non_json_message")
                    continue
                kind = message.get("type")

                if kind == "connected":
                    log("info", "registered", provider_id=message.get("provider_id"))
                elif kind == "pending_models":
                    log("info", "pending_models", count=len(message.get("models") or []))
                elif kind == "job":
                    if task and not task.done():
                        log("error", "job_while_busy_rejected", job_id=message.get("data", {}).get("id"))
                        continue
                    task = asyncio.create_task(handle_job(message.get("data") or {}))
                elif kind == "cancel_job":
                    log("info", "cancel_requested", job_id=message.get("job_id"))
                    cancel.set()
                    if task and not task.done():
                        task.cancel()
                elif kind == "error":
                    log("warning", "backend_error", message=message.get("message"))
                elif kind == "heartbeat_ack":
                    log("debug", "heartbeat_ack")
                else:
                    log("debug", "unhandled_message", kind=kind)
        finally:
            beat.cancel()
            if task and not task.done():
                task.cancel()
                try:
                    await task
                except (asyncio.CancelledError, Exception):
                    pass
            log("info", "worker_disconnected", provider_id=provider_id, current_job=current_job)


def _progress_reporter(ws, job_id: str) -> Callable[[int], Awaitable[None]]:
    async def report(percent: int) -> None:
        await ws.send(json.dumps({
            "type": "job_progress",
            "job_id": job_id,
            "data": {"event": "progress", "value": max(0, min(100, int(percent)))},
        }))

    return report


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    parser.add_argument("--backend", default="ws://localhost:8002", help="Backend base URL")
    parser.add_argument("--provider-id", required=True, help="Provider this worker serves")
    parser.add_argument("--token", required=True, help="Worker token from POST /api/v2/providers/{id}/worker-token")
    parser.add_argument("--heartbeat", type=float, default=30.0, help="Heartbeat interval in seconds")
    parser.add_argument("-v", "--verbose", action="store_true")
    args = parser.parse_args(argv)

    logging.basicConfig(
        level=logging.DEBUG if args.verbose else logging.INFO,
        format="%(asctime)s %(levelname)s %(name)s %(message)s",
    )
    # A stable id per process, so a backend log line can be tied to this worker.
    log("info", "worker_start", instance=uuid.uuid4().hex[:8], provider_id=args.provider_id)

    try:
        asyncio.run(run_worker(
            backend=args.backend,
            provider_id=args.provider_id,
            token=args.token,
            handler=_default_handler,
            heartbeat_seconds=args.heartbeat,
        ))
    except KeyboardInterrupt:
        log("info", "worker_interrupted")
    except Exception as exc:
        # A rejected handshake carries the close code in the exception args or its
        # string form, depending on the websockets version. 4001 is "provider not
        # found" and 4002 is "bad token" — the two ways this is set up wrong, so
        # name them instead of making the user read a stack trace. Always log the
        # underlying text as well, since the code is the only thing that says
        # *which* of the two it was.
        # The backend rejects the handshake *before* accepting, which is what we
        # want (an unauthenticated socket is never opened), but it means the
        # close codes 4001/4002 never reach the client — the ASGI server turns a
        # pre-accept close into an HTTP rejection, so both cases arrive as
        # `InvalidStatus`. That means a client cannot distinguish "provider does
        # not exist" from "token is wrong or missing", and both are the same
        # operator error, so one hint covers it.
        message = f"{exc!r} {exc}"
        log("error", "worker_connect_failed", provider_id=args.provider_id, error=str(exc))
        if "403" in message or "4002" in message:
            log(
                "error",
                "hint_rejected_by_auth",
                reason="no worker token is minted for this provider, or the token is wrong",
                mint_endpoint=f"POST /api/v2/providers/{args.provider_id}/worker-token",
            )
        elif "404" in message or "4001" in message:
            log("error", "hint_provider_not_found", provider_id=args.provider_id)
        else:
            logger.exception("worker_crashed")
        return 1
    return 0


if __name__ == "__main__":
    sys.exit(main())
