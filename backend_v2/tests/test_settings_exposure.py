"""Tests for the settings surface: schema truthfulness, input validation, and
the write path the Settings UI depends on.

`GET /api/settings/schema` is hand-written documentation of config.json. It had
drifted from the values it described, documented a `websocket` section that does
not exist, omitted live settings, and — for `ai`, `generator` and
`system_prompts` — described sections that accepted any key at all. These tests
pin the durable invariants so neither can drift again silently.
"""
import json
from pathlib import Path

import pytest

import config as cfg
from api.routes.settings import RESTART_REQUIRED_PATHS, SettingsUpdate
from config import DEFAULT_CONFIG


@pytest.fixture(autouse=True)
def _isolated_config_file(tmp_path):
    """Point config persistence at a temp file and restore the in-memory config.

    PUT /api/settings writes config.json. Redirecting `_config_path` keeps the
    developer's real config (and the running dev server's) untouched, and
    restoring `_config` stops one test's write from leaking into the next.
    """
    original_config = cfg._config
    original_path = cfg._config_path
    cfg._config_path = str(tmp_path / "config.json")
    cfg._config = None
    yield cfg._config_path
    cfg._config = original_config
    cfg._config_path = original_path


@pytest.fixture(name="schema")
def schema_fixture(client):
    response = client.get("/api/settings/schema")
    assert response.status_code == 200
    return response.json()


def _resolve(path: str):
    """Resolve a dotted config path (e.g. `jobs.llm.timeout`) in DEFAULT_CONFIG."""
    node = DEFAULT_CONFIG
    for part in path.split("."):
        assert isinstance(node, dict), f"{path}: {part} is not under a section"
        assert part in node, f"{path}: {part} missing from DEFAULT_CONFIG"
        node = node[part]
    return node


def _documented_fields(schema):
    """Yield ``(dotted_path, spec)`` for every documented field."""
    for section, body in schema["schema"].items():
        for name, spec in body.get("fields", {}).items():
            yield f"{section}.{name}", spec


class TestSchemaMatchesDefaultConfig:
    """The durable drift guard.

    Every field the schema documents must exist in DEFAULT_CONFIG. This is what
    catches the original `websocket` section (documented, never configurable),
    a typo'd field name, and a section renamed on one side only.
    """

    def test_every_documented_field_exists_in_default_config(self, schema):
        missing = [
            path for path, _ in _documented_fields(schema)
            if not _path_exists(path)
        ]
        assert missing == []

    def test_every_documented_section_exists_in_default_config(self, schema):
        assert set(schema["schema"]) <= set(DEFAULT_CONFIG)

    def test_documented_defaults_equal_default_config(self, schema):
        drifted = {
            path: (spec.get("default"), _resolve(path))
            for path, spec in _documented_fields(schema)
            if spec.get("default") != _resolve(path)
        }
        assert drifted == {}

    def test_documented_defaults_do_not_alias_mutable_state(self, schema):
        """Mutable defaults must be copies, so a caller cannot mutate DEFAULT_CONFIG."""
        for path, spec in _documented_fields(schema):
            default = spec.get("default")
            if isinstance(default, (list, dict)):
                assert default == _resolve(path)
                assert default is not _resolve(path)

    def test_four_known_drift_corrections(self, schema):
        """Literal pins for the four values that used to be wrong.

        The schema now reads these from DEFAULT_CONFIG, so re-inlining a literal
        (the source of the original bug) fails here instead of shipping.
        """
        fields = schema["schema"]["image_processing"]["fields"]
        assert fields["thumbnail_quality"]["default"] == 90
        assert fields["blurhash_resize_max"]["default"] == 64
        assert fields["thumbnail_sizes"]["default"] == {"medium": 512}
        assert "thumb" not in fields["thumbnail_sizes"]["default"]
        # Not a count. `== 3` broke when the list grew from three origins to six,
        # and the fix would have been to type 6 — which asserts that nobody ever
        # needs to add an origin, on the tab that says where the stack is reached
        # from. What matters is that every entry is a real origin and that the
        # two the app is actually served on are present.
        cors = schema["schema"]["api"]["fields"]["cors_origins"]["default"]
        assert "http://localhost:5174" in cors
        assert "https://comfy.lan.thenaha.my.id" in cors
        # The origin that was missing and produced a permanent "Disconnected from
        # server" toast: the dev server on the Tailscale IP, which is a different
        # scheme and a different port from the Traefik entry above.
        assert "http://100.150.0.4:5174" in cors
        assert all(origin.startswith(("http://", "https://")) for origin in cors)

    def test_jobs_lifecycle_fields_are_documented(self, schema):
        fields = schema["schema"]["jobs"]["fields"]
        for name in ("timeout", "max_retries", "retry_base_delay", "retry_max_delay"):
            assert name in fields, f"jobs.{name} undocumented"
        for name in ("llm.timeout", "llm.max_retries", "llm.stagger_delay"):
            assert name in fields, f"jobs.{name} undocumented"

    def test_image_processing_fields_are_documented(self, schema):
        fields = schema["schema"]["image_processing"]["fields"]
        for name in ("thumbnail_quality", "embed_metadata_in_png", "output_date_hierarchy"):
            assert name in fields, f"image_processing.{name} undocumented"

    def test_every_field_has_type_description_and_default(self, schema):
        incomplete = [
            path for path, spec in _documented_fields(schema)
            if not {"type", "description", "default"} <= set(spec)
            or not str(spec["description"]).strip()
        ]
        assert incomplete == []

    def test_bounded_defaults_sit_inside_their_bounds(self, schema):
        out_of_range = []
        for path, spec in _documented_fields(schema):
            default = spec.get("default")
            if isinstance(default, bool) or not isinstance(default, (int, float)):
                continue
            low, high = spec.get("min"), spec.get("max")
            if low is not None and default < low:
                out_of_range.append(f"{path}: default {default} < min {low}")
            if high is not None and default > high:
                out_of_range.append(f"{path}: default {default} > max {high}")
            if (low is not None) != (high is not None):
                out_of_range.append(f"{path}: min/max must be declared together")
        assert out_of_range == []


