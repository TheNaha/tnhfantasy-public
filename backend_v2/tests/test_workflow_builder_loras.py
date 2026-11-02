from core.workflow_builder import (
    GeneratorOptions,
    LoraOption,
    WorkflowBuilder,
    extract_prompt_loras,
)


def test_extract_prompt_loras_basic():
    prompt = "1girl, solo, <lora:rem_swimsuit:0.8>, blue hair, <lora:maid_outfit>"
    loras, cleaned = extract_prompt_loras(prompt)

    assert len(loras) == 2
    assert loras[0].name == "rem_swimsuit"
    assert loras[0].strength == 0.8
    assert loras[1].name == "maid_outfit"
    assert loras[1].strength == 1.0

    assert "<lora:" not in cleaned
    assert "1girl, solo, blue hair" in cleaned


def test_workflow_builder_extracts_loras_from_prompt(monkeypatch):
    monkeypatch.setattr(
        "core.workflow_builder.resolve_lora_name",
        lambda name: f"{name}.safetensors",
    )
    monkeypatch.setattr(
        "core.workflow_postprocess.embedding_file_exists",
        lambda name: True,
    )

    builder = WorkflowBuilder()
    options = GeneratorOptions(
        prompt="1girl, <lora:rem_bikini:0.75>, smiling",
        negativePrompt="bad quality",
        checkpoint="model.safetensors",
        loras=[LoraOption(name="existing_lora", strength=0.9)],
    )

    graph = builder.build(options)

    # Both existing and prompt-extracted LoRAs should be in the graph nodes
    lora_loaders = [
        node["inputs"]
        for node in graph.values()
        if node.get("class_type") == "LoraLoader"
    ]
    assert len(lora_loaders) == 2
    names = {l["lora_name"] for l in lora_loaders}
    assert "existing_lora.safetensors" in names
    assert "rem_bikini.safetensors" in names

    # Prompt text in CLIPTextEncode must NOT have <lora:...>
    text_encodes = [
        node["inputs"]["text"]
        for node in graph.values()
        if node.get("class_type") == "CLIPTextEncode"
    ]
    for text in text_encodes:
        assert "<lora:" not in text


def test_workflow_builder_resolves_cjk_checkpoint_and_loras(monkeypatch):
    import unicodedata
    nfd_ckpt = unicodedata.normalize("NFD", "한국어_체크포인트.safetensors")
    nfc_ckpt = unicodedata.normalize("NFC", "한국어_체크포인트.safetensors")

    monkeypatch.setattr(
        "core.workflow_builder.resolve_checkpoint_name",
        lambda name: nfd_ckpt if unicodedata.normalize("NFC", name) == nfc_ckpt else name,
    )
    monkeypatch.setattr(
        "core.workflow_builder.resolve_lora_name",
        lambda name: "anime_lora.safetensors" if "anime" in name else name,
    )
    monkeypatch.setattr(
        "core.workflow_postprocess.embedding_file_exists",
        lambda name: True,
    )

    builder = WorkflowBuilder()
    options = GeneratorOptions(
        prompt="1girl",
        negativePrompt="bad quality",
        checkpoint=nfc_ckpt,
        loras=[LoraOption(name="anime", strength=0.8)],
    )
    graph = builder.build(options)
    # Find CheckpointLoaderSimple node
    ckpt_nodes = [n for n in graph.values() if n.get("class_type") == "CheckpointLoaderSimple"]
    assert len(ckpt_nodes) == 1
    assert ckpt_nodes[0]["inputs"]["ckpt_name"] == nfd_ckpt

    lora_nodes = [n for n in graph.values() if n.get("class_type") == "LoraLoader"]
    assert len(lora_nodes) == 1
    assert lora_nodes[0]["inputs"]["lora_name"] == "anime_lora.safetensors"

