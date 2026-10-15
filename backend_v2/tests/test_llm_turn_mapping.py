"""How a stored chat message becomes an LLM turn.

The mapping used to be four copies of the same if/elif — the context builder,
the suggest-reply assembly, the impersonate assembly, and the orchestrator's
follow-up rebuild — and they had already drifted. One mapped narrator turns to
`role: "system"`, one dropped them, one wrapped system text in brackets, and
NONE carried the speaker. So a group chat reached the model as a wall of
anonymous `assistant` turns, and `kind` was computed, used for pruning, and then
stripped before the payload went out.

`llm_turn_for` is the one implementation, and this file is why it exists: every
property those four copies were supposed to have, asserted once.
"""


from core.entities import Message, MessageKind, MessageRole
from services.context_builder import llm_turn_for, speaker_context


def _msg(role, content, **extra):
    return Message(chat_id="c", role=role, content=content, **extra)


# ── the speaker is named ─────────────────────────────────────────────────────


class TestSpeakerLabelling:
    def test_a_single_character_chat_is_not_labelled(self):
        """The name is already the whole subject of the system prompt."""
        turn = llm_turn_for(_msg(MessageRole.CHAR, "Hello."), participants=1)
        assert turn == {"role": "assistant", "content": "Hello."}

    def test_a_group_chat_labels_each_speaker(self):
        """The only thing telling two `assistant` turns apart."""
        names = {"char-1": "Aria", "char-2": "Bram"}
        turn = llm_turn_for(
            _msg(MessageRole.CHAR, "Hello.", character_id="char-2"),
            speaker_names=names,
            participants=2,
        )
        assert turn == {"role": "assistant", "content": "Bram: Hello."}

    def test_an_unknown_speaker_falls_back_to_the_bare_turn(self):
        """No name in the lookup is not a reason to drop the message."""
        turn = llm_turn_for(
            _msg(MessageRole.CHAR, "Hello.", character_id="missing"),
            speaker_names={"char-1": "Aria"},
            participants=2,
        )
        assert turn == {"role": "assistant", "content": "Hello."}

    def test_a_user_turn_is_never_labelled(self):
        """`user` is already unambiguous — there is only one of them."""
        turn = llm_turn_for(
            _msg(MessageRole.USER, "I wave."),
            speaker_names={"char-1": "Aria"},
            participants=3,
        )
        assert turn == {"role": "user", "content": "I wave."}

    def test_labelling_is_switchable_off(self):
        """A caller who has taught the model the convention sends it bare."""
        cfg = {"label_speakers": False, "narrator_prefix": "[Narration]", "image_prefix": "[Scene]"}
        turn = llm_turn_for(
            _msg(MessageRole.CHAR, "Hello.", character_id="char-2"),
            speaker_names={"char-2": "Bram"},
            participants=2,
            roleplay_config=cfg,
        )
        assert turn == {"role": "assistant", "content": "Hello."}

    def test_speaker_context_counts_from_the_messages(self, session):
        """The count is derived from the data, not passed by the caller.

        That is what makes it free at every call site: the four copies this
        replaces each had the messages in hand and none of them looked.
        """
        messages = [
            _msg(MessageRole.CHAR, "A", character_id="c1"),
            _msg(MessageRole.CHAR, "B", character_id="c2"),
            _msg(MessageRole.USER, "C"),
        ]
        names, total = speaker_context(messages, session)
        assert total == 2

    def test_a_single_speaker_needs_no_name_lookup(self, session):
        """One extra query is only paid when there is ambiguity to resolve."""
        messages = [_msg(MessageRole.CHAR, "A", character_id="c1")]
        names, total = speaker_context(messages, session)
        assert total == 1
        assert names == {}


# ── narrator and image are not `system` ──────────────────────────────────────


