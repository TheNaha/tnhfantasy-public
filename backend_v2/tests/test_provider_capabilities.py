"""Provider capabilities: which jobs a provider may be handed.

`worker_type` is a single value, so it could only ever say "image" or "llm".
That was sufficient while each task type was served by exactly one kind of
worker, and TTS breaks it: the same ComfyUI container serves `image` and `tts`,
differing only in the workflow graph. So there are now two questions and two
fields:

    `worker_type`   which EXECUTION PATH — a ComfyUI container that cold-starts,
                    or an always-on HTTP endpoint the load balancer branches on
    `capabilities`  which JOBS may be handed to it

This exists because a TTS job had no honest route. `voices.py` created it with
`task_type="image"` — "TTS runs on the image_worker adapter" — which was true of
the code path and false of the capability: no provider in this deployment has a
text-to-speech node installed, so the job went to a worker that cannot build its
graph. `config.py` already conceded it, in a comment: `ttsEnabled` is
"frontend-only for now".

A second, quieter win: `get_next_provider` used to return `None` both for "no
provider is healthy" and for "no provider can serve this task type", and the
caller could not tell them apart. It now logs the declared capabilities.
"""

import pytest

from core.entities import CONTAINER_TASK_TYPES, VALID_TASK_TYPES, Provider
from core.exceptions import ValidationError
from services.provider_service import _normalize_capabilities


def _provider(session, pid, **kw):
    p = Provider(id=pid, type=kw.pop("type", "modal"), enabled=True, **kw)
    session.add(p)
    session.commit()
    session.refresh(p)
    return p


class TestServes:
    def test_tts_is_a_task_type(self):
        assert "tts" in VALID_TASK_TYPES
        # TTS is container-backed, not an always-on endpoint, so it shares the
        # image queue and the `max_containers` budget.
        assert "tts" in CONTAINER_TASK_TYPES
        assert "llm" not in CONTAINER_TASK_TYPES

    def test_a_provider_with_no_capabilities_keeps_its_old_behaviour(self):
        """Every provider that existed before this column was edited. The empty
        case has to mean "same as worker_type" or the backfill would have to
        touch all of them on read."""
        p = Provider(id="x", worker_type="image")
        assert p.capabilities == []
        assert p.serves("image") is True
        assert p.serves("tts") is False
        assert p.serves("llm") is False

    def test_one_container_serves_image_and_tts(self):
        """The case `worker_type` could not express."""
        p = Provider(id="x", worker_type="image", capabilities=["image", "tts"])
        assert p.serves("image") is True
        assert p.serves("tts") is True
        assert p.serves("llm") is False

    def test_hybrid_provider_serves_both_image_and_llm(self):
        """A hybrid provider inherently serves both image and llm."""
        p = Provider(id="x", worker_type="hybrid")
        assert p.serves("image") is True
        assert p.serves("llm") is True
        assert p.serves("tts") is False

        p_with_tts = Provider(id="x", worker_type="hybrid", capabilities=["tts"])
        assert p_with_tts.serves("image") is True
        assert p_with_tts.serves("llm") is True
        assert p_with_tts.serves("tts") is True

    def test_capabilities_are_additive_not_authoritative(self):
        """Declaring `tts` must not take the provider out of image rotation.

        The first version treated a non-empty list as authoritative, so a
        provider declaring only `["tts"]` stopped serving `image` — reachable
        from any UI that sent the capabilities it knew about, and the symptom
        ("no provider available" for every image job) points nowhere near a
        form field. Additive: `worker_type` is always served, and the list only
        adds."""
        p = Provider(id="x", worker_type="image", capabilities=["tts"])
        assert p.serves("image") is True
        assert p.serves("tts") is True

    def test_capabilities_do_not_override_worker_type_for_routing_shape(self):
        """Declaring `tts` must not make the container look like an LLM
        endpoint — the load balancer branches on `worker_type` for the cold-start
        and health-check machinery, and that must not change."""
        p = Provider(id="x", worker_type="image", capabilities=["image", "tts"])
        assert p.worker_type == "image"
        assert p.worker_type in CONTAINER_TASK_TYPES


