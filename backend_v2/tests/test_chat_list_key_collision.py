"""A chat id of `list` must be impossible (audit-2026-10-30b, m5).

The frontend caches the chat list under `CHAT_LIST_KEY = ['world_vault',
'chats', 'list']` and a chat's detail under `CHAT_DETAIL_KEY(id) = ['world_vault',
'chats', id]` — so a chat whose id is literally `list` makes the two keys
byte-identical, and a detail write/invalidation lands on the cached list.

The invariant that keeps this unreachable:

1. `CreateChatRequest` whitelists its fields explicitly (backend convention)
   and has no `id`, so a client cannot name a chat over the create route —
   the server always generates uuid4.
2. The one producer that DOES take a client-chosen chat id — character-card
   import, where a bundle string becomes the primary key — rejects the
   reserved marker via `validate_imported_chat_id`.

If either half changes, this test fails before the cache collision can exist.
"""
from __future__ import annotations

import pytest

from api.routes.world_vault.characters import (
    RESERVED_CHAT_IDS,
    validate_imported_chat_id,
)
from api.routes.world_vault.chats import CreateChatRequest
from core.exceptions import ValidationError


class TestChatIdCannotBeList:
    def test_create_request_has_no_id_field(self):
        assert "id" not in CreateChatRequest.model_fields, (
            "CreateChatRequest grew an `id` field: a client can now choose the "
            "chat primary key, and `list` collides with the frontend's "
            "CHAT_LIST_KEY — guard it with validate_imported_chat_id or "
            "reject reserved ids at the route"
        )

    def test_import_rejects_the_reserved_marker(self):
        with pytest.raises(ValidationError):
            validate_imported_chat_id("list")
        # The check runs on the normalized value, whitespace included.
        with pytest.raises(ValidationError):
            validate_imported_chat_id("  list  ")

    def test_import_passes_normal_ids_through(self):
        assert validate_imported_chat_id("  3f2504e0-4f89-11d3-9a0c-0305e82c3301 ") == (
            "3f2504e0-4f89-11d3-9a0c-0305e82c3301"
        )
        assert validate_imported_chat_id(None) == ""
        assert validate_imported_chat_id("") == ""
        assert "list" in RESERVED_CHAT_IDS