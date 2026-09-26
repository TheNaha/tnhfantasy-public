"""Tests for the backend secret-redaction helper and the boundaries it guards.

The live leak: provider_core/downloads.py appends the CivitAI token to the model
download URL as `?token=<secret>`, a transport exception's message carries that
whole URL, the error is persisted as a reconciliation error, and
`GET /api/v2/providers/status-cards` served it back. These tests pin the two
properties that close it: the helper strips the secret, and the response
boundary scrubs both messages written before the helper existed and ones written
after it.
"""

import pytest

from core.events import REDACTED, redact_secrets
from services.provider_status_service import ProviderStatusService


# ── the helper itself ───────────────────────────────────────────────────────

def test_token_query_param_is_stripped_from_a_url():
    """The exact shape observed on the running system."""
    message = (
        "Connection error: https://civitai.com/api/download/models/123456"
        "?token=sk-CIVITAI-FAKE-TOKEN-DO-NOT-USE"
    )

    redacted = redact_secrets(message)

    assert "sk-CIVITAI-FAKE-TOKEN-DO-NOT-USE" not in redacted
    assert REDACTED in redacted
    # The non-secret part of the URL survives, so the message stays diagnosable.
    assert "civitai.com/api/download/models/123456" in redacted


@pytest.mark.parametrize("param", [
    "token", "key", "access_token", "api_key", "hf_token", "civitai_token",
    "Authorization", "X-Api-Key", "X-Amz-Signature", "secret", "password",
])
def test_every_documented_secret_param_is_stripped(param):
    secret = f"FAKE-SECRET-VALUE-{param}"
    message = f"GET https://example.com/model.safetensors?{param}={secret}&format=SafeTensor"

    redacted = redact_secrets(message)

    assert secret not in redacted
    assert REDACTED in redacted


def test_only_the_secret_value_is_replaced():
    """Redaction must not eat the rest of the URL — a redacted message is useless."""
    message = (
        "url=https://civitai.com/api/download/models/999?type=Model"
        "&token=FAKESECRET&format=SafeTensor&sizeKb=2000"
    )

    redacted = redact_secrets(message)

    assert redacted == (
        "url=https://civitai.com/api/download/models/999?type=Model"
        f"&token={REDACTED}&format=SafeTensor&sizeKb=2000"
    )


def test_bearer_header_value_is_stripped():
    secret = "hf_FAKEHUGGINGFACETOKEN"

    redacted = redact_secrets(f'headers: {{"Authorization": "Bearer {secret}"}} retrying')

    assert secret not in redacted
    assert "Bearer" in redacted  # the scheme stays; the credential does not


def test_json_shaped_message_keeps_its_shape():
    secret = "FAKE-JSON-SECRET"

    redacted = redact_secrets(f'{{"api_key": "{secret}", "model": "sd15"}}')

    assert secret not in redacted
    assert '"model": "sd15"' in redacted
    assert REDACTED in redacted


def test_message_without_secrets_is_untouched():
    message = "HTTP 503 from the model host — gave up after 3 attempt(s)"

    assert redact_secrets(message) == message


def test_words_that_merely_contain_a_param_name_are_not_mangled():
    """`secrets` is not a `secret=`, and mangling it hides the real problem."""
    for message in (
        "no secrets here at all",
        "monkey=1 and keyhole=2 and tokenizer=3",
        "the monkey business is fine",
    ):
        assert redact_secrets(message) == message


def test_nested_payloads_are_walked():
    payload = {
        "error": "https://civitai.com/api/download/models/1?token=FAKENESTED",
        "stats": {"last_error": ["bearer FAKEINLIST"]},
    }

    redacted = redact_secrets(payload)

    assert "FAKENESTED" not in str(redacted)
    assert "FAKEINLIST" not in str(redacted)
    assert redacted["error"].endswith(REDACTED)


def test_non_string_values_pass_through():
    assert redact_secrets(None) is None
    assert redact_secrets(7) == 7
    assert redact_secrets(True) is True


# ── the response boundary ───────────────────────────────────────────────────

def test_reconciliation_state_is_scrubbed_for_the_card():
    """Covers rows persisted BEFORE the helper existed, not just new ones."""
    secret = "sk-CIVITAI-FAKE-TOKEN-DO-NOT-USE"
    stored = {
        "status": "failed",
        "error": (
            "HTTPError for url: https://civitai.com/api/download/models/42"
            f"?token={secret}"
        ),
    }

    card = ProviderStatusService.normalize_reconciliation_for_card(stored)

    assert secret not in str(card)
    assert REDACTED in card["error"]


def test_reconciliation_message_field_is_scrubbed_too():
    secret = "FAKE-DEPLOY-MESSAGE-SECRET"

    card = ProviderStatusService.normalize_reconciliation_for_card({
        "status": "failed",
        "message": f"deploy blew up with Authorization: Bearer {secret}",
    })

    assert secret not in str(card)


def test_storage_error_is_scrubbed():
    payload = ProviderStatusService.empty_storage_payload(
        "p1", error="failed listing files?token=FAKESTORAGETOKEN"
    )

    assert "FAKESTORAGETOKEN" not in payload["error"]


def test_diagnostics_do_not_carry_the_token():
    """build_provider_diagnostics is the second place a state message is served.

    It is a public static method, so it scrubs its own inputs rather than
    trusting the caller to have done it.
    """
    secret = "sk-CIVITAI-FAKE-TOKEN-DO-NOT-USE"
    secret_url = f"https://civitai.com/api/download/models/7?token={secret}"

    diagnostics = ProviderStatusService.build_provider_diagnostics(
        provider_id="p1",
        provider_info={"enabled": True},
        runtime=type("R", (), {"worker_url": None, "mode": "x", "connected": False,
                               "supports_setup": False, "supports_reconciliation": False})(),
        storage_stats={"error": None},
        reconciliation_state={
            "status": "failed",
            "error": secret_url,
            "message": f"mirror of {secret_url}",
        },
        deploy_state={"status": "failed", "message": f"deploy retried {secret_url}"},
        model_sync={"stats": {"downloading": 0}},
    )

    assert secret not in str(diagnostics)
    assert diagnostics["errors"]  # the error is still reported, just sanitised
