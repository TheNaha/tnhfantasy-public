import base64
import io
import json
import zipfile

PNG_BYTES = base64.b64decode(
    "iVBORw0KGgoAAAANSUhEUgAAAAEAAAABCAQAAAC1HAwCAAAAC0lEQVR42mNk+A8AAQUBAScY42YAAAAASUVORK5CYII="
)


def _charx_bytes(card: dict, include_avatar: bool = True) -> bytes:
    output = io.BytesIO()
    with zipfile.ZipFile(output, "w", compression=zipfile.ZIP_DEFLATED) as archive:
        archive.writestr("card.json", json.dumps(card))
        if include_avatar:
            archive.writestr("assets/main.png", PNG_BYTES)
    return output.getvalue()


def _card(name: str = "Archivist") -> dict:
    return {
        "spec": "chara_card_v3",
        "spec_version": "3.0",
        "data": {
            "name": name,
            "description": "Keeps archives.",
            "custom_field": {"kept": True},
        },
        "root_field": "preserved",
    }


def test_parse_charx_preserves_card_and_manifest():
    from core.character_cards import parse_card_file

    mapped, avatar = parse_card_file(_charx_bytes(_card()), "archivist.charx")
    assert mapped["name"] == "Archivist"
    assert mapped["card_metadata"]["data"]["custom_field"] == {"kept": True}
    assert mapped["card_metadata"]["charx_assets"] == ["assets/main.png"]
    assert avatar == PNG_BYTES


def test_charx_route_import_and_export(client, tmp_path, monkeypatch):
    import config as app_config

    monkeypatch.setattr(app_config.settings, "character_avatar_dir", str(tmp_path / "characters"))
    response = client.post(
        "/api/v2/characters/import",
        files={"file": ("archivist.charx", _charx_bytes(_card()), "application/zip")},
    )
    assert response.status_code == 200, response.text
    imported = response.json()

    exported = client.get(f"/api/v2/characters/{imported['id']}/export?format=charx")
    assert exported.status_code == 200
    assert exported.headers["content-type"].startswith("application/zip")
    with zipfile.ZipFile(io.BytesIO(exported.content)) as archive:
        payload = json.loads(archive.read("card.json"))
        assert payload["data"]["name"] == "Archivist"
        assert payload["data"]["custom_field"] == {"kept": True}
        assert "assets/main.png" in archive.namelist()
