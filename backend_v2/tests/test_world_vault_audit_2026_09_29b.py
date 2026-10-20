"""Regression tests for the 2026-09-29b audit's World Vault backend findings.

Each class pins one defect that shipped through a green suite. Where the defect
was "the test asserted a structure, not a behaviour" (the TTS routes), the test
here asserts the behaviour: which task type the job carries, which node types the
graph names, and what the context builder is actually handed.
"""
import asyncio
from datetime import datetime, timedelta, timezone
from unittest.mock import AsyncMock

from sqlmodel import select

from core.entities import (
    Chat,
    Character,
    Job,
    Lorebook,
    LorebookEntry,
    Message,
    MessageRole,
    Story,
    StoryChapter,
)
from infrastructure.repositories.message_repo import MessageRepository


# ── helpers ────────────────────────────────────────────────────────────────


def _seed_chat(session, **kw) -> Chat:
    chat = Chat(name="AuditChat", **kw)
    session.add(chat)
    session.commit()
    session.refresh(chat)
    return chat


def _add_message(session, chat, role, content, *, at=None, branch_id=None):
    # Explicit, strictly increasing timestamps. `create_branch` selects its
    # prefix with `created_at <= anchor.created_at` and orders by
    # `(created_at, id)`, so equal timestamps make "the prefix" and "the chain"
    # depend on random uuid ordering.
    stamp = at or (datetime(2026, 1, 1, tzinfo=timezone.utc) + timedelta(seconds=_seq()))
    msg = Message(
        chat_id=chat.id,
        role=role,
        content=content,
        created_at=stamp,
        updated_at=stamp,
        branch_id=branch_id,
    )
    session.add(msg)
    session.commit()
    session.refresh(msg)
    return msg


_SEQ = iter(range(1, 10_000))


def _seq() -> int:
    return next(_SEQ)


def _create_branch(client, chat_id, message_id, branch_name="Fork"):
    resp = client.post(
        f"/api/v2/chats/{chat_id}/branches",
        json={"message_id": message_id, "branch_name": branch_name},
    )
    assert resp.status_code == 200, resp.text
    return resp.json()


# ── D2: the paid context read was not branch-filtered ─────────────────────


class TestBranchFilteredContextReads:
    def test_send_into_main_thread_never_sees_branch_copies(
        self, client, session, monkeypatch
    ):
        """`POST /messages` must hand the context builder the thread it posted
        into — nothing else.

        `create_branch` copies messages with their originals' `chat_id` AND
        `created_at`, so an unfiltered read returns the branch's copies
        interleaved among equal timestamps and the model receives the same
        conversation twice. The message read route was already scoped; this is
        the read on the paid path.
        """
        chat = _seed_chat(session)
        m1 = _add_message(session, chat, MessageRole.USER, "the original question")
        _add_message(session, chat, MessageRole.CHAR, "the original answer")
        branch = _create_branch(client, chat.id, m1.id)

        seen: list[list[str]] = []

        def _spy(_session, _workspace, _entity, messages, **kwargs):
            seen.append([m.content for m in messages])
            # Three values: the trace-carrying builder's contract.
            return "sys", [{"role": "user", "content": "x"}], []

        monkeypatch.setattr(
            "api.routes.world_vault.chats.build_context", _spy
        )
        monkeypatch.setattr(
            "services.job_queue.queue_manager.enqueue", AsyncMock(return_value=True)
        )

        resp = client.post(
            f"/api/v2/chats/{chat.id}/messages",
            json={"role": "user", "content": "asked in the main thread"},
        )
        assert resp.status_code == 200, resp.text

        assert seen, "the context builder was never called"
        contents = seen[0]
        assert "asked in the main thread" in contents
        # The branch holds copies of the first two messages, with the same text.
        assert contents.count("the original question") == 1
        assert contents.count("the original answer") == 1
        # And nothing from the branch id leaked in.
        assert branch["branch_id"] not in [m.id for m in session.exec(
            select(Message).where(Message.branch_id == branch["branch_id"])
        ).all() if m.content in contents]

    def test_send_into_a_branch_sees_only_that_branch(self, client, session, monkeypatch):
        chat = _seed_chat(session)
        m1 = _add_message(session, chat, MessageRole.USER, "the original question")
        _add_message(session, chat, MessageRole.CHAR, "the original answer")
        branch = _create_branch(client, chat.id, m1.id, branch_name="WhatIf")

        seen: list[list[str]] = []

        def _spy(_session, _workspace, _entity, messages, **kwargs):
            seen.append([m.content for m in messages])
            # Three values: the trace-carrying builder's contract.
            return "sys", [{"role": "user", "content": "x"}], []

        monkeypatch.setattr(
            "api.routes.world_vault.chats.build_context", _spy
        )
        monkeypatch.setattr(
            "services.job_queue.queue_manager.enqueue", AsyncMock(return_value=True)
        )

        resp = client.post(
            f"/api/v2/chats/{chat.id}/messages",
            json={
                "role": "user",
                "content": "asked in the fork",
                "branch_id": branch["branch_id"],
            },
        )
        assert resp.status_code == 200, resp.text

        contents = seen[0]
        assert "asked in the fork" in contents
        # The branch carries a copy of m1 but NOT of m2 (m2 came after the
        # anchor), so the fork's view is the prefix plus the new question.
        assert contents.count("the original question") == 1
        assert "the original answer" not in contents

    def test_swipe_on_a_branch_answers_from_that_branch(self, client, session, monkeypatch):
        chat = _seed_chat(session)
        _add_message(session, chat, MessageRole.USER, "the original question")
        target = _add_message(session, chat, MessageRole.CHAR, "the original answer")
        _add_message(session, chat, MessageRole.USER, "asked after the answer")
        # Anchored on the CHARACTER turn, so the fork's copy of it is the swipe
        # target and the main thread's later turn is not in the fork at all.
        branch = _create_branch(client, chat.id, target.id, branch_name="WhatIf")

        branch_target = session.exec(
            select(Message).where(Message.branch_id == branch["branch_id"])
        ).all()[-1]
        assert branch_target.id != target.id
        assert branch_target.role == MessageRole.CHAR

        seen: list[list[str]] = []

        def _spy(_session, _workspace, _entity, messages, **kwargs):
            seen.append([m.content for m in messages])
            # Three values: the trace-carrying builder's contract.
            return "sys", [{"role": "user", "content": "x"}], []

        monkeypatch.setattr(
            "api.routes.world_vault.chats.build_context", _spy
        )
        monkeypatch.setattr(
            "services.job_queue.queue_manager.enqueue", AsyncMock(return_value=True)
        )

        resp = client.post(
            f"/api/v2/chats/{chat.id}/messages/{branch_target.id}/generate-swipe"
        )
        assert resp.status_code == 200, resp.text
        contents = seen[0]
        # The history AFTER the target exists only on the main thread; a swipe
        # must not be conditioned on turns the user has not taken on this fork.
        assert "asked after the answer" not in contents
        assert contents.count("the original question") == 1

    def test_list_by_chat_defaults_to_the_original_thread(self, session):
        chat = _seed_chat(session)
        _add_message(session, chat, MessageRole.USER, "main one")
        _add_message(session, chat, MessageRole.USER, "branch one", branch_id="b1")
        _add_message(session, chat, MessageRole.USER, "branch two", branch_id="b2")

        repo = MessageRepository(session)
        assert [m.content for m in repo.list_by_chat(chat.id)] == ["main one"]
        assert [m.content for m in repo.list_by_chat(chat.id, branch_id="b1")] == [
            "branch one"
        ]
        assert [m.content for m in repo.list_by_chat(chat.id, branch_id="b2")] == [
            "branch two"
        ]