class TestNormaliseCapabilities:
    def test_a_new_provider_inherits_its_worker_type(self):
        assert _normalize_capabilities(None, existing=None, worker_type="image") == ["image"]

    def test_an_existing_provider_keeps_its_capabilities(self):
        existing = Provider(id="x", worker_type="image", capabilities=["image", "tts"])
        assert _normalize_capabilities(None, existing=existing, worker_type="image") == ["image", "tts"]

    def test_an_empty_list_inherits_rather_than_declaring_nothing(self):
        """`[]` must not mean "serves nothing" — that would silently disable a
        provider by sending an empty array."""
        assert _normalize_capabilities([], existing=None, worker_type="llm") == ["llm"]

    def test_order_is_preserved_and_duplicates_dropped(self):
        assert _normalize_capabilities(
            ["tts", "image", "tts"], existing=None, worker_type="image"
        ) == ["tts", "image"]

    def test_a_typo_is_rejected_rather_than_ignored(self):
        """The failure this prevents: `serves()` would exclude the provider for a
        task type nobody asked about, the job would fail as "no provider
        available", and nothing would point at a spelling mistake in a JSON
        column."""
        with pytest.raises(ValidationError) as exc:
            _normalize_capabilities(["images"], existing=None, worker_type="image")
        assert "images" in str(exc.value)
        assert "tts" in str(exc.value), "the message should list what IS valid"

    def test_a_bare_string_is_rejected(self):
        with pytest.raises(ValidationError):
            _normalize_capabilities("image,tts", existing=None, worker_type="image")


class TestRouting:
    """The behaviour change, not just the data model."""

    @pytest.mark.asyncio
    async def test_tts_is_not_routed_to_an_image_only_provider(self, session):
        from services.load_balancer_factory import create_load_balancer

        _provider(session, "img-only", worker_type="image", capabilities=["image"])
        lb = create_load_balancer(session, task_type="tts")
        assert await lb.get_next_provider(task_type="tts") is None, (
            "a TTS job was routed to a provider with no TTS nodes"
        )

    @pytest.mark.asyncio
    async def test_tts_routes_to_a_provider_that_declares_it(self, session):
        from services.load_balancer_factory import create_load_balancer

        _provider(session, "img-only", worker_type="image", capabilities=["image"])
        _provider(session, "comfy-tts", worker_type="image", capabilities=["image", "tts"])
        lb = create_load_balancer(session, task_type="tts")
        chosen = await lb.get_next_provider(task_type="tts")
        assert chosen is not None
        assert chosen.id == "comfy-tts", (
            "the provider that declared tts was not the one chosen"
        )

    @pytest.mark.asyncio
    async def test_declaring_tts_does_not_stop_a_provider_serving_images(self, session):
        """The regression a capability filter could easily introduce: filtering
        too hard and taking the provider out of image rotation."""
        from services.load_balancer_factory import create_load_balancer

        _provider(session, "comfy-tts", worker_type="image", capabilities=["image", "tts"])
        lb = create_load_balancer(session, task_type="image")
        chosen = await lb.get_next_provider(task_type="image")
        assert chosen is not None and chosen.id == "comfy-tts"

    @pytest.mark.asyncio
    async def test_an_undeclared_capability_does_not_disable_image(self, session):
        """A provider that declares ONLY `tts` still serves images, because
        `worker_type` is what decides the execution path."""
        from services.load_balancer_factory import create_load_balancer

        _provider(session, "tts-only", worker_type="image", capabilities=["tts"])
        assert await create_load_balancer(session, task_type="image").get_next_provider(
            task_type="image"
        ) is not None


