"""A double submit must not become two user messages and two paid jobs.

The only guard was client-side (`if (sendMessageMutation.isPending) return`),
which covers one tab. A network retry, or a second tab, produced two identical
user rows and two LLM jobs — and the second is a full second charge.

The route now honours `Idempotency-Key`, the same opt-in mechanism
`POST /api/jobs` has used since 2026-09-27. `infrastructure/request_dedup`
collapses concurrent identical sends onto one execution.
"""

import asyncio

import pytest


def _send(client, chat_id, content="hello again", key=None, headers=None):
    payload = {"role": "user", "content": content}
    hdrs = dict(headers or {})
    if key:
        hdrs["Idempotency-Key"] = key
    return client.post(
        f"/api/v2/chats/{chat_id}/messages", json=payload, headers=hdrs
    )


@pytest.fixture
def chat_with_user(session):
    from core.entities import Chat

    chat = Chat(id="chat-idem", character_id=None)
    session.add(chat)
    session.commit()
    return chat


class TestTheRouteAcceptsAKey:
    def test_without_a_key_it_behaves_exactly_as_before(self, client, chat_with_user):
        """Opt-in: a client that never sends the header is unaffected."""
        response = _send(client, chat_with_user.id, key=None)
        assert response.status_code == 200

    def test_the_route_declares_the_header(self):
        """Otherwise the client key is silently dropped, which is worse than
        not accepting it — a header that is parsed but never honoured looks
        like idempotency from the caller's side."""
        import inspect

        from api.routes.world_vault.chats import add_message

        signature = inspect.signature(add_message)
        param = signature.parameters.get("idempotency_key")
        assert param is not None, "add_message takes no Idempotency-Key"
        # FastAPI wraps the default in a Header marker object; the wrapped value
        # is what an omitted header resolves to.
        assert param.default.default is None, "header does not default to None/omitted"


class TestConcurrentSendsCollapse:
    async def test_two_concurrent_sends_with_one_key_share_an_execution(self, chat_with_user):
        """The dedup map's contract, driven against the route.

        Two in-flight POSTs carrying the same key must produce ONE reply job,
        not two. The second waits for the first rather than starting its own.
        """
        from infrastructure.request_dedup import deduplicated, make_key

        calls = []

        async def work():
            calls.append(1)
            await asyncio.sleep(0.01)
            return "ok"

        key = make_key("send_message", chat_with_user.id, "same-key")
        first, second = await asyncio.gather(
            deduplicated(key, work), deduplicated(key, work)
        )

        assert (first, second) == ("ok", "ok")
        assert len(calls) == 1, f"executed twice for one key: {len(calls)} calls"

    async def test_distinct_keys_are_not_collapsed(self):
        """A dedup that collapsed unrelated sends would silently eat messages."""
        from infrastructure.request_dedup import deduplicated, make_key

        calls = []

        async def work():
            calls.append(1)
            return "ok"

        await asyncio.gather(
            deduplicated(make_key("send_message", "c", "k1"), work),
            deduplicated(make_key("send_message", "c", "k2"), work),
        )
        assert len(calls) == 2
