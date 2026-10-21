"""The provider taxonomy: three categories, four transports, one pool each.

Before this, a provider was described by one flat `type` string that bundled the
kind of work with the way the backend reached it, and two of the twelve possible
combinations were impossible to see were missing. `worker_type` already held the
category; the transport was implied. Both are explicit now, and every task type
has exactly one pool.
"""

import pytest

from core.entities import (
    CATEGORY_CLAIM_TASK_TYPES,
    CATEGORY_HYBRID,
    CATEGORY_IMAGE,
    CATEGORY_LLM,
    CATEGORY_TTS,
    VALID_CATEGORIES,
    VALID_TASK_TYPES,
    Provider,
)
from services.engines.registry import (
    ENGINE_SPECS,
    PROVIDER_MATRIX,
    TRANSPORTS,
    matrix_cells,
    resolve_provider_type,
    resolve_transport,
)


class TestTheMatrix:
    def test_all_sixteen_cells_are_declared(self):
        """4 categories x 4 transports, all present — including the empty ones."""
        assert set(PROVIDER_MATRIX) == set(TRANSPORTS)
        for transport, columns in PROVIDER_MATRIX.items():
            assert set(columns) == VALID_CATEGORIES, (
                f"transport {transport!r} does not declare every category"
            )
        assert len(matrix_cells()) == 16

    def test_every_filled_cell_names_a_real_spec(self):
        for cell in matrix_cells():
            if cell["provider_type"] is None:
                continue
            assert cell["provider_type"] in ENGINE_SPECS, (
                f"{cell['transport']}/{cell['category']} points at "
                f"{cell['provider_type']}, which is not a spec"
            )

    def test_every_spec_declares_a_transport_and_matches_its_matrix_cell(self):
        """A spec that is not in the matrix is a provider the UI cannot place."""
        for type_id, spec in ENGINE_SPECS.items():
            transport = spec.get("transport")
            assert transport in TRANSPORTS, f"{type_id} has transport {transport!r}"
            assert spec.get("category") in VALID_CATEGORIES
            # The matrix and the spec agree on which cell this type occupies.
            from services.engines.registry import _cell_provider_types

            assert type_id in _cell_provider_types(PROVIDER_MATRIX[transport][spec["category"]]), (
                f"{type_id} claims {transport}/{spec['category']} but the matrix "
                f"that cell says {PROVIDER_MATRIX[transport][spec['category']]!r}"
            )

    def test_the_four_previously_missing_cells_now_exist(self):
        """Beam/Remote for LLM and TTS were invisible holes in the product."""
        for transport in ("beam", "remote"):
            for category in (CATEGORY_LLM, CATEGORY_TTS):
                type_id = PROVIDER_MATRIX[transport][category]
                assert type_id in ENGINE_SPECS, (
                    f"{transport}/{category} is still an empty cell"
                )

    def test_the_direct_llm_cell_holds_a_family_not_a_hole(self):
        """Direct LLM is several types, not one — and not empty.

        The cell lists the hosted-API family because they differ only in protocol
        (OpenAI-compatible/Ollama, Anthropic, Google). It used to be a bare
        `None`, which read as "not available" while a hostable local vLLM was
        sitting right there.
        """
        cell = next(
            c for c in matrix_cells()
            if c["transport"] == "direct" and c["category"] == CATEGORY_LLM
        )
        assert cell["filled"] is True
        assert set(cell["provider_types"]) == {
            "openai_compat", "ollama", "anthropic", "google",
        }
        assert PROVIDER_MATRIX["direct"][CATEGORY_TTS] == "direct_tts"


class TestTransportResolution:
    @pytest.mark.parametrize("provider_type,expected", [
        ("modal", "modal"),
        ("modal_llm", "modal"),
        ("modal_tts", "modal"),
        ("beam", "beam"),
        ("beam_llm", "beam"),
        ("beam_tts", "beam"),
        ("remote_comfy", "remote"),
        ("remote_llm", "remote"),
        ("remote_tts", "remote"),
        ("remote_hybrid", "remote"),
        ("direct_url", "direct"),
        ("direct_tts", "direct"),
        ("openai_compat", "direct"),
        ("anthropic", "direct"),
        ("google", "direct"),
        # `modal_llm` is an alias now, and an alias must still answer "modal"
        # rather than None — a row still carrying it is a modal_llm row.
        ("modal_llm", "modal"),
    ])
    def test_every_type_resolves(self, provider_type, expected):
        assert resolve_transport(provider_type) == expected

    def test_an_unknown_type_is_none_not_a_guess(self):
        """None, so callers fail loudly rather than defaulting to `direct`."""
        assert resolve_transport("made-up-type") is None
        assert resolve_transport("") is None
        assert resolve_transport(None) is None