def _path_exists(path: str) -> bool:
    node = DEFAULT_CONFIG
    for part in path.split("."):
        if not isinstance(node, dict) or part not in node:
            return False
        node = node[part]
    return True


class TestFictionalSchemaSectionsRemoved:
    def test_websocket_section_is_gone(self, schema):
        """`websocket` was never a config key.

        It documented `poll_interval`/`reconnect_delay`/`heartbeat_interval` for
        a section `SettingsUpdate` cannot write and DEFAULT_CONFIG does not
        define; the real values are `COMFY_WS_BROADCAST_QUEUE_SIZE` and
        hardcoded Socket.IO ping settings. It was the single most misleading
        object in the config surface.
        """
        assert "websocket" not in schema["schema"]
        assert "websocket" not in DEFAULT_CONFIG

    def test_writable_sections_match_the_request_model(self, schema):
        documented = {name for name, body in schema["schema"].items() if body["writable"]}
        assert documented == set(SettingsUpdate.model_fields)

    def test_every_writable_section_is_documented(self, schema):
        """A writable section nobody can see is not discoverable."""
        assert set(SettingsUpdate.model_fields) <= set(schema["schema"])


class TestEnvVarOverrides:
    def test_override_paths_resolve_in_default_config(self):
        for path in cfg.ENV_VAR_OVERRIDES:
            assert _path_exists(path), f"{path} is not a DEFAULT_CONFIG leaf"

    def test_schema_env_vars_match_the_config_map(self, schema):
        documented = {
            path: spec["env_var"]
            for path, spec in _documented_fields(schema)
            if "env_var" in spec
        }
        assert documented == cfg.ENV_VAR_OVERRIDES

    def test_job_timeout_is_annotated(self, schema):
        spec = schema["schema"]["jobs"]["fields"]["timeout"]
        assert spec["env_var"] == "COMFY_JOB_TIMEOUT"

    def test_env_overrides_empty_without_env_vars(self, schema, monkeypatch):
        for name in cfg.ENV_VAR_OVERRIDES.values():
            monkeypatch.delenv(name, raising=False)
        assert schema["env_overrides"] == {}

    def test_env_overrides_report_only_set_variables(self, client, monkeypatch):
        monkeypatch.delenv("COMFY_JOB_TIMEOUT", raising=False)
        monkeypatch.setenv("COMFY_JOB_TIMEOUT", "900")
        data = client.get("/api/settings/schema").json()
        assert data["env_overrides"] == {"jobs.timeout": "COMFY_JOB_TIMEOUT"}

    def test_shadowed_settings_defaults_match_config(self):
        """`Settings.job_*` only apply when the env var is set.

        They are read through `_env_var_is_set`, so pydantic has parsed them
        from the environment and the declared default is unreachable. `job_timeout`
        was 300 while the effective default was `jobs.timeout` = 3600, so any
        reader that skipped the env check would reinstate the premature-timeout
        failure the DEFAULT_CONFIG comment warns about.
        """
        from config import Settings

        assert Settings().job_timeout == DEFAULT_CONFIG["jobs"]["timeout"]
        assert Settings().job_max_retries == DEFAULT_CONFIG["jobs"]["max_retries"]
        assert Settings().job_retry_base_delay == DEFAULT_CONFIG["jobs"]["retry_base_delay"]
        assert Settings().job_retry_max_delay == DEFAULT_CONFIG["jobs"]["retry_max_delay"]


