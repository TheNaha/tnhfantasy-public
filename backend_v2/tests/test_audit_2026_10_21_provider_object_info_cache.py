"""A provider edit must drop the cached ComfyUI node graph.

`PUT /api/v2/providers/{id}` is supposed to clear every provider's cached
`object_info` graph, because a provider edit can change what its worker
exposes. It did not, ever: the handler imported `services.nodes`, which does
not exist (the real module is `api.routes.nodes`), and swallowed the
resulting `ModuleNotFoundError` in a bare `except Exception: pass`. The cache
kept serving the pre-edit graph for its whole TTL.

The import is correct now, and a broken import is logged instead of being
swallowed.
"""

import sys
from unittest.mock import MagicMock, call


def _provider_payload(provider_id="object-info-provider"):
    return {
        "id": provider_id,
        "type": "modal",
        "enabled": True,
        "priority": 1,
        "credentials": {"token_id": "tok_123", "token_secret": "secret_456"},
        "config": {},
    }


def test_updating_a_provider_invalidates_the_object_info_cache(client, monkeypatch):
    from api.routes import nodes as nodes_module

    created = client.post("/api/v2/providers", json=_provider_payload())
    assert created.status_code == 200

    invalidate = MagicMock()
    monkeypatch.setattr(nodes_module, "invalidate_object_info_cache", invalidate)

    response = client.put(
        "/api/v2/providers/object-info-provider",
        json={"priority": 3},
    )
    assert response.status_code == 200

    assert invalidate.called, "the cached object_info graph was not invalidated"
    # The route's own call clears EVERY provider's cached graph — that is what
    # the handler was written to do. `invalidate_engine` also clears the
    # edited provider's graph, with the provider id as the argument, so the
    # no-argument call is the one that proves this route's import works.
    assert call() in invalidate.call_args_list, (
        "the route did not clear every provider's cached object_info graph"
    )


def test_the_invalidation_imports_a_module_that_exists():
    """The bug was a module path that does not exist. Pin the path, so a
    rename cannot turn this back into a silent no-op."""
    from api.routes.nodes import invalidate_object_info_cache  # noqa: F401


def test_a_broken_import_is_logged_not_swallowed(client, monkeypatch):
    """The handler used to hide a `ModuleNotFoundError` behind
    `except Exception: pass`, which is how the typo survived. A broken import
    has to be visible, and it must not take the edit down with it."""
    import api.routes.providers.crud as crud_module

    created = client.post("/api/v2/providers", json=_provider_payload("object-info-provider-2"))
    assert created.status_code == 200

    logger = MagicMock()
    monkeypatch.setattr(crud_module, "logger", logger)
    # `None` in sys.modules makes `from api.routes.nodes import ...` raise
    # ImportError, which is exactly the failure the old bare `except` hid.
    monkeypatch.setitem(sys.modules, "api.routes.nodes", None)

    response = client.put("/api/v2/providers/object-info-provider-2", json={"priority": 3})

    assert response.status_code == 200
    logger.warning.assert_called_once()
    assert logger.warning.call_args.args[0] == "provider_object_info_cache_invalidation_unavailable"
    assert logger.warning.call_args.kwargs.get("error")
