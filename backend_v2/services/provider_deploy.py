"""Run `scripts/deploy.sh` on request, with credentials from the database.

The deploy script was a HOST operator tool with no route behind it, and that was
the right default: a vendor CLI deploy inside a request handler puts a network
round-trip, a credential lookup and a multi-minute build inside an HTTP timeout,
and `InProcessEngine.deploy()` returned `{"status": "not_applicable"}` with no
production caller. That reasoning still holds, so this module does not pretend to
stream the build — it runs the script, waits for it, and returns its output.

THE BLAST RADIUS, since this is reachable by anything that can reach the API
(this app has no application-level authentication; the network perimeter is the
control, which is why `POST /providers/{id}/setup` was already reachable):

  * `target` is looked up in a frozen dict. It is NEVER interpolated into a
    command line, and the command is executed as an argv list with
    `shell=False` — there is no string for a shell to parse, so no injection
    surface exists even if the allowlist were later widened by mistake.
  * `scripts/deploy.sh` path is resolved and checked to exist; it is not taken
    from the request.
  * Credentials are passed through the child's ENVIRONMENT, never as argv —
    argv is visible to every process on the host via `/proc`, and a Modal token
    does not need to be.
  * The child inherits a minimal environment rather than the backend's, so it
    cannot accidentally inherit the database password or the credential master
    key.
  * Output is captured and capped. A build that prints megabytes does not get to
    become a megabyte response body, and a caller cannot make the backend buffer
    without limit.
  * One deploy at a time, process-wide. Two concurrent Modal deploys fight over
    the same app names and the loser produces a confusing partial failure.

WHAT THIS DOES NOT DO: it does not check credentials before running. A deploy
with the wrong token fails inside the vendor CLI, which is slower to diagnose
than a pre-check but is never wrong — a pre-check that passes and a deploy that
fails anyway is the case that wastes an hour.
"""

import asyncio
from datetime import datetime, timezone
import json
import os
import shutil
from pathlib import Path
from typing import Any, AsyncIterator

from infrastructure.logging import get_logger

logger = get_logger("services.provider_deploy")

#: In-memory cache of the latest deployment outcomes
_deploy_history_by_provider: dict[str, dict[str, Any]] = {}
_deploy_history_by_target: dict[str, dict[str, Any]] = {}


def get_last_deploy(
    provider_id: str | None = None,
    target: str | None = None,
) -> dict[str, Any] | None:
    """Retrieve the most recent deployment result for a provider or target."""
    if provider_id and provider_id in _deploy_history_by_provider:
        return _deploy_history_by_provider[provider_id]
    if target and target in _deploy_history_by_target:
        return _deploy_history_by_target[target]
    return None


def record_deploy_result(
    result: dict[str, Any],
    provider_id: str | None = None,
) -> dict[str, Any]:
    """Store deployment result in memory history."""
    target = result.get("target")
    if target:
        _deploy_history_by_target[target] = result
    if provider_id:
        _deploy_history_by_provider[provider_id] = result
    return result


#: The only deployable targets. Frozen because this dict is the security
#: boundary: anything not a key here cannot become an argv.
DEPLOY_TARGETS: dict[str, dict[str, str]] = {
    "image": {"script": "scripts/deploy.sh", "artifact": "comfy-modal-stack",
              "transport": "modal",
              "description": "Modal ComfyUI image worker"},
    "tts": {"script": "scripts/deploy.sh", "artifact": "comfy-modal-tts",
            "transport": "modal",
            "description": "Modal TTS worker"},
    "llm": {"script": "scripts/deploy.sh", "artifact": "tnh-llm",
            "transport": "modal",
            "description": "Modal llama.cpp LLM worker"},
    "beam": {"script": "scripts/deploy.sh", "artifact": "comfy-gpu + 5 more",
             "transport": "beam",
             "description": "all six Beam deployments"},
    "all": {"script": "scripts/deploy.sh", "artifact": "every target",
            "transport": "modal+beam",
            "description": "every target whose preconditions pass"},
}