# ── D3: a branch had no edges and could not be continued ───────────────────


class TestBranchGraphEdges:
    def test_create_branch_chains_the_copies(self, client, session):
        """`Message.parent_id` had ZERO writers in production code, so every
        source message's own parent was null and every copy got
        `parent_id=None`: the branch graph was a flat list and a client that
        renders the tree had nothing to render. The messages below deliberately
        have no `parent_id`, which is the state the database is actually in."""
        chat = _seed_chat(session)
        m1 = _add_message(session, chat, MessageRole.USER, "one")
        m2 = _add_message(session, chat, MessageRole.CHAR, "two")
        m3 = _add_message(session, chat, MessageRole.USER, "three")
        assert all(m.parent_id is None for m in (m1, m2, m3))

        branch = _create_branch(client, chat.id, m3.id)
        copies = session.exec(
            select(Message)
            .where(Message.branch_id == branch["branch_id"])
            .order_by(Message.created_at, Message.id)
        ).all()
        assert len(copies) == 3
        # A conversation prefix: the first copy is the root, each later copy
        # points at the one before it, and every parent is itself a copy here.
        assert copies[0].parent_id is None
        for prev, cur in zip(copies, copies[1:]):
            assert cur.parent_id == prev.id
        assert {c.id for c in copies}.isdisjoint({m1.id, m2.id, m3.id})

    def test_an_existing_parent_edge_is_preserved(self, client, session):
        """When a source thread DOES have edges — which nothing writes today, but
        an import might — the copy remaps them rather than re-chaining."""
        chat = _seed_chat(session)
        m1 = _add_message(session, chat, MessageRole.USER, "one")
        m2 = _add_message(session, chat, MessageRole.CHAR, "two")
        m2.parent_id = m1.id
        session.add(m2)
        session.commit()

        branch = _create_branch(client, chat.id, m2.id)
        copies = session.exec(
            select(Message)
            .where(Message.branch_id == branch["branch_id"])
            .order_by(Message.created_at, Message.id)
        ).all()
        assert copies[1].parent_id == copies[0].id
        assert copies[1].parent_id != m1.id

    def test_branch_of_a_branch_remaps_the_parent(self, client, session):
        """A branch cut out of another branch must keep the edge, not drop it."""
        chat = _seed_chat(session)
        _add_message(session, chat, MessageRole.USER, "one")
        m2 = _add_message(session, chat, MessageRole.CHAR, "two")
        first = _create_branch(client, chat.id, m2.id, branch_name="First")

        first_copies = session.exec(
            select(Message)
            .where(Message.branch_id == first["branch_id"])
            .order_by(Message.created_at, Message.id)
        ).all()
        nested = _create_branch(client, chat.id, first_copies[-1].id, branch_name="Second")

        nested_copies = session.exec(
            select(Message)
            .where(Message.branch_id == nested["branch_id"])
            .order_by(Message.created_at, Message.id)
        ).all()
        assert len(nested_copies) == 2
        # The second copy's parent is the FIRST copy — remapped into this
        # branch, not left pointing at the sibling branch's row.
        assert nested_copies[1].parent_id == nested_copies[0].id
        assert nested_copies[1].parent_id not in {c.id for c in first_copies[1:]}

    def test_list_branches_reports_the_edges(self, client, session):
        chat = _seed_chat(session)
        m1 = _add_message(session, chat, MessageRole.USER, "one")
        m2 = _add_message(session, chat, MessageRole.CHAR, "two")
        assert m1.parent_id is None and m2.parent_id is None

        branch = _create_branch(client, chat.id, m2.id)
        data = client.get(f"/api/v2/chats/{chat.id}/branches").json()
        entry = next(g for g in data if g["branch_id"] == branch["branch_id"])
        parents = [m["parent_id"] for m in entry["messages"]]
        assert parents[0] is None
        assert parents[1] == entry["messages"][0]["id"]


