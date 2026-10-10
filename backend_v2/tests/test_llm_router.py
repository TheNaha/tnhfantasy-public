"""The rp/util router: job kind -> role -> model.

The two-model split exists because an rp finetune is chosen for prose and a
util model for structure, and neither does the other's job well. Before this,
`get_default_llm_model()` answered "which model serves LLM work" — a question
that only had one sensible answer while there was one model.

The safety property matters most: a deployment with a single provider and no
per-role setup must resolve *exactly* as it did before, because most people do
not have two models deployed.
"""

import pytest

from services.llm_router import (
    DEFAULT_ROLE,
    ROLE_BY_KIND,
    LLMRouter,
    get_router,
    refresh_router,
    unresolved_kinds,
)


@pytest.fixture
def router():
    return get_router()


class TestRoleByKind:
    def test_the_kinds_the_codebase_actually_emits(self):
        """Every `type_=` string in chats/stories/memory_extraction."""
        from services.llm_config import resolve_model_for_kind  # noqa: F401

        for kind in (
            "chat_reply", "narrator", "story_continue", "story_action",
            "suggest_reply", "story_parse", "story_illustrate_prompt",
            "memory_extraction",
        ):
            assert kind in ROLE_BY_KIND, f"{kind!r} is emitted but not routed"

    def test_prose_kinds_route_to_rp(self):
        for kind in ("chat_reply", "narrator", "story_continue",
                     "story_action", "suggest_reply"):
            assert ROLE_BY_KIND[kind] == "rp", kind

    def test_structured_kinds_route_to_util(self):
        """These are the kinds a finetune is worst at, and where vision lives."""
        for kind in ("story_parse", "story_illustrate_prompt",
                     "memory_extraction", "tool_call", "agentic",
                     "vision", "caption", "summarize"):
            assert ROLE_BY_KIND[kind] == "util", kind

    def test_an_unknown_kind_falls_back_not_crashes(self, router):
        """A new workflow kind still gets a reply, just from the prose model."""
        assert router.role_for_kind("brand_new_kind") == DEFAULT_ROLE
        assert router.role_for_kind(None) == DEFAULT_ROLE
        assert router.primary_for_kind("brand_new_kind") is not None

    def test_a_role_with_no_enabled_model_raises_rather_than_dispatching(self):
        """A caller that resolves to None dispatches a job with no model."""
        empty = LLMRouter(type("R", (), {"fallback": {"rp": []},
                                         "models": {},
                                         "enabled_for": lambda self, role: [],
                                         "enabled_ids": lambda self: []})())
        with pytest.raises(LookupError):
            empty.primary_for_kind("chat_reply")

    def test_unresolved_kinds_reports_what_falls_through(self):
        assert unresolved_kinds(["chat_reply", "not_a_kind"]) == ["not_a_kind"]
        assert unresolved_kinds(["chat_reply"]) == []


class TestRegistryIsTheSourceOfTruth:
    def test_reordering_models_json_is_the_whole_interface(self, router):
        """No model id is hardcoded in the router — only kinds are.

        This is the assertion that makes the registry the one file to edit.
        """
        source = open("services/llm_router.py").read()
        import re

        hardcoded = re.findall(r'"(artemis|writers_31b|gemma4_31b|sompoa|magnum_diamond)"', source)
        assert not hardcoded, f"router hardcodes model ids: {hardcoded}"

    def test_the_primary_comes_from_the_registry_not_this_file(self, router):
        model = router.primary_for_kind("chat_reply")
        assert model.id in router.registry.models
        assert model.role == "rp"

    def test_the_util_primary_is_the_registrys_first_enabled_util(self, router):
        util = router.registry.enabled_for("util")
        assert [m.id for m in util] == list(router.registry.fallback["util"])
        assert router.primary_for_kind("memory_extraction").id == util[0].id

    def test_the_shared_weights_entry_keeps_one_download(self, router):
        """The util twin of an rp entry must not re-download the same weights."""
        rp = router.registry.get("gemma4_31b_heretic")
        util = router.registry.get("gemma4_31b_heretic_util")
        assert util.volume_dir == "gemma4_31b_heretic"
        assert rp.repo == util.repo and rp.gguf == util.gguf

    def test_a_per_chat_pin_wins_over_the_router(self, router):
        assert router.primary_for_kind("chat_reply", override="weirdcompound_24b").id == \
            "weirdcompound_24b"

    def test_an_unknown_pin_raises_rather_than_silently_ignoring_it(self, router):
        """Falling back would make the user's choice appear to be ignored."""
        with pytest.raises(KeyError):
            router.primary_for_kind("chat_reply", override="nope")

    def test_enabled_false_models_are_not_routed_to(self, router):
        for model in router.registry.enabled_for("rp"):
            assert model.enabled is True
        assert "dark_thoughts_v2_31b" not in [m.id for m in router.registry.enabled_for("rp")]

    def test_a_model_with_no_vision_is_visible_as_such(self, router):
        """Only `util` should be asked to read an image."""
        assert router.primary_for_kind("memory_extraction").has_vision is True
        assert router.registry.get("weirdcompound_24b").has_vision is False


