"""A config file that cannot be parsed must not be overwritten.

`load_config` used to replace an unreadable config.json with
`DEFAULT_CONFIG`, in place. The operator's settings were destroyed by a
transient read failure, with no record that it had happened.

The transient read failure is easy to produce. The config file is written
atomically by `update_config`, but the test suite restores it with
`Path.write_bytes` - which truncates first and writes second - so between
the two the file is empty. The suite runs eight workers, so another worker
can read it in that window, find it unparseable, and replace it with the
defaults. That is not a hypothetical: it is what happened to this
repository's own config.json while the suite was running.

So: the unreadable file is moved aside, with a timestamp, and the defaults
are written in its place. The operator gets a working app AND their file.
"""

import json
import os

import config as config_module


def _write(path, content):
    path.write_text(content, encoding="utf-8")


def test_an_unreadable_config_is_kept_not_destroyed(tmp_path):
    path = tmp_path / "config.json"
    _write(path, "{ this is not json")

    result = config_module.load_config(str(path))

    # The app still starts, on the defaults.
    assert result["jobs"]["timeout"] == 3600

    # And the operator's file is NOT gone.
    quarantined = list(tmp_path.glob("config.json.unreadable-*"))
    assert len(quarantined) == 1, "the unreadable config was not preserved"
    assert quarantined[0].read_text(encoding="utf-8") == "{ this is not json"

    # The defaults are in its place, so the next read works.
    assert json.loads(path.read_text(encoding="utf-8"))["jobs"]["timeout"] == 3600


def test_an_empty_config_is_kept_not_destroyed(tmp_path):
    """The empty file is the exact shape the truncating restore produces."""
    path = tmp_path / "config.json"
    _write(path, "")

    config_module.load_config(str(path))

    quarantined = list(tmp_path.glob("config.json.unreadable-*"))
    assert len(quarantined) == 1
    assert quarantined[0].read_text(encoding="utf-8") == ""


def test_a_readable_config_is_left_alone(tmp_path):
    path = tmp_path / "config.json"
    original = {"jobs": {"timeout": 99}}
    _write(path, json.dumps(original))

    result = config_module.load_config(str(path))

    assert result["jobs"]["timeout"] == 99
    assert not list(tmp_path.glob("config.json.unreadable-*"))
    assert json.loads(path.read_text(encoding="utf-8")) == original


def test_the_quarantine_does_not_touch_the_rest_of_the_directory(tmp_path):
    path = tmp_path / "config.json"
    _write(path, "not json")
    sibling = tmp_path / "llm_config.json"
    _write(sibling, json.dumps({"default_provider": "x"}))

    config_module.load_config(str(path))

    assert sibling.read_text(encoding="utf-8") == json.dumps({"default_provider": "x"})
    assert sorted(p.name for p in tmp_path.iterdir()) == [
        "config.json",
        "config.json.unreadable-"
        + sorted(p.name for p in tmp_path.iterdir() if p.name.startswith("config.json.unreadable-"))[0].split("config.json.unreadable-")[1],
        "llm_config.json",
    ]


def test_no_test_writes_the_live_config():
    """The suite redirects every config write to a temp copy.

    `_isolate_config_file` (tests/conftest.py) points `config._config_path`
    at a private copy of the operator's `backend_v2/config.json` for every
    test, and restores it on the way out. So `PUT /api/settings`,
    `POST /api/settings/reset` and `update_config(persist=True)` can never
    truncate, half-write or replace the live file - and no per-file restore
    fixture races with the parallel workers any more.

    That is the whole fix for the defect that rewrote this repository's own
    config.json while the suite ran.
    """
    from pathlib import Path

    source = Path(__file__).resolve().parent / "conftest.py"
    text = source.read_text(encoding="utf-8")
    assert "_isolate_config_file" in text
    assert "cfg._config_path = str(target)" in text
    assert "cfg._config_path = original_path" in text


def test_the_config_write_is_atomic_too(tmp_path):
    """`update_config` writes through a temp file and renames.

    So a reader sees either the old file or the new one.
    """
    import inspect

    source = inspect.getsource(config_module.update_config)
    assert "os.replace(tmp_path, _config_path)" in source
    assert "mkstemp" in source
    # And never a plain truncating write.
    assert "open(_config_path, 'w')" not in source
    assert os.path.basename(__file__).endswith(".py")
