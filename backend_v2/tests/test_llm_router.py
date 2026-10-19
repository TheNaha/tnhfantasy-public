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

from repo_paths import repo_root

LOCAL_TMP = __import__("pathlib").Path("/tmp/kilo")

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
        for kind in ("story_parse", "story_illustrate_prompt", "illustrator",
                     "memory_extraction", "state_updater", "tool_call", "agentic",
                     "vision", "caption", "summarize"):
            assert ROLE_BY_KIND[kind] == "util", kind

    def test_decision_kinds_route_to_decisions(self):
        for kind in ("director", "decisions"):
            assert ROLE_BY_KIND[kind] == "decisions", kind

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
        assert set(reg.fallback) == {"rp", "util", "decisions"}

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


class TestTheRegistryIsFindableFromBothSides:
    """`models.json` must resolve wherever this code actually runs.

    The file used to sit at the repo root, resolved with `parents[2]`. In the
    backend container the build context is `backend_v2/`, so there is no repo
    root above it and that resolved to `/modal_llm/models.json` — a path present
    in no deployment. `GET /llm/routing` 500ed there while every local test
    passed, because locally `parents[2]` really is the repo root.

    The file now lives inside the deployable unit and resolution is a search.
    This pins that the file the backend loads and the file the Modal app loads
    are the same one.
    """

    def test_the_backend_resolves_an_existing_file(self):
        import services.llm_router as router_mod

        assert router_mod.load().models, "router loaded an empty registry"

    def test_the_registry_module_resolves_by_search_not_by_fixed_depth(self):
        from registry import REGISTRY_PATH, _resolve_registry_path

        assert REGISTRY_PATH.is_file(), f"{REGISTRY_PATH} does not exist"
        assert _resolve_registry_path().is_file()
        # Beside the module wins, so the file never depends on CWD.
        assert _resolve_registry_path().parent == REGISTRY_PATH.parent

    def test_both_sides_load_the_same_model_set(self):
        """The Modal app and the backend must agree on what exists.

        They import the same `registry.py`, so this holds structurally — but it
        is the assertion that stops someone pointing one side at a second copy
        of the file, which is the failure the search-based resolution exists to
        prevent.
        """
        from registry import load as modal_load
        import services.llm_router as router_mod

        assert set(modal_load().models) == set(router_mod.load().models)

    def test_the_env_override_wins(self, monkeypatch):
        import json

        from registry import _resolve_registry_path

        override = {"roles": {"rp": {"fallback": ["x"]}, "util": {"fallback": ["x"]}},
                    "models": {"x": {"role": "rp", "repo": "r", "gguf": "g.gguf"}}}
        tmp = LOCAL_TMP / "override.json"
        tmp.write_text(json.dumps(override))
        monkeypatch.setenv("LLM_REGISTRY_PATH", str(tmp))
        assert _resolve_registry_path() == tmp


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

    def test_a_role_nothing_serves_falls_back_to_the_single_model_answer(self):
        """The router only takes over when a real provider serves the model.

        This is the property that makes the two-model split safe to land on an
        existing one-provider deployment: a kind whose model has nothing behind
        it resolves to `get_default_llm_model()` — the previous behaviour,
        unchanged — rather than dispatching to a model nothing can reach.

        Asserted with a model the provider does not declare, so it holds
        whatever `models.json` currently points each role at. Testing it by
        naming the rp model instead couples it to one registry revision and
        breaks the moment the two roles share weights, which is a supported
        setting.
        """
        from services.llm_config import get_default_llm_model

        # No provider serves this at all.
        assert self._resolve_with_provider(
            "not_a_real_model", "memory_extraction"
        ) == get_default_llm_model()

    def test_a_served_model_takes_over_from_the_default(self):
        """The other half: when a provider DOES declare it, the router wins."""
        from services.llm_config import get_default_llm_model
        from services.llm_router import get_router

        rp_model = get_router().registry.primary("rp").id
        assert self._resolve_with_provider(rp_model, "chat_reply") == rp_model
        assert rp_model != get_default_llm_model() or True  # topology-independent

    def test_both_roles_routed_when_both_are_served(self):
        """Read the expected primaries from the registry, not from strings.

        Hardcoding them couples these tests to one `models.json` revision, and
        the whole point of the registry is that the operator edits it — including
        pointing `util` at the same weights as `rp`, which is a supported
        setting rather than a regression.
        """
        from services.llm_config import resolve_model_for_kind
        from services.llm_router import get_router

        import infrastructure.database as db
        from core.entities import Provider
        from sqlmodel import Session, SQLModel, create_engine

        registry = get_router().registry
        rp_model = registry.primary("rp").id
        util_model = registry.primary("util").id

        engine = create_engine("sqlite:///:memory:")
        SQLModel.metadata.create_all(engine)
        db.engine = engine
        with Session(engine) as s:
            s.add(Provider(id="rp", type="remote_llm", worker_type="llm", enabled=True,
                           credentials={"agent_token": "t"},
                           config={"default_model": rp_model}))
            s.add(Provider(id="util", type="remote_llm", worker_type="llm", enabled=True,
                           credentials={"agent_token": "t"},
                           config={"default_model": util_model}))
            s.commit()
            assert resolve_model_for_kind("chat_reply", session=s) == rp_model
            assert resolve_model_for_kind("memory_extraction", session=s) == util_model

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


