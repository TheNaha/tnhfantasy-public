"""Chat and lorebook round-trips lost data, and an edit desynchronised the swipes.

Three related defects in `chats.py` / `lorebooks.py`, all in the same family:
state that exists on one side of a round trip and is dropped on the other.

1. The SillyTavern exporter wrote `swipes` and `swipe_id`; the importer read only
   `mes`. So exporting a chat from this app and re-importing it dropped every
   alternate. The JSON exporter wrote `pinned` and `message_metadata` and the
   JSON importer read neither, so that round trip dropped the pin state and every
   swipe too.

2. The ST exporter built its `swipes` array as
   `[msg.content] + [a for a in alternates if a != msg.content]` while leaving
   `swipe_id` at the app's `active_index`. `alternates` already contains the
   active text at `active_index`, so the exported list was in a different order
   from the one the index addressed — ST showed a different reply than the user
   was looking at.

3. `edit_message` assigned `content` and left `message_metadata` alone. After an
   edit the displayed text appeared nowhere in `alternates` while `active_index`
   still pointed at the old entry, and the next `swipe_message` did
   `if content not in alternates: alternates.insert(0, content)` — shifting every
   stored index by one, so "swipe right" landed on the wrong reply.
"""

import json

import pytest

from core.entities import Chat, Character, Message, MessageKind, MessageRole


@pytest.fixture
def character(session):
    c = Character(name="Aria")
    session.add(c)
    session.commit()
    session.refresh(c)
    return c


@pytest.fixture
def chat(session, character):
    ch = Chat(title="round trip", character_id=character.id)
    session.add(ch)
    session.commit()
    session.refresh(ch)
    return ch


def _add(session, chat, content, *, alternates=None, active_index=0, pinned=False, role=MessageRole.CHAR):
    meta = None
    if alternates is not None:
        meta = {"alternates": list(alternates), "active_index": active_index}
    m = Message(
        chat_id=chat.id, role=role, kind=MessageKind.CHAR, content=content,
        message_metadata=meta, pinned=pinned,
    )
    session.add(m)
    session.commit()
    session.refresh(m)
    return m


class TestSwipeRoundTrip:
    def test_the_exporter_addresses_the_list_it_emits(self, session, chat):
        """The defect: `swipes` was rebuilt in a different order from the one
        `swipe_id` indexed into, so the exported id named a different reply."""
        _add(session, chat, "second", alternates=["first", "second", "third"], active_index=1)
        lines = _st_jsonl(session, chat).splitlines()
        entry = json.loads(lines[1])

        assert entry["swipe_id"] == 1
        # The invariant: whatever `swipe_id` names IS the text in `mes`.
        assert entry["mes"] == entry["swipes"][entry["swipe_id"]]
        assert entry["mes"] == "second", "the active text was not the one the index named"

    def test_an_out_of_range_active_index_is_clamped(self, session, chat):
        """Metadata can arrive stale from an older schema. Without a clamp the
        export emits `swipe_id: 7` against a 3-element list and ST indexes
        undefined."""
        _add(session, chat, "a", alternates=["a"], active_index=7)
        entry = json.loads(_st_jsonl(session, chat).splitlines()[1])
        assert 0 <= entry["swipe_id"] < len(entry["swipes"])
        assert entry["mes"] == entry["swipes"][entry["swipe_id"]]

    def test_pinned_survives_the_export(self, session, chat):
        _add(session, chat, "kept", pinned=True)
        entry = json.loads(_st_jsonl(session, chat).splitlines()[1])
        assert entry["pinned"] is True

    def test_swipes_and_pinned_survive_the_st_import(self, session, character, chat):
        """The headline: the exporter wrote `swipes`, `swipe_id` and `mes`, and
        the importer read only `mes` — so a chat exported from this app came back
        with every alternate gone."""
        from api.routes.world_vault.chats import _import_chat_sync

        _add(session, chat, "second", alternates=["first", "second", "third"], active_index=2, pinned=True)
        payload = _st_jsonl(session, chat)

        imported = _import_chat_sync(
            session,
            _CharRepo(character),
            name="imported",
            character_id=character.id,
            st_format=True,
            persona_name=None,
            source_chat={},
            raw_messages=[json.loads(line) for line in payload.splitlines()],
        )
        msgs = session.exec(
            select_messages(imported.id)
        ).all()
        assert len(msgs) == 1
        m = msgs[0]
        assert m.content == "third", "content did not follow swipe_id"
        assert (m.message_metadata or {}).get("alternates") == ["first", "second", "third"]
        assert (m.message_metadata or {}).get("active_index") == 2
        assert m.pinned is True

    def test_the_json_round_trip_keeps_pinned_and_metadata(self, session, character, chat):
        """The JSON exporter wrote `pinned` and `message_metadata`; the importer
        read neither."""
        from api.routes.world_vault.chats import _import_chat_sync

        _add(session, chat, "edited", alternates=["a", "edited"], active_index=1, pinned=True)
        exported = {
            "content": "edited",
            "role": "char",
            "kind": "char",
            "character_id": character.id,
            "created_at": "2026-01-01T00:00:00",
            "pinned": True,
            "message_metadata": {"alternates": ["a", "edited"], "active_index": 1},
        }
        imported = _import_chat_sync(
            session, _CharRepo(character), name="i", character_id=character.id,
            st_format=False, persona_name=None, source_chat={}, raw_messages=[exported],
        )
        m = session.exec(select_messages(imported.id)).all()[0]
        assert m.pinned is True
        assert m.message_metadata["alternates"] == ["a", "edited"]
        assert m.message_metadata["active_index"] == 1

    def test_st_extra_metadata_is_preserved(self, session, character):
        """`extra` is ST's own bag. A chat authored in ST keeps what it carried."""
        from api.routes.world_vault.chats import _import_chat_sync

        obj = {
            "mes": "hello", "is_user": False, "name": "Aria",
            "send_date": "2026-01-01T00:00:00",
            "extra": {"some_st_field": {"x": 1}},
        }
        imported = _import_chat_sync(
            session, _CharRepo(character), name="i", character_id=character.id,
            st_format=True, persona_name=None, source_chat={}, raw_messages=[obj],
        )
        m = session.exec(select_messages(imported.id)).all()[0]
        assert m.message_metadata["some_st_field"] == {"x": 1}