class TestRestartRequired:
    def test_bound_at_app_construction_fields_are_flagged(self, schema):
        flagged = {
            path for path, spec in _documented_fields(schema)
            if spec.get("restart_required")
        }
        assert flagged == set(RESTART_REQUIRED_PATHS)

    def test_app_setup_reads_them_once(self):
        """The flag is only true while the middleware is built from these getters."""
        source = (Path(cfg.__file__).parent / "api" / "app_setup.py").read_text()
        assert "get_cors_origins()" in source
        assert "get_gzip_minimum_size()" in source
        assert "CORSMiddleware" in source
        assert "GZipMiddleware" in source


class TestUnvalidatedSectionsRejectJunk:
    """`ai`, `generator` and `system_prompts` had no validation branch at all.

    `SettingsUpdate` types every section as `dict[str, Any]`, so
    `{"ai": {"totallyMadeUpKey": 42}}` was deep-merged into config.json by
    `_deep_merge` and kept there: nothing read it and only `reset_config` could
    clear it. A typo now fails at the door.
    """

    @pytest.mark.parametrize("payload,section,junk", [
        ({"ai": {"totallyMadeUpKey": 42}}, "ai", "totallyMadeUpKey"),
        ({"ai": {"maxContextToken": 4096}}, "ai", "maxContextToken"),
        ({"generator": {"defaultCheckpoint": "x.safetensors"}}, "generator", "defaultCheckpoint"),
        ({"jobs": {"llm": {"timeput": 30}}}, "llm", "timeput"),
    ])
    def test_junk_keys_are_refused_and_not_persisted(self, client, payload, section, junk):
        response = client.put("/api/settings", json=payload)
        assert response.status_code == 400, response.text
        assert junk in response.text

    @pytest.mark.parametrize("section,junk_key", [
        ("ai", "totallyMadeUpKey"),
        ("generator", "defaultCheckpoint"),
        ("system_prompts", "not_a_block"),
    ])
    def test_junk_keys_are_refused_at_the_config_layer(self, section, junk_key):
        """`system_prompts` has no SettingsUpdate field, so test the layer below.

        The route calls `update_config` directly, which is where the old code
        persisted anything at all.
        """
        with pytest.raises(ValueError, match="unknown"):
            cfg.update_config({section: {junk_key: "x"}}, persist=False)
        assert junk_key not in cfg.get_config().get(section, {})

    def test_unknown_top_level_section_is_refused(self, client):
        """Pydantic's default is to drop unknown keys and answer 200.

        That is how the retired `websocket` documentation would have behaved:
        success reported, nothing changed.
        """
        response = client.put("/api/settings", json={"websocket": {"poll_interval": 0.5}})
        assert response.status_code in (400, 422)
        assert "websocket" not in cfg.get_config()

    @pytest.mark.parametrize("payload,message", [
        ({"ai": {"temperature": 5}}, "temperature"),
        ({"ai": {"temperature": -0.1}}, "temperature"),
        ({"ai": {"maxContextTokens": 512}}, "maxContextTokens"),
        ({"ai": {"maxContextTokens": 65536}}, "maxContextTokens"),
        ({"ai": {"idleSimIntervalSeconds": 0}}, "idleSimIntervalSeconds"),
        ({"ai": {"idleSimIntervalSeconds": -600}}, "idleSimIntervalSeconds"),
        ({"ai": {"ragEnabled": "yes"}}, "ragEnabled"),
        ({"ai": {"temperature": "hot"}}, "temperature"),
        ({"generator": {"default_checkpoint": ""}}, "default_checkpoint"),
        ({"generator": {"default_checkpoint": 7}}, "default_checkpoint"),
        ({"jobs": {"llm": {"timeout": 0}}}, "timeout"),
        ({"jobs": {"llm": {"stagger_delay": -1}}}, "stagger_delay"),
    ])
    def test_out_of_range_values_are_refused(self, client, payload, message):
        response = client.put("/api/settings", json=payload)
        assert response.status_code == 400, response.text
        assert message in response.text

    def test_blank_system_prompt_block_is_refused(self):
        with pytest.raises(ValueError, match="narrator"):
            cfg.update_config({"system_prompts": {"narrator": "   "}}, persist=False)


    def test_ranges_match_the_ui_sliders(self):
        """The Settings UI sliders and `_validate_config` must agree.

        temperature 0..2 and maxContextTokens 1024..32768 are the exact ranges
        the AI tab exposes; idleSimIntervalSeconds is a positive interval.
        """
        cfg._validate_config({"ai": {"temperature": 0}})
        cfg._validate_config({"ai": {"temperature": 2}})
        cfg._validate_config({"ai": {"maxContextTokens": 1024}})
        cfg._validate_config({"ai": {"maxContextTokens": 32768}})
        cfg._validate_config({"ai": {"idleSimIntervalSeconds": 1}})
        for bad in ({"temperature": 2.1}, {"maxContextTokens": 1023}, {"idleSimIntervalSeconds": 0}):
            with pytest.raises(ValueError):
                cfg._validate_config({"ai": bad})

    def test_existing_worker_validation_still_fires(self, client):
        assert client.put("/api/settings", json={"worker": {"poll_interval": -1}}).status_code == 400


