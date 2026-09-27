

class TestParseCivitaiDatetime:
    """`civitai_published_at` / `civitai_created_at` are `UTCDateTime` columns,
    and SQLModel's bind processor REJECTS a naive value. Returning a naive
    datetime therefore made "Add model" on the Discover page a 500 for every
    model whose version carried a timestamp — the reported symptom was a button
    that did nothing plus a wall of traceback."""

    def test_never_returns_a_naive_datetime(self):
        from datetime import timezone
        from infrastructure.repositories.model_repo_v2 import parse_civitai_datetime

        samples = [
            "2026-04-10T07:59:57.750000",   # real value from the failing log: no offset at all
            "2024-01-15T12:00:00.000Z",
            "2024-01-15T12:00:00Z",
            "2024-01-15T12:00:00",
            "2024-01-15T12:00:00+02:00",
            "2024-01-15T12:00:00.1234567+02:00",
            "2024-01-15 12:00:00",
            "2024-01-15",
        ]
        for value in samples:
            parsed = parse_civitai_datetime(value)
            assert parsed is not None, value
            assert parsed.tzinfo is not None, f"{value} produced a naive datetime"
            assert parsed.utcoffset() == timezone.utc.utcoffset(None), value

    def test_accepts_datetime_objects_and_normalises_them(self):
        from datetime import datetime, timezone
        from infrastructure.repositories.model_repo_v2 import parse_civitai_datetime

        naive = datetime(2024, 1, 15, 12, 0, 0)
        assert parse_civitai_datetime(naive).tzinfo is not None
        aware = datetime(2024, 1, 15, 12, 0, 0, tzinfo=timezone.utc)
        assert parse_civitai_datetime(aware) == aware

    def test_offsets_are_converted_to_utc(self):
        from infrastructure.repositories.model_repo_v2 import parse_civitai_datetime

        assert parse_civitai_datetime("2024-01-15T12:00:00+02:00").hour == 10

    def test_unparseable_values_return_none_rather_than_raising(self):
        from infrastructure.repositories.model_repo_v2 import parse_civitai_datetime

        for value in (None, "", "   ", "not a date", 12345, [], {}):
            assert parse_civitai_datetime(value) is None

    def test_the_value_from_the_reported_failure_parses(self):
        from infrastructure.repositories.model_repo_v2 import parse_civitai_datetime

        parsed = parse_civitai_datetime("2026-04-10T07:59:57.750000")
        assert (parsed.year, parsed.month, parsed.day) == (2026, 4, 10)
        assert parsed.microsecond == 750000