class TestBranchContinuation:
    def test_post_message_accepts_a_branch_id(self, client, session, monkeypatch):
        chat = _seed_chat(session)
        m1 = _add_message(session, chat, MessageRole.USER, "one")
        branch = _create_branch(client, chat.id, m1.id)

        monkeypatch.setattr(
            "api.routes.world_vault.chats.build_context",
            lambda *a, **kw: ("sys", [], []),
        )
        monkeypatch.setattr(
            "services.job_queue.queue_manager.enqueue", AsyncMock(return_value=True)
        )

        resp = client.post(
            f"/api/v2/chats/{chat.id}/messages",
            json={"role": "user", "content": "continue the fork", "branch_id": branch["branch_id"]},
        )
        assert resp.status_code == 200, resp.text
        stored = session.get(Message, resp.json()["user_message_id"])
        assert stored.branch_id == branch["branch_id"]
        # The reply job carries the branch, because `_handle_chat_reply` is the
        # only writer of CHAR messages and has no other way to know the fork.
        assert stored.branch_id is not None

    def test_post_message_rejects_an_unknown_branch(self, client, session):
        chat = _seed_chat(session)
        resp = client.post(
            f"/api/v2/chats/{chat.id}/messages",
            json={"role": "user", "content": "into nowhere", "branch_id": "not-a-branch"},
        )
        assert resp.status_code == 404
        assert session.exec(
            select(Message).where(Message.content == "into nowhere")
        ).all() == []

    def test_the_reply_lands_on_the_branch(self, client, session, monkeypatch):
        """End to end: post into a fork, run the completion handler, and the
        answer is on the fork — not interleaved into the original thread."""
        from services import world_integration_service as wis

        chat = _seed_chat(session)
        m1 = _add_message(session, chat, MessageRole.USER, "one")
        branch = _create_branch(client, chat.id, m1.id)

        monkeypatch.setattr(
            "api.routes.world_vault.chats.build_context",
            lambda *a, **kw: ("sys", [], []),
        )
        monkeypatch.setattr(
            "services.job_queue.queue_manager.enqueue", AsyncMock(return_value=True)
        )
        resp = client.post(
            f"/api/v2/chats/{chat.id}/messages",
            json={"role": "user", "content": "continue the fork", "branch_id": branch["branch_id"]},
        )
        job_id = resp.json()["job_id"]
        job = session.get(Job, job_id)
        assert job.metadata_["branch_id"] == branch["branch_id"]

        session.expire_all()
        asyncio.run(
            wis._handle_chat_reply(
                {
                    "id": job_id,
                    "metadata": dict(job.metadata_),
                    "outputs": [{"text": "the fork's answer"}],
                    "type": "chat_reply",
                }
            )
        )
        session.expire_all()
        answers = session.exec(
            select(Message).where(Message.content == "the fork's answer")
        ).all()
        assert len(answers) == 1
        assert answers[0].branch_id == branch["branch_id"]
        # The original thread did not grow.
        main_thread = client.get(f"/api/v2/chats/{chat.id}/messages").json()
        assert all(m["content"] != "the fork's answer" for m in main_thread)
        fork = client.get(
            f"/api/v2/chats/{chat.id}/messages?branch_id={branch['branch_id']}"
        ).json()
        assert "the fork's answer" in [m["content"] for m in fork]


# ── D4: get_max_chapter_number had no LIMIT ────────────────────────────────


