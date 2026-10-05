"""Listing the model files in one directory — one copy, and it raises.

Three implementations of the same sweep existed: the image worker's
`image_worker/comfy/models_utils.py`, and the inlined twin inside each Modal app
(`image_worker/engines/modal/modal_app.py` and
`llm_worker/engines/modal/modal_app.py`). All three caught an `os.scandir`
failure, logged it at `warning`, and returned an empty result.

An empty result is not a neutral answer here. Step 3 of reconciliation
(`provider_core/reconciliation.py`) computes

    missing_files = all_expected_paths - existing_files

and re-downloads every one of them. So a directory whose scan *failed* is not
"a directory with no models" — it is "a directory we could not read", and the two
have opposite consequences. The first costs nothing; the second re-fetches every
checkpoint in it, on a volume that is usually the reason the scan failed in the
first place (gcsfuse, a network mount, a Modal volume hiccup). One transient EIO
on `models/checkpoints` becomes a full re-download of a directory of multi-GB
weights.

The third implementation, `remote_agent/server.py::_walk`, never had the catch, so
it already failed loud and aborted step 3. Three copies of one function, two of
them swallowing the one error that must not be swallowed, is the entire defect —
which is why the fix is one shared function rather than three separate edits that
will drift again.

Raising is safe because every caller already expects it. The three `_fetch_dir`
closures in `image_worker/engines/{modal,beam,remote_comfy}/client.py` wrap their
listing in `except Exception: raise RuntimeError(...)`, and `asyncio.gather`
without `return_exceptions=True` propagates the first raise — so a failed
directory aborts step 3 loudly, which is the safe direction, rather than
silently re-fetching gigabytes.
"""

from __future__ import annotations

import os
from typing import List, Set, Tuple

from .utils import is_model_file


def scan_model_directory(target_dir: str) -> Tuple[List[Tuple[str, int]], Set[str]]:
    """Model files in `target_dir` as `(name, size)`, plus every entry name.

    `entry_set` is the sidecar lookup used by the callers: they test it for
    `<stem>.preview.png`, `<stem>.json` and `<name>.sha256` rather than probing
    the filesystem per sidecar, so it deliberately holds **every** entry name and
    not just the model files.

    Any failure — `scandir` itself, `is_file`, or `stat` on one entry — is
    propagated. There is deliberately no partial result: a half-scanned directory
    is indistinguishable from an empty one to the caller, and reconciliation acts
    on that difference by re-downloading. `remote_agent/server.py::_walk` raises
    for the same reason; see this module's docstring.
    """
    file_entries: List[Tuple[str, int]] = []
    entry_set: Set[str] = set()
    with os.scandir(target_dir) as it:
        for entry in it:
            if entry.is_file():
                entry_set.add(entry.name)
                if is_model_file(entry.name):
                    file_entries.append((entry.name, entry.stat().st_size))
    return file_entries, entry_set