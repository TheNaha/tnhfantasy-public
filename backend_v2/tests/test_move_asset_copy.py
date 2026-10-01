""""Copy Asset" moved the original file and reported success.

From the 2026-10-01 audit. The dashboard posted `{ copy: true }` to an
endpoint whose model declares `copy_file`, so pydantic dropped it, the
flag stayed False, and the handler took the os.rename branch."""

import base64
from datetime import datetime, timezone

import pytest


# A real 1x1 PNG, so the "is the file still there" assertion below is about the
# filesystem and not about a mock.
PNG_BYTES = base64.b64decode(
    "iVBORw0KGgoAAAANSUhEUgAAAAEAAAABCAYAAAAfFcSJAAAADUlEQVR42mP8z8BQDwAEhQGAhKmMIQAAAABJRU5ErkJggg=="
)


@pytest.fixture(name="sandbox_dirs")
def sandbox_dirs_fixture(tmp_path, monkeypatch):
    """Point the file routes at a temp output/input tree.

    Mirrors the fixture in `test_upload_export_hardening.py` — it is not in
    `conftest.py`, so it is redeclared rather than imported from a test module.
    """
    from api.routes import files as files_module

    output_dir = tmp_path / "output"
    input_dir = tmp_path / "input"
    output_dir.mkdir()
    input_dir.mkdir()
    monkeypatch.setattr(files_module, "OUTPUT_DIR", str(output_dir))
    monkeypatch.setattr(files_module, "INPUT_DIR", str(input_dir))
    return {"output": output_dir, "input": input_dir}


@pytest.fixture(name="seeded_asset")
def seeded_asset_fixture(sandbox_dirs, session):
    """An asset row whose bytes are on disk, so `/file` can serve it."""
    from core.entities import Asset

    rel = "default/shot.png"
    path = sandbox_dirs["output"] / rel
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_bytes(PNG_BYTES)

    asset = Asset(
        relative_path=rel,
        filename="shot.png",
        workspace="default",
        generated_at=datetime.now(timezone.utc),
    )
    session.add(asset)
    session.commit()
    session.refresh(asset)
    return asset.id


class TestCopyAssetDoesNotMoveTheOriginal:
    """The dashboard's Copy Asset button sent `copy: true`.

    `MoveAssetRequest` declares `copy_file`, so pydantic dropped `copy`,
    `copy_file` stayed False, and the handler took the `os.rename` branch: the
    "copy" MOVED the original file and the UI toasted "Asset copied". Silent
    data loss with a success message.

    The frontend is fixed to send `copy_file`, and the backend accepts the old
    spelling as an alias so a stale cached bundle cannot reproduce it.
    """

    def test_the_new_spelling_is_accepted(self):
        from api.routes.files import MoveAssetRequest

        assert MoveAssetRequest(workspace="main", copy_file=True).copy_file is True
        assert MoveAssetRequest(workspace="main", copy_file=False).copy_file is False

    def test_the_old_spelling_still_means_copy(self):
        """A cached bundle sending `copy: true` must not move the original."""
        from api.routes.files import MoveAssetRequest

        assert MoveAssetRequest(workspace="main", copy=True).copy_file is True

    def test_default_is_still_a_move(self):
        from api.routes.files import MoveAssetRequest

        assert MoveAssetRequest(workspace="main").copy_file is False

    def test_copy_true_reaches_the_copy_branch(self, client, seeded_asset):
        """End to end: the original file is still readable afterwards.

        This is the assertion that matters. The unit tests above only prove the
        field parses; this one proves a copy did not become a rename.
        """
        asset_id = seeded_asset
        source = client.get(f"/api/v2/assets/{asset_id}/file")
        assert source.status_code == 200, "the fixture asset must be readable first"

        copied = client.post(
            f"/api/v2/assets/{asset_id}/move",
            json={"workspace": "copy-probe", "copy_file": True},
        )
        assert copied.status_code == 200

        still_there = client.get(f"/api/v2/assets/{asset_id}/file")
        assert still_there.status_code == 200, (
            "after a copy the original must still be served; a 404 here means "
            "the copy branch fell through to os.rename"
        )

    def test_legacy_copy_spelling_does_not_move_either(self, client, seeded_asset):
        asset_id = seeded_asset
        client.post(
            f"/api/v2/assets/{asset_id}/move",
            json={"workspace": "copy-probe-legacy", "copy": True},
        )
        assert client.get(f"/api/v2/assets/{asset_id}/file").status_code == 200

    def test_a_move_really_does_move(self, client, seeded_asset, sandbox_dirs):
        """The other half of the pair: the fix must not have disabled moving.

        A test that only proves "nothing is destroyed" passes just as happily
        against a handler that never moves anything.
        """
        asset_id = seeded_asset
        moved = client.post(
            f"/api/v2/assets/{asset_id}/move",
            json={"workspace": "move-probe", "copy_file": False},
        )
        assert moved.status_code == 200
        assert moved.json()["relative_path"].startswith("move-probe/")

        assert client.get(f"/api/v2/assets/{asset_id}/file").status_code == 200
        assert not (sandbox_dirs["output"] / "default/shot.png").exists(), (
            "a move must leave the original path; if it still exists the "
            "handler silently became a copy and Move is broken"
        )
        assert (sandbox_dirs["output"] / "move-probe/shot.png").exists()