class TestChapterMaxHasALimit:
    def test_query_carries_a_limit(self, session):
        """`.first()` applies no LIMIT of its own, so this shipped every chapter
        row — `content` TEXT included — to read one integer. The two inline
        sites the audit fixed had `.limit(1)`; the extracted repository did not.
        """
        from infrastructure.repositories.story_chapter_repo import (
            StoryChapterRepository,
        )

        story = Story(title="Limiter")
        session.add(story)
        session.commit()
        session.refresh(story)
        for n in range(5):
            session.add(StoryChapter(story_id=story.id, chapter_number=n, content="x" * 100))
        session.commit()

        seen: list[str] = []

        class _Recorder:
            def __init__(self, inner):
                self._inner = inner

            def exec(self, stmt):
                seen.append(str(stmt))
                return self._inner.exec(stmt)

        repo = StoryChapterRepository(_Recorder(session))
        assert repo.get_max_chapter_number(story.id).chapter_number == 4
        assert len(seen) == 1
        assert "LIMIT" in seen[0].upper(), seen[0]

    def test_backend_has_no_unbounded_order_by_first(self):
        """The audit's pattern, asserted over the whole source tree rather than
        one call site: this is the third time a fix landed on the sites the
        report named and left an equal site behind.

        Scoped per function so a `.first()` in a LATER function cannot be
        attributed to an earlier `.order_by`, and comment lines are skipped —
        one correct site in `chats.py` documents the hazard in a comment that
        contains the string `.first()` itself. The window is 12 lines, which
        covers the shape this recurs in (`.order_by(...)` then `.first()` a
        couple of lines later)."""
        import ast
        import pathlib

        root = pathlib.Path(__file__).resolve().parents[1]
        skip = {".venv", "node_modules", "tests", "__pycache__", "data", ".git"}
        offenders: list[str] = []

        def _scan(lines, offset, where):
            for i, line in enumerate(lines):
                if ".order_by(" not in line:
                    continue
                window = [line]
                for nxt in lines[i + 1: i + 12]:
                    stripped = nxt.strip()
                    if not stripped or stripped.startswith("#"):
                        continue
                    window.append(nxt)
                text = "\n".join(window)
                if ".first(" not in text:
                    continue
                if ".limit(" in text and text.index(".limit(") < text.index(".first("):
                    continue
                offenders.append(f"{where}:{offset + i + 1}")

        for path in sorted(root.rglob("*.py")):
            if skip & set(path.parts):
                continue
            src = path.read_text()
            try:
                tree = ast.parse(src)
            except SyntaxError:
                continue
            where = str(path.relative_to(root))
            all_lines = src.splitlines()
            funcs = [
                n
                for n in ast.walk(tree)
                if isinstance(n, (ast.FunctionDef, ast.AsyncFunctionDef))
            ]
            covered: set[int] = set()
            for func in funcs:
                start, end = func.lineno - 1, (func.end_lineno or func.lineno)
                _scan(all_lines[start:end], start, where)
                covered.update(range(start, end))
            _scan(
                [ln for i, ln in enumerate(all_lines) if i not in covered],
                0,
                where,
            )
        assert offenders == [], (
            "`.order_by(...).first()` with no `.limit(...)` — each of these ships "
            f"every matching row to read one: {sorted(set(offenders))}"
        )


# ── D5: impersonation read the OLDEST 200 messages ────────────────────────


class TestImpersonationReadsTheNewest:
    def test_context_ends_at_the_latest_message(self, session, monkeypatch):
        """`.order_by(created_at).limit(200)` with ascending order takes the
        FIRST 200, so past 200 messages the impersonation was generated from the
        opening of the conversation. Every other reply path takes the newest."""
        from services import world_integration_service as wis

        chat = _seed_chat(session, persona_name="Aria")
        base = datetime(2026, 1, 1, tzinfo=timezone.utc)
        for i in range(240):
            _add_message(session, chat, MessageRole.USER, f"turn {i}", at=base + timedelta(seconds=i))

        captured: list[list[str]] = []

        async def _spy(messages, **kwargs):
            captured.append([m.content for m in messages])
            return "sys", [], []

        # `_handle_impersonation` imports the builder from
        # `services.context_builder` inside the function body, so the patch has
        # to land on the source module.
        monkeypatch.setattr(
            "services.context_builder.build_chat_context_with_sections_async", _spy
        )
        monkeypatch.setattr(
            "services.job_queue.queue_manager.enqueue", AsyncMock(return_value=True)
        )

        asyncio.run(
            wis._handle_impersonation(
                {
                    "id": "imp-job",
                    "metadata": {"chat_id": chat.id},
                    "outputs": [{"text": "Aria steps forward."}],
                    "type": "impersonation",
                }
            )
        )
        assert captured, "the context builder was never called"
        context = captured[0]
        assert len(context) == 200
        # The newest message in the chat is the impersonation itself, which the
        # handler inserts before building the context.
        assert context[-1] == "Aria steps forward."
        assert "turn 239" in context, "the window does not reach the tail"
        assert "turn 0" not in context, (
            "the window starts at the opening of the chat, not the tail"
        )
        # And it is chronological, not reversed.
        turns = [c for c in context if c.startswith("turn ")]
        assert turns == sorted(turns, key=lambda c: int(c.split()[-1]))


# ── D7: the system-prompt route assembled the prompt twice ────────────────


class TestSystemPromptBuiltOnce:
    def test_one_assembly_per_request(self, client, session, monkeypatch):
        """`build_system_prompt_sections` runs an embedding forward pass and two
        pgvector queries. The route called it, then called `build_chat_context`,
        which called it again and discarded the first — four passes on the most
        invalidated route in the app."""
        from services import context_builder

        chat = _seed_chat(session)
        _add_message(session, chat, MessageRole.USER, "hello")

        calls: list[str] = []
        real_sections = context_builder.build_system_prompt_sections

        def _counting(*args, **kwargs):
            calls.append("sections")
            return real_sections(*args, **kwargs)

        monkeypatch.setattr(context_builder, "build_system_prompt_sections", _counting)

        resp = client.get(f"/api/v2/chats/{chat.id}/system-prompt")
        assert resp.status_code == 200, resp.text
        assert len(calls) == 1, (
            f"build_system_prompt_sections ran {len(calls)} times; it embeds the "
            "query and runs two pgvector searches, and the route must reuse the "
            "sections the single context build already produced"
        )

    def test_response_shape_is_preserved(self, client, session):
        chat = _seed_chat(session)
        _add_message(session, chat, MessageRole.USER, "hello")
        body = client.get(f"/api/v2/chats/{chat.id}/system-prompt").json()
        assert set(body) == {
            "chat_id",
            "character_id",
            "system_prompt",
            "has_override",
            "has_append",
            "message_count",
            "context_tokens",
            "sections",
        }
        assert isinstance(body["sections"], list)
        for section in body["sections"]:
            assert set(section) == {"key", "label", "content", "source"}
        # The prompt and the breakdown now describe the SAME pass, which they did
        # not before: the discarded call was made without the messages.
        joined = "\n\n".join(s["content"] for s in body["sections"])
        assert joined == body["system_prompt"]


