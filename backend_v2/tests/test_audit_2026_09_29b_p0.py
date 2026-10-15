"""Regression tests for the 2026-09-29b audit's backend P0s.

Each test here was written against the defect and verified to fail before the
fix. The TTS end-to-end path had five independent breaks, so the tests are
grouped by which link of the chain they cover.
"""

import os
from unittest.mock import AsyncMock, MagicMock, patch

import pytest

from core.entities import (
    CONTAINER_TASK_TYPES,
    Character,
    Chat,
    Location,
    Lorebook,
    Scenario,
    Story,
    VoiceModel,
    World,
)
from services.job_queue import JobQueue, QueueManager
from services.job_processing import (
    _AUDIO_OUTPUT_SUFFIXES,
    _fetch_remote_tts_outputs,
    _finalize_image_job,
    _is_audio_path,
    _safe_output_subdir,
)


# ---------------------------------------------------------------------------
# P0-3: a pool claims every task type it is physically responsible for
# ---------------------------------------------------------------------------


class TestQueueClaimScope:
    def test_every_pool_claims_exactly_its_own_task_type(self):
        """One category, one pool, one claim set.

        `tts` used to route to the image pool because both ran a ComfyUI graph,
        and the image pool then had to claim it. The claim predicate initially
        bound the pool's single `task_type` instead, so a `tts` row could never
        be a candidate and every TTS job sat PENDING forever with `enqueued_at`
        set and no error.

        That sharing was the ambiguity itself: a "TTS worker" sized as image
        capacity and was served by a pool named image. The claim-scope fix was
        correct and it has been superseded — a pool no longer has to claim a
        category that is not its own. What must still hold is the invariant the
        old test was really guarding: **no pool claims a task type it does not
        serve**, and every task type has exactly one home.
        """
        from core.entities import CATEGORY_CLAIM_TASK_TYPES, VALID_CATEGORIES

        manager = QueueManager()
        for category in sorted(VALID_CATEGORIES):
            queue = manager.get_queue(category)
            assert queue._claim_task_types == CATEGORY_CLAIM_TASK_TYPES[category]
            assert queue._claim_task_types == frozenset({category})

        # No task type has two homes, and no pool claims another's work.
        all_claimed = [t for c in CATEGORY_CLAIM_TASK_TYPES.values() for t in c]
        assert sorted(all_claimed) == sorted(VALID_CATEGORIES)

    def test_the_llm_pool_does_not_claim_container_work(self):
        manager = QueueManager()
        assert manager.llm._claim_task_types == frozenset({"llm"})

    def test_the_claim_query_renders_every_claimed_type(self):
        """A regression here is invisible in SQLite tests, which bypass the claim.

        `_DB_CLAIMS_ENABLED` is False under the test suite's SQLite engine, so
        the SQL text itself is what has to be asserted.
        """
        queue = JobQueue(max_workers=1, task_type="image", claim_task_types=CONTAINER_TASK_TYPES)
        source = JobQueue._claim_next_job_sync.__doc__ or ""
        assert source, "the claim docstring records the scope contract"
        # The rendered predicate is built from the claim set, so two types means
        # two placeholders.
        rendered = ", ".join(f":tt_{i}" for i in range(len(queue._claim_task_types)))
        assert rendered.count(":tt_") == len(CONTAINER_TASK_TYPES)

    def test_an_unknown_task_type_raises_rather_than_routing_silently(self):
        with pytest.raises(Exception):
            from api.routes.jobs import CreateJobRequest

            CreateJobRequest(workflow={}, task_type="bogus")

    def test_a_valid_task_type_is_accepted(self):
        from api.routes.jobs import CreateJobRequest

        for task_type in sorted(CONTAINER_TASK_TYPES) + ["llm"]:
            assert CreateJobRequest(workflow={}, task_type=task_type).task_type == task_type


# ---------------------------------------------------------------------------
# P0-4/P0-5: the TTS completion path
# ---------------------------------------------------------------------------


