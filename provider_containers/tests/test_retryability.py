"""Every LLM engine used to mark every failure `retryable=True`.

The backend's reducer (`backend_v2/services/provider_client.py`) turns a
`retryable` task event into `ProviderCallError(is_retryable=True)`, and the
dispatcher then re-runs the request against every other provider. A malformed
`messages` array or a 400 from the upstream cannot succeed on a second attempt,
so the blanket flag turned a guaranteed failure into a guaranteed spend across
every provider in the pool.

The ComfyUI image path already got this right by accident: `_queue_prompt`
errors carry no `retryable` key, so `comfy_status_to_task_event` leaves it
`None` and the backend treats it as `False`. The LLM side had no such accident.

These pin the classifier that all four LLM engines now share, rather than the
per-engine call site — the engines each had their own copy of the same wrong
rule, which is why a fix in one would not have held.
"""

from __future__ import annotations

import pytest

from provider_core.responses import retryable_for_exception, retryable_for_status


class _Resp:
    def __init__(self, status_code):
        self.status_code = status_code


class _StatusError(Exception):
    """Shaped like `httpx.HTTPStatusError`, which attaches the response."""

    def __init__(self, status_code, message=""):
        super().__init__(message or f"HTTP {status_code}")
        self.response = _Resp(status_code)


class _Timeout(Exception):
    pass


class _Connect(Exception):
    pass


class TestPermanentFailures:
    @pytest.mark.parametrize("status", [400, 401, 403, 404, 409, 413, 422])
    def test_4xx_is_never_retryable(self, status):
        """4xx is the client's fault. Re-dispatching reproduces it exactly."""
        assert retryable_for_exception(_StatusError(status)) is False

    def test_a_bare_exception_is_permanent(self):
        """A parse bug, a TypeError, a programming error.

        Retrying a bug spends the same money for the same failure, on every
        provider in the pool, and reports the same error again.
        """
        assert retryable_for_exception(ValueError("unpack error")) is False

    def test_an_explicit_marker_wins(self):
        """A raiser that knows better says so."""

        class _Permanent(Exception):
            retryable = False

        class _Transient(Exception):
            retryable = True

        assert retryable_for_exception(_Permanent()) is False
        assert retryable_for_exception(_Transient()) is True


class TestTransientFailures:
    @pytest.mark.parametrize("status", [500, 502, 503, 504])
    def test_5xx_is_retryable(self, status):
        assert retryable_for_exception(_StatusError(status)) is True

    @pytest.mark.parametrize("status", [408, 429])
    def test_429_and_408_are_the_transient_4xx(self, status):
        """The server is asking for a retry, not reporting a mistake.

        429 is a rate limit and 408 is a request timeout. Failing the job over
        either discards work the provider explicitly invited us to repeat, and
        the blanket "4xx is never retryable" rule that predated this classifier
        did exactly that.
        """
        assert retryable_for_exception(_StatusError(status)) is True

    def test_a_status_raised_directly_on_the_exception(self):
        """Some raisers attach `status_code` without an httpx response."""

        class _Direct(Exception):
            status_code = 503

        assert retryable_for_exception(_Direct()) is True


class TestTheStatusHelperItself:
    """`retryable_for_status` predates this and is used by the HTTP router.

    It has a 503-specific history: a provider with no `PROVIDER_WORKER_TOKEN`
    answers 503 on every protected route, and a blanket `>= 500` made the
    dispatcher read that as "try this elsewhere".
    """

    def test_an_explicit_dict_marker_overrides(self):
        assert retryable_for_status(503, {"retryable": False}) is False
        assert retryable_for_status(400, {"retryable": True}) is True

    def test_the_default_split(self):
        assert retryable_for_status(500) is True
        assert retryable_for_status(400) is False
        assert retryable_for_status(403) is False
        assert retryable_for_status(429) is True
        assert retryable_for_status(408) is True

    def test_a_403_from_an_auth_layer_is_permanent(self):
        """The Google case, verbatim: a rejected key never starts working."""
        assert retryable_for_status(403) is False
