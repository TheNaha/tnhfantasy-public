from fastapi.testclient import TestClient
from api.main import app
from core.entities import Character


def test_generate_character_expressions_not_found():
    client = TestClient(app)
    res = client.post(
        "/api/v2/characters/nonexistent_char_id/expressions/generate",
        json={"emotions": ["happy", "sad"]},
    )
    assert res.status_code == 404


def test_generate_character_expressions_success(session, monkeypatch):
    client = TestClient(app)

    # Create character in DB
    char = Character(
        id="char_test_exp_01",
        name="Seraphina",
        description="A radiant paladin with silver hair",
    )
    session.add(char)
    session.commit()

    # Mock submit_job to avoid needing live ComfyUI
    submitted_jobs = []

    class FakeJob:
        def __init__(self, job_id):
            self.id = job_id

    async def fake_submit_job(sess, workflow, meta, task_type="image"):
        job_id = f"job_{len(submitted_jobs) + 1}"
        submitted_jobs.append({"id": job_id, "meta": meta, "workflow": workflow})
        return FakeJob(job_id)

    monkeypatch.setattr("services.job_submission_service.submit_job", fake_submit_job)

    res = client.post(
        f"/api/v2/characters/{char.id}/expressions/generate",
        json={
            "emotions": ["neutral", "happy", "angry"],
            "seed": 4242,
        },
    )

    assert res.status_code == 200
    data = res.json()
    assert len(data["job_ids"]) == 3
    assert data["seed"] == 4242
    assert len(submitted_jobs) == 3
    assert submitted_jobs[0]["meta"]["emotion"] == "neutral"
    assert submitted_jobs[1]["meta"]["emotion"] == "happy"
    assert submitted_jobs[2]["meta"]["emotion"] == "angry"