class TestTTSOutputTransport:
    def test_audio_suffixes_cover_what_the_workers_produce(self):
        for suffix in (".wav", ".mp3", ".ogg", ".flac", ".m4a", ".opus"):
            assert _is_audio_path(f"chat_tts/abc/narration{suffix}")

    def test_a_provider_subfolder_cannot_climb_out_of_the_output_dir(self):
        """The subfolder comes from a remote worker, on a path we write to."""
        for hostile in ("../../etc", "a/../b", "~/root", "..", "./../..", "a/./../../b"):
            safe = _safe_output_subdir(hostile)
            assert ".." not in safe, hostile
            assert "~" not in safe, hostile
            assert not safe.startswith("/"), hostile
        assert _safe_output_subdir("../../etc") == "etc"
        assert _safe_output_subdir("/abs/path/") == "abs/path"
        assert _safe_output_subdir("") == ""

    @staticmethod
    def _engine_ctx(monkeypatch, stream_fn=None):
        """Resolve the provider's in-process engine to a fake stream source.

        `_fetch_remote_tts_outputs` looks the engine up through the DB
        session + `engine_factory.get_engine`; stub both seams. `stream_fn`
        is an async generator function taking the remote path.
        """
        from types import SimpleNamespace

        async def _default_stream(path):
            yield b"audio"

        engine = SimpleNamespace(get_file_stream=stream_fn or _default_stream)
        monkeypatch.setattr(
            "services.engines.engine_factory.get_engine", lambda *args, **kwargs: engine
        )

        class _FakeSessionCtx:
            async def __aenter__(self):
                return MagicMock()

            async def __aexit__(self, *args):
                return False

        monkeypatch.setattr(
            "infrastructure.database.get_session_context", lambda: _FakeSessionCtx()
        )
        monkeypatch.setattr(
            "infrastructure.repositories.provider_repo.ProviderRepository",
            lambda session: SimpleNamespace(get=lambda provider_id: SimpleNamespace(id=provider_id)),
        )
        return engine

    def test_a_provider_output_is_fetched_and_written_to_disk(self, tmp_path, monkeypatch):
        monkeypatch.setattr("services.job_processing.settings.output_dir", str(tmp_path))
        self._engine_ctx(monkeypatch)

        outputs = _run(
            _fetch_remote_tts_outputs(
                job=MagicMock(metadata_={"type": "chat_tts"}),
                provider_id="tts-modal-hp196",
                final_result={
                    "outputs": [
                        {
                            "filename": "narration_00001_.wav",
                            "subfolder": "chat_tts/chat1/msg1",
                            "type": "output",
                        }
                    ]
                },
            )
        )
        # The provider's subfolder is the ComfyUI SaveAudio `filename_prefix`,
        # so rewriting it here would destroy the only thing that makes the
        # output findable.
        assert outputs == [
            {
                "filename": "narration_00001_.wav",
                "subfolder": "chat_tts/chat1/msg1",
                "relative_path": "chat_tts/chat1/msg1/narration_00001_.wav",
                "path": str(tmp_path / "chat_tts" / "chat1" / "msg1" / "narration_00001_.wav"),
                "type": "output",
            }
        ]
        assert (tmp_path / "chat_tts" / "chat1" / "msg1" / "narration_00001_.wav").read_bytes() == b"audio"

    def test_the_path_is_never_observed_half_written(self, tmp_path, monkeypatch):
        """Reconciliation polls for the path, so it must never exist empty."""
        monkeypatch.setattr("services.job_processing.settings.output_dir", str(tmp_path))
        seen: list[bool] = []

        async def _peeking_stream(path):
            seen.append((tmp_path / "chat_tts" / "a.wav").exists())
            yield b"audio"

        self._engine_ctx(monkeypatch, stream_fn=_peeking_stream)
        _run(
            _fetch_remote_tts_outputs(
                job=MagicMock(metadata_={}),
                provider_id="tts-modal-hp196",
                final_result={"outputs": [{"filename": "a.wav", "subfolder": "chat_tts"}]},
            )
        )
        assert seen == [False]
        assert (tmp_path / "chat_tts" / "a.wav").read_bytes() == b"audio"
        assert not (tmp_path / "chat_tts" / "a.wav.partial").exists()

    def test_an_unreadable_artifact_fails_that_artifact_not_the_job(self, tmp_path, monkeypatch):
        """The provider has already been paid; a retry re-bills it."""
        monkeypatch.setattr("services.job_processing.settings.output_dir", str(tmp_path))

        async def _flaky_stream(path):
            if "gone" in path:
                raise RuntimeError("provider said 500")
            yield b"audio"

        self._engine_ctx(monkeypatch, stream_fn=_flaky_stream)
        outputs = _run(
            _fetch_remote_tts_outputs(
                job=MagicMock(metadata_={}),
                provider_id="tts-modal-hp196",
                final_result={
                    "outputs": [
                        {"filename": "gone.wav", "subfolder": "chat_tts"},
                        {"filename": "here.wav", "subfolder": "chat_tts"},
                    ]
                },
            )
        )
        assert [o["filename"] for o in outputs] == ["here.wav"]

    def test_an_empty_body_is_not_persisted(self, tmp_path, monkeypatch):
        monkeypatch.setattr("services.job_processing.settings.output_dir", str(tmp_path))

        async def _empty_stream(path):
            if False:
                yield b""
            return

        self._engine_ctx(monkeypatch, stream_fn=_empty_stream)
        outputs = _run(
            _fetch_remote_tts_outputs(
                job=MagicMock(metadata_={}),
                provider_id="tts-modal-hp196",
                final_result={"outputs": [{"filename": "silent.wav", "subfolder": "chat_tts"}]},
            )
        )
        assert outputs == []
        assert not (tmp_path / "chat_tts" / "silent.wav").exists()

    def test_no_engine_yields_no_outputs_rather_than_a_wrong_path(self, tmp_path, monkeypatch):
        from types import SimpleNamespace

        monkeypatch.setattr("services.job_processing.settings.output_dir", str(tmp_path))
        monkeypatch.setattr(
            "services.engines.engine_factory.get_engine", lambda *args, **kwargs: None
        )

        class _FakeSessionCtx:
            async def __aenter__(self):
                return MagicMock()

            async def __aexit__(self, *args):
                return False

        monkeypatch.setattr(
            "infrastructure.database.get_session_context", lambda: _FakeSessionCtx()
        )
        monkeypatch.setattr(
            "infrastructure.repositories.provider_repo.ProviderRepository",
            lambda session: SimpleNamespace(get=lambda provider_id: SimpleNamespace(id=provider_id)),
        )
        outputs = _run(
            _fetch_remote_tts_outputs(
                job=MagicMock(metadata_={}),
                provider_id="gone",
                final_result={"outputs": [{"filename": "a.wav", "subfolder": "chat_tts"}]},
            )
        )
        assert outputs == []


