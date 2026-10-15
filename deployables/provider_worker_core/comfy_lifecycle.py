"""The three things a long-lived ComfyUI container needs between runs.

Both Modal apps that run ComfyUI — the image worker and the TTS worker — need
exactly the same lifecycle around every run, and until now each had its own
version, or none:

* **Reload the volume** before the run, so a file another container wrote after
  this one started is visible. Without it a job reads the state the container
  booted with.
* **Free VRAM** after the run, by asking ComfyUI itself. It runs in a separate OS
  process, so a `torch.cuda.empty_cache()` in the Modal function would empty the
  *driver's* CUDA context and never touch ComfyUI's; it has to be an HTTP call to
  its `/free` endpoint. This is what mitigates KSampler hangs caused by VRAM
  fragmentation from LoRA patch-backup accumulation.
* **Restart the process** after N runs. A ComfyUI container accumulates state and
  eventually stalls; a restart is cheaper than a timeout and far cheaper than
  debugging a hung graph.

They live here rather than in either app because `tts_worker`'s modal app
documents that it must not import the image worker's module graph — a shared
import would drag the image stack's dependencies into the speech container,
which is the entire cost the separation exists to avoid — and because this module
imports no provider SDK, so the logic is unit-testable in the provider venv
instead of only inside a Modal build.

`restart_comfy_process` takes the caller's `start` and `wait_for_ready` callables
rather than owning a launcher: the two apps launch ComfyUI differently (the
image worker passes `--highvram` and uses `--background`, the TTS worker does
neither), and the parts worth sharing are the kill, the confirmed-dead wait and
the port check — not the command line.
"""

from __future__ import annotations

import os
import signal
import time
from typing import Callable, List, Optional

LogFn = Callable[..., None]


def find_pids_on_port(port: int, label: str = "", log: Optional[LogFn] = None) -> List[int]:
    """PIDs actually bound to `port`, from the socket table.

    Not cmdline pattern matching: `comfy-cli`'s launch daemonizes under a
    cmdline that does not contain `ComfyUI/main.py`, so `pgrep -f` matched
    nothing and every "restart" silently skipped the kill and restarted nothing.
    """
    import psutil

    emit = log or (lambda *a, **k: None)
    pids = set()
    try:
        for conn in psutil.net_connections(kind="inet"):
            if conn.laddr and conn.laddr.port == port and conn.pid:
                pids.add(conn.pid)
    except Exception as exc:  # noqa: BLE001 - a probe that cannot answer finds nothing
        emit(f"[{label}] psutil.net_connections failed: {exc}")
    emit(f"[{label}] pids bound to port {port}: {sorted(pids)}")
    return sorted(pids)


def wait_for_pids_gone(pids: List[int], timeout_seconds: float = 15.0) -> bool:
    deadline = time.time() + timeout_seconds
    remaining = set(pids)
    while remaining and time.time() < deadline:
        remaining = {p for p in remaining if os.path.exists(f"/proc/{p}")}
        if remaining:
            time.sleep(0.5)
    return not remaining


def wait_for_port_closed(port: int, timeout_seconds: float = 15.0) -> bool:
    import socket

    deadline = time.time() + timeout_seconds
    while time.time() < deadline:
        with socket.socket(socket.AF_INET, socket.SOCK_STREAM) as sock:
            sock.settimeout(0.5)
            if sock.connect_ex(("127.0.0.1", port)) != 0:
                return True
        time.sleep(0.5)
    return False


def free_comfy_vram(port: int, label: str, log: Optional[LogFn] = None, timeout: float = 10.0) -> None:
    """Ask the ComfyUI subprocess to unload models and free VRAM."""
    import requests

    emit = log or (lambda *a, **k: None)
    try:
        resp = requests.post(
            f"http://127.0.0.1:{port}/free",
            json={"unload_models": True, "free_memory": True},
            timeout=timeout,
        )
        resp.raise_for_status()
        emit(f"[{label}] /free succeeded ({resp.status_code})")
    except Exception as exc:  # noqa: BLE001 - a failed free is not a failed job
        emit(f"[{label}] /free call failed: {exc}")


def restart_comfy_process(
    port: int,
    label: str,
    *,
    start: Callable[[], None],
    wait_for_ready: Callable[[], None],
    log: Optional[LogFn] = None,
    timeout_seconds: float = 180.0,
) -> None:
    """Kill the ComfyUI process, confirm it is dead, start a new one, wait for it.

    Kill by PID with a confirmed-dead wait, not fire-and-forget `pkill`. The bug
    that shape hides: `pkill` sends SIGTERM and the caller immediately spawns a
    replacement and polls readiness, and the readiness probe regularly catches the
    OLD (still-dying) process still answering 200. The "restart" then keeps
    running the same long-lived process while the freshly spawned one fails with
    "port already in use" and is discarded — so the restart that was supposed to
    fix an accumulating container is the thing that leaves it in place.
    """
    emit = log or (lambda *a, **k: None)
    pids = find_pids_on_port(port, label, log=emit)
    for pid in pids:
        try:
            os.kill(pid, signal.SIGTERM)
        except ProcessLookupError:
            pass
        except Exception as exc:  # noqa: BLE001
            emit(f"[{label}] SIGTERM failed for pid {pid}: {exc}")

    if not wait_for_pids_gone(pids, timeout_seconds=15.0):
        still_alive = [pid for pid in pids if os.path.exists(f"/proc/{pid}")]
        emit(f"[{label}] pids {still_alive} still alive after SIGTERM, sending SIGKILL")
        for pid in still_alive:
            try:
                os.kill(pid, signal.SIGKILL)
            except ProcessLookupError:
                pass
        wait_for_pids_gone(still_alive, timeout_seconds=10.0)

    if not wait_for_port_closed(port, timeout_seconds=15.0):
        emit(f"[{label}] port {port} still bound after killing known pids — new launch may collide")

    start()
    wait_for_ready()