class TestTheRegistryParses:
    def test_it_parses_and_validates(self):
        reg = refresh_router().registry
        assert reg.models
        assert set(reg.fallback) == {"rp", "util"}

    def test_a_typo_in_a_fallbentry_names_a_model_that_does_not_exist(self, tmp_path):
        """Both mistakes are silent in JSON and expensive at deploy time."""
        import json

        from registry import load

        broken = {
            "roles": {"rp": {"fallback": ["ghost_model"]}, "util": {"fallback": []}},
            "models": {"real": {"role": "rp", "repo": "r", "gguf": "g.gguf"}},
        }
        path = tmp_path / "models.json"
        path.write_text(json.dumps(broken))
        with pytest.raises(ValueError, match="do not exist"):
            load(path)

    def test_a_typo_in_a_models_role_is_caught(self, tmp_path):
        import json

        from registry import load

        broken = {
            "roles": {"rp": {"fallback": ["real"]}, "util": {"fallback": ["real"]}},
            "models": {"real": {"role": "typo_role", "repo": "r", "gguf": "g.gguf"}},
        }
        path = tmp_path / "models.json"
        path.write_text(json.dumps(broken))
        with pytest.raises(ValueError, match="not in"):
            load(path)

    def test_llama_args_put_the_model_path_first_and_the_kv_flags_last(self):
        from registry import load, REGISTRY_PATH

        reg = load(REGISTRY_PATH)
        model = reg.primary("util")
        args = model.llama_args()
        assert args[0:2] == ["-m", f"/models/{model.volume_dir}/{model.gguf}"]
        assert args.count("--cache-type-k") == 1
        assert "--jinja" in args


class TestKindResolutionKeepsOneModelWorking:
    """The property that makes this safe to land on a working deployment."""

    @staticmethod
    def _resolve_with_provider(model_id, kind, **kwargs):
        """Resolve inside the session's scope.

        A session returned from a closed `with` block has already released its
        connection, and `sqlite:///:memory:` gives each connection a fresh empty
        database — so a provider added inside the block is simply gone by the
        time the caller resolves. This is the test's bug, not the resolver's.
        """
        import infrastructure.database as db
        from core.entities import Provider
        from sqlmodel import Session, SQLModel, create_engine

        from services.llm_config import resolve_model_for_kind

        engine = create_engine("sqlite:///:memory:")
        SQLModel.metadata.create_all(engine)
        db.engine = engine
        with Session(engine) as s:
            s.add(Provider(
                id="llm-test", type="remote_llm", worker_type="llm", enabled=True,
                credentials={"agent_token": "t"},
                config={"agent_url": "http://x:8001", "default_model": model_id},
            ))
            s.commit()
            return resolve_model_for_kind(kind, session=s, **kwargs)

    def test_a_single_provider_deployment_is_unchanged(self):
        """`chat_reply` upgrades to the rp model; `util` keeps the old answer.

        With rp served and util not, `memory_extraction` must resolve to
        `get_default_llm_model()` — the single-model answer, unchanged — rather
        than to a model nothing can reach. Asserting it equals the served rp
        model would be wrong: the fallback is the pre-existing default, which is
        what a one-model deployment has been using all along.
        """
        from services.llm_config import get_default_llm_model

        assert self._resolve_with_provider("artemis_31b", "chat_reply") == "artemis_31b"
        assert self._resolve_with_provider("artemis_31b", "memory_extraction") == \
            get_default_llm_model()

    def test_both_roles_routed_when_both_are_served(self):
        from services.llm_config import resolve_model_for_kind

        import infrastructure.database as db
        from core.entities import Provider
        from sqlmodel import Session, SQLModel, create_engine

        engine = create_engine("sqlite:///:memory:")
        SQLModel.metadata.create_all(engine)
        db.engine = engine
        with Session(engine) as s:
            s.add(Provider(id="rp", type="remote_llm", worker_type="llm", enabled=True,
                           credentials={"agent_token": "t"},
                           config={"default_model": "artemis_31b"}))
            s.add(Provider(id="util", type="remote_llm", worker_type="llm", enabled=True,
                           credentials={"agent_token": "t"},
                           config={"default_model": "gemma4_31b_heretic_util"}))
            s.commit()
            assert resolve_model_for_kind("chat_reply", session=s) == "artemis_31b"
            assert resolve_model_for_kind("memory_extraction", session=s) == \
                "gemma4_31b_heretic_util"

    def test_a_pin_wins_over_every_automatic_decision(self):
        assert self._resolve_with_provider(
            "artemis_31b", "memory_extraction", override="magnum_diamond_24b"
        ) == "magnum_diamond_24b"

    def test_a_missing_registry_degrades_to_the_old_answer(self, monkeypatch):
        """Registry malformed must not break every chat message."""
        from services import llm_config

        monkeypatch.setattr(llm_config, "get_default_llm_model", lambda: "legacy-model")

        def _boom():
            raise ValueError("registry is broken")

        import services.llm_router as router_mod

        monkeypatch.setattr(router_mod, "load", _boom)
        monkeypatch.setattr(router_mod, "_ROUTER", None)

        assert self._resolve_with_provider("artemis_31b", "chat_reply") == "legacy-model"