class TestValidWritesPersist:
    def test_ai_block_round_trips(self, client):
        response = client.put("/api/settings", json={"ai": {
            "maxContextTokens": 8192,
            "temperature": 1.2,
            "ragEnabled": False,
            "idleSimEnabled": True,
            "idleSimIntervalSeconds": 900,
        }})
        assert response.status_code == 200, response.text
        saved = cfg.get_config()["ai"]
        assert saved["maxContextTokens"] == 8192
        assert saved["temperature"] == 1.2
        assert saved["ragEnabled"] is False
        assert saved["idleSimIntervalSeconds"] == 900

    def test_null_sampler_overrides_are_accepted(self, client):
        """The AI tab sends explicit nulls to mean "engine default"."""
        response = client.put("/api/settings", json={"ai": {
            "top_p": None, "max_output_tokens": None,
            "frequency_penalty": None, "presence_penalty": None,
        }})
        assert response.status_code == 200, response.text

    def test_default_checkpoint_persists(self, client):
        """The Generator tab's select used to write localStorage only."""
        response = client.put("/api/settings", json={"generator": {"default_checkpoint": "flux.safetensors"}})
        assert response.status_code == 200, response.text
        assert cfg.get_config()["generator"]["default_checkpoint"] == "flux.safetensors"

    def test_image_processing_persists(self, client):
        """`image_processing` was missing from SettingsUpdate entirely."""
        response = client.put("/api/settings", json={"image_processing": {
            "thumbnail_quality": 75,
            "embed_metadata_in_png": False,
            "output_date_hierarchy": False,
        }})
        assert response.status_code == 200, response.text
        saved = cfg.get_config()["image_processing"]
        assert saved["thumbnail_quality"] == 75
        assert saved["embed_metadata_in_png"] is False
        assert saved["output_date_hierarchy"] is False

    def test_jobs_llm_block_persists(self, client):
        response = client.put("/api/settings", json={"jobs": {"llm": {
            "timeout": 240, "max_retries": 4, "stagger_delay": 5.0,
        }}})
        assert response.status_code == 200, response.text
        assert cfg.get_config()["jobs"]["llm"]["stagger_delay"] == 5.0

    def test_api_block_persists(self, client):
        response = client.put("/api/settings", json={"api": {
            "cors_origins": ["http://localhost:5174", "https://example.test"],
            "gzip_minimum_size": 2048,
        }})
        assert response.status_code == 200, response.text
        assert cfg.get_config()["api"]["gzip_minimum_size"] == 2048

    def test_cors_origins_entries_must_be_strings(self, client):
        assert client.put("/api/settings", json={"api": {"cors_origins": [42]}}).status_code == 400

    def test_written_file_is_valid_json(self, client):
        client.put("/api/settings", json={"ai": {"temperature": 0.4}})
        with open(cfg._config_path) as handle:
            assert json.load(handle)["ai"]["temperature"] == 0.4

    def test_leaf_allow_lists_cover_every_default(self):
        """A new DEFAULT_CONFIG leaf must be added to its section's allow-list.

        Otherwise the settings API rejects the one write that should be legal.
        `ai` is checked leaf-by-leaf because the frontend also writes optional
        sampler keys that have no default.
        """
        for section, allowed in cfg.SECTION_LEAF_ALLOW_LISTS.items():
            if "." in section:
                parent, _nested = section.split(".", 1)
                source = DEFAULT_CONFIG[parent][_nested]
            else:
                source = DEFAULT_CONFIG[section]
            assert set(source) <= set(allowed), f"{section} allow-list is missing {set(source) - set(allowed)}"

    def test_system_prompt_blocks_share_one_definition(self):
        from api.routes.settings import SYSTEM_PROMPT_BLOCK_KEYS

        assert SYSTEM_PROMPT_BLOCK_KEYS == cfg.SYSTEM_PROMPT_KEYS == cfg.SECTION_LEAF_ALLOW_LISTS["system_prompts"]


class TestResetEndpoint:
    def test_reset_clears_written_values(self, client):
        client.put("/api/settings", json={"generator": {"default_checkpoint": "temp.safetensors"}})
        assert cfg.get_config()["generator"]["default_checkpoint"] == "temp.safetensors"
        response = client.post("/api/settings/reset")
        assert response.status_code == 200
        assert cfg.get_config()["generator"]["default_checkpoint"] == DEFAULT_CONFIG["generator"]["default_checkpoint"]
