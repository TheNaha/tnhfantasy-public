"""All four LLM engines reported `healthy` without contacting anything.

The backend's `_check_provider_health` (`services/load_balancer.py`) requires
HTTP 200, so a hardcoded `{"status": "healthy"}` made a dead endpoint look like a
usable target: the balancer dispatched paid LLM jobs at it, every job failed, and
because the failure events were also all `retryable=True` it then re-dispatched
across the whole provider pool. One bad key could burn spend on every provider.

`direct_url` and `remote_comfy` were already fixed to do a real probe, with the
failure mode written down. The fix was never ported to the LLM side, and when it
was eventually applied to `openai_compat` alone it gave that engine a response
shape its three siblings did not share — so a reader had to work out why one
engine differed. That is the class of thing this file exists to prevent.

These assert the *invariant across engines*, not one engine's behaviour: no
engine may report healthy without either contacting something or validating a
configuration prerequisite, and all four must speak the same response shape.
"""

from __future__ import annotations

import ast
from pathlib import Path

import pytest

from provider_core.responses import llm_healthy, llm_unhealthy

ENGINES = ["openai_compat", "anthropic", "google", "modal"]
CLIENT_DIR = Path(__file__).resolve().parents[1] / "llm_worker" / "engines"


def _client_source(engine: str) -> str:
    return (CLIENT_DIR / engine / "client.py").read_text(encoding="utf-8")


def _get_health_body(source: str) -> str:
    """The code of `get_health`, with its docstring removed.

    The docstring matters for reading but must not be asserted against: each one
    quotes `{"status": "healthy"}` in prose while explaining that the engine used
    to return exactly that. Matching the raw segment would flag the explanation
    as if it were the bug.
    """
    tree = ast.parse(source)
    for node in ast.walk(tree):
        if isinstance(node, ast.AsyncFunctionDef) and node.name == "get_health":
            stripped = ast.parse(ast.unparse(node))
            fn = stripped.body[0]
            doc = ast.get_docstring(fn, clean=False)
            if doc is not None:
                fn.body = fn.body[1:]
            return ast.unparse(fn)
    raise AssertionError("no get_health found")


class TestTheSharedShape:
    def test_both_builders_agree_on_their_keys(self):
        healthy = llm_healthy("e", "p", api_base="http://x")
        unhealthy = llm_unhealthy("e", "p", "because")

        assert healthy["status"] == "healthy"
        assert healthy["ready"] is True
        assert healthy["engine"] == "e"
        assert healthy["provider_id"] == "p"

        assert unhealthy["status"] == "unhealthy"
        assert unhealthy["ready"] is False
        assert unhealthy["engine"] == "e"
        assert unhealthy["provider_id"] == "p"

    def test_a_config_fault_defaults_to_not_retryable(self):
        """The default matters: `retryable=True` is what re-dispatches the job."""
        assert llm_unhealthy("e", "p", "no key")["retryable"] is False
        assert llm_unhealthy("e", "p", "no key", retryable=True)["retryable"] is True

    def test_the_detail_prefix_says_whether_waiting_helps(self):
        assert llm_unhealthy("e", "p", "no key")["detail"].startswith("config_fault:")
        assert llm_unhealthy("e", "p", "refused", retryable=True)["detail"].startswith(
            "probe_failed:"
        )

    def test_extra_keys_pass_through(self):
        assert llm_healthy("e", "p", modal_app="a")["modal_app"] == "a"


class TestEveryEngineUsesTheSharedShape:
    @pytest.mark.parametrize("engine", ENGINES)
    def test_no_engine_hand_rolls_its_own_health_dict(self, engine):
        body = _get_health_body(_client_source(engine))
        # An engine that builds `{"status": "healthy", ...}` inline is exactly
        # the shape that let the four drift apart in the first place.
        assert '"status": "healthy"' not in body, (
            f"{engine} builds its healthy response inline instead of via "
            "llm_healthy(), so its shape can drift from the other engines"
        )
        assert '"status": "unhealthy"' not in body, (
            f"{engine} builds its unhealthy response inline instead of via "
            "llm_unhealthy()"
        )

    @pytest.mark.parametrize("engine", ENGINES)
    def test_no_engine_reports_healthy_unconditionally(self, engine):
        """A `return` of a healthy literal before any check, or no check at all.

        Detected by requiring at least one branch: the healthy verdict must be
        reachable only after something has been validated.
        """
        body = _get_health_body(_client_source(engine))
        assert "return llm_healthy(" in body, f"{engine} never returns a healthy verdict"
        assert "return llm_unhealthy(" in body, f"{engine} never returns an unhealthy verdict"