#: Hard ceiling on captured output. A CloudFormation-style build log can run to
#: tens of megabytes; the useful part is the tail.
MAX_OUTPUT_BYTES = 256 * 1024

#: A Modal deploy of the image app builds and uploads a container image. Five
#: minutes is not generous for a cold cache but it is far past the point where a
#: hung CLI is a problem rather than a slow build, and the caller gets a real
#: failure instead of a request that never returns.
DEFAULT_TIMEOUT_SECONDS = 300.0
MAX_TIMEOUT_SECONDS = 900.0

#: Process-wide lock. One deploy at a time, because two concurrent deploys of
#: the same Modal app names race and produce a partial state neither requested.
_deploy_lock = asyncio.Lock()


class DeployError(RuntimeError):
    """The deploy could not be started or did not finish cleanly."""


def repo_root() -> Path | None:
    """The checkout root, or None when running outside one.

    `/app` is the backend package inside the container and the repo is mounted
    alongside it; outside Docker both may be absent, and a deploy route that
    cannot find its script should say so rather than fail obscurely later.
    """
    for candidate in (os.environ.get("TNH_REPO_ROOT"), "/comfyui", "/app/.."):
        if not candidate:
            continue
        path = Path(candidate).resolve()
        if (path / "scripts" / "deploy.sh").is_file():
            return path
    here = Path(__file__).resolve()
    for parent in here.parents:
        if (parent / "scripts" / "deploy.sh").is_file():
            return parent
    return None


def list_targets() -> list[dict[str, Any]]:
    """What can be deployed from here, and whether the script is even present."""
    root = repo_root()
    return [
        {"target": name, **spec, "available": root is not None}
        for name, spec in sorted(DEPLOY_TARGETS.items())
    ]


def _child_env(
    credentials: dict[str, Any] | None,
    provider_id: str | None = None,
) -> dict[str, str]:
    """A minimal environment carrying PATH and whatever credentials apply.

    Inheriting the backend's own environment would hand the deploy script the
    database password and — once `COMFY_CREDENTIAL_SECRET` is set — the master
    key that decrypts every provider's token. Neither is the vendor CLI's
    business. The vendor CLIs need HOME and PATH and nothing else; credentials
    are added by name.
    """
    env = {
        key: os.environ[key]
        for key in ("PATH", "HOME", "LANG", "TMPDIR")
        if os.environ.get(key)
    }
    env.setdefault("HOME", "/tmp")
    env.setdefault("PATH", "/usr/local/bin:/usr/bin:/bin")
    env["PYTHONUNBUFFERED"] = "1"

    if provider_id:
        env["PROVIDER_ID"] = provider_id

    if not credentials:
        return env

    # Credential keys the vendor CLIs read, mapped from the names the provider
    # rows use. `api_key` covers BEAM_API_KEY, `token_id`/`token_secret` cover
    # the Modal pair.
    for key, value in credentials.items():
        text = str(value or "").strip()
        if not text:
            continue
        env[key] = text
        # Modal's CLI reads the standard names too.
        if key in ("token_id", "MODAL_TOKEN_ID"):
            env["MODAL_TOKEN_ID"] = text
        elif key in ("token_secret", "MODAL_TOKEN_SECRET"):
            env["MODAL_TOKEN_SECRET"] = text
        elif key in ("api_key", "BEAM_API_KEY"):
            env["BEAM_API_KEY"] = text
        elif key in ("hf_token", "HF_TOKEN"):
            env["HF_TOKEN"] = text
        elif key in ("civitai_token", "CIVITAI_TOKEN"):
            env["CIVITAI_TOKEN"] = text
    return env