class TestEditKeepsSwipesInStep:
    def test_editing_rewrites_the_active_slot_in_place(self, session, chat):
        from api.routes.world_vault.chats import edit_message

        m = _add(session, chat, "second", alternates=["first", "second", "third"], active_index=1)
        out = edit_message(chat.id, m.id, _Edit("EDITED"), session=session, chat_repo=_Repo())
        assert out.content == "EDITED"
        assert out.message_metadata["active_index"] == 1
        assert out.message_metadata["alternates"] == ["first", "EDITED", "third"]

    def test_the_other_alternates_survive(self, session, chat):
        """Replacing the list with just the new text would throw away swipes the
        user generated and paid for."""
        from api.routes.world_vault.chats import edit_message

        m = _add(session, chat, "b", alternates=["a", "b", "c"], active_index=1)
        out = edit_message(chat.id, m.id, _Edit("EDITED"), session=session, chat_repo=_Repo())
        assert set(out.message_metadata["alternates"]) == {"a", "EDITED", "c"}

    def test_an_unswiped_message_gets_no_metadata(self, session, chat):
        from api.routes.world_vault.chats import edit_message

        m = _add(session, chat, "plain")
        out = edit_message(chat.id, m.id, _Edit("EDITED"), session=session, chat_repo=_Repo())
        assert out.content == "EDITED"
        assert not out.message_metadata

    def test_a_stale_index_is_corrected_rather_than_crashing(self, session, chat):
        from api.routes.world_vault.chats import edit_message

        m = _add(session, chat, "x", alternates=["a", "b"], active_index=9)
        out = edit_message(chat.id, m.id, _Edit("EDITED"), session=session, chat_repo=_Repo())
        assert out.message_metadata["active_index"] == 0

    def test_the_next_swipe_lands_where_the_user_expects(self, session, chat):
        """The consequence that motivated all of it: after an edit, the next swipe
        used to land one slot off, because the edited text was pushed to the front
        of `alternates` and shifted every index."""
        from api.routes.world_vault.chats import edit_message, swipe_message

        m = _add(session, chat, "b", alternates=["a", "b", "c"], active_index=1)
        edit_message(chat.id, m.id, _Edit("EDITED"), session=session, chat_repo=_Repo())

        session.refresh(m)
        out = swipe_message(chat.id, m.id, _Swipe("right"), session=session, chat_repo=_Repo())
        # "right" from index 1 in ["a", "EDITED", "c"] is index 2 -> "c".
        assert out.content == "c"
        assert out.message_metadata["active_index"] == 2


