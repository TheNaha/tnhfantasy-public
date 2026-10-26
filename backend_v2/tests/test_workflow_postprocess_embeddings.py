import pytest
from sqlmodel import Session

from core.entities import ModelFile, ModelV2, ModelVersion
from core.exceptions import ValidationError
from core.workflow_postprocess import (
    embedding_file_exists,
    postprocess_prompt_text,
)


def test_embedding_file_exists_on_disk(tmp_path, monkeypatch):
    embed_dir = tmp_path / "models" / "embeddings"
    embed_dir.mkdir(parents=True)
    (embed_dir / "badhandv4.safetensors").write_text("dummy")

    input_dir = tmp_path / "input"
    input_dir.mkdir(parents=True)

    from config import settings
    monkeypatch.setattr(settings, "input_dir", str(input_dir))

    assert embedding_file_exists("badhandv4") is True
    assert embedding_file_exists("badhandv4.safetensors") is True
    assert embedding_file_exists("nonexistent") is False


def test_embedding_file_exists_in_database_when_not_on_disk(tmp_path, session: Session, monkeypatch):
    # Ensure disk path has no embeddings
    input_dir = tmp_path / "input"
    input_dir.mkdir(parents=True)

    from config import settings
    monkeypatch.setattr(settings, "input_dir", str(input_dir))

    # Register embedding in DB
    model = ModelV2(
        name="EasyNegative",
        type="TextualInversion",
        directory="embeddings",
    )
    session.add(model)
    session.flush()

    version = ModelVersion(
        model_id=model.id,
        name="v1.0",
        base_model="SD 1.5",
    )
    session.add(version)
    session.flush()

    file_record = ModelFile(
        version_id=version.id,
        original_filename="EasyNegative.pt",
        storage_filename="EasyNegative.pt",
        size_kb=100,
        format="pt",
    )
    session.add(file_record)
    session.commit()

    # Should be detected via DB catalog
    assert embedding_file_exists("EasyNegative") is True
    assert embedding_file_exists("EasyNegative.pt") is True
    assert embedding_file_exists("nonexistent_embedding") is False

    # postprocess_prompt_text should succeed without ValidationError
    expanded = postprocess_prompt_text("masterpiece, embedding:EasyNegative, high quality")
    assert "embedding:EasyNegative" in expanded

    # Unregistered embedding raises ValidationError
    with pytest.raises(ValidationError) as exc_info:
        postprocess_prompt_text("masterpiece, embedding:unknown_embed")
    assert "unknown_embed" in str(exc_info.value)
