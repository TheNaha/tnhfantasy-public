import asyncio
import os
import subprocess
from collections import deque
from datetime import datetime, timezone
from typing import Deque, Dict, List

from provider_core.base_client import _DEPLOY_STATE
from provider_core.logging import get_logger

logger = get_logger("provider_core.deploy")

# How much deploy output is retained for `/deploy-status` to serve.
#
# The old loop did `out_str += chunk` and `_DEPLOY_STATE["logs"] = out_str` for
# every 1 KB of `modal deploy` output: a 5 MB log was ~5000 whole-buffer
# re-concatenations (~12 GB of memcpy) plus a dict write per chunk, and every
# poll then serialised the entire buffer back to the caller. Chunks are kept in
# a deque and joined on read, and the total is capped — a deploy log's head is
# old news and the tail is what anyone reading the Deploy tab wants.
DEPLOY_LOG_MAX_BYTES = int(os.getenv("DEPLOY_LOG_MAX_BYTES", str(256 * 1024)))

# Bounded by DEPLOY_LOG_MAX_BYTES, not by a chunk count: _append_log drops empty
# chunks, so every retained chunk owns at least one byte and the byte budget
# bounds the deque length on its own. A `deque(maxlen=...)` would silently
# discard the oldest chunk *and* leave `_LOG_BYTES` over-counted and
# `_LOG_TRUNCATED` unset.
_LOG_CHUNKS: Deque[str] = deque()
_LOG_BYTES = 0
_LOG_TRUNCATED = False


def _reset_logs() -> None:
    global _LOG_BYTES, _LOG_TRUNCATED
    _LOG_CHUNKS.clear()
    _LOG_BYTES = 0
    _LOG_TRUNCATED = False


def _append_log(text: str) -> None:
    """Append to the retained tail. O(1) — no buffer is ever re-concatenated."""
    global _LOG_BYTES, _LOG_TRUNCATED
    if not text:
        return
    _LOG_CHUNKS.append(text)
    _LOG_BYTES += len(text)
    while _LOG_BYTES > DEPLOY_LOG_MAX_BYTES and _LOG_CHUNKS:
        dropped = _LOG_CHUNKS.popleft()
        _LOG_BYTES -= len(dropped)
        _LOG_TRUNCATED = True


def get_deploy_logs() -> str:
    """The retained tail, joined once per read."""
    return "".join(_LOG_CHUNKS)


def get_deploy_state() -> Dict[str, object]:
    """The state served by `/deploy-status` and returned by `/deploy`.

    ``logs`` is materialised here rather than kept in ``_DEPLOY_STATE`` so the
    running log is never part of the dict that each chunk used to overwrite.
    ``logs_truncated`` tells the UI that the head is missing instead of letting
    it look like a complete log. An untouched worker has no deploy state at
    all, so this returns ``{}`` and the caller substitutes its own default.
    """
    if not _DEPLOY_STATE:
        return {}
    state: Dict[str, object] = {
        key: value for key, value in _DEPLOY_STATE.items() if key != "logs"
    }
    state["logs"] = get_deploy_logs()
    if _LOG_TRUNCATED:
        state["logs_truncated"] = True
    return state


def _log_deploy_done(task: asyncio.Task):
    if task.cancelled():
        logger.warning("Deploy task was cancelled")
    elif task.exception():
        logger.error(f"Deploy task failed with unhandled exception: {task.exception()}", exc_info=task.exception())


def start_deploy_task(provider_name: str, commands: List[List[str]]) -> asyncio.Task:
    """
    Start a background task to run a sequence of CLI commands and stream their combined stdout/stderr to _DEPLOY_STATE.
    """
    _DEPLOY_STATE.clear()
    _reset_logs()
    _DEPLOY_STATE.update({
        "status": "deploying",
        "message": "Deployment started",
        "started_at": datetime.now(timezone.utc).isoformat()
    })

    async def _run():
        return_codes = []

        try:
            for i, cmd in enumerate(commands):
                if i > 0:
                    _append_log(f"\n\n--- Running Next Command: {' '.join(cmd)} ---\n\n")

                proc = await asyncio.create_subprocess_exec(
                    *cmd,
                    stdout=subprocess.PIPE,
                    stderr=subprocess.STDOUT
                )

                while True:
                    chunk = await proc.stdout.read(1024)
                    if not chunk:
                        break
                    _append_log(chunk.decode('utf-8', errors='replace'))

                await proc.wait()
                return_codes.append(proc.returncode)

                if proc.returncode != 0:
                    break

            success = all(code == 0 for code in return_codes)
            if success:
                _DEPLOY_STATE.update({"status": "completed", "message": "Deployment successful"})
                logger.info(f"{provider_name} deployment completed successfully")
            else:
                codes_str = ", ".join(map(str, return_codes))
                _DEPLOY_STATE.update({"status": "failed", "message": f"Deployment failed with codes {codes_str}"})
                logger.error(f"{provider_name} deployment failed with codes {codes_str}: {get_deploy_logs()[-500:]}")
        except Exception as e:
            _DEPLOY_STATE.update({"status": "failed", "message": str(e)})
            logger.error(f"{provider_name} deployment error: {e}", exc_info=True)

    deploy_task = asyncio.create_task(_run())
    deploy_task.add_done_callback(_log_deploy_done)
    return deploy_task