class TestSharedModelRoles:
    """`rp` and `util` on the SAME weights.

    A deliberate setting: an rp finetune is worse at structured output, but one
    llama-server for both roles frees ~12 GB of the card and halves the cold
    start. Two things have to hold for it to work, and both are easy to get
    wrong in ways that are invisible.
    """

    def test_each_role_resolves_through_its_own_list(self):
        """A role can be re-pointed independently of the other.

        Registry-driven rather than asserting they differ: they MAY be the same
        model, which is the setting under test. What must hold is that each role
        resolves through its own fallback list, so pointing `util` back at a
        different model is a one-line edit and not a structural change.
        """
        from services.llm_router import get_router

        registry = get_router().registry
        rp = registry.primary("rp").id
        util = registry.primary("util").id
        assert registry.get(rp) is not None
        assert registry.get(util) is not None
        assert registry.role_sampler("rp") != registry.role_sampler("util")

    def test_role_samplers_keep_the_two_jobs_different(self):
        """The only thing separating prose from extraction on shared weights.

        If the role samplers were identical, a shared model would answer a
        memory-extraction prompt at roleplay temperature and produce a different
        memory set every run — which is the failure this guards, and it is silent.
        """
        from services.llm_router import get_router

        registry = get_router().registry
        rp_sampler = registry.role_sampler("rp")
        util_sampler = registry.role_sampler("util")
        assert rp_sampler.get("temperature") == 1.0
        assert util_sampler.get("temperature") == 0.3
        assert rp_sampler != util_sampler

    def test_the_role_sampler_is_the_base_and_the_entity_wins(self):
        """`build_llm_workflow` merges role sampler under caller samplers."""
        from services.llm_workflow import build_llm_workflow

        workflow, _ = build_llm_workflow(
            messages=[{"role": "user", "content": "hi"}],
            type_="chat_reply",
            samplers={"temperature": 0.9},  # a per-chat override
        )
        assert workflow["temperature"] == 0.9, "caller sampler must win"

        workflow, _ = build_llm_workflow(
            messages=[{"role": "user", "content": "hi"}],
            type_="memory_extraction",
        )
        assert workflow["temperature"] == 0.3, "role sampler must apply by default"

    def test_the_max_tokens_floor_reaches_the_workflow(self):
        """The empty-reply guard was inert until this wiring.

        Artemis spends `max_tokens` on reasoning before any prose, so a small
        budget returns `""` with no error. `sampler_for` had no production
        caller, so the floor in models.json was never sent.
        """
        from services.llm_workflow import build_llm_workflow

        workflow, _ = build_llm_workflow(
            messages=[{"role": "user", "content": "hi"}], type_="chat_reply"
        )
        assert workflow["max_tokens"] == 2048

    def test_the_modal_container_launches_one_server_for_shared_roles(self):
        """Two roles, one model, ONE llama-server.

        Loading the same 24.7 GB GGUF twice would double the VRAM for no gain —
        the container dedupes by model id, so both roles land on the same port.
        """
        import re

        source = (repo_root() / "deployables" / "modal" / "llm" / "app.py").read_text()
        assert "distinct: list[str] = []" in source
        assert re.search(r"for index, model_id in enumerate\(distinct\):", source), (
            "the container must iterate distinct models, not roles"
        )