class TestTypeResolutionCannotBeHijacked:
    """A provider that knows what it is keeps its identity.

    The legacy substring rule ("vllm in the id means modal_llm") rescued rows
    written before `type` was reliable. With the new transports, a `beam_llm` or
    `remote_llm` row legitimately contains "vllm", so that rule can no longer be
    allowed to win.
    """

    def test_a_remote_llm_row_that_says_vllm_stays_remote_llm(self):
        assert resolve_provider_type("remote_llm", "remote-llm-vllm-1") == "remote_llm"

    def test_a_beam_llm_row_that_says_vllm_stays_beam_llm(self):
        assert resolve_provider_type("beam_llm", "beam-vllm-1") == "beam_llm"

    def test_an_id_prefix_resolves_before_the_substring_rules(self):
        assert resolve_provider_type("", "remote-llm-vllm-1") == "remote_llm"
        assert resolve_provider_type("", "beam-tts-main") == "beam_tts"

    def test_the_legacy_rescue_still_works_for_a_mistyped_row(self):
        """A row whose generic hosted type was a mis-typed Modal vLLM pod.

        The rescue now also requires the id to name Modal, so a legitimate
        self-hosted vLLM provider (openai_compat / ollama) whose id merely
        says "vllm" keeps its identity instead of being re-labelled modal_llm
        and routed to a Modal llama.cpp app.
        """
        assert resolve_provider_type("openai_compat", "svc-modal-vllm-3") == "modal_llm"
        assert resolve_provider_type("", "svc-modal-vllm-3") == "modal_llm"
        assert resolve_provider_type("openai_compat", "selfhost-vllm") == "openai_compat"
        assert resolve_provider_type("ollama", "local-vllm") == "ollama"

    def test_modal_llm_is_one_type_not_two(self):
        """`modal_llm` is canonical and `modal_vllm` is the legacy spelling.

        The direction was flipped on 2026-10-15. `modal_vllm` was canonical
        while the engine still ran vLLM; it has been llama.cpp since
        `deployables/modal/llm/app.py` was rewritten, so the type that names the runtime
        honestly is the one in `ENGINE_SPECS`.
        """
        assert resolve_provider_type("modal_llm", "") == "modal_llm"
        assert "modal_llm" in ENGINE_SPECS
        assert "modal_vllm" not in ENGINE_SPECS
        # Both spellings still resolve to the one canonical type, so a row
        # written before the rename keeps working without a migration.
        assert resolve_provider_type("modal_vllm", "") == "modal_llm"


class TestProviderCategoryProperty:
    def test_the_column_is_read_through_a_property_that_names_it(self):
        provider = Provider(id="x", type="modal", worker_type="image")
        assert provider.category == CATEGORY_IMAGE
        assert provider.worker_type == "image"  # the column keeps its name

    def test_every_category_round_trips(self):
        for category in sorted(VALID_CATEGORIES):
            provider = Provider(id="y", type="modal", worker_type=category)
            assert provider.category == category

    def test_a_blank_category_falls_back_to_image(self):
        provider = Provider(id="z", type="modal", worker_type="")
        assert provider.category == CATEGORY_IMAGE

    def test_transport_comes_from_the_registry_not_the_row(self):
        provider = Provider(id="p", type="beam_llm", worker_type="llm")
        assert provider.category == CATEGORY_LLM
        assert provider.transport == "beam"


class TestOneClaimSetPerCategory:
    def test_no_pool_claims_another_categorys_work(self):
        for category, task_types in CATEGORY_CLAIM_TASK_TYPES.items():
            assert set(task_types) == {category}

    def test_every_task_type_has_exactly_one_home(self):
        homes = [t for ts in CATEGORY_CLAIM_TASK_TYPES.values() for t in ts]
        assert sorted(homes) == sorted(VALID_TASK_TYPES)


