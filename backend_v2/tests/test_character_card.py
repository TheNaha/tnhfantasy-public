"""Tests for character card export/import (SillyTavern-compatible PNG format)."""
import base64
import io
import json
from unittest.mock import patch

import pytest
from PIL import Image, PngImagePlugin
from sqlmodel import Session

from core.entities import Character


def _make_test_character(session: Session, name: str = "Test Character") -> Character:
    char = Character(
        name=name,
        description="A test character for export/import",
        personality="Brave and loyal",
        scenario="A dark dungeon",
        first_mes="Hello, adventurer!",
        mes_example="<START>\n{{char}}: Greetings!\n{{user}}: Hi there!",
        creator_notes="Test notes",
        system_prompt="You are a helpful assistant.",
        visual_tags=["1boy", "warrior"],
    )
    session.add(char)
    session.commit()
    session.refresh(char)
    return char


def _create_card_png(name: str = "Imported Char") -> bytes:
    """Create a minimal PNG with a chara tEXt chunk."""
    card_data = {
        "spec": "chara2.0",
        "spec_version": "2.0",
        "data": {
            "name": name,
            "description": "An imported character",
            "personality": "Mysterious",
            "scenario": "A dark forest",
            "first_mes": "Who goes there?",
            "mes_example": "",
            "creator_notes": "",
            "system_prompt": "",
            "post_history_instructions": "",
            "alternate_greetings": [],
            "creator": "",
            "character_version": "1.0",
            "tags": ["elf", "archer"],
            "extensions": {
                "lora_triggers": [],
                "visual_tags": ["elf", "archer"],
                "voice_profile": "",
            },
        },
    }
    json_str = json.dumps(card_data, ensure_ascii=False)
    encoded = base64.b64encode(json_str.encode("utf-8")).decode("ascii")

    img = Image.new("RGBA", (1, 1), (0, 0, 0, 0))
    metadata = PngImagePlugin.PngInfo()
    metadata.add_text("chara", encoded)

    output = io.BytesIO()
    img.save(output, format="PNG", pnginfo=metadata)
    return output.getvalue()


class TestCharacterCardExport:
    def test_export_returns_png(self, client, session):
        char = _make_test_character(session)
        response = client.get(f"/api/v2/characters/{char.id}/export")
        assert response.status_code == 200
        assert "image/png" in response.headers.get("content-type", "")

    def test_export_contains_chara_chunk(self, client, session):
        char = _make_test_character(session)
        response = client.get(f"/api/v2/characters/{char.id}/export")
        png_bytes = response.content

        img = Image.open(io.BytesIO(png_bytes))
        assert "chara" in img.info

    def test_export_chara_data_is_valid_json(self, client, session):
        char = _make_test_character(session)
        response = client.get(f"/api/v2/characters/{char.id}/export")
        png_bytes = response.content

        img = Image.open(io.BytesIO(png_bytes))
        decoded = base64.b64decode(img.info["chara"])
        card_data = json.loads(decoded)

        assert "data" in card_data
        assert card_data["data"]["name"] == char.name
        assert card_data["data"]["description"] == char.description
        assert card_data["data"]["personality"] == char.personality

    def test_export_404_for_missing_character(self, client, session):
        response = client.get("/api/v2/characters/nonexistent-id/export")
        assert response.status_code == 404

    def test_export_filename_header(self, client, session):
        char = _make_test_character(session, name="My Hero")
        response = client.get(f"/api/v2/characters/{char.id}/export")
        assert "My_Hero" in response.headers.get("content-disposition", "")

    def test_export_without_avatar_succeeds(self, client, session):
        """Export should work even without an avatar image."""
        char = _make_test_character(session)
        char.avatar_path = None
        session.add(char)
        session.commit()

        response = client.get(f"/api/v2/characters/{char.id}/export")
        assert response.status_code == 200


class TestCharacterCardImport:
    def test_import_creates_character(self, client, session, tmp_path):
        png_bytes = _create_card_png("Elven Archer")
        with patch("api.routes.world_vault.characters.app_config") as mock_cfg:
            mock_cfg.settings.character_avatar_dir = str(tmp_path)
            response = client.post(
                "/api/v2/characters/import",
                files={"file": ("test.png", png_bytes, "image/png")},
            )
        assert response.status_code == 200, response.text
        data = response.json()
        assert data["name"] == "Elven Archer"

    def test_import_character_persists_to_db(self, client, session, tmp_path):
        png_bytes = _create_card_png("Forest Elf")
        with patch("api.routes.world_vault.characters.app_config") as mock_cfg:
            mock_cfg.settings.character_avatar_dir = str(tmp_path)
            response = client.post(
                "/api/v2/characters/import",
                files={"file": ("test.png", png_bytes, "image/png")},
            )
        assert response.status_code == 200, response.text
        char_id = response.json()["id"]

        char = session.get(Character, char_id)
        assert char is not None
        assert char.name == "Forest Elf"
        assert char.personality == "Mysterious"
        assert "elf" in (char.visual_tags or [])

    def test_import_rejects_non_png(self, client, session):
        response = client.post(
            "/api/v2/characters/import",
            files={"file": ("test.txt", b"not a png", "text/plain")},
        )
        assert response.status_code == 400

    def test_import_rejects_png_without_chara(self, client, session):
        img = Image.new("RGBA", (1, 1), (0, 0, 0, 0))
        output = io.BytesIO()
        img.save(output, format="PNG")
        png_bytes = output.getvalue()

        response = client.post(
            "/api/v2/characters/import",
            files={"file": ("test.png", png_bytes, "image/png")},
        )
        assert response.status_code == 400
        assert "chara" in response.json().get("error", "").lower() or "character data" in response.json().get("error", "").lower()