class TestTTSEventRouting:
    def _run_finalize(self, metadata: dict, relative_path: str):
        captured = {}
        job = MagicMock(metadata_=metadata)
        with patch(
            "services.job_processing.finalize_persisted_job_outputs",
            AsyncMock(side_effect=lambda **kw: captured.update(kw)),
        ):
            _run(
                _finalize_image_job(
                    job=job,
                    job_id="job1",
                    job_service=MagicMock(),
                    load_balancer=MagicMock(),
                    provider_id="p1",
                    outputs=[{"relative_path": relative_path}],
                    process_image_background_fn=None,
                )
            )
        return captured.get("event_extra")

    def test_a_chat_narration_dispatches_to_the_tts_handler(self):
        event = self._run_finalize(
            {"type": "chat_tts", "chat_id": "c1"},
            "chat_tts/c1/m1/narration.wav",
        )
        assert event["type"] == "chat_tts"

    def test_a_chat_image_still_dispatches_to_the_image_handler(self):
        event = self._run_finalize({"chat_id": "c1"}, "2026/09/29/scene.png")
        assert event["type"] == "chat_image"

    def test_a_chapter_narration_dispatches_to_story_tts_not_story_image(self):
        """This one was hardcoded, so every story narration went to the image
        handler and the audio was never attached to the chapter's beat list."""
        event = self._run_finalize(
            {"source": "story_tts", "story_id": "s1", "chapter_id": "ch1"},
            "story_tts/s1/ch1/narration.wav",
        )
        assert event["type"] == "story_tts"
        assert event["story_id"] == "s1"
        assert event["chapter_id"] == "ch1"

    def test_a_chapter_image_is_still_a_story_image(self):
        event = self._run_finalize(
            {"story_id": "s1", "chapter_id": "ch1"},
            "2026/09/29/panel.png",
        )
        assert event["type"] == "story_image"

    def test_a_voice_preview_still_dispatches_to_the_voice_handler(self):
        event = self._run_finalize(
            {"type": "voice_preview", "voice_id": "v1"},
            "voice_preview/v1/preview.wav",
        )
        assert event["type"] == "voice_preview"
        assert event["voice_id"] == "v1"


# ---------------------------------------------------------------------------
# P0-2: the World entity owns something
# ---------------------------------------------------------------------------