class TestTheTtsProviderIsItsOwnThing:
    """A TTS worker registers itself, like any other provider.

    It is a container, not a second Modal app behind the image worker. That was
    the first attempt and it was wrong on the codebase's own model: one provider
    is one container, and the image worker's `/health` only checks that
    `MODAL_APP_NAME` is set — so a shared container would report healthy for both
    apps while being entirely blind to the TTS one.
    """

    def test_the_database_constraint_allows_tts(self):
        """The enum lived in three places and the database was the one missed.

        `VALID_TASK_TYPES`, `Provider._validate_worker_type` and the discovery
        guard all learned about `tts`; `chk_providers_worker_type` did not. A TTS
        worker passed every layer of application validation and was then rejected
        by Postgres at insert, so registration failed with a 500 and the provider
        stayed unregistered forever. This asserts the SQL constraint's vocabulary
        is exactly the Python constant's, so the two cannot drift again.

        SQLite, which the suite runs on, has no such constraint — so the test
        asserts the vocabulary the migration installs, from the migration source,
        and the live constraint is verified against the real database by the
        migration itself.
        """
        import inspect
        import re

        from core.entities import VALID_TASK_TYPES
        from infrastructure.migrations.steps import _migration_078_provider_worker_type_tts

        src = inspect.getsource(_migration_078_provider_worker_type_tts)
        # The tuple the migration installs into the CHECK constraint.
        m = re.search(r"CHECK \(worker_type IN \(([^)]*)\)\)", src)
        assert m, "could not find the CHECK constraint the migration installs"
        allowed = set(re.findall(r"'([a-z]+)'", m.group(1)))
        assert allowed == set(VALID_TASK_TYPES), (
            f"the SQL constraint allows {sorted(allowed)} but VALID_TASK_TYPES is "
            f"{sorted(VALID_TASK_TYPES)}; an enumeration in two places has to be "
            "changed in both and nothing else enforces that"
        )

    @pytest.mark.asyncio
    async def test_a_tts_provider_is_offered_tts_and_not_image(self, session):
        """The end of the chain: the container registered as `tts`, and the load
        balancer hands it speech without ever offering it a checkpoint."""
        from services.load_balancer_factory import create_load_balancer

        _provider(session, "tts-modal-x", worker_type="tts", capabilities=["tts"])
        _provider(session, "img-only", worker_type="image", capabilities=["image"])

        tts = await create_load_balancer(session, task_type="tts").get_next_provider(
            task_type="tts"
        )
        assert tts is not None and tts.id == "tts-modal-x"

        # And the image provider still gets image work, unchanged.
        img = await create_load_balancer(session, task_type="image").get_next_provider(
            task_type="image"
        )
        assert img is not None and img.id == "img-only"


class TestQueueSelection:
    def test_tts_has_its_own_pool(self):
        """TTS stops sharing the image pool.

        It used to, because both ran a ComfyUI graph and the old rule made
        `worker_type != "llm"` count as image capacity. The consequence was that
        a TTS worker you enabled grew *image* concurrency while the TTS pool
        itself stayed pinned at one — the provider page could not explain why a
        TTS setting changed image throughput. It is a category now, with its own
        pool and its own sizing rule.
        """
        from services.job_queue import QueueManager

        mgr = QueueManager()
        assert mgr.get_queue("image") is mgr.image
        assert mgr.get_queue("llm") is mgr.llm
        assert mgr.get_queue("tts") is mgr.tts
        assert mgr.tts is not mgr.image
        assert mgr.tts._claim_task_types == frozenset({"tts"})

    def test_an_unknown_task_type_has_no_pool(self):
        """`get_queue` used to be `if task_type == "llm": llm else image`, so a
        new category landed on the image pool by omission rather than by
        decision — and then silently shared image capacity. It now fails loudly:
        adding a category means adding a pool, which is the point."""
        from services.job_queue import QueueManager

        mgr = QueueManager()
        for known in ("image", "llm", "tts"):
            assert mgr.get_queue(known) is mgr.pools[known]
        for unknown in ("video", "audio", ""):
            try:
                mgr.get_queue(unknown)
            except KeyError:
                continue
            raise AssertionError(f"{unknown!r} resolved to a pool by omission")