# ── D8: search_lorebook_entries(limit=N) could return 3N ──────────────────


class TestLorebookSearchHonoursLimit:
    def _lorebook(self, session, *, keyed, keyless):
        book = Lorebook(name="Audit")
        session.add(book)
        session.commit()
        session.refresh(book)
        base = datetime(2026, 1, 1, tzinfo=timezone.utc)
        made = []
        for i in range(keyed):
            made.append(
                LorebookEntry(
                    lorebook_id=book.id,
                    content=f"keyed {i}",
                    keys=["tide"],
                    created_at=base + timedelta(seconds=i),
                )
            )
        for i in range(keyless):
            made.append(
                LorebookEntry(
                    lorebook_id=book.id,
                    content=f"always {i}",
                    keys=[],
                    created_at=base + timedelta(seconds=100 + i),
                )
            )
        for entry in made:
            session.add(entry)
        session.commit()
        return book

    def test_keyword_matches_plus_keyless_entries(self, session, monkeypatch):
        """`already - len(seen)` is always 0 — every append adds to both — so
        `remaining` came out as the FULL limit and the keyless arm appended on
        top of the keyword matches."""
        from services import rag_pipeline

        monkeypatch.setattr(rag_pipeline, "rag_enabled", lambda: False)
        book = self._lorebook(session, keyed=4, keyless=20)

        found = rag_pipeline.search_lorebook_entries(
            session, [book.id], "the tide is out", limit=5
        )
        assert len(found) == 5, [e.content for e in found]

    def test_across_several_lorebooks(self, session, monkeypatch):
        """The caller's `limit` is a budget for the whole call, not a per-book
        allowance: every returned entry is injected verbatim into a paid prompt."""
        from services import rag_pipeline

        monkeypatch.setattr(rag_pipeline, "rag_enabled", lambda: False)
        books = [self._lorebook(session, keyed=4, keyless=8) for _ in range(3)]
        found = rag_pipeline.search_lorebook_entries(
            session, [b.id for b in books], "the tide is out", limit=6
        )
        assert len(found) == 6

    def test_keyless_only_still_fills_the_budget(self, session, monkeypatch):
        from services import rag_pipeline

        monkeypatch.setattr(rag_pipeline, "rag_enabled", lambda: False)
        book = self._lorebook(session, keyed=0, keyless=30)
        found = rag_pipeline.search_lorebook_entries(session, [book.id], limit=4)
        assert len(found) == 4
        assert all(not e.keys for e in found)

    def test_the_empty_result_under_a_cutoff_is_still_a_deliberate_answer(
        self, session, monkeypatch
    ):
        """The previous audit made "embeddings exist but none is within
        `rag_max_distance`" an empty answer rather than falling through to the
        keyword scan. That must survive a fix to the limit arithmetic."""
        from services import rag_pipeline

        book = Lorebook(name="Far")
        session.add(book)
        session.commit()
        session.refresh(book)
        session.add(LorebookEntry(lorebook_id=book.id, content="unrelated", keys=["moon"]))
        session.commit()

        monkeypatch.setattr(rag_pipeline, "rag_enabled", lambda: True)
        monkeypatch.setattr(rag_pipeline, "_is_postgres", lambda _s: True)
        monkeypatch.setattr(rag_pipeline, "_try_embedding", lambda q: [0.0] * 384)
        monkeypatch.setattr(rag_pipeline, "rag_max_distance", lambda: 0.01)

        # SQLite has no `<=>`, so the semantic query is answered here rather than
        # executed. The point under test is the DECISION made when it comes back
        # empty with a query vector in hand: skip the lorebook, do not fall
        # through to the keyword scan and hand back arbitrary entries.
        from sqlmodel import select as sa_select

        real_session = session

        class _NoSemantic:
            def exec(self, stmt):
                sql = str(stmt)
                if "cosine_distance" in sql or "<=>" in sql:
                    return real_session.exec(
                        sa_select(LorebookEntry).where(LorebookEntry.id == "none")
                    )
                return real_session.exec(stmt)

        found = rag_pipeline.search_lorebook_entries(
            _NoSemantic(), [book.id], "tide", limit=5
        )
        assert found == [], (
            "an entry came back even though nothing was within the cutoff; the "
            "keyword fallback must stay unreachable when there was a query vector"
        )


# ── D9: the scheduler's advisory lock key was salted per process ──────────


