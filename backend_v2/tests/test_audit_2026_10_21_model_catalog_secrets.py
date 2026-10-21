"""`GET /api/v2/models/catalog` must never return a secret.

The route is unauthenticated and used to answer with a `tokens` block holding
the plaintext `HF_TOKEN` / `CIVITAI_TOKEN` environment values, falling back
to the DECRYPTED per-provider credentials (`ProviderRepository.get()`
decrypts) when the environment did not carry them. Either way the response
body carried a usable token.

The block is gone. A token's presence is still readable — through the
write-only credential routes, which answer with presence and a masked hint —
but never its value.
"""

ENV_HF_TOKEN = "hf_FAKE_ENVIRONMENT_TOKEN_DO_NOT_USE"
ENV_CIVITAI_TOKEN = "sk-FAKE-ENVIRONMENT-CIVITAI-TOKEN-DO-NOT-USE"
PROVIDER_HF_TOKEN = "hf_FAKE_PROVIDER_TOKEN_DO_NOT_USE"
PROVIDER_CIVITAI_TOKEN = "sk-FAKE-PROVIDER-CIVITAI-TOKEN-DO-NOT-USE"


def _assert_no_token_in(response, *secrets):
    assert response.status_code == 200, response.text
    body = response.json()

    assert "tokens" not in body, "the catalog still carries a `tokens` block"
    text = response.text
    for secret in secrets:
        assert secret not in text, "the catalog leaked a credential"


def test_the_catalog_carries_no_environment_tokens(client, monkeypatch):
    monkeypatch.setenv("HF_TOKEN", ENV_HF_TOKEN)
    monkeypatch.setenv("CIVITAI_TOKEN", ENV_CIVITAI_TOKEN)

    response = client.get("/api/v2/models/catalog")

    _assert_no_token_in(response, ENV_HF_TOKEN, ENV_CIVITAI_TOKEN)


def test_the_catalog_carries_no_provider_credentials(client, monkeypatch):
    """The fallback path: no environment token, so the route used to read the
    decrypted per-provider credentials and serve them."""
    monkeypatch.delenv("HF_TOKEN", raising=False)
    monkeypatch.delenv("CIVITAI_TOKEN", raising=False)

    created = client.post(
        "/api/v2/providers",
        json={
            "id": "catalog-secret-provider",
            "type": "modal",
            "credentials": {
                "token_id": "tok_123",
                "token_secret": "secret_456",
                "hf_token": PROVIDER_HF_TOKEN,
                "civitai_token": PROVIDER_CIVITAI_TOKEN,
            },
        },
    )
    assert created.status_code == 200, created.text

    response = client.get("/api/v2/models/catalog")

    _assert_no_token_in(response, PROVIDER_HF_TOKEN, PROVIDER_CIVITAI_TOKEN)


def test_the_catalog_still_serves_its_actual_payload(client):
    """Removing the secret must not remove the catalog."""
    response = client.get("/api/v2/models/catalog")

    assert response.status_code == 200
    body = response.json()
    for key in ("catalog", "roles", "active", "shared_weights"):
        assert key in body
