"""A non-numeric CivitAI model id reached an integer column comparison.

From the 2026-10-01 audit. The suite runs on SQLite, which returns no rows
where Postgres raises InvalidTextRepresentation, so a loose "not 500"
assertion passes against the broken code and only fails in production."""



class TestCheckInstalledRejectsNonNumericIds:
    """`civitai_model_id` was declared `str` and compared against an integer column.

    A bare non-numeric path segment reached
    `ModelV2.civitai_model_id == '<str>'`, which Postgres answers with
    `InvalidTextRepresentation`, i.e. an unmapped 500.

    Reproduced live before the fix:
        GET /api/v2/models/check-installed/abc-not-a-number -> 500
    """

    def test_non_numeric_id_is_rejected_not_crashed(self, client):
        """Asserted as 422 specifically, not as "not 500".

        The suite runs on SQLite, and SQLite returns no rows for
        `integer_col == 'not-a-number'` instead of raising the
        `InvalidTextRepresentation` Postgres raises. So a loose "not 500"
        assertion passes against the broken `str` signature on SQLite and only
        fails in production — which is the whole failure mode this repo's own
        STATUS.md warns about. With the param declared `int`, pydantic rejects
        the segment with a 422 on both engines, so that is what is asserted.
        """
        response = client.get("/api/v2/models/check-installed/not-a-number")
        assert response.status_code == 422, (
            "a non-numeric civitai id must be rejected at the boundary; a 200 "
            "means the string reached the integer comparison, and a 500 means "
            "it reached Postgres"
        )

    def test_numeric_id_still_answers(self, client):
        """The declared type changed; the working case must keep working."""
        response = client.get("/api/v2/models/check-installed/99999")
        assert response.status_code == 200
        assert response.json().get("model_installed") is False


