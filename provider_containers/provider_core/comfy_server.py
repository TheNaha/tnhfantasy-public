import subprocess
import time
import json
import logging
from datetime import datetime, timezone
from typing import Dict, Any, Optional
from pathlib import Path

logger = logging.getLogger("provider_core.comfy_server")

def _start_comfy_server(port: int, extra_args: list[str] = None):
    cmd = ["comfy", "launch", "--background", "--", "--listen", "0.0.0.0", "--port", str(port)]
    if extra_args:
        cmd.extend(extra_args)
    subprocess.Popen(cmd)

def _wait_for_comfy_ready(port: int, timeout_seconds: float, label: str):
    import requests

    deadline = time.time() + max(timeout_seconds, 1.0)
    while time.time() < deadline:
        try:
            response = requests.get(f"http://127.0.0.1:{port}", timeout=2)
            if response.status_code == 200:
                logger.info(f"[{label}] ComfyUI is ready")
                return True
        except requests.exceptions.RequestException:
            pass
        time.sleep(1)

    logger.warning(f"[{label}] ComfyUI did not respond within {int(timeout_seconds)} seconds")
    return False

def _restart_comfy_server(port: int, label: str, timeout_seconds: float = 180.0):
    logger.warning(f"[{label}] Restarting ComfyUI server")
    try:
        subprocess.run(["pkill", "-f", "ComfyUI/main.py"], check=False)
        subprocess.run(["pkill", "-f", "comfy launch"], check=False)
    except Exception as exc:
        logger.info(f"[{label}] Process cleanup warning during restart: {exc}")

    time.sleep(1)
    _start_comfy_server(port)
    _wait_for_comfy_ready(port, timeout_seconds, label)

def _truncate_output(raw: str, max_chars: int) -> str:
    if not isinstance(raw, str):
        return ""
    if len(raw) <= max_chars:
        return raw
    return raw[:max_chars] + "\n...<truncated>..."

def _run_command_capture(command: list[str], timeout_seconds: float, max_chars: int = 12000) -> str:
    try:
        result = subprocess.run(
            command,
            capture_output=True,
            text=True,
            timeout=max(timeout_seconds, 1.0),
            check=False,
        )
    except Exception as exc:
        return f"<command_failed: {exc}>"

    stdout = (result.stdout or "").strip()
    stderr = (result.stderr or "").strip()
    output = "\n".join(part for part in [stdout, stderr] if part).strip()
    if not output:
        output = f"<no_output exit_code={result.returncode}>"
    return _truncate_output(output, max_chars)

def _fetch_local_json(port: int, path: str, timeout_seconds: float = 2.5) -> Dict[str, Any]:
    import requests

    url = f"http://127.0.0.1:{port}{path}"
    try:
        response = requests.get(url, timeout=max(timeout_seconds, 1.0))
    except Exception as exc:
        return {"_error": str(exc), "_url": url}

    if response.status_code != 200:
        return {
            "_status_code": response.status_code,
            "_url": url,
            "_body": _truncate_output(response.text or "", 1200),
        }

    try:
        return response.json()
    except Exception as exc:
        return {
            "_error": f"json_decode_failed: {exc}",
            "_url": url,
            "_body": _truncate_output(response.text or "", 1200),
        }

def _find_comfy_pid() -> Optional[int]:
    try:
        result = subprocess.run(
            ["pgrep", "-f", "ComfyUI/main.py"],
            capture_output=True,
            text=True,
            timeout=2,
            check=False,
        )
    except Exception:
        return None

    if result.returncode != 0:
        return None

    for line in (result.stdout or "").splitlines():
        token = line.strip()
        if token.isdigit():
            return int(token)
    return None

def capture_stall_diagnostics(
    port: int,
    label: str,
    details: Optional[Dict[str, Any]] = None,
    enabled: bool = True,
    diagnostics_timeout: float = 8.0,
    max_chars: int = 12000,
    volume_commit_fn = None
) -> Optional[str]:
    """Capture best-effort diagnostics for frozen ComfyUI runs before recycling the server."""
    if not enabled:
        return None

    details = details or {}
    prompt_id = details.get("prompt_id") or "unknown"
    safe_prompt_id = str(prompt_id).replace("/", "_").replace(" ", "_")
    timestamp = datetime.now(timezone.utc).strftime("%Y%m%dT%H%M%SZ")

    diagnostics_dir = Path("/mnt/data/diagnostics/comfyui_stalls")
    diagnostics_dir.mkdir(parents=True, exist_ok=True)
    diagnostics_path = diagnostics_dir / f"{label.lower()}_{timestamp}_{safe_prompt_id}.json"

    comfy_pid = _find_comfy_pid()
    py_spy_dump = "<comfy_pid_not_found>"
    if comfy_pid is not None:
        py_spy_dump = _run_command_capture(
            ["py-spy", "dump", "--pid", str(comfy_pid)],
            diagnostics_timeout,
            max_chars
        )

    report = {
        "captured_at": datetime.now(timezone.utc).isoformat(),
        "label": label,
        "port": port,
        "stall_details": details,
        "comfy_pid": comfy_pid,
        "queue": _fetch_local_json(port, "/queue"),
        "system_stats": _fetch_local_json(port, "/system_stats"),
        "history": _fetch_local_json(port, f"/history/{prompt_id}") if prompt_id != "unknown" else {"_skipped": "no_prompt_id"},
        "process_table": _run_command_capture(
            ["ps", "-eo", "pid,ppid,pcpu,pmem,etime,stat,command"],
            diagnostics_timeout,
            max_chars
        ),
        "nvidia_smi": _run_command_capture(
            [
                "nvidia-smi",
                "--query-gpu=timestamp,index,utilization.gpu,utilization.memory,memory.used,memory.total,temperature.gpu",
                "--format=csv,noheader,nounits",
            ],
            diagnostics_timeout,
            max_chars
        ),
        "py_spy_dump": py_spy_dump,
    }

    try:
        with open(diagnostics_path, "w", encoding="utf-8") as file_obj:
            json.dump(report, file_obj, indent=2)
    except Exception as exc:
        logger.error(f"[{label}] Failed to persist stall diagnostics: {exc}")
        return None

    if volume_commit_fn:
        try:
            volume_commit_fn()
        except Exception as exc:
            logger.info(f"[{label}] Volume commit failed for diagnostics file: {exc}")

    logger.warning(f"[{label}] Captured ComfyUI stall diagnostics: {diagnostics_path}")
    return str(diagnostics_path)
