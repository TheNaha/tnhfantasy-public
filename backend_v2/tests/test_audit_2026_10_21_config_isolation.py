"""The test suite must never write the operator's live config.json
(audit-2026-10-21 §new).

`PUT /api/settings` persists to `config._config_path`, and in the test
suite that path is the operator's real `backend_v2/config.json`. So running
the suite rewrote the live configuration.

Two per-file fixtures tried to compensate by RESTORING the file at
teardown, and both are defeated by the suite's parallelism:

  - the live config is wrong for the whole run, and
  - with eight xdist workers, worker A's restore can land before worker
    B's write, so the file is left with worker B's value.

This was not hypothetical: a suite run left the live
`jobs.max_concurrent` at 3 instead of the operator's 5, and rewrote the
whole file from the defaults - so a setting nobody touched changed, and
every section the operator's file predated was replaced by a default.

The fix is not another restore. It is to make the write go somewhere else:
every test gets a private copy of the operator's config.
"""

import json
from pathlib import Path


import config as cfg

LIVE_CONFIG = Path(__file__).resolve().parents[1] / "config.json"


def test_the_live_config_is_never_the_write_target(_isolate_config_file):
    """The autouse fixture points `config._config_path` at a copy."""
    assert Path(cfg._config_path) != LIVE_CONFIG
    assert Path(cfg._config_path).exists()


def test_a_settings_write_does_not_touch_the_live_config(client):
    """The regression itself: a settings PUT must not reach the live file."""
    before = LIVE_CONFIG.read_bytes()

    response = client.put("/api/settings", json={"jobs": {"max_concurrent": 3}})
    assert response.status_code == 200

    assert LIVE_CONFIG.read_bytes() == before, (
        "the settings route wrote the operator's live config.json"
    )


def test_a_settings_reset_does_not_touch_the_live_config(client):
    """`POST /api/settings/reset` rewrites the whole file from the defaults.

    It is the most destructive write in the app, and it used to land on the
    operator's file.
    """
    before = LIVE_CONFIG.read_bytes()

    response = client.post("/api/settings/reset")
    assert response.status_code == 200

    assert LIVE_CONFIG.read_bytes() == before, (
        "the settings reset rewrote the operator's live config.json"
    )


def test_the_fixture_still_sees_the_operator_settings():
    """The copy is seeded from the live file, so a test that depends on the
    operator's configuration still sees it - it just cannot damage it."""
    live = json.loads(LIVE_CONFIG.read_text())
    isolated = json.loads(Path(cfg._config_path).read_text())
    assert isolated["jobs"]["max_concurrent"] == live["jobs"]["max_concurrent"]


def test_the_live_config_is_valid_json_and_has_the_jobs_section():
    """A cheap tripwire: the live file is the one the app reads on boot, and
    a truncated or rewritten one is a silent outage."""
    live = json.loads(LIVE_CONFIG.read_text())
    assert "jobs" in live
    assert "max_concurrent" in live["jobs"]