class TestLorebookExport:
    def test_depth_and_probability_use_the_real_columns(self, session):
        """Both columns exist on `LorebookEntry` and both were hardcoded, so a
        depth or probability the user had set was discarded on export."""
        from core.entities import Lorebook, LorebookEntry

        lb = Lorebook(name="wb")
        session.add(lb)
        session.commit()
        session.refresh(lb)
        session.add(LorebookEntry(lorebook_id=lb.id, idx=0, keys=["k"], content="c", depth=9, probability=42))
        session.commit()

        entry = _exported_lorebook(lb, session)["entries"]["0"]
        assert entry["depth"] == 9
        assert entry["probability"] == 42

    def test_a_keyless_entry_exports_as_constant(self, session):
        """`rag_pipeline` treats a keyless entry as always-on, so exporting it as
        `constant: false` made it stop firing the moment it left this app."""
        from core.entities import Lorebook, LorebookEntry

        lb = Lorebook(name="wb")
        session.add(lb)
        session.commit()
        session.refresh(lb)
        session.add(LorebookEntry(lorebook_id=lb.id, idx=0, keys=[], content="always on"))
        session.commit()

        assert _exported_lorebook(lb, session)["entries"]["0"]["constant"] is True

    def test_a_keyed_entry_exports_as_not_constant(self, session):
        from core.entities import Lorebook, LorebookEntry

        lb = Lorebook(name="wb")
        session.add(lb)
        session.commit()
        session.refresh(lb)
        session.add(LorebookEntry(lorebook_id=lb.id, idx=0, keys=["flood"], content="keyed"))
        session.commit()

        assert _exported_lorebook(lb, session)["entries"]["0"]["constant"] is False


class TestIllustratePromptIsBounded:
    def test_rag_off_does_not_load_every_entry(self, session, monkeypatch):
        """The RAG-off branch had no LIMIT and concatenated every entry of every
        lorebook into a paid LLM system prompt. The setting the UI offers as a
        memory saver made THIS prompt larger."""
        from api.routes.world_vault.stories import _illustrate_system_prompt_sync
        from core.entities import Lorebook, LorebookEntry, Story, StoryChapter

        lb = Lorebook(name="big")
        session.add(lb)
        session.commit()
        session.refresh(lb)
        session.add_all([
            LorebookEntry(lorebook_id=lb.id, idx=i, keys=[f"k{i}"],
                          content=f"entry {i} " + "x" * 2000)
            for i in range(300)
        ])
        session.commit()

        story = Story(title="s", lorebook_ids=[lb.id])
        session.add(story)
        session.commit()
        session.refresh(story)
        chapter = StoryChapter(story_id=story.id, title="c", content="a scene in the drowned city")
        session.add(chapter)
        session.commit()
        session.refresh(chapter)

        import config

        # The flag is read inside `rag_pipeline.rag_enabled()`, not in stories, so
        # it is patched at the config the retrieval reads.
        for enabled in (True, False):
            with monkeypatch.context() as m:
                m.setattr(config, "get_config", lambda: {"ai": {"ragEnabled": enabled}})
                from api.routes.world_vault.stories import _illustrate_system_prompt_sync

                prompt = _illustrate_system_prompt_sync(session, story, chapter)
            assert prompt.count("- [") <= 8 * len(story.lorebook_ids), (
                f"RAG enabled={enabled} injected {prompt.count('- [')} entries"
            )
            assert len(prompt) < 50_000, f"RAG enabled={enabled} produced a {len(prompt)}-char prompt"


# --- helpers ---------------------------------------------------------------


def select_messages(chat_id):
    from sqlmodel import select

    from core.entities import Message as M

    return select(M).where(M.chat_id == chat_id).order_by(M.created_at)


class _CharRepo:
    def __init__(self, character):
        self._c = character

    def get(self, _id):
        return self._c


class _Edit:
    def __init__(self, content):
        self.content = content


class _Repo:
    def get(self, _id):
        return None


class _Swipe:
    def __init__(self, direction, index=None):
        self.direction = direction
        self.index = index


def _st_jsonl(session, chat) -> str:
    """Run the real ST exporter over a chat's messages."""
    from sqlmodel import select

    from api.routes.world_vault.chats import _chat_to_sillytavern_jsonl
    from core.entities import Message as M

    msgs = list(session.exec(
        select(M).where(M.chat_id == chat.id).order_by(M.created_at)
    ).all())
    return _chat_to_sillytavern_jsonl(chat, msgs, None, [])


def _exported_lorebook(lorebook, session) -> dict:
    """Call the real exporter and read back the download body."""
    from api.routes.world_vault.lorebooks import export_lorebook_sillytavern

    resp = export_lorebook_sillytavern(
        lorebook.id, session=session,
        lorebook_repo=_LbRepo(lorebook), lorebook_entry_repo=_EntryRepo(session),
    )
    return json.loads(resp.body)


class _LbRepo:
    def __init__(self, lorebook):
        self._lb = lorebook

    def get(self, _id):
        return self._lb


class _EntryRepo:
    def __init__(self, session):
        self._s = session

    def list_by_lorebook(self, lorebook_id, **_kw):  # noqa: D401
        from sqlmodel import select

        from core.entities import LorebookEntry

        return self._s.exec(
            select(LorebookEntry).where(LorebookEntry.lorebook_id == lorebook_id)
        ).all()
