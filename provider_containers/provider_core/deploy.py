import asyncio
import subprocess
from datetime import datetime, timezone
from typing import List

from provider_core.base_client import _DEPLOY_STATE
from provider_core.logging import get_logger

logger = get_logger("provider_core.deploy")


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
    _DEPLOY_STATE.update({
        "status": "deploying",
        "message": "Deployment started",
        "started_at": datetime.now(timezone.utc).isoformat()
    })

    async def _run():
        out_str = ""
        _DEPLOY_STATE["logs"] = out_str
        return_codes = []

        try:
            for i, cmd in enumerate(commands):
                if i > 0:
                    out_str += f"\n\n--- Running Next Command: {' '.join(cmd)} ---\n\n"
                    _DEPLOY_STATE["logs"] = out_str

                proc = await asyncio.create_subprocess_exec(
                    *cmd,
                    stdout=subprocess.PIPE,
                    stderr=subprocess.STDOUT
                )

                while True:
                    chunk = await proc.stdout.read(1024)
                    if not chunk:
                        break
                    out_str += chunk.decode('utf-8', errors='replace')
                    _DEPLOY_STATE["logs"] = out_str

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
                logger.error(f"{provider_name} deployment failed with codes {codes_str}: {out_str[-500:]}")
        except Exception as e:
            _DEPLOY_STATE.update({"status": "failed", "message": str(e)})
            logger.error(f"{provider_name} deployment error: {e}", exc_info=True)

    deploy_task = asyncio.create_task(_run())
    deploy_task.add_done_callback(_log_deploy_done)
    return deploy_task
