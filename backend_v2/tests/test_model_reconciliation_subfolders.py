import pytest
from sqlmodel import Session

from core.entities import ModelV2, ProviderVersionStatus
from infrastructure.repositories.model_repo_v2 import ModelRepositoryV2
from services.model_reconciliation import (
    ModelReconciliationService,
    split_canonical_storage_path,
)


def test_split_canonical_storage_path():
    # Shallow path
    assert split_canonical_storage_path("models/checkpoints/v1-5-pruned.safetensors") == (
        "checkpoints",
        "v1-5-pruned.safetensors",
        "v1-5-pruned.safetensors",
    )
    # Deep subfolder path
    assert split_canonical_storage_path("models/checkpoints/sdxl/juggernaut_v9.safetensors") == (
        "checkpoints",
        "sdxl/juggernaut_v9.safetensors",
        "juggernaut_v9.safetensors",
    )
    # Deeper nested subfolder path
    assert split_canonical_storage_path("models/loras/style/anime/retro.safetensors") == (
        "loras",
        "style/anime/retro.safetensors",
        "retro.safetensors",
    )
    # Two-segment directory
    assert split_canonical_storage_path("models/ultralytics/bbox/face_yolov8n.pt") == (
        "ultralytics/bbox",
        "face_yolov8n.pt",
        "face_yolov8n.pt",
    )
    # Two-segment directory with subfolder
    assert split_canonical_storage_path("models/ultralytics/seg/sub/seg_model.pt") == (
        "ultralytics/seg",
        "sub/seg_model.pt",
        "seg_model.pt",
    )
    # Path without 'models/' prefix
    assert split_canonical_storage_path("checkpoints/sdxl/model.safetensors") == (
        "checkpoints",
        "sdxl/model.safetensors",
        "model.safetensors",
    )
    # Invalid paths
    assert split_canonical_storage_path("") is None
    assert split_canonical_storage_path("just_a_filename.safetensors") is None


@pytest.mark.asyncio
async def test_register_discovered_files_preserves_canonical_directory_and_subfolder(session: Session):
    service = ModelReconciliationService(session)
    repo = ModelRepositoryV2(session)

    files = [
        {
            "path": "models/checkpoints/sdxl/juggernaut_v9.safetensors",
            "size_bytes": 1024 * 1024 * 100,
        },
        {
            "path": "models/ultralytics/bbox/face_yolov8n.pt",
            "size_bytes": 1024 * 50,
        },
    ]

    res = await service.register_discovered_files("test-prov-1", files)
    assert res["imported"] == 2
    assert res["errors"] == 0

    # Verify Checkpoint model
    ckpt_file = repo.get_file_by_storage_path("checkpoints", "sdxl/juggernaut_v9.safetensors")
    assert ckpt_file is not None
    assert ckpt_file.storage_filename == "juggernaut_v9.safetensors"
    assert ckpt_file.original_filename == "sdxl/juggernaut_v9.safetensors"

    # Also retrievable by basename
    ckpt_file_base = repo.get_file_by_storage_path("checkpoints", "juggernaut_v9.safetensors")
    assert ckpt_file_base is not None
    assert ckpt_file_base.id == ckpt_file.id

    # Verify model table properties
    ckpt_model = session.get(ModelV2, ckpt_file.version.model_id)
    assert ckpt_model.directory == "checkpoints"
    assert ckpt_model.type == "Checkpoint"

    # Verify ProviderVersionStatus
    pvs = session.query(ProviderVersionStatus).filter_by(file_id=ckpt_file.id, provider_id="test-prov-1").first()
    assert pvs is not None
    assert pvs.status == "ready"
    assert pvs.storage_path == "models/checkpoints/sdxl/juggernaut_v9.safetensors"

    # Verify ultralytics model
    bbox_file = repo.get_file_by_storage_path("ultralytics/bbox", "face_yolov8n.pt")
    assert bbox_file is not None
    bbox_model = session.get(ModelV2, bbox_file.version.model_id)
    assert bbox_model.directory == "ultralytics/bbox"
    assert bbox_model.type == "Other"

    # Verify get_file_ids_by_storage_paths resolves the subfolder path
    path_to_id = repo.get_file_ids_by_storage_paths([
        "models/checkpoints/sdxl/juggernaut_v9.safetensors",
        "models/ultralytics/bbox/face_yolov8n.pt",
    ])
    assert path_to_id.get("models/checkpoints/sdxl/juggernaut_v9.safetensors") == ckpt_file.id
    assert path_to_id.get("models/ultralytics/bbox/face_yolov8n.pt") == bbox_file.id
