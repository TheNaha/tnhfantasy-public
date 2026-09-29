"""Tests for Voice Model CRUD and preview endpoints."""
import pytest

from core.entities import VoiceModel, Character


@pytest.fixture
def character_with_voice(session):
    char = Character(name="TestVoiceChar", description="test")
    session.add(char)
    session.commit()
    session.refresh(char)
    return char


@pytest.fixture
def voice_model(session, character_with_voice):
    vm = VoiceModel(
        name="Test XTTS Voice",
        description="A test voice model",
        type="xtts",
        voice_profile="test_speaker",
        language="en",
        preview_text="Hello, this is a test.",
        character_id=character_with_voice.id,
    )
    session.add(vm)
    session.commit()
    session.refresh(vm)
    return vm


def test_list_voices(client, session, character_with_voice, voice_model):
    response = client.get("/api/v2/voices")
    assert response.status_code == 200
    data = response.json()
    assert len(data) >= 1
    assert any(v["name"] == "Test XTTS Voice" for v in data)


def test_list_voices_filtered_by_character(client, session, character_with_voice, voice_model):
    response = client.get(f"/api/v2/voices?character_id={character_with_voice.id}")
    assert response.status_code == 200
    data = response.json()
    assert len(data) == 1
    assert data[0]["name"] == "Test XTTS Voice"


def test_get_voice(client, session, voice_model):
    response = client.get(f"/api/v2/voices/{voice_model.id}")
    assert response.status_code == 200
    data = response.json()
    assert data["name"] == "Test XTTS Voice"
    assert data["type"] == "xtts"
    assert data["voice_profile"] == "test_speaker"


def test_get_voice_not_found(client):
    response = client.get("/api/v2/voices/nonexistent-id")
    assert response.status_code == 404


def test_create_voice(client, session):
    response = client.post("/api/v2/voices", json={
        "name": "New Voice",
        "type": "bark",
        "language": "en",
        "preview_text": "Hi there",
    })
    assert response.status_code == 200
    data = response.json()
    assert data["name"] == "New Voice"
    assert data["type"] == "bark"


def test_update_voice(client, session, voice_model):
    response = client.put(f"/api/v2/voices/{voice_model.id}", json={
        "name": "Updated Voice",
        "language": "es",
    })
    assert response.status_code == 200
    data = response.json()
    assert data["name"] == "Updated Voice"
    assert data["language"] == "es"


def test_patch_voice(client, session, voice_model):
    response = client.patch(f"/api/v2/voices/{voice_model.id}", json={
        "preview_text": "New preview text"
    })
    assert response.status_code == 200
    data = response.json()
    assert data["preview_text"] == "New preview text"


def test_delete_voice(client, session, voice_model):
    response = client.delete(f"/api/v2/voices/{voice_model.id}")
    assert response.status_code == 200
    # Verify it's gone
    response = client.get(f"/api/v2/voices/{voice_model.id}")
    assert response.status_code == 404


def test_voice_preview(client, session, voice_model, tts_capable):
    response = client.post(f"/api/v2/voices/{voice_model.id}/preview")
    assert response.status_code == 200
    data = response.json()
    assert data["voice_id"] == voice_model.id
    assert data["job_id"]

    from core.entities import Job
    job = session.get(Job, data["job_id"])
    assert job is not None
    # Was "image", with the comment "TTS runs on the image_worker adapter". That
    # was true of the code path and false of the capability: no provider image
    # had a text-to-speech node, so the job went to a worker that could not build
    # its graph. The dedicated TTS app is a different provider capability, so the
    # task type has to say so.
    assert job.task_type == "tts"
    metadata = job.metadata_ or {}
    assert metadata.get("type") == "voice_preview"
    assert metadata.get("voice_id") == voice_model.id


def test_voice_preview_missing_voice(client, tts_capable):
    response = client.post("/api/v2/voices/nonexistent-id/preview")
    assert response.status_code == 404


def test_voice_preview_refuses_when_no_provider_can_serve_tts(client, voice_model):
    """The failure this replaces: a job accepted, queued, and then died inside a
    container on a ComfyUI graph naming a node that was never installed. Now it
    is refused before a job row exists, with a message that says what to do."""
    response = client.post(f"/api/v2/voices/{voice_model.id}/preview")
    assert response.status_code == 400
    body = response.text.lower()
    assert "tts" in body
    assert "capabilit" in body, "the error should name the missing capability"


def test_voice_preview_no_preview_text(client, session):
    vm = VoiceModel(name="NoPreview", type="xtts")
    session.add(vm)
    session.commit()
    session.refresh(vm)
    response = client.post(f"/api/v2/voices/{vm.id}/preview")
    assert response.status_code == 400  # ComfyError raised for missing preview_text
