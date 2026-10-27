from services.wildcard_service import WildcardService


def test_wildcard_service_expand_braces():
    text = "1girl, {cyberpunk|fantasy|steampunk} outfit, {blue|red} eyes"
    expanded = WildcardService.expand_wildcards(text, seed=42)

    assert "{" not in expanded
    assert "}" not in expanded
    assert any(style in expanded for style in ["cyberpunk", "fantasy", "steampunk"])
    assert any(color in expanded for color in ["blue", "red"])


def test_wildcard_service_nested_braces():
    text = "{light|{vibrant|dark}} blue sky"
    expanded = WildcardService.expand_wildcards(text, seed=123)

    assert "{" not in expanded
    assert "}" not in expanded
    assert any(choice in expanded for choice in ["light blue sky", "vibrant blue sky", "dark blue sky"])


def test_wildcard_service_weighted_braces():
    text = "{10::rare_artifact|0.001::impossible_relic}"
    expanded = WildcardService.expand_wildcards(text, seed=99)
    assert expanded == "rare_artifact"


def test_wildcard_service_file_resolution(tmp_path, monkeypatch):
    wildcards_dir = tmp_path / "wildcards"
    wildcards_dir.mkdir()
    outfits_file = wildcards_dir / "hairstyles.txt"
    outfits_file.write_text("# Comment line\ntwin braids\nponytail\nshort bob\n", encoding="utf-8")

    monkeypatch.setattr("services.wildcard_service._resolve_wildcard_dirs", lambda: [str(wildcards_dir)])

    text = "1girl with __hairstyles__, smiling"
    expanded = WildcardService.expand_wildcards(text, seed=42)

    assert "__hairstyles__" not in expanded
    assert any(hair in expanded for hair in ["twin braids", "ponytail", "short bob"])


def test_wildcard_service_nonexistent_wildcard_remains():
    text = "1girl with __missing_wildcard_token__, smiling"
    expanded = WildcardService.expand_wildcards(text, seed=42)
    assert expanded == "1girl with __missing_wildcard_token__, smiling"
