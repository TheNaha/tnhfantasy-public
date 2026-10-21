"""`jobs.default_limit` and `jobs.max_in_memory` are gone.

They were user-editable settings, with a description in the settings schema
and a validation rule, and nothing read them: the job list limit is the
hardcoded `limit: int = 20` on `GET /api/jobs`, and the in-process queue is
an unbounded `asyncio.Queue()`. A settings page that offered them promised
an effect that never happened.

`config.get_max_concurrent_jobs()` went the same way from the other
direction: the queue reads `jobs.max_concurrent` straight out of the config
dict, so the accessor had no callers at all.

A config.json that still carries the removed keys keeps working — they are
ignored, not fatal.
"""

import json
import os

import config as cfg


def test_the_removed_settings_are_not_in_the_defaults():
    assert "default_limit" not in cfg.DEFAULT_CONFIG["jobs"]
    assert "max_in_memory" not in cfg.DEFAULT_CONFIG["jobs"]


def test_the_accessors_are_gone():
    for name in (
        "get_default_jobs_limit",
        "get_max_jobs_in_memory",
        "get_max_concurrent_jobs",
    ):
        assert not hasattr(cfg, name), f"config.{name} is still there"


def test_the_settings_schema_no_longer_documents_them(client):
    """The schema is what the settings page builds its controls from, so a
    field that is not documented here is not offered."""
    response = client.get("/api/settings/schema")
    assert response.status_code == 200
    jobs = response.json()["schema"]["jobs"]["fields"]

    assert "default_limit" not in jobs
    assert "max_in_memory" not in jobs
    # The section itself is still there, with the setting that does work.
    assert "max_concurrent" in jobs


def test_a_persisted_config_with_the_removed_keys_still_loads(tmp_path, monkeypatch):
    """An operator's config.json from before the removal must not break
    startup: the keys are ignored, not fatal."""
    config_path = tmp_path / "config.json"
    config_path.write_text(
        json.dumps(
            {
                "jobs": {
                    "default_limit": 30,
                    "max_in_memory": 100,
                    "max_concurrent": 5,
                }
            }
        ),
        encoding="utf-8",
    )

    monkeypatch.setattr(cfg, "_config_path", str(config_path))
    loaded = cfg.load_config()

    assert loaded["jobs"]["max_concurrent"] == 5
    # The stale keys are carried along but read by nothing.
    assert loaded["jobs"]["default_limit"] == 30


def test_the_removed_keys_are_not_validated_any_more():
    """A validation rule for a setting that does not exist is a rule that
    rejects a value nobody can use."""
    cfg._validate_config({"jobs": {"max_concurrent": 5}})


def test_a_stale_key_in_a_persisted_file_does_not_break_the_settings_route(
    client, tmp_path, monkeypatch
):
    config_path = tmp_path / "config.json"
    config_path.write_text(
        json.dumps({"jobs": {"default_limit": 30, "max_in_memory": 100}}),
        encoding="utf-8",
    )
    monkeypatch.setattr(cfg, "_config_path", str(config_path))
    cfg.load_config()

    response = client.get("/api/settings")

    assert response.status_code == 200
    assert os.path.exists(config_path)