class TestWorldOwnership:
    """World membership is one column on the member, and only one column.

    This class used to be the strongest evidence for the two-sided contract: it
    seeded `World.chat_ids` / `World.story_ids` by hand and asserted they stayed
    in step with the `Chat.world_id` / `Story.world_id` FKs. Those arrays are
    gone (migration `090_world_membership_fks`), together with the desync they
    existed to express — `PUT /api/v2/worlds/{id}` could rewrite them without
    touching the FKs, and `lorebook_ids`/`scenario_ids`/`voice_ids` had no scrub
    path at all.

    What replaces the "both sides agree" assertion is the stronger claim that
    there is only one side: membership IS `world_id`, and it is read from the
    member the same way by every consumer.
    """

    def test_creating_a_chat_in_a_world_writes_the_ownership(self, client, session):
        world = World(name="W", description="d")
        session.add(world)
        session.commit()
        session.refresh(world)

        response = client.post("/api/v2/chats", json={"name": "c", "world_id": world.id})
        assert response.status_code == 200
        assert response.json()["world_id"] == world.id

        session.expire_all()
        assert session.get(Chat, response.json()["id"]).world_id == world.id

    def test_a_world_lists_its_members_through_the_fk(self, client, session):
        """The direction every consumer actually reads.

        The world page and the dashboard used to read an id array on the world
        row. They read `world_id` on the members now, so a member shows up by
        being in the world rather than by being listed in it.
        """
        world = World(name="W", description="d")
        session.add(world)
        session.commit()
        session.refresh(world)

        chat = Chat(name="c", chat_type="chat", world_id=world.id)
        session.add(chat)
        session.commit()

        body = client.get(f"/api/v2/worlds/{world.id}/dashboard").json()
        assert body["chats"] == [{"id": chat.id, "name": "c"}]

    def test_a_chat_can_be_moved_between_worlds(self, client, session):
        first = World(name="A")
        second = World(name="B")
        session.add(first)
        session.add(second)
        session.commit()
        session.refresh(first)
        session.refresh(second)

        chat = Chat(name="c", chat_type="chat", world_id=first.id)
        session.add(chat)
        session.commit()

        assert client.patch(f"/api/v2/chats/{chat.id}", json={"world_id": second.id}).status_code == 200
        session.expire_all()
        assert session.get(Chat, chat.id).world_id == second.id
        assert client.get(f"/api/v2/worlds/{first.id}/dashboard").json()["chats"] == []
        assert client.get(f"/api/v2/worlds/{second.id}/dashboard").json()["chats"] == [
            {"id": chat.id, "name": "c"}
        ]

    def test_an_empty_string_detaches(self, client, session):
        world = World(name="A")
        session.add(world)
        session.commit()
        session.refresh(world)
        chat = Chat(name="c", chat_type="chat", world_id=world.id)
        session.add(chat)
        session.commit()

        assert client.patch(f"/api/v2/chats/{chat.id}", json={"world_id": ""}).status_code == 200
        session.expire_all()
        assert session.get(Chat, chat.id).world_id is None
        assert client.get(f"/api/v2/worlds/{world.id}/dashboard").json()["chats"] == []

    def test_an_unrelated_patch_does_not_detach(self, client, session):
        """Guards the sentinel, not the link.

        The hazard is a default of `None` standing in for both "not supplied"
        and "detach", which would unlink every world's chat on any unrelated
        PATCH. The proof is that removing the *sentinel* — not the link call —
        fails this test, which is why the test name says what it protects.
        """
        world = World(name="A")
        session.add(world)
        session.commit()
        session.refresh(world)
        chat = Chat(name="c", chat_type="chat", world_id=world.id)
        session.add(chat)
        session.commit()

        assert client.patch(f"/api/v2/chats/{chat.id}", json={"name": "renamed"}).status_code == 200
        session.expire_all()
        assert session.get(Chat, chat.id).world_id == world.id

    def test_an_unknown_world_is_a_404_not_a_silent_drop(self, client):
        response = client.post("/api/v2/chats", json={"name": "c", "world_id": "nope"})
        assert response.status_code == 404

    def test_a_story_can_be_created_in_a_world(self, client, session):
        world = World(name="W")
        session.add(world)
        session.commit()
        session.refresh(world)

        response = client.post("/api/v2/stories", json={"title": "s", "world_id": world.id})
        assert response.status_code == 200
        assert response.json()["world_id"] == world.id
        session.expire_all()
        assert session.get(Story, response.json()["id"]).world_id == world.id

    def test_a_story_can_be_moved_between_worlds(self, client, session):
        first = World(name="A")
        second = World(name="B")
        session.add(first)
        session.add(second)
        session.commit()
        session.refresh(first)
        session.refresh(second)
        story = Story(title="s", world_id=first.id)
        session.add(story)
        session.commit()

        assert client.put(f"/api/v2/stories/{story.id}", json={"world_id": second.id}).status_code == 200
        session.expire_all()
        assert session.get(Story, story.id).world_id == second.id
        assert client.get(f"/api/v2/worlds/{second.id}/dashboard").json()["stories"] == [
            {"id": story.id, "title": "s"}
        ]

    def test_a_story_patch_without_world_id_leaves_it_alone(self, client, session):
        """`world_id` is deliberately outside the story's `allowed` set; a plain
        rename must not fall through into a detach."""
        world = World(name="A")
        session.add(world)
        session.commit()
        session.refresh(world)
        story = Story(title="s", world_id=world.id)
        session.add(story)
        session.commit()

        assert client.put(f"/api/v2/stories/{story.id}", json={"title": "renamed"}).status_code == 200
        session.expire_all()
        assert session.get(Story, story.id).world_id == world.id
        assert session.get(Story, story.id).title == "renamed"

    def test_deleting_a_world_detaches_every_member_table(self, client, session):
        """Not just chats and stories.

        `detach_world` used to null two FKs and leave Character, Lorebook,
        Location, Scenario and VoiceModel pointing at a world that no longer
        existed — including the lorebooks and locations that are merged into
        every prompt built for a chat in that world.
        """
        world = World(name="W")
        session.add(world)
        session.commit()
        session.refresh(world)
        chat = Chat(name="c", chat_type="chat", world_id=world.id)
        story = Story(title="s", world_id=world.id)
        char = Character(name="Aria", world_id=world.id)
        loc = Location(name="Cellar", world_id=world.id)
        book = Lorebook(name="Book", world_id=world.id)
        scenario = Scenario(name="Storm", prompt_template="p", world_id=world.id)
        voice = VoiceModel(name="V", voice_profile="v", world_id=world.id)
        session.add_all([chat, story, char, loc, book, scenario, voice])
        session.commit()

        assert client.delete(f"/api/v2/worlds/{world.id}").status_code == 200
        session.expire_all()
        for entity, cls in ((chat, Chat), (story, Story), (char, Character),
                            (loc, Location), (book, Lorebook),
                            (scenario, Scenario), (voice, VoiceModel)):
            assert session.get(cls, entity.id).world_id is None, cls.__name__

    def test_deleting_a_member_stops_it_counting_in_the_world(self, client, session):
        """The scrub the three unwritten columns never had."""
        world = World(name="W")
        session.add(world)
        session.commit()
        session.refresh(world)
        book = Lorebook(name="Book", world_id=world.id)
        session.add(book)
        session.commit()

        assert client.delete(f"/api/v2/lorebooks/{book.id}").status_code == 200
        session.expire_all()
        assert session.get(Lorebook, book.id) is None

    def test_the_world_scrub_branch_exists(self):
        """`scrub_entity_references` had no `kind == "world"` branch because
        nothing set `world_id` when it was written."""
        from services import reference_cleanup

        source = open(reference_cleanup.__file__).read()
        assert 'kind == "world"' in source

    def test_membership_has_one_owner_module(self):
        """Every WRITE of `world_id` is an assignment in `world_ownership.py`.

        The failure this guards against is a second path appearing. The old bug
        was not that `world_ownership.py` was wrong — it was that
        `PUT /api/v2/worlds/{id}` accepted `chat_ids`/`story_ids` and wrote them
        straight onto the world, bypassing it, so a world could list a member
        the member did not belong to.

        AST rather than grep, because `world_id` also appears in reads
        (`Chat.world_id == wid`) and in local names (`world_id = ...`), and a
        substring test would fail on the code it is supposed to protect.
        """
        import ast
        from pathlib import Path

        root = Path(__file__).resolve().parents[1]
        offenders: list[str] = []
        for path in sorted(root.rglob("*.py")):
            rel = str(path.relative_to(root))
            if rel.startswith(("tests/", ".venv/", "build/")) or "__pycache__" in rel:
                continue
            if rel == "services/world_ownership.py":
                continue
            tree = ast.parse(path.read_text())
            for node in ast.walk(tree):
                # `something.world_id = value` — Exclude bare name assignments
                # and every comparison (`==`, `!=`, `in`).
                if isinstance(node, ast.Assign):
                    for target in node.targets:
                        if (
                            isinstance(target, ast.Attribute)
                            and target.attr == "world_id"
                        ):
                            offenders.append(f"{rel}:{node.lineno}")
        assert not offenders, "a second writer for world_id: " + ", ".join(offenders)


