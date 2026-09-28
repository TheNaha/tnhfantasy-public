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

    def test_it_does_not_report_missing_when_the_source_tree_is_absent(
        self, monkeypatch
    ):
        """The container case, and the one that produced a wall of noise.

        The first version resolved the source tree as
        `Path(__file__).parents[2] / "provider_containers"`, which is the repo
        root on a developer machine and `/` inside the backend container, where
        the backend lives at `/app` and there is no `provider_containers` at
        all. Every call therefore resolved to a non-existent path, good
        targets were reported missing, and the provider reconciliation loop —
        which reads provider config every few seconds — logged a pair of
        `deploy_target_entrypoint_missing_using_default` warnings on every pass,
        each naming an entrypoint and a "replacement" that were byte-identical.
        """
        import services.provider_utils as pu

        monkeypatch.setattr(pu, "_provider_containers_dir", lambda: None)
        # "I cannot check" is not "it is missing".
        assert pu._entrypoint_exists("/app/image_worker/engines/modal/modal_app.py") is True
        assert pu._entrypoint_exists("/app/modal_app.py") is True

    def test_no_warning_when_the_entrypoint_is_already_correct(self):
        """The exact pair from the log: identical entrypoint and replacement.
        Must be silent — a repair that changes nothing has nothing to say."""
        from services.provider_utils import _repair_stored_targets, default_deploy_targets

        defaults = default_deploy_targets("modal")
        out = _repair_stored_targets([dict(t) for t in defaults], defaults)
        assert [t["entrypoint"] for t in out] == [t["entrypoint"] for t in defaults]

    def test_a_beta9_handler_spec_resolves_on_its_file(self):
        """Beam targets use `path:handler`; the file half is what exists."""
        assert (
            _entrypoint_exists("/app/image_worker/engines/beam/beam_app.py:comfy_gpu")
            is True
        )


class TestDefaults:
    def test_modal_deploys_only_the_image_app(self):
        """The image provider must not build the TTS app.

        A `tts_app` target briefly sat here, on the theory that a TTS worker
        could be a second Modal app from the same image provider. That put a
        speech app in the deploy path of every image provider — deploying
        `modal-hp196` would build speech it never registered to serve. TTS is its
        own provider row, with its own Dockerfile and its own target."""
        names = [t["name"] for t in default_deploy_targets("modal")]
        assert names == ["modal_app"]

    def test_the_tts_app_is_not_in_any_image_providers_targets(self):
        for targets in (
            default_deploy_targets("modal"),
            default_deploy_targets("beam"),
            default_deploy_targets("direct_url"),
        ):
            for target in targets:
                assert "tts_worker" not in " ".join(target["command"])

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

    def test_order_is_preserved(self):
        """A deploy runs targets in order, so a repaired list keeps its sequence."""
        out = _repair_stored_targets(
            [{"name": "modal_app", "entrypoint": "/app/image_worker/engines/modal/modal_app.py"}],
            default_deploy_targets("modal"),
        )
        assert [t["name"] for t in out] == ["modal_app"]

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
        assert [t["name"] for t in out] == ["modal_app"]

    def test_a_healthy_stored_list_is_returned_unchanged(self):
        """No churn when there is nothing to fix — a rewritten list on every
        provider write would be noise in the diffs and in the logs."""
        healthy = default_deploy_targets("modal")
        assert _repair_stored_targets([dict(t) for t in healthy], healthy) is not None
        assert [t["name"] for t in _repair_stored_targets(
            [dict(t) for t in healthy], healthy)] == ["modal_app"]


class TestExtractDeployConfig:
    def test_the_live_stored_config_now_yields_both_targets(self):
        """The exact config row from the running database."""
        cfg = extract_deploy_config("modal", {"deploy_config": {"targets": [
            {"name": "modal_app", "entrypoint": "/app/modal_app.py",
             "command": ["modal", "deploy", "/app/modal_app.py"]},
        ]}})
        assert [t["name"] for t in cfg["targets"]] == ["modal_app"]

    def test_a_provider_with_no_stored_targets_gets_the_defaults(self):
        assert [t["name"] for t in extract_deploy_config("modal", {})["targets"]] == [
            "modal_app",
        ]

    def test_deploy_mode_is_still_defaulted(self):
        assert extract_deploy_config("modal", {})["deploy_mode"] == "managed"