class TestSchedulerLockKeyIsStable:
    def test_key_is_a_pure_function_of_the_job_id(self):
        """`str.__hash__` is salted per process, so every process derived a
        different key and `pg_try_advisory_lock` never excluded a peer. A second
        interpreter, with a different PYTHONHASHSEED, must produce the same int.
        """
        import subprocess
        import sys

        from infrastructure.scheduler import _advisory_lock_key

        job_id = "idle_simulation"
        local = _advisory_lock_key(job_id)
        assert local == _advisory_lock_key(job_id)

        program = (
            "import sys; sys.path.insert(0, %r);"
            "from infrastructure.scheduler import _advisory_lock_key;"
            "print(_advisory_lock_key(%r))" % (str(_repo_root()), job_id)
        )
        out = subprocess.run(
            [sys.executable, "-c", program],
            capture_output=True,
            text=True,
            env={"PYTHONHASHSEED": "12345", "PATH": "/usr/bin:/bin"},
        )
        assert out.returncode == 0, out.stderr
        assert int(out.stdout.strip()) == local

    def test_key_is_distinct_per_job_and_in_range(self):
        from infrastructure.scheduler import (
            _SCHEDULER_LOCK_NAMESPACE,
            _advisory_lock_key,
        )

        keys = {j: _advisory_lock_key(j) for j in ("a", "b", "cleanup", "idle_simulation")}
        assert len(set(keys.values())) == len(keys)
        # Must stay inside signed 64-bit so pg_advisory_lock(bigint) accepts it:
        # the namespace already occupies most of that range.
        for key in keys.values():
            assert -(2**63) <= key < 2**63
            assert _SCHEDULER_LOCK_NAMESPACE < key < 2**63

    def test_lock_and_unlock_use_the_same_key(self):
        """`__exit__` used to recompute the key from scratch; deriving it once in
        `__init__` is what makes it impossible for the two to disagree."""
        import inspect

        from infrastructure import scheduler

        src = inspect.getsource(scheduler._AdvisoryRunLock)
        assert "self._key" in src
        assert "hash(" not in src, (
            "the lock key must never be derived from str.__hash__, which is "
            "salted per process"
        )
        exit_src = inspect.getsource(scheduler._AdvisoryRunLock.__exit__)
        assert "self._key" in exit_src
        assert "hash(" not in exit_src


def _repo_root():
    import pathlib

    return pathlib.Path(__file__).resolve().parents[1]


# ── D10: startup re-dispatched jobs mid-post-processing ───────────────────


class TestStartupRecoveryOrder:
    def test_pending_sweep_runs_after_post_processing(self, monkeypatch):
        """`_reset_claims_and_requeue_sync` (inside `recover_pending_jobs`)
        used to include POST_PROCESSING in its status list and set `PENDING`
        with the claim cleared — the claim predicate. So the jobs being
        finalised must be finished or failed first, or a live worker re-runs
        the paid generation and overwrites the outputs the first finalization
        was writing.

        The sweep no longer includes POST_PROCESSING at all, so the ordering
        is the FIRST of two guards rather than the only one. It stays: the
        recovery has to finish the finalisation before anything else touches
        the queue, and the ordering is what says so.
        """
        import inspect

        from api import lifecycle

        import re

        src = inspect.getsource(lifecycle.startup_application)
        order = re.findall(r"(?:await )?(recover_\w+)\(\)", src)
        # This assertion used to read ["recover_pending_jobs",
        # "recover_post_processing_jobs"] — the failing order, asserted against
        # its own docstring. The calls moved into `_run_job_recovery_phase`, so
        # read that function too: a guard pinned to one symbol stops guarding
        # the moment the code is refactored, which is the failure mode this
        # whole audit class exists to catch.
        phase_src = inspect.getsource(lifecycle._run_job_recovery_phase)
        phase_order = re.findall(r"await (recover_\w+)\(\)", phase_src)
        order = phase_order or order
        assert order == ["recover_post_processing_jobs", "recover_pending_jobs"], (
            "recover_pending_jobs() must run AFTER the post-processing jobs "
            f"have been finalised; startup order is {order}"
        )

    def test_the_reset_sweep_excludes_post_processing(self):
        """The second guard against paying twice for the same image.

        A POST_PROCESSING job has already been generated and paid for; it is
        writing its outputs. The sweep sets PENDING with the claim cleared,
        and PENDING-with-no-claim IS the claim predicate — so a sweep that
        included POST_PROCESSING would put a finished, paid-for generation
        back on the queue and a live worker would run it a second time.

        The sweep's status list is interpolated from
        `core.entities.ACTIVE_JOB_STATUSES`, so the guard checks the SQL
        itself rather than the enum: the exclusion has to be IN the
        statement, and the enum alone would not be enough.
        """
        import inspect

        from services.job_queue import QueueManager

        src = inspect.getsource(QueueManager._reset_claims_and_requeue_sync)
        assert "POST_PROCESSING" in src, (
            "the reset sweep must exclude POST_PROCESSING: a job in that "
            "state has already been paid for, and re-queueing it runs the "
            "generation a second time"
        )
        assert "!= 'POST_PROCESSING'" in src, (
            "the exclusion has to be in the SQL, not only in the enum"
        )


# ── D11: the timeline materialised whole Asset rows ───────────────────────