class TestTheSchemasEndpointServesTheGrid:
    """The provider modal must be able to render the full 3x4 grid.

    It renders from `GET /schemas`. Before this it got a flat `engines` dict and a
    `categories` list, so the four empty cells were not merely unbuildable — they
    were unknowable. The endpoint now also serves the matrix.
    """

    def test_the_schemas_payload_carries_transport_matrix_and_matrix(self):
        """The route handler is called directly, deliberately.

        A `TestClient(app)` here drags in the whole app lifespan, whose shutdown
        runs `RuntimeError: Event loop is closed` once an earlier test has
        finished with an asyncio loop — which turns a payload-shape assertion
        into a test-ordering landmine. The shape is what is being asserted.
        """
        from api.routes.providers.crud import get_provider_schemas

        body = get_provider_schemas()

        assert "engines" in body and "categories" in body
        assert len(body["transports"]) == 4
        assert len(body["matrix"]) == 16

        # Every cell the matrix declares must actually be servable: a filled
        # cell whose type is missing from `engines` is a choice the provider
        # modal would offer that cannot be saved.
        engine_ids = set(body["engines"])
        for cell in body["matrix"]:
            if cell["provider_type"] is None:
                continue
            assert cell["provider_type"] in engine_ids, (
                f"{cell['transport']}/{cell['category']} names "
                f"{cell['provider_type']}, which /schemas does not describe"
            )

    def test_every_engine_advertises_its_transport(self):
        from services.engines.registry import ENGINE_SPECS, TRANSPORTS, ui_schemas

        schemas = ui_schemas()
        assert set(schemas) == set(ENGINE_SPECS)
        for type_id, schema in schemas.items():
            assert schema["transport"] in TRANSPORTS, (
                f"{type_id} does not advertise a transport, so the UI cannot "
                "group it into the grid"
            )

    def test_every_matrix_cell_is_constructible(self):
        """A cell the factory cannot resolve is a form that saves a broken row.

        Before the engines existed, `beam_llm` / `beam_tts` / `remote_llm` /
        `remote_tts` / `direct_tts` were advertised by the registry and refused
        by `can_create_engine`, so the provider modal offered a choice that
        could only produce a provider which failed every job. Every cell now
        resolves to a real engine.
        """
        from services.engines.engine_factory import can_create_engine, get_engine

        from core.entities import Provider

        for type_id, category in (
            ("beam_llm", CATEGORY_LLM),
            ("beam_tts", CATEGORY_TTS),
            ("remote_llm", CATEGORY_LLM),
            ("remote_tts", CATEGORY_TTS),
            ("direct_tts", CATEGORY_TTS),
            ("remote_hybrid", CATEGORY_HYBRID),
        ):
            is_beam = type_id.startswith("beam")
            provider = Provider(
                id=f"{type_id}-x",
                type=type_id,
                worker_type=category,
                credentials={"api_key": "k"} if is_beam else {"agent_token": "t"},
                config=(
                    {"gpu_url": "http://beam/llm"}
                    if is_beam
                    else {"agent_url": "http://gpu-box:8001"}
                ),
            )
            assert can_create_engine(provider), (
                f"{type_id} validates as a provider but the factory cannot build "
                "its engine — a user could save it and every job would fail"
            )
            # And it must actually be one of the six new engine classes.
            engine = get_engine(f"{type_id}-x", provider)
            assert engine is not None
            assert type(engine).__name__ in (
                "BeamLLMEngine", "BeamTTSEngine", "RemoteLLMEngine",
                "RemoteTTSEngine", "DirectTTSEngine", "HybridRemoteEngine",
            ), f"{type_id} resolved to {type(engine).__name__}"

    def test_an_unknown_type_degrades_to_its_category_not_to_a_broken_row(self):
        """The legacy fallback, asserted rather than assumed.

        An unrecognised `type` on an llm worker used to be ambiguous — it now
        resolves to the hosted OpenAI-compatible engine through
        `_capability_fallback`, which is the documented legacy behaviour and is
        what keeps rows written before `type` was reliable working. What must
        NOT be possible is a type the registry *declares* with no engine behind
        it; that was the four-cell hole, and `can_create_engine` ends in a bare
        `return False` for exactly those.
        """
        from services.engines.engine_factory import can_create_engine

        from core.entities import Provider

        provider = Provider(
            id="ghost-provider",
            type="not_a_real_type",
            worker_type="llm",
            credentials={"api_key": "k"},
            config={"base_url": "http://x/v1"},
        )
        # Falls back to openai_compat rather than failing the row.
        assert can_create_engine(provider) is True

        # A declared type with nothing behind it still refuses, so the hole
        # cannot come back through a cell added to the registry by mistake.
        declared = Provider(
            id="declared-provider",
            type="beam",
            worker_type="image",
            credentials={"api_key": "k"},
            config={"gpu_url": "http://beam/gpu"},
        )
        # `beam` needs a storage_url too, which is the real reason this refuses:
        # the branch exists and enforces its own requirements.
        assert can_create_engine(declared) is False
        declared.config["storage_url"] = "http://beam/storage"
        assert can_create_engine(declared) is True
