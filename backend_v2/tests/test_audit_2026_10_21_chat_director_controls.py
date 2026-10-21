"""Regression tests for audit-2026-10-21 finding 1: the Director Autonomy
control was silently dropped.

`Chat.director_autonomy_level` and `Chat.max_autonomous_turns` are real
columns, the pipeline reads them (`services/pipeline_stages.py`) and the chat
context panel PATCHed them (`ChatContextPanel.jsx` -> `useChats.js` ->
`PATCH /api/v2/chats/{id}`). But neither `UpdateChatRequest` nor
`CreateChatRequest` DECLARED them, and pydantic v2's default
`extra='ignore'` drops an undeclared field at the edge of the request. The
route therefore answered 200 and changed nothing.

So the Strict/Balanced/Cinematic selector was unreachable, and the
"up to 4 autonomous turns" budget could not be configured at all.
"""

import pytest
from sqlmodel import select

from core.entities import Chat


def _new_chat(client) -> str:
    response = client.post("/api/v2/chats", json={"name": "C"})
    assert response.status_code == 200, response.text
    return response.json()["id"]


class TestTheRequestModelsDeclareTheControls:
    def test_the_update_schema_declares_both_controls(self):
        from api.routes.world_vault.chats import UpdateChatRequest

        fields = UpdateChatRequest.model_fields
        assert "director_autonomy_level" in fields
        assert "max_autonomous_turns" in fields

    def test_the_create_schema_declares_both_controls(self):
        """A chat that never set an autonomy could not be given one later."""
        from api.routes.world_vault.chats import CreateChatRequest

        fields = CreateChatRequest.model_fields
        assert "director_autonomy_level" in fields
        assert "max_autonomous_turns" in fields


class TestTheControlsAreApplied:
    def test_patch_persists_the_autonomy_level(self, client, session):
        chat_id = _new_chat(client)

        response = client.patch(
            f"/api/v2/chats/{chat_id}", json={"director_autonomy_level": "cinematic"}
        )
        assert response.status_code == 200, response.text

        session.expire_all()
        assert session.get(Chat, chat_id).director_autonomy_level == "cinematic"

    def test_patch_persists_the_turn_budget(self, client, session):
        chat_id = _new_chat(client)

        response = client.patch(
            f"/api/v2/chats/{chat_id}", json={"max_autonomous_turns": 2}
        )
        assert response.status_code == 200, response.text

        session.expire_all()
        assert session.get(Chat, chat_id).max_autonomous_turns == 2

    def test_a_refetch_reports_the_controls_it_stored(self, client):
        """The round trip the optimistic UI update was hiding."""
        chat_id = _new_chat(client)
        client.patch(f"/api/v2/chats/{chat_id}", json={"director_autonomy_level": "strict"})

        body = client.get(f"/api/v2/chats/{chat_id}").json()
        assert body["director_autonomy_level"] == "strict"

    def test_create_accepts_the_controls(self, client, session):
        response = client.post(
            "/api/v2/chats",
            json={
                "name": "C",
                "director_autonomy_level": "strict",
                "max_autonomous_turns": 3,
            },
        )
        assert response.status_code == 200, response.text

        session.expire_all()
        chat = session.get(Chat, response.json()["id"])
        assert chat.director_autonomy_level == "strict"
        assert chat.max_autonomous_turns == 3

    @pytest.mark.parametrize("level", ["strict", "balanced", "cinematic"])
    def test_every_level_the_pipeline_knows_is_accepted(self, client, session, level):
        """The vocabulary is the pipeline's own, not a copy of it."""
        from core.pipeline_limits import AUTONOMY_CHAIN_THRESHOLDS

        assert level in AUTONOMY_CHAIN_THRESHOLDS
        chat_id = _new_chat(client)

        response = client.patch(
            f"/api/v2/chats/{chat_id}", json={"director_autonomy_level": level}
        )
        assert response.status_code == 200, response.text

        session.expire_all()
        assert session.get(Chat, chat_id).director_autonomy_level == level


class TestTheControlsAreValidated:
    def test_an_unknown_autonomy_level_is_a_422(self, client, session):
        """A typo must not be a silent 200."""
        chat_id = _new_chat(client)

        response = client.patch(
            f"/api/v2/chats/{chat_id}", json={"director_autonomy_level": "wild"}
        )
        assert response.status_code == 422, response.text

        session.expire_all()
        assert session.get(Chat, chat_id).director_autonomy_level == "balanced"

    def test_a_turn_budget_above_the_pipeline_limit_is_a_422(self, client):
        from core.pipeline_limits import MAX_AUTONOMOUS_TURNS

        chat_id = _new_chat(client)
        response = client.patch(
            f"/api/v2/chats/{chat_id}", json={"max_autonomous_turns": MAX_AUTONOMOUS_TURNS + 1}
        )
        assert response.status_code == 422, response.text

    def test_a_turn_budget_below_one_is_a_422(self, client):
        """Zero turns is not a budget; the chain would never run."""
        chat_id = _new_chat(client)
        response = client.patch(
            f"/api/v2/chats/{chat_id}", json={"max_autonomous_turns": 0}
        )
        assert response.status_code == 422, response.text

    def test_the_limit_is_the_manifests_own(self):
        """The bound comes from the pipeline, not from a number typed here."""
        from core.pipeline_limits import MAX_AUTONOMOUS_TURNS

        from api.routes.world_vault.chats import UpdateChatRequest

        field = UpdateChatRequest.model_fields["max_autonomous_turns"]
        assert field.metadata[-1].le == MAX_AUTONOMOUS_TURNS

    def test_an_explicit_null_leaves_the_columns_alone(self, client, session):
        """Both columns are NOT NULL; a null must not poison the session."""
        chat_id = _new_chat(client)

        response = client.patch(
            f"/api/v2/chats/{chat_id}",
            json={"director_autonomy_level": None, "max_autonomous_turns": None},
        )
        assert response.status_code == 200, response.text

        session.expire_all()
        chat = session.get(Chat, chat_id)
        assert chat.director_autonomy_level == "balanced"
        assert chat.max_autonomous_turns == 4

    def test_the_chat_still_works_after_the_patch(self, client, session):
        """The control is on a live chat, not a detached row."""
        chat_id = _new_chat(client)
        client.patch(f"/api/v2/chats/{chat_id}", json={"director_autonomy_level": "cinematic"})

        rows = session.exec(select(Chat).where(Chat.id == chat_id)).all()
        assert len(rows) == 1
        assert rows[0].director_autonomy_level == "cinematic"