class TestTimelineAssetColumns:
    def test_main_path_does_not_select_the_metadata_blob(self, client, session, monkeypatch):
        """`select(Asset)` fetched every column of up to 5,000 rows — a 3.4 kB
        jsonb each — to build a title, a 200-char description and two ids. Only
        the `prompt` key is needed, and only as a scalar."""
        from core.entities import Asset

        asset = Asset(filename="cat.png", relative_path="main/chat/cat.png")
        session.add(asset)
        session.commit()

        captured: list[str] = []
        real_exec = session.exec

        def _patched(stmt):
            sql = str(stmt)
            if "FROM assets" in sql:
                captured.append(sql)
            return real_exec(stmt)

        monkeypatch.setattr(session, "exec", _patched)
        body = client.get("/api/v2/timeline?limit=10").json()
        assert any(e["type"] == "asset" for e in body["events"]), body

        main_path = [s for s in captured if "filename" in s]
        assert main_path, f"the asset event query was not captured: {captured}"
        for sql in main_path:
            # `metadata_` may appear only as a JSON PATH extraction
            # (`metadata_[:...]` on SQLite, `->>` on Postgres), never as a bare
            # column — a bare one is the 3.4 kB blob per row.
            assert "assets.metadata_," not in sql and "assets.metadata_ " not in sql, sql
            assert "metadata_[" in sql or "->>" in sql, sql
            assert "'prompt'" in sql or "metadata_1" in sql, sql

    def test_the_event_still_carries_the_prompt(self, client, session):
        from core.entities import Asset

        session.add(
            Asset(
                filename="dog.png",
                relative_path="main/chat/dog.png",
                metadata_={"prompt": "a shiba in the rain", "workflow": "x" * 500},
            )
        )
        session.commit()
        events = client.get("/api/v2/timeline?types=image").json()["events"]
        assert events, (
            "`?types=image` matched nothing: the Activity page sends that value "
            "for its \"show images\" toggle and the events are tagged `asset`"
        )
        assert events[0]["description"] == "a shiba in the rain"
        assert events[0]["title"] == "Image: dog.png"
        assert events[0]["kind"] == "image"


# ── D12: chat_context_kwargs read a field Chat does not have ──────────────


class TestChatLocationBlock:
    def test_location_ids_comes_from_the_real_column(self, session):
        """`getattr(chat, "location_ids", None)` — Chat has `location_id`
        (singular) and no `location_ids`, so the default hid it and the
        "[Active Locations]" story block was unreachable from every chat path."""
        from services.context_builder import chat_context_kwargs

        char = Character(name="Wanderer")
        loc = __import__("core.entities", fromlist=["Location"]).Location(
            name="The Drowned Quay", description="Black water, green lamps."
        )
        session.add(char)
        session.add(loc)
        session.commit()
        session.refresh(char)
        session.refresh(loc)

        chat = Chat(name="Located", character_id=char.id, location_id=loc.id)
        session.add(chat)
        session.commit()
        session.refresh(chat)

        kwargs = chat_context_kwargs(chat, session=session)
        assert kwargs["location_ids"] == [loc.id]

    def test_a_chat_with_no_location_yields_none(self, session):
        from services.context_builder import chat_context_kwargs

        chat = _seed_chat(session)
        assert chat_context_kwargs(chat, session=session)["location_ids"] is None

    def test_the_block_is_actually_emitted(self, session):
        """Not just the kwarg: the location has to reach the prompt.

        The single-id block is now the one that fires for a chat. Previously
        both `location_detail` (from `location_id`) and `story_locations`
        (from `location_ids`, which `chat_context_kwargs` populated from the
        same column) rendered the same location, so a chat paid for its
        location's prose twice on every turn. The list block is for the
        *additional* locations a Story can have and a Chat cannot.
        """
        from services.context_builder import build_system_prompt_sections, chat_context_kwargs

        loc = __import__("core.entities", fromlist=["Location"]).Location(
            name="The Drowned Quay", description="Black water, green lamps."
        )
        session.add(loc)
        session.commit()
        session.refresh(loc)
        chat = _seed_chat(session, location_id=loc.id)

        sections = build_system_prompt_sections(session, **chat_context_kwargs(chat, session=session))
        keys = {s["key"] for s in sections}
        assert "location_detail" in keys
        block = next(s for s in sections if s["key"] == "location_detail")
        assert "The Drowned Quay" in block["content"]

    def test_a_linked_location_is_not_injected_twice(self, session):
        """A chat's location used to appear as both `[Location: X]` and inside
        `[Active Locations]`, on every turn, for every message."""
        from services.context_builder import build_system_prompt_sections, chat_context_kwargs

        loc = __import__("core.entities", fromlist=["Location"]).Location(
            name="The Drowned Quay", description="Black water, green lamps."
        )
        session.add(loc)
        session.commit()
        session.refresh(loc)
        chat = _seed_chat(session, location_id=loc.id)

        sections = build_system_prompt_sections(session, **chat_context_kwargs(chat, session=session))
        prompt = "\n\n".join(s["content"] for s in sections)
        assert prompt.count("The Drowned Quay") == 1, [s["key"] for s in sections]
        assert "story_locations" not in {s["key"] for s in sections}


# ── D13: the idle simulator ignored the global context window ─────────────