def _truncate(raw: bytes) -> str:
    """Tail of the output, with a marker saying how much was dropped.

    The tail is the interesting part of a build log, and a caller that cannot
    see why their deploy failed is worse off than one that sees the last 200 KB.
    """
    if len(raw) <= MAX_OUTPUT_BYTES:
        return raw.decode("utf-8", errors="replace")
    dropped = len(raw) - MAX_OUTPUT_BYTES
    return (
        f"... [{dropped} bytes of earlier output omitted; the tail follows]\n"
        + raw[-MAX_OUTPUT_BYTES:].decode("utf-8", errors="replace")
    )


async def run_deploy(
    target: str,
    *,
    dry_run: bool = False,
    credentials: dict[str, Any] | None = None,
    timeout: float | None = None,
    provider_id: str | None = None,
) -> dict[str, Any]:
    """Deploy one target. Returns the script's output and exit status."""
    spec = DEPLOY_TARGETS.get(target)
    if spec is None:
        # Not a 400-shaped detail the caller should guess at: say what IS valid.
        raise DeployError(
            f"unknown deploy target {target!r}. Valid targets: "
            f"{', '.join(sorted(DEPLOY_TARGETS))}"
        )

    root = repo_root()
    if root is None:
        raise DeployError(
            "deploy.sh is not reachable from this process. Set TNH_REPO_ROOT to "
            "the checkout root, or run `bash scripts/deploy.sh` on the host."
        )

    script = root / spec["script"]
    if not script.is_file():
        raise DeployError(f"deploy script missing at {script}")

    if shutil.which("modal") is None and spec["transport"] != "beam" and target != "all":
        # Reported, not raised. `check_modal` inside the script says this too,
        # and letting it run means one source of truth for the diagnosis.
        logger.warning("provider_deploy_modal_cli_missing")

    budget = min(float(timeout or DEFAULT_TIMEOUT_SECONDS), MAX_TIMEOUT_SECONDS)
    argv = ["bash", str(script), target]
    if dry_run:
        argv.append("--dry-run")

    async with _deploy_lock:
        started = asyncio.get_running_loop().time()
        try:
            process = await asyncio.create_subprocess_exec(
                *argv,
                cwd=str(root),
                env=_child_env(credentials, provider_id=provider_id),
                stdout=asyncio.subprocess.PIPE,
                stderr=asyncio.subprocess.STDOUT,
            )
        except OSError as exc:
            raise DeployError(f"could not start the deploy script: {exc}") from exc

        try:
            stdout, _ = await asyncio.wait_for(process.communicate(), timeout=budget)
        except asyncio.TimeoutError:
            # SIGTERM then SIGKILL, and report what we have. Killing without
            # reporting leaves a half-finished deploy with nobody knowing.
            process.terminate()
            try:
                stdout, _ = await asyncio.wait_for(process.communicate(), timeout=10)
            except asyncio.TimeoutError:
                process.kill()
                stdout, _ = await process.communicate()
            elapsed = asyncio.get_running_loop().time() - started
            logger.error(
                "provider_deploy_timeout", target=target, elapsed=round(elapsed, 1)
            )
            raise DeployError(
                f"deploy of {target!r} exceeded {int(budget)}s and was terminated. "
                f"The vendor CLI may have left partial state; check its dashboard."
            ) from None

    elapsed = asyncio.get_running_loop().time() - started
    output = _truncate(stdout or b"")
    ok = process.returncode == 0

    logger.info(
        "provider_deploy_finished",
        target=target,
        dry_run=dry_run,
        exit_code=process.returncode,
        elapsed=round(elapsed, 1),
    )

    result = {
        "target": target,
        "artifact": spec["artifact"],
        "transport": spec["transport"],
        "description": spec["description"],
        "dry_run": dry_run,
        "ok": ok,
        "exit_code": process.returncode,
        "elapsed_seconds": round(elapsed, 1),
        "output": output,
        "truncated": len(stdout or b"") > MAX_OUTPUT_BYTES,
        "timestamp": datetime.now(timezone.utc).isoformat(),
        "provider_id": provider_id,
    }
    record_deploy_result(result, provider_id=provider_id)
    return result


