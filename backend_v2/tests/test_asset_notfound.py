"""Asset 404s answered 500 instead of 404, because the raise site passed
the wrong number of arguments to a two-argument exception.

From the 2026-10-01 audit. Reproduced live before the fix: every
`/file`, `/thumb` and `/move` request for a missing asset returned 500
and logged a TypeError from the exception's own constructor."""

import pytest


class TestAssetNotFoundIsAFourHundredAndFour:
    """`NotFoundError(resource, identifier)` takes two required arguments.

    Six sites in `api/routes/files.py` raised it with one, so the constructor
    raised `TypeError` inside the handler and FastAPI had no mapping for it:
    every "asset not found" answer on `/file`, `/thumb` and `/move` was an
    unmapped 500 that also logged a stack trace and burned the generic
    exception handler's timing.

    Reproduced live before the fix:
        GET  /api/v2/assets/does-not-exist/file  -> 500
        GET  /api/v2/assets/does-not-exist/thumb -> 500
        POST /api/v2/assets/does-not-exist/move  -> 500
    """

    @pytest.mark.parametrize(
        "method,path",
        [
            ("get", "/api/v2/assets/does-not-exist/file"),
            ("get", "/api/v2/assets/does-not-exist/thumb"),
        ],
    )
    def test_missing_asset_serves_404_not_500(self, client, method, path):
        response = getattr(client, method)(path)
        assert response.status_code == 404, (
            "a missing asset must be a 404; a 500 means the raise site passed "
            "the wrong number of arguments to NotFoundError"
        )

    def test_move_missing_asset_serves_404_not_500(self, client):
        response = client.post(
            "/api/v2/assets/does-not-exist/move",
            json={"workspace": "main"},
        )
        assert response.status_code == 404

    def test_the_404_body_names_the_asset(self, client):
        """The mapped error body, not a stack trace."""
        response = client.get("/api/v2/assets/does-not-exist/file")
        assert response.status_code == 404
        assert "does-not-exist" in response.text