class TestProbingEnginesProbe:
    """`openai_compat`, `anthropic` and `google` front an API somebody runs.

    A free list-models call is available to each — it is not a completion — and
    each already uses it in `list_models`, so health and capability cannot
    disagree.
    """

    @pytest.mark.parametrize(
        "engine,needle",
        [
            # Quote-agnostic: the segment is produced by `ast.unparse`, which
            # normalises string literals to single quotes.
            ("openai_compat", "{self.api_base}/models"),
            ("anthropic", "api.anthropic.com/v1/models"),
            ("google", "{GOOGLE_API_BASE}/models"),
        ],
    )
    def test_the_probe_targets_the_free_models_endpoint(self, engine, needle):
        body = _get_health_body(_client_source(engine))
        assert needle in body

    @pytest.mark.parametrize("engine", ["openai_compat", "anthropic", "google"])
    def test_a_missing_key_is_caught_before_the_network(self, engine):
        body = _get_health_body(_client_source(engine))
        assert "if not self.api_key" in body, (
            f"{engine} spends a round trip to be told it has no key"
        )

    @pytest.mark.parametrize("engine", ["openai_compat", "anthropic", "google"])
    def test_a_dead_endpoint_is_transient_not_permanent(self, engine):
        """A refused connection can come back, so it stays retryable."""
        body = _get_health_body(_client_source(engine))
        assert "retryable=True" in body, f"{engine} marks an unreachable endpoint permanent"

    @pytest.mark.parametrize("engine", ["openai_compat", "anthropic", "google"])
    def test_the_probe_is_bounded(self, engine):
        body = _get_health_body(_client_source(engine))
        assert "timeout=HEALTH_PROBE_TIMEOUT" in body, (
            f"{engine}'s probe has no timeout; a hung probe blocks the health "
            "endpoint the balancer is polling"
        )


class TestModalDoesNotProbe:
    """`modal_llm` must NOT probe, and that is the correct design.

    The only way to ask whether a Modal deployment is alive is to instantiate it,
    and that bills. The image engine reaches the same conclusion and documents
    it. A test asserting "modal does not probe" is here so a future reader who
    adds a probe learns they have to justify the cost, not just that it would
    have been nice.
    """

    def test_no_network_call(self):
        body = _get_health_body(_client_source("modal"))
        assert ".get(" not in body
        assert "client.get" not in body

    def test_it_validates_configuration_instead(self):
        body = _get_health_body(_client_source("modal"))
        assert "self.modal_app_name" in body
        assert "self.modal_username" in body

    def test_a_config_fault_is_not_retryable(self):
        body = _get_health_body(_client_source("modal"))
        # Every unhealthy return must omit `retryable=True`.
        for line in body.splitlines():
            if "llm_unhealthy(" in line:
                assert "retryable=True" not in line, (
                    "a missing MODAL_APP_NAME will not fix itself; marking it "
                    "transient re-dispatches every job to a provider that can "
                    "never instantiate it"
                )


class TestNoKeyLeaksThroughAHealthCheck:
    """The Google engine's own module docstring explains the hazard.

    The key goes in the `x-goog-api-key` header rather than the query string
    because a URL reaches proxy logs and httpx exception text, and this engine's
    failure path puts exception text into a TaskEvent that is streamed to the
    backend and persisted on the job. A health check is a new place that could
    reintroduce exactly that, so it is asserted rather than trusted.
    """

    def test_google_health_sends_the_key_as_a_header(self):
        body = _get_health_body(_client_source("google"))
        assert "GOOGLE_API_KEY_HEADER" in body
        assert "?key=" not in body
        assert "key={self.api_key}" not in body

    def test_google_health_does_not_echo_the_raw_exception(self):
        body = _get_health_body(_client_source("google"))
        assert "type(exc).__name__" in body, (
            "httpx embeds the request URL in its exception text, so the raw "
            "message can carry the key into the job record"
        )