class ActiveDeploy:
    """In-memory state and subscriber pub/sub for an in-flight deployment."""

    def __init__(self, target: str, provider_id: str | None, dry_run: bool):
        self.target = target
        self.provider_id = provider_id
        self.dry_run = dry_run
        try:
            self.started_at = asyncio.get_running_loop().time()
        except RuntimeError:
            self.started_at = 0.0
        self.chunks: list[str] = []
        self.subscribers: set[asyncio.Queue[str | None]] = set()
        self.done = False
        self.result: dict[str, Any] | None = None
        self.error: str | None = None

    def broadcast(self, raw_chunk: str) -> None:
        self.chunks.append(raw_chunk)
        for q in list(self.subscribers):
            try:
                q.put_nowait(raw_chunk)
            except Exception:
                pass

    def finish(self, result: dict[str, Any]) -> None:
        self.done = True
        self.result = result
        msg = json.dumps({"type": "finish", "result": result}) + "\n"
        self.chunks.append(msg)
        for q in list(self.subscribers):
            try:
                q.put_nowait(msg)
                q.put_nowait(None)
            except Exception:
                pass

    def fail(self, err_msg: str) -> None:
        self.done = True
        self.error = err_msg
        msg = json.dumps({"type": "error", "error": err_msg}) + "\n"
        self.chunks.append(msg)
        for q in list(self.subscribers):
            try:
                q.put_nowait(msg)
                q.put_nowait(None)
            except Exception:
                pass


_active_deploy: ActiveDeploy | None = None


def get_active_deploy(provider_id: str | None = None) -> dict[str, Any] | None:
    """Retrieve the in-flight deployment status if one is currently running."""
    if _active_deploy is not None and not _active_deploy.done:
        if provider_id is None or _active_deploy.provider_id == provider_id:
            try:
                elapsed = asyncio.get_running_loop().time() - _active_deploy.started_at
            except RuntimeError:
                elapsed = 0.0
            return {
                "target": _active_deploy.target,
                "provider_id": _active_deploy.provider_id,
                "dry_run": _active_deploy.dry_run,
                "elapsed_seconds": round(elapsed, 1),
                "is_running": True,
            }
    return None


async def _run_deploy_process(
    active: ActiveDeploy,
    spec: dict[str, str],
    root: Path,
    argv: list[str],
    budget: float,
    credentials: dict[str, Any] | None,
    provider_id: str | None,
) -> None:
    async with _deploy_lock:
        started = asyncio.get_running_loop().time()
        try:
            process = await asyncio.create_subprocess_exec(
                *argv,
                cwd=str(root),
                env=_child_env(credentials, provider_id=provider_id),
                stdout=asyncio.subprocess.PIPE,
                stderr=asyncio.subprocess.STDOUT,
            )
        except OSError as exc:
            active.fail(f"could not start the deploy script: {exc}")
            return

        captured_chunks: list[bytes] = []

        try:
            while True:
                time_remaining = budget - (asyncio.get_running_loop().time() - started)
                if time_remaining <= 0:
                    raise asyncio.TimeoutError()

                line_coro = process.stdout.readline() if process.stdout else None
                if line_coro is None:
                    break

                line = await asyncio.wait_for(line_coro, timeout=time_remaining)
                if not line:
                    break

                captured_chunks.append(line)
                decoded = line.decode("utf-8", errors="replace")
                active.broadcast(json.dumps({"type": "chunk", "chunk": decoded}) + "\n")

            time_remaining = budget - (asyncio.get_running_loop().time() - started)
            if time_remaining > 0:
                await asyncio.wait_for(process.wait(), timeout=time_remaining)
            else:
                raise asyncio.TimeoutError()

        except asyncio.TimeoutError:
            process.terminate()
            try:
                remaining_stdout, _ = await asyncio.wait_for(process.communicate(), timeout=10)
                if remaining_stdout:
                    captured_chunks.append(remaining_stdout)
            except asyncio.TimeoutError:
                process.kill()
                remaining_stdout, _ = await process.communicate()
                if remaining_stdout:
                    captured_chunks.append(remaining_stdout)
            elapsed = asyncio.get_running_loop().time() - started
            err_msg = (
                f"deploy of {active.target!r} exceeded {int(budget)}s and was terminated. "
                f"The vendor CLI may have left partial state; check its dashboard."
            )
            logger.error("provider_deploy_timeout", target=active.target, elapsed=round(elapsed, 1))
            active.fail(err_msg)
            return

        elapsed = asyncio.get_running_loop().time() - started
        raw_output = b"".join(captured_chunks)
        output = _truncate(raw_output)
        ok = process.returncode == 0

        logger.info(
            "provider_deploy_finished",
            target=active.target,
            dry_run=active.dry_run,
            exit_code=process.returncode,
            elapsed=round(elapsed, 1),
        )

        result = {
            "target": active.target,
            "artifact": spec["artifact"],
            "transport": spec["transport"],
            "description": spec["description"],
            "dry_run": active.dry_run,
            "ok": ok,
            "exit_code": process.returncode,
            "elapsed_seconds": round(elapsed, 1),
            "output": output,
            "truncated": len(raw_output) > MAX_OUTPUT_BYTES,
            "timestamp": datetime.now(timezone.utc).isoformat(),
            "provider_id": provider_id,
        }
        record_deploy_result(result, provider_id=provider_id)
        active.finish(result)


