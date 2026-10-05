"""`ModelCivitaiSyncService.autopopulate_model` version linking.

The version-matching loop read

    matched_version = civitai_by_id.get(civ_id) or civitai_by_name.get(civ_name) or unlinked_v1
    if matched_version is unlinked_v1:

which broke in two ways at once:

* `unlinked_v1` is `None` once the placeholder has been consumed, and
  `None is None` is True — so the *second* CivitAI version with no local match
  took the branch and raised `AttributeError: 'NoneType' object has no
  attribute 'name'`. The route turned that into a 422 from
  `POST /api/v2/models/{id}/autopopulate`; `autopopulate-all` counted it failed.
* The placeholder was *renamed* and then immediately replaced by a brand-new
  `ModelVersion`, so autopopulating an auto-discovered model left two
  same-named versions: the original still holding the `ModelFile`s but with
  `civitai_version_id = NULL`, and the new one linked to CivitAI with none.

The placeholder is now adopted — it keeps its files and gains the CivitAI id.
"""
import pytest
from sqlmodel import Session, SQLModel, create_engine
from sqlmodel.pool import StaticPool

from core.entities import ModelFile, ModelV2, ModelVersion
from services.model_civitai_sync import ModelCivitaiSyncService


@pytest.fixture(name="engine")
def engine_fixture():
    engine = create_engine(
        "sqlite://",
        connect_args={"check_same_thread": False},
        poolclass=StaticPool,
    )
    SQLModel.metadata.create_all(engine)
    return engine


@pytest.fixture(name="session")
def session_fixture(engine):
    with Session(engine) as session:
        yield session


def _placeholder_model(session: Session) -> tuple[ModelV2, ModelVersion]:
    """An auto-discovered model: one unlinked `v1.0` version holding one file.

    This is the shape `services/model_reconciliation.py:144` produces.
    """
    model = ModelV2(name="Auto-discovered checkpoint", type="Checkpoint", directory="models/checkpoints")
    session.add(model)
    session.commit()
    version = ModelVersion(model_id=model.id, name="v1.0")
    session.add(version)
    session.commit()
    session.add(
        ModelFile(
            version_id=version.id,
            original_filename="auto.safetensors",
            storage_filename="auto.safetensors",
        )
    )
    session.commit()
    return model, version


def _civitai_payload(version_ids: list[int]) -> dict:
    return {
        "id": 555,
        "name": "Real Checkpoint Name",
        "type": "Checkpoint",
        "nsfw": False,
        "description": "from civitai",
        "creator": {"username": "someone", "image": ""},
        "tags": ["anime"],
        "modelVersions": [
            {
                "id": vid,
                "name": f"CivitAI release {idx + 1}",
                "baseModel": "SDXL",
                "description": "",
                "trainedWords": [],
                "files": [{"id": vid * 10, "primary": True, "sizeKB": 2048, "downloadUrl": "https://x/y"}],
            }
            for idx, vid in enumerate(version_ids)
        ],
    }


def _patch_civitai(monkeypatch, payload: dict) -> None:
    async def _get_civitai_model(self, civitai_id):
        return payload

    from services.external_model_service import ExternalModelService

    monkeypatch.setattr(ExternalModelService, "get_civitai_model", _get_civitai_model)


@pytest.mark.asyncio
async def test_two_unmatched_versions_no_longer_raise(session, monkeypatch):
    """The reported crash: iteration 2+ with `unlinked_v1` already consumed."""
    model, _ = _placeholder_model(session)
    _patch_civitai(monkeypatch, _civitai_payload([9001, 9002]))

    service = ModelCivitaiSyncService(session)
    result = await service.autopopulate_model(model.id, target_civitai_id=555)

    assert result.get("civitai_model_id") == 555
    versions = session.query(ModelVersion).filter(ModelVersion.model_id == model.id).all()
    assert len(versions) == 2, "one version per CivitAI version, no more"
    assert {v.civitai_version_id for v in versions} == {9001, 9002}


@pytest.mark.asyncio
async def test_the_placeholder_is_adopted_so_its_files_stay_linked(session, monkeypatch):
    """The silent half of the bug: no duplicate version, files not stranded."""
    model, placeholder = _placeholder_model(session)
    _patch_civitai(monkeypatch, _civitai_payload([9001]))

    service = ModelCivitaiSyncService(session)
    await service.autopopulate_model(model.id, target_civitai_id=555)

    versions = session.query(ModelVersion).filter(ModelVersion.model_id == model.id).all()
    assert len(versions) == 1, "the placeholder was adopted, not duplicated"

    adopted = versions[0]
    assert adopted.id == placeholder.id
    assert adopted.civitai_version_id == 9001

    files = session.query(ModelFile).filter(ModelFile.version_id == adopted.id).all()
    assert len(files) == 1, "the file stayed on the version that is now linked"


@pytest.mark.asyncio
async def test_an_already_linked_version_is_reused_not_duplicated(session, monkeypatch):
    """A second autopopulate of the same model must be idempotent in row count."""
    model, _ = _placeholder_model(session)
    _patch_civitai(monkeypatch, _civitai_payload([9001, 9002]))

    service = ModelCivitaiSyncService(session)
    await service.autopopulate_model(model.id, target_civitai_id=555)
    after_first = session.query(ModelVersion).filter(ModelVersion.model_id == model.id).count()

    await service.autopopulate_model(model.id, target_civitai_id=555)
    after_second = session.query(ModelVersion).filter(ModelVersion.model_id == model.id).count()

    assert after_first == 2
    assert after_second == 2, "re-running autopopulate created more versions"
