import pytest
from core.exceptions import ValidationError
from core.workflow_postprocess import (
    expand_prompt_shortcuts,
    extract_embedding_names,
    postprocess_prompt_text,
)


def test_expand_prompt_shortcuts_preserves_embeddings(monkeypatch):
    monkeypatch.setattr(
        "config.get_config",
        lambda: {
            "generator": {
                "prompt_shortcuts": {
                    "lazypos": "masterpiece, newest, absurdres",
                    "lazyneg": "worst quality, bad anatomy",
                }
            }
        },
    )

    text = "1girl, embedding:lazypos, (embedding:lazyneg:1.1), lazypos, lazyneg"
    expanded = expand_prompt_shortcuts(text)

    # Embedding tokens must remain untouched
    assert "embedding:lazypos" in expanded
    assert "(embedding:lazyneg:1.1)" in expanded
    assert "embedding:masterpiece" not in expanded

    # Standalone shortcuts should be expanded
    assert "masterpiece, newest, absurdres" in expanded
    assert "worst quality, bad anatomy" in expanded


def test_extract_embedding_names_variants():
    text = (
        "1girl, (embedding:lazypos:1.1), (embedding:style/lazyreal.safetensors:0.9), "
        "embedding:easynegative, (embedding:lazyneg), embedding:sub-dir_1/badhandv4.pt"
    )
    names = extract_embedding_names(text)
    assert names == [
        "lazypos",
        "style/lazyreal.safetensors",
        "easynegative",
        "lazyneg",
        "sub-dir_1/badhandv4.pt",
    ]


def test_postprocess_prompt_text_raises_on_missing(monkeypatch):
    monkeypatch.setattr(
        "config.get_config",
        lambda: {"generator": {"prompt_shortcuts": {}}},
    )
    monkeypatch.setattr(
        "core.workflow_postprocess.embedding_file_exists",
        lambda name: name == "installed_emb",
    )

    # Succeeds when installed
    ok = postprocess_prompt_text("1girl, (embedding:installed_emb:1.2)")
    assert ok == "1girl, (embedding:installed_emb:1.2)"

    # Fails when missing
    with pytest.raises(ValidationError) as exc:
        postprocess_prompt_text("1girl, embedding:missing_emb")
    assert "Embedding file(s) not found" in str(exc.value)
    assert "missing_emb" in str(exc.value)