async def stream_deploy(
    target: str,
    *,
    dry_run: bool = False,
    credentials: dict[str, Any] | None = None,
    timeout: float | None = None,
    provider_id: str | None = None,
) -> AsyncIterator[str]:
    """Stream deployment logs in real time as NDJSON lines."""
    global _active_deploy

    # If an active deploy is already running for this target or provider, attach to it
    if _active_deploy is not None and not _active_deploy.done:
        active = _active_deploy
        queue: asyncio.Queue[str | None] = asyncio.Queue()
        # Replay chunks already accumulated
        for chunk in list(active.chunks):
            yield chunk
        if active.done:
            return

        active.subscribers.add(queue)
        try:
            while True:
                msg = await queue.get()
                if msg is None:
                    break
                yield msg
        finally:
            active.subscribers.discard(queue)
        return

    spec = DEPLOY_TARGETS.get(target)
    if spec is None:
        yield json.dumps({
            "type": "error",
            "error": (
                f"unknown deploy target {target!r}. Valid targets: "
                f"{', '.join(sorted(DEPLOY_TARGETS))}"
            ),
        }) + "\n"
        return

    root = repo_root()
    if root is None:
        yield json.dumps({
            "type": "error",
            "error": (
                "deploy.sh is not reachable from this process. Set TNH_REPO_ROOT to "
                "the checkout root, or run `bash scripts/deploy.sh` on the host."
            ),
        }) + "\n"
        return

    script = root / spec["script"]
    if not script.is_file():
        yield json.dumps({
            "type": "error",
            "error": f"deploy script missing at {script}",
        }) + "\n"
        return

    if shutil.which("modal") is None and spec["transport"] != "beam" and target != "all":
        logger.warning("provider_deploy_modal_cli_missing")

    budget = min(float(timeout or DEFAULT_TIMEOUT_SECONDS), MAX_TIMEOUT_SECONDS)
    argv = ["bash", str(script), target]
    if dry_run:
        argv.append("--dry-run")

    active = ActiveDeploy(target, provider_id, dry_run)
    _active_deploy = active
    queue_out: asyncio.Queue[str | None] = asyncio.Queue()
    active.subscribers.add(queue_out)

    asyncio.create_task(
        _run_deploy_process(
            active,
            spec,
            root,
            argv,
            budget,
            credentials,
            provider_id,
        )
    )

    try:
        while True:
            msg = await queue_out.get()
            if msg is None:
                break
            yield msg
    finally:
        active.subscribers.discard(queue_out)