class TestNarratorAndImageAreDialogueTurns:
    def test_a_narrator_turn_is_an_assistant_turn_with_a_label(self):
        """The whole point.

        `role == "system"` is on the never-prune list, and on the Google
        provider every system message is concatenated into the system prompt and
        dropped from the conversation — so a narration sent as `system` is torn
        out of its place in the dialogue and appended to the end of the
        instructions, unmarked.
        """
        turn = llm_turn_for(
            _msg(MessageRole.SYSTEM, "The harbour goes quiet.", kind=MessageKind.NARRATOR)
        )
        assert turn["role"] == "assistant"
        assert turn["content"] == "[Narration] The harbour goes quiet."

    def test_an_image_turn_is_an_assistant_turn_with_a_label(self):
        """Same shape, so an illustration stays where it happened."""
        turn = llm_turn_for(
            _msg(MessageRole.SYSTEM, "[Scene illustration]", kind=MessageKind.IMAGE)
        )
        assert turn == {"role": "assistant", "content": "[Scene] [Scene illustration]"}

    def test_a_legacy_narrator_row_without_kind_is_treated_the_same(self):
        """`kind` was added later; an old transcript must not keep the bug.

        The narrator rows written before it existed are distinguished by
        `message_metadata.source`, not by `kind`, so they need the same mapping
        or the change only helps new chats.
        """
        msg = _msg(MessageRole.SYSTEM, "Rain.")
        msg.message_metadata = {"source": "narrator"}
        turn = llm_turn_for(msg)
        assert turn == {"role": "assistant", "content": "[Narration] Rain."}

    def test_an_ordinary_system_turn_stays_system(self):
        """An injected instruction really is one, and must stay on that channel."""
        msg = _msg(MessageRole.SYSTEM, "[Author's Note] keep it dark")
        turn = llm_turn_for(msg)
        assert turn == {"role": "system", "content": "[Author's Note] keep it dark"}

    def test_the_prefixes_are_configurable(self):
        cfg = {"label_speakers": True, "narrator_prefix": "*", "image_prefix": ""}
        assert llm_turn_for(
            _msg(MessageRole.SYSTEM, "Rain.", kind=MessageKind.NARRATOR), roleplay_config=cfg
        ) == {"role": "assistant", "content": "* Rain."}
        # An EMPTY prefix means "send it bare", not "prefix with nothing plus a
        # space" — which would put a stray space at the head of every turn.
        assert llm_turn_for(
            _msg(MessageRole.SYSTEM, "a picture", kind=MessageKind.IMAGE), roleplay_config=cfg
        ) == {"role": "assistant", "content": "a picture"}

    def test_dict_messages_are_supported(self):
        """The suggest and impersonate paths build from dicts, not rows."""
        turn = llm_turn_for(
            {"role": "system", "content": "Rain.", "kind": "narrator", "message_metadata": {}}
        )
        assert turn == {"role": "assistant", "content": "[Narration] Rain."}


# ── what gets dropped ────────────────────────────────────────────────────────


class TestSkippedTurns:
    def test_world_state_markers_are_dropped(self):
        """Derived state, rebuilt on every context build.

        Re-sending it makes the model treat its own summary as history, and it
        was the one case all four copies agreed on.
        """
        msg = _msg(MessageRole.SYSTEM, "The world darkens.", kind=MessageKind.SYSTEM)
        msg.message_metadata = {"source": "world_state"}
        assert llm_turn_for(msg) is None

    def test_empty_content_is_dropped(self):
        assert llm_turn_for(_msg(MessageRole.CHAR, "")) is None
        assert llm_turn_for(_msg(MessageRole.USER, "")) is None
        assert llm_turn_for(_msg(MessageRole.SYSTEM, "")) is None

    def test_an_unknown_role_is_dropped(self):
        """`MessageRole.STORY` has no LLM channel and must not become one."""
        assert llm_turn_for(_msg(MessageRole.STORY, "text")) is None


# ── the inverted perspective ─────────────────────────────────────────────────


class TestAsUserPerspective:
    def test_the_two_channels_swap(self):
        """Suggest-reply and impersonate write as the USER.

        From the model's seat a prior user message is `assistant` and a character
        message is the `user` it answers. This is the same rule with two labels
        swapped — a parameter here rather than a fifth copy of the if/elif.
        """
        assert llm_turn_for(_msg(MessageRole.USER, "I wave."), as_user=True) == {
            "role": "assistant", "content": "I wave."
        }
        assert llm_turn_for(_msg(MessageRole.CHAR, "Hello."), as_user=True) == {
            "role": "user", "content": "Hello."
        }

    def test_a_narration_stays_on_the_assistant_channel_either_way(self):
        """It is not the user's voice, whichever direction the roles run."""
        msg = _msg(MessageRole.SYSTEM, "Rain.", kind=MessageKind.NARRATOR)
        assert llm_turn_for(msg, as_user=True)["role"] == "assistant"

    def test_the_user_is_not_labelled_in_the_mirror(self):
        """Labelling describes the OTHER party when the model writes as the user."""
        turn = llm_turn_for(
            _msg(MessageRole.CHAR, "Hello.", character_id="c1"),
            speaker_names={"c1": "Aria"},
            participants=2,
            as_user=True,
        )
        assert turn == {"role": "user", "content": "Hello."}


# ── the four call sites use it ───────────────────────────────────────────────


class TestEveryCallSiteUsesIt:
    def test_the_context_builder_does_not_have_its_own_copy(self):
        import inspect

        from services import context_builder

        source = inspect.getsource(context_builder.build_chat_context_with_sections)
        assert "llm_turn_for(" in source, "the context builder has drifted back to inline mapping"
        assert "MessageRole.SYSTEM.value" not in source

    def test_chats_route_does_not_have_its_own_copy(self):
        import inspect

        from api.routes.world_vault import chats

        for fn in (chats.suggest_reply, chats.impersonate):
            source = inspect.getsource(fn)
            assert "llm_turn_for(" in source, f"{fn.__name__} has an inline copy of the mapping"
            assert "MessageRole.CHAR" not in source

    def test_the_orchestrator_does_not_have_its_own_copy(self):
        import inspect

        from services import orchestrator_service

        source = inspect.getsource(orchestrator_service._tool_narrate_scene)
        assert "llm_turn_for(" in source
        assert "MessageRole.USER else" not in source, "the blanket else-assign is back"
