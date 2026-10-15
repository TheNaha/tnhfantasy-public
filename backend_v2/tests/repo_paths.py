"""Locating the checkout root from tests that read files outside `backend_v2`.

A handful of tests assert things about files that live OUTSIDE the backend
package — `docs/api.md`, `frontend_v2/e2e/*.spec.js`, `remote_agent/`. They
used to reach them with `Path(__file__).resolve().parents[2]`, which is only
correct when pytest runs from a checkout (`backend_v2/tests/<file>`).

Compose mounts `backend_v2` at `/app` and the repo at `/comfyui`, so in Docker
`parents[2]` is `/` and every one of those modules raises at import. Two of
them aborted collection for the ENTIRE suite, and the third (`llama_server`)
imported fine only because some earlier test happened to have put
`remote_agent/` on `sys.path` — a test that only passes in the right order is
not a test.

So: look for a marker that identifies the root. Try the ancestors first, then
`TNH_REPO_ROOT`, then the compose mount point. Return None rather than raising,
because the honest answer for "that file is not in this image" is a skip, not a
crash that takes 3,400 unrelated tests down with it.
"""

import os
from pathlib import Path

import pytest

#: Any one of these identifies a checkout root.
_ROOT_MARKERS = ("docs/api.md", "remote_agent/server.py")


def repo_root():
    """The checkout root, or None when pytest is running outside one."""
    candidates = list(Path(__file__).resolve().parents)
    env_root = os.environ.get("TNH_REPO_ROOT")
    if env_root:
        candidates.append(Path(env_root))
    # Where compose puts the repo when backend_v2 itself is bind-mounted.
    candidates.append(Path("/comfyui"))
    for candidate in candidates:
        if any((candidate / marker).exists() for marker in _ROOT_MARKERS):
            return candidate
    return None


def require_repo_root(what: str):
    """`repo_root()`, or skip the module when there is no checkout to read.

    `what` names the artefact so the skip reason says what was missing and why,
    rather than surfacing as an unimportable module that reads like a broken
    test. Safe to call at import time — it passes `allow_module_level=True`.
    """
    root = repo_root()
    if root is not None:
        return root
    pytest.skip(
        f"{what} lives outside the backend package and is not present in this "
        f"environment, so this contract test cannot run. Set TNH_REPO_ROOT to "
        f"the checkout root to enable it.",
        allow_module_level=True,
    )