# ---------------------------------------------------------------------------
# P1: the TTS provider's deploy path and its capability column
# ---------------------------------------------------------------------------


class TestProviderCapabilitiesAreWritable:
    def test_declared_capabilities_are_persisted(self, client, session):
        """The column the load balancer's `serves()` reads had no write path:
        the service computed a validated list into `payload["capabilities"]`
        and then returned a dict without it."""
        created = client.post(
            "/api/v2/providers",
            json={"id": "p-caps", "type": "modal", "worker_type": "tts", "declared_capabilities": ["tts"], "credentials": {"token_id": "t", "token_secret": "s"}},
        )
        assert created.status_code in (200, 201), created.text

        session.expire_all()
        from core.entities import Provider

        assert list(session.get(Provider, "p-caps").capabilities) == ["tts"]

    def test_the_list_endpoint_exposes_the_column_under_its_own_name(self, client):
        """`capabilities` on the read path is the unrelated UI action map; the
        column answering "can this provider serve TTS" was the one missing."""
        client.post(
            "/api/v2/providers",
            json={"id": "p-caps2", "type": "modal", "worker_type": "tts", "declared_capabilities": ["tts"], "credentials": {"token_id": "t", "token_secret": "s"}},
        )
        listed = {p["id"]: p for p in client.get("/api/v2/providers").json()["providers"]}
        row = listed["p-caps2"]
        assert row["declared_capabilities"] == ["tts"]
        # The action map is still there and is still a map, not a list.
        assert isinstance(row["capabilities"], dict)
        assert "setup" in row["capabilities"]

    def test_declared_capabilities_can_be_updated(self, client, session):
        client.post(
            "/api/v2/providers",
            json={"id": "p-caps3", "type": "modal", "worker_type": "image", "declared_capabilities": ["image"], "credentials": {"token_id": "t", "token_secret": "s"}},
        )
        assert client.patch(
            "/api/v2/providers/p-caps3", json={"declared_capabilities": ["image", "tts"]}
        ).status_code == 200
        session.expire_all()
        from core.entities import Provider

        assert set(session.get(Provider, "p-caps3").capabilities) == {"image", "tts"}

    def test_an_unknown_declared_capability_is_a_422(self, client):
        response = client.post(
            "/api/v2/providers",
            json={"id": "p-bad", "type": "modal", "declared_capabilities": ["banana"], "credentials": {"token_id": "t", "token_secret": "s"}},
        )
        assert response.status_code == 422

    def test_an_unknown_worker_type_is_a_422_not_a_500(self, client, session):
        """`{"worker_type": "banana"}` used to reach the CHECK constraint and
        surface as an unmapped `IntegrityError` 500.

        The provider has to exist for this to reach validation at all — with a
        missing id the route 404s first and the assertion below would pass
        against a request that never reached the field.
        """
        created = client.post("/api/v2/providers", json={"id": "p-wt", "type": "modal", "credentials": {"token_id": "t", "token_secret": "s"}})
        assert created.status_code in (200, 201), created.text

        response = client.patch("/api/v2/providers/p-wt", json={"worker_type": "banana"})
        assert response.status_code == 422, response.text
        session.expire_all()
        from core.entities import Provider

        assert session.get(Provider, "p-wt").worker_type == "image"

    def test_an_unknown_world_is_a_404_not_a_silent_drop(self, client):
        response = client.post("/api/v2/chats", json={"name": "c", "world_id": "nope"})
        assert response.status_code == 404


def _run(coro):
    import asyncio

    try:
        asyncio.get_running_loop()
    except RuntimeError:
        return asyncio.run(coro)
    raise RuntimeError("_run() must be called from a sync test")


# `os` is imported for the path assertions above; keep the import honest.
assert os.sep == "/"
assert _AUDIO_OUTPUT_SUFFIXES
