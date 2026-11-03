"""The ``memory_snapshot_helper`` package lives in two trees and must stay in step.

``backend_v2/memory_snapshot_helper/`` is the copy imported by the backend at
runtime; ``deployables/modal/image/memory_snapshot_helper/`` is the copy baked
into the Modal worker image. They are deliberate duplicates (like the
``provider_core`` / ``provider_worker_core`` fork): separate deployables, neither
imports the other at runtime, so nothing enforces that they agree.

Unlike that fork, there is no documented reason for these two copies to differ
-- they are the same helper script, deployed to both places. This test pins
that assumption so an edit to one tree that forgets the other is caught here
rather than as a silent worker-image drift.

It deliberately compares full file contents (not just the functions the backend
imports): any drift, including comments or whitespace, is a signal that someone
touched one tree and not the other.
"""

import pytest

from tests.repo_paths import require_repo_root

ROOT = require_repo_root("deployables/modal/image/memory_snapshot_helper/")

BACKEND_DIR = ROOT / "backend_v2" / "memory_snapshot_helper"
DEPLOYABLE_DIR = ROOT / "deployables" / "modal" / "image" / "memory_snapshot_helper"

FILES = ("__init__.py", "prestartup_script.py")


@pytest.mark.skipif(ROOT is None, reason="running outside a checkout root")
class TestMemorySnapshotHelperDrift:
    """Both copies of memory_snapshot_helper must remain byte-identical."""

    @pytest.mark.parametrize("filename", FILES)
    def test_both_copies_exist(self, filename):
        backend = BACKEND_DIR / filename
        deployable = DEPLOYABLE_DIR / filename
        assert backend.is_file(), f"missing backend copy: {backend}"
        assert deployable.is_file(), f"missing deployable copy: {deployable}"

    @pytest.mark.parametrize("filename", FILES)
    def test_copies_are_identical(self, filename):
        backend = (BACKEND_DIR / filename).read_text()
        deployable = (DEPLOYABLE_DIR / filename).read_text()
        assert backend == deployable, (
            f"memory_snapshot_helper/{filename} drifted between the backend and "
            f"the Modal deployable. Update both copies, or document why they "
            f"may differ (as provider_core / provider_worker_core does)."
        )
