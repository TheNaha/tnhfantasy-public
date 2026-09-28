"""Deploy targets: repair what is stale, add what is new.

Two findings drove this file, and both came from the live database rather than
from reading the code.

1. Every deployed Modal provider had
   `deploy_config.targets[0].entrypoint = /app/modal_app.py`. That path has not
   existed since the engine code moved under `engines/<engine>/` — the Dockerfile
   copies `image_worker/` to `/app/image_worker/`. A stored target list WINS over
   `default_deploy_targets`, by design, so the deploy would fail inside the
   container with a `FileNotFoundError` that says nothing about the cause.

2. Adding a second target to the defaults — the TTS app — would therefore never
   have appeared on an existing provider, because the stored list shadowed the
   defaults entirely. A new capability would have needed a manual database edit
   per provider row, which is how a feature ends up half-deployed on exactly the
   providers nobody looked at.
"""


from services.provider_utils import (
    _entrypoint_exists,
    _repair_stored_targets,
    default_deploy_targets,
    extract_deploy_config,
)


class TestEntrypointExists:
    def test_a_live_path_is_recognised(self):
        assert _entrypoint_exists("/app/image_worker/engines/modal/modal_app.py") is True

    def test_the_stale_path_is_not(self):
        """The literal string every Modal provider had stored."""
        assert _entrypoint_exists("/app/modal_app.py") is False

    def test_the_new_tts_path_is_recognised(self):
        assert _entrypoint_exists("/app/tts_worker/engines/modal/modal_app.py") is True

    def test_a_bare_name_is_not_treated_as_a_path(self):
        assert _entrypoint_exists("") is False
        assert _entrypoint_exists(None) is False

    def test_a_beta9_handler_spec_resolves_on_its_file(self):
        """Beam targets use `path:handler`; the file half is what exists."""
        assert (
            _entrypoint_exists("/app/image_worker/engines/beam/beam_app.py:comfy_gpu")
            is True
        )


class TestDefaults:
    def test_modal_deploys_the_image_worker_and_the_tts_app(self):
        names = [t["name"] for t in default_deploy_targets("modal")]
        assert names == ["modal_app", "tts_app"]

    def test_the_tts_target_points_at_the_tts_app(self):
        tts = next(t for t in default_deploy_targets("modal") if t["name"] == "tts_app")
        assert tts["command"] == [
            "modal", "deploy", "/app/tts_worker/engines/modal/modal_app.py",
        ]

    def test_llm_and_beam_are_untouched(self):
        """Renaming the modal target list must not disturb the other two, which
        are the variants that took a night to get right."""
        assert [t["name"] for t in default_deploy_targets("modal_llm")] == ["modal_llm_app"]
        assert len(default_deploy_targets("beam")) == 3


class TestRepair:
    def test_a_stale_target_is_replaced_by_the_current_default(self):
        stored = [
            {"name": "modal_app", "entrypoint": "/app/modal_app.py",
             "command": ["modal", "deploy", "/app/modal_app.py"]},
        ]
        out = _repair_stored_targets(stored, default_deploy_targets("modal"))
        entry = next(t for t in out if t["name"] == "modal_app")
        assert entry["entrypoint"] == "/app/image_worker/engines/modal/modal_app.py"

    def test_a_missing_default_is_appended(self):
        """The feature this exists for: a new worker kind reaches existing
        providers without a manual database edit."""
        stored = [
            {"name": "modal_app", "entrypoint": "/app/image_worker/engines/modal/modal_app.py"},
        ]
        out = _repair_stored_targets(stored, default_deploy_targets("modal"))
        assert [t["name"] for t in out] == ["modal_app", "tts_app"]

    def test_order_is_preserved_so_image_builds_first(self):
        """A deploy runs targets in order; image-first keeps the working worker
        deployed before a new, unproven one."""
        out = _repair_stored_targets(
            [{"name": "modal_app", "entrypoint": "/app/image_worker/engines/modal/modal_app.py"}],
            default_deploy_targets("modal"),
        )
        assert [t["name"] for t in out] == ["modal_app", "tts_app"]

    def test_a_user_target_we_have_no_default_for_is_kept(self):
        stored = [
            {"name": "modal_app", "entrypoint": "/app/image_worker/engines/modal/modal_app.py"},
            {"name": "my_custom", "entrypoint": "/app/image_worker/engines/modal/modal_app.py"},
        ]
        out = _repair_stored_targets(stored, default_deploy_targets("modal"))
        assert "my_custom" in [t["name"] for t in out]

    def test_a_stored_target_whose_file_vanished_and_has_no_default_is_dropped(self):
        stored = [{"name": "ghost", "entrypoint": "/app/deleted/thing.py"}]
        out = _repair_stored_targets(stored, default_deploy_targets("modal"))
        assert [t["name"] for t in out] == ["modal_app", "tts_app"]

    def test_a_healthy_stored_list_is_returned_unchanged(self):
        """No churn when there is nothing to fix — a rewritten list on every
        provider write would be noise in the diffs and in the logs."""
        healthy = default_deploy_targets("modal")
        assert _repair_stored_targets([dict(t) for t in healthy], healthy) is not None
        assert [t["name"] for t in _repair_stored_targets(
            [dict(t) for t in healthy], healthy)] == ["modal_app", "tts_app"]


class TestExtractDeployConfig:
    def test_the_live_stored_config_now_yields_both_targets(self):
        """The exact config row from the running database."""
        cfg = extract_deploy_config("modal", {"deploy_config": {"targets": [
            {"name": "modal_app", "entrypoint": "/app/modal_app.py",
             "command": ["modal", "deploy", "/app/modal_app.py"]},
        ]}})
        assert [t["name"] for t in cfg["targets"]] == ["modal_app", "tts_app"]

    def test_a_provider_with_no_stored_targets_gets_the_defaults(self):
        assert [t["name"] for t in extract_deploy_config("modal", {})["targets"]] == [
            "modal_app", "tts_app",
        ]

    def test_deploy_mode_is_still_defaulted(self):
        assert extract_deploy_config("modal", {})["deploy_mode"] == "managed"