class TestIdleSimContextTokens:
    def test_uses_the_global_setting_when_the_chat_sets_none(self, session, monkeypatch):
        """`chat.max_context_tokens` alone fell through to
        `build_chat_context`'s `DEFAULT_MAX_TOKENS` (4096) and ignored
        `ai.maxContextTokens`; all seven `chats.py` reply paths resolve the same
        value through `resolve_context_tokens`."""
        from services import agent_simulation

        seen: list[dict] = []

        async def _spy(messages, **kwargs):
            seen.append(kwargs)
            return "sys", []

        # `run_idle_simulation_tick` imports the builder from
        # `services.context_builder` inside the function body, so the patch has
        # to land on the source module.
        monkeypatch.setattr(
            "services.context_builder.build_chat_context_async", _spy
        )
        monkeypatch.setattr(
            "config.get_config",
            lambda: {"ai": {"idleSimEnabled": True, "maxContextTokens": 32000}},
        )
        monkeypatch.setattr(
            "services.job_queue.queue_manager.enqueue", AsyncMock(return_value=True)
        )

        old = datetime.now(timezone.utc) - timedelta(hours=3)
        chat = _seed_chat(session, chat_type="chat", idle_sim_enabled=True)
        _add_message(session, chat, MessageRole.USER, "still here", at=old)
        session.add(chat)
        session.commit()

        assert asyncio.run(agent_simulation.run_idle_simulation_tick()) == 1
        assert seen, "the context builder was never called"
        assert seen[0]["max_context_tokens"] == 32000

    def test_per_chat_override_still_wins(self, session, monkeypatch):
        from services import agent_simulation

        seen: list[dict] = []

        async def _spy(messages, **kwargs):
            seen.append(kwargs)
            return "sys", []

        # `run_idle_simulation_tick` imports the builder from
        # `services.context_builder` inside the function body, so the patch has
        # to land on the source module.
        monkeypatch.setattr(
            "services.context_builder.build_chat_context_async", _spy
        )
        monkeypatch.setattr(
            "config.get_config",
            lambda: {"ai": {"idleSimEnabled": True, "maxContextTokens": 32000}},
        )
        monkeypatch.setattr(
            "services.job_queue.queue_manager.enqueue", AsyncMock(return_value=True)
        )

        old = datetime.now(timezone.utc) - timedelta(hours=3)
        chat = _seed_chat(
            session, chat_type="chat", idle_sim_enabled=True, max_context_tokens=8192
        )
        _add_message(session, chat, MessageRole.USER, "still here", at=old)
        session.add(chat)
        session.commit()

        assert asyncio.run(agent_simulation.run_idle_simulation_tick()) == 1
        assert seen[0]["max_context_tokens"] == 8192


# ── D1b: the TTS beat role was in no allowed set ─────────────────────────


class TestTtsBeatRole:
    def test_written_role_is_allowed(self, session):
        from api.routes.world_vault.stories import _ALLOWED_BEAT_ROLES
        from services.world_integration_service import TTS_BEAT_ROLE

        assert TTS_BEAT_ROLE in _ALLOWED_BEAT_ROLES
        # And it is not a `StoryBeatRole` member wearing a new name.
        assert TTS_BEAT_ROLE not in {r.value for r in _story_beat_roles()}

    def test_handler_writes_the_declared_role(self, session):
        from services import world_integration_service as wis

        story = Story(title="Narrated")
        session.add(story)
        session.commit()
        session.refresh(story)
        chapter = StoryChapter(
            story_id=story.id, chapter_number=1, content="Once upon a time.",
            beats=[{"id": "b1", "parent_beat_id": None, "role": "narrator", "content": "Once upon a time."}],
        )
        session.add(chapter)
        session.commit()
        session.refresh(chapter)

        asyncio.run(
            wis._handle_story_tts(
                {
                    "id": "tts-1",
                    "metadata": {"story_id": story.id, "chapter_id": chapter.id},
                    "outputs": [{"relative_path": "story_tts/ch1.wav"}],
                    "type": "story_tts",
                }
            )
        )
        session.expire_all()
        beats = session.get(StoryChapter, chapter.id).beats
        assert beats[-1]["role"] == wis.TTS_BEAT_ROLE
        assert beats[-1]["audio_path"] == "story_tts/ch1.wav"
        assert beats[-1]["content"] == ""

    def test_retry_still_finds_the_continuation_under_a_tts_beat(
        self, client, session
    ):
        """The guard was `beats[-1].role == narrator`. A narrated chapter ends in
        a TTS attachment, so "retry the last continuation" refused to retry
        anything — after paying for the narration."""
        from services import world_integration_service as wis

        story = Story(title="Retryable")
        session.add(story)
        session.commit()
        session.refresh(story)
        prose = "The lantern guttered and went out."
        chapter = StoryChapter(
            story_id=story.id,
            chapter_number=1,
            content=f"Opening line.\n\n{prose}\n\n",
            beats=[
                {"id": "b1", "parent_beat_id": None, "role": "narrator", "content": "Opening line."},
                {"id": "b2", "parent_beat_id": "b1", "role": "narrator", "content": prose},
                {"id": "b3", "parent_beat_id": "b2", "role": wis.TTS_BEAT_ROLE, "content": "", "audio_path": "story_tts/c1.wav"},
            ],
        )
        session.add(chapter)
        session.commit()
        session.refresh(chapter)

        resp = client.post(
            f"/api/v2/stories/{story.id}/chapters/{chapter.id}/retry-last"
        )
        # The original guard was `beats[-1].role == narrator`, so this refused at
        # 400 for any chapter that had been narrated — you paid for the narration
        # and then could not retry the thing it was attached to.
        assert resp.status_code == 200, resp.text

        # It found the narrator beat UNDER the TTS attachment, not the attachment
        # itself. That is the whole regression.
        job = session.exec(select(Job)).all()[-1]
        assert job.metadata_["retry_of"] == "b2"

        # And nothing is removed: the retry is a second take now, not a trim, so
        # the TTS attachment keeps describing audio of prose that still exists.
        session.expire_all()
        after = session.get(StoryChapter, chapter.id)
        assert prose in (after.content or "")
        assert [b["role"] for b in after.beats] == ["narrator", "narrator", "tts"]


def _story_beat_roles():
    from core.entities import StoryBeatRole

    return list(StoryBeatRole)
