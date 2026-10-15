"""Provider credentials are encrypted at rest and never leave the process.

Two separate guarantees, and they fail in different ways, so they are tested
separately:

  * AT REST — the `providers.credentials` column holds ciphertext. Asserted by
    reading the column with a raw SQLAlchemy query, because the repository's own
    read path decrypts and would hide the very thing under test.
  * NOT SERIALIZED — nothing an API route returns contains a secret. Asserted by
    walking the actual response payloads.

The second one is the invariant everything else rests on. `_provider_to_dict`
already refuses to emit `credentials` and emits `credential_summary` instead, and
pops `worker_token` from config with a comment saying it is doing so on purpose
— but "is there a test for that" was the answer no. A future refactor that
spreads `**provider.config` into a payload would leak a token with no failing
test, and the endpoint that leaks is unauthenticated.
"""

import asyncio
import os

import pytest

from core.entities import Provider
from infrastructure.repositories.provider_repo import ProviderRepository
from services.credential_crypto import (
    MASTER_SECRET_ENV,
    CredentialDecryptionError,
    credential_presence,
    decrypt_credentials,
    encrypt_credentials,
    encryption_status,
    is_encrypted,
)

SECRET = "a-master-secret-for-tests"
BAG = {"token_id": "ak-abcdefghijklmnopqrst", "token_secret": "as-zzzzzzzzzzzzzzzz"}


@pytest.fixture(autouse=True)
def _master_secret(monkeypatch):
    monkeypatch.setenv(MASTER_SECRET_ENV, SECRET)


class TestEncryptionAtRest:
    def test_the_column_holds_ciphertext_and_callers_hold_plaintext(self, session):
        repo = ProviderRepository(session)
        repo.create({"id": "enc-1", "type": "modal", "worker_type": "image",
                     "credentials": dict(BAG), "config": {}})

        # What a database dump would contain.
        from sqlalchemy import text as sql_text

        raw = str(session.exec(
            sql_text("SELECT credentials FROM providers WHERE id = 'enc-1'")
        ).first())
        assert BAG["token_secret"] not in raw, (
            "the secret is readable in the column; encryption did not apply"
        )
        assert "__enc__" in raw

        # What the rest of the application sees.
        loaded = repo.get("enc-1")
        assert loaded.credentials == BAG

    def test_get_all_and_get_enabled_also_decrypt(self, session):
        repo = ProviderRepository(session)
        repo.create({"id": "enc-2", "type": "modal", "worker_type": "image",
                     "credentials": dict(BAG), "enabled": True, "config": {}})
        assert repo.get_all()[0].credentials == BAG
        assert repo.get_enabled()[0].credentials == BAG

    def test_an_update_re_encrypts(self, session):
        repo = ProviderRepository(session)
        repo.create({"id": "enc-3", "type": "modal", "worker_type": "image",
                     "credentials": dict(BAG), "config": {}})
        repo.update("enc-3", {"credentials": {"token_id": "ak-rotated"}})

        from sqlalchemy import text as sql_text

        raw = str(session.exec(
            sql_text("SELECT credentials FROM providers WHERE id = 'enc-3'")
        ).first())
        assert "ak-rotated" not in raw
        assert repo.get("enc-3").credentials == {"token_id": "ak-rotated"}

    def test_reading_does_not_rewrite_the_row(self, session):
        """A decrypt on load must not mark the column dirty.

        Otherwise every provider read in a reconciliation sweep issues a write.
        Note this is checked on the raw column, not by comparison of ciphertext:
        Fernet uses a random IV, so two encryptions of the same bag are
        different bytes by design and comparing them would prove nothing.
        """
        from sqlalchemy import text as sql_text

        repo = ProviderRepository(session)
        repo.create({"id": "enc-4", "type": "modal", "worker_type": "image",
                     "credentials": dict(BAG), "config": {}})
        before = str(session.exec(
            sql_text("SELECT credentials FROM providers WHERE id = 'enc-4'")
        ).first())

        repo.get("enc-4")
        repo.get_all()
        session.expire_all()
        after = str(session.exec(
            sql_text("SELECT credentials FROM providers WHERE id = 'enc-4'")
        ).first())

        assert before == after

    def test_a_rotated_key_raises_rather_than_reading_as_empty(self, session, monkeypatch):
        """An unreadable token must not look like no token.

        Returning `{}` turns a rotated master key into an unexplained 401 from
        Modal on the next dispatch, with nothing in the log saying why.
        """
        repo = ProviderRepository(session)
        repo.create({"id": "enc-5", "type": "modal", "worker_type": "image",
                     "credentials": dict(BAG), "config": {}})
        session.expunge_all()

        monkeypatch.setenv(MASTER_SECRET_ENV, "a-different-secret")
        with pytest.raises(CredentialDecryptionError) as excinfo:
            ProviderRepository(session).get("enc-5")
        assert MASTER_SECRET_ENV in str(excinfo.value)

    def test_plaintext_rows_still_load(self, session):
        """A pre-migration row is plaintext and must keep working.

        This is what makes the backfill a backfill: an operator can upgrade, run
        the app, and only then choose a secret, without the app refusing to read
        the credentials it already had.
        """
        session.add(Provider(id="legacy-1", type="modal", worker_type="image",
                             credentials=dict(BAG), config={}))
        session.commit()
        session.expunge_all()

        assert ProviderRepository(session).get("legacy-1").credentials == BAG

    def test_get_raw_does_not_decrypt(self, session):
        """Maintenance paths must be able to check a row without reading it."""
        repo = ProviderRepository(session)
        repo.create({"id": "enc-6", "type": "modal", "worker_type": "image",
                     "credentials": dict(BAG), "config": {}})
        raw = repo.get_raw("enc-6")
        assert is_encrypted(raw.credentials)
        assert BAG["token_secret"] not in str(raw.credentials)


class TestPlaintextFallback:
    def test_no_secret_stores_plaintext_and_says_so(self, monkeypatch):
        """Not failing startup is the right call; being silent about it is not.

        Refusing to boot would break every existing deployment on upgrade for a
        control nobody asked for. Storing plaintext without saying so would just
        move the problem somewhere nobody is looking.
        """
        monkeypatch.delenv(MASTER_SECRET_ENV, raising=False)
        assert encryption_status()["enabled"] is False
        assert MASTER_SECRET_ENV in encryption_status()["detail"]
        assert encrypt_credentials(dict(BAG)) == BAG

    def test_encrypted_rows_become_unreadable_without_a_secret(self, monkeypatch):
        token = encrypt_credentials(dict(BAG))
        monkeypatch.delenv(MASTER_SECRET_ENV, raising=False)
        assert is_encrypted(token)
        with pytest.raises(CredentialDecryptionError):
            decrypt_credentials(token)


class TestCredentialsNeverLeave:
    """The invariant the whole design rests on."""

    def test_provider_dict_omits_credentials(self, session):
        from services.provider_service import ProviderService

        repo = ProviderRepository(session)
        repo.create({"id": "leak-1", "type": "modal", "worker_type": "image",
                     "credentials": dict(BAG), "config": {"worker_token": "wt-secret"}})

        payload = ProviderService(session)._provider_to_dict(repo.get("leak-1"))
        serialised = repr(payload)

        assert "as-zzzzzzzzzzzzzzzz" not in serialised, (
            "the credential leaked into the provider payload"
        )
        assert "ak-abcdefghijklmnopqrst" not in serialised
        assert "wt-secret" not in serialised, (
            "worker_token leaked into the provider payload"
        )
        # Presence is still available — that is what the UI actually needs.
        assert payload["has_worker_token"] is True
        assert payload["credential_summary"]

    def test_presence_reports_keys_and_masks_never_values(self, session):
        repo = ProviderRepository(session)
        repo.create({"id": "leak-2", "type": "modal", "worker_type": "image",
                     "credentials": dict(BAG), "config": {}})
        presence = credential_presence(repo.get_raw("leak-2").credentials)

        assert set(presence) == {"token_id", "token_secret"}
        assert presence["token_id"]["set"] is True
        assert "abcdefghij" not in presence["token_id"]["masked"]
        assert "ak-a" in presence["token_id"]["masked"]

    def test_the_whole_provider_list_endpoint_leaks_nothing(self, client, session):
        """End-to-end, through the real route.

        The unit test above proves `_provider_to_dict` is clean. This proves the
        route does not add anything on top — a response model with a
        `credentials` field, or a middleware that dumps the row, would both pass
        the unit test and fail here.
        """
        repo = ProviderRepository(session)
        repo.create({"id": "leak-3", "type": "modal", "worker_type": "image",
                     "credentials": dict(BAG), "config": {}})

        response = client.get("/api/v2/providers")
        assert response.status_code == 200
        body = response.text
        assert "as-zzzzzzzzzzzzzzzz" not in body
        assert "ak-abcdefghijklmnopqrst" not in body


class TestCiphertextIsAuthenticated:
    def test_a_tampered_row_fails_loudly(self):
        """Fernet's whole point: corruption is an error, not garbage output."""
        token = encrypt_credentials(dict(BAG))
        raw = token["__enc__"]
        tampered = dict(token)
        tampered["__enc__"] = raw[:-4] + ("AAAA" if not raw.endswith("AAAA") else "BBBB")

        with pytest.raises(CredentialDecryptionError):
            decrypt_credentials(tampered)

    def test_the_key_is_derived_not_assumed(self):
        """Any-length secret works; Fernet's 32-byte requirement is absorbed."""
        os.environ[MASTER_SECRET_ENV] = "x"
        try:
            assert encrypt_credentials(dict(BAG))
            os.environ[MASTER_SECRET_ENV] = "y" * 500
            assert encrypt_credentials(dict(BAG))
        finally:
            os.environ[MASTER_SECRET_ENV] = SECRET

    def test_ciphertext_is_not_byte_stable(self):
        """Fernet uses a random IV — assert that, so nobody "optimises" it.

        Two encryptions of the same bag differ, which means "did this row
        change" can never be answered by comparing ciphertext. Change detection
        therefore has to compare the plaintext bags (`secrets_differ`), and a
        future reader who assumed ciphertext comparison worked would be wrong.
        """
        assert encrypt_credentials(dict(BAG)) != encrypt_credentials(dict(BAG))
        assert decrypt_credentials(encrypt_credentials(dict(BAG))) == BAG

    def test_key_order_does_not_read_as_a_change(self):
        from services.credential_crypto import secrets_differ

        assert not secrets_differ({"a": 1, "b": 2}, {"b": 2, "a": 1})
        assert secrets_differ({"a": 1}, {"a": 2})

class TestCredentialRoutes:
    """The write-only contract, through the real routes."""

    def _make(self, session, **creds):
        repo = ProviderRepository(session)
        repo.create({"id": "cred-1", "type": "modal", "worker_type": "image",
                     "enabled": True, "priority": 1,
                     "credentials": dict(creds) or dict(BAG), "config": {}})
        return repo

    def test_get_reports_presence_and_never_a_value(self, client, session):
        self._make(session)
        response = client.get("/api/v2/providers/cred-1/credentials")
        assert response.status_code == 200
        body = response.json()
        assert set(body["credentials"]) == {"token_id", "token_secret"}
        assert BAG["token_secret"] not in response.text
        assert body["encryption"]["enabled"] is True

    def test_put_merges_and_returns_no_value(self, client, session):
        repo = self._make(session)
        response = client.put(
            "/api/v2/providers/cred-1/credentials",
            json={"credentials": {"api_key": "sk-brand-new-token-value"}},
        )
        assert response.status_code == 200
        assert "sk-brand-new-token-value" not in response.text
        assert repo.get("cred-1").credentials["api_key"] == "sk-brand-new-token-value"
        # merge, not replace
        assert set(repo.get("cred-1").credentials) >= {"token_id", "token_secret", "api_key"}

    def test_put_replace_swaps_the_whole_bag(self, client, session):
        repo = self._make(session)
        client.put("/api/v2/providers/cred-1/credentials",
                   json={"credentials": {"api_key": "only"}, "replace": True})
        assert set(repo.get("cred-1").credentials) == {"api_key"}

    def test_put_rejects_a_blank_value(self, client, session):
        """A blank credential reads as absent, so storing one is a trap."""
        repo = self._make(session)
        response = client.put("/api/v2/providers/cred-1/credentials",
                              json={"credentials": {"token_id": ""}})
        assert response.status_code == 400
        assert "empty string" in response.text
        # ...and the old value survived.
        assert repo.get("cred-1").credentials["token_id"] == BAG["token_id"]

    def test_delete_removes_one_key_and_keeps_the_rest(self, client, session):
        repo = self._make(session)
        response = client.delete("/api/v2/providers/cred-1/credentials/token_secret")
        assert response.status_code == 200
        remaining = repo.get("cred-1").credentials
        assert "token_secret" not in remaining
        assert remaining["token_id"] == BAG["token_id"]

    def test_delete_of_an_absent_key_is_a_404(self, client, session):
        self._make(session)
        assert client.delete(
            "/api/v2/providers/cred-1/credentials/nope"
        ).status_code == 404

    def test_missing_provider_is_a_404(self, client, session):
        assert client.get("/api/v2/providers/ghost/credentials").status_code == 404
        assert client.put("/api/v2/providers/ghost/credentials",
                          json={"credentials": {"a": "b"}}).status_code == 404

    def test_the_credential_routes_do_not_collide_with_the_provider_patch(self, client, session):
        """`PUT /{id}/credentials` must not be read as a provider update.

        Both are PUT on the same path prefix; if the router let the provider
        update match first it would file the value under `config` instead, and
        `can_create_engine` would read `config["token_id"]` and find nothing —
        a credential that saves successfully and silently does nothing.
        """
        repo = self._make(session)
        client.put("/api/v2/providers/cred-1/credentials",
                   json={"credentials": {"marker": "only-in-credentials"}})

        provider = repo.get("cred-1")
        assert provider.credentials["marker"] == "only-in-credentials"
        assert "marker" not in (provider.config or {}), (
            "the credential was written into config, where no engine will read it"
        )


class TestDeployRoute:
    def test_an_unknown_target_is_a_400_naming_the_valid_ones(self, client):
        response = client.post("/api/v2/providers/deploy", json={"target": "rm-rf"})
        assert response.status_code == 400
        for name in ("image", "tts", "llm", "beam"):
            assert name in response.text

    def test_targets_are_listed(self, client):
        response = client.get("/api/v2/providers/deploy/targets")
        assert response.status_code == 200
        names = {t["target"] for t in response.json()["targets"]}
        assert names == {"image", "tts", "llm", "beam", "all"}

    def test_a_target_is_never_interpolated_into_a_command(self):
        """The allowlist is the boundary; a missing key must not reach a shell.

        `run_deploy` raises before anything is executed, so the request-controlled
        string never becomes an argv element at all.
        """
        from services.provider_deploy import DeployError, run_deploy

        with pytest.raises(DeployError) as excinfo:
            asyncio.run(run_deploy("llm; rm -rf /"))
        assert "unknown deploy target" in str(excinfo.value)

    def test_the_deploy_command_is_an_argv_list_not_a_string(self):
        """`shell=False` means there is nothing for a shell to misparse.

        Asserting the construction rather than the intent: a future "just add
        `shell=True` so we can pipe" is the change this catches.
        """
        import inspect

        from services import provider_deploy

        source = inspect.getsource(provider_deploy.run_deploy)
        assert "create_subprocess_exec" in source
        assert "create_subprocess_shell" not in source
        assert "shell=True" not in source

    def test_credentials_reach_the_child_as_env_not_argv(self, monkeypatch):
        from services.provider_deploy import _child_env

        env = _child_env({"token_id": "ak-abc", "token_secret": "as-def",
                          "api_key": "sk-ghi", "blank": ""})
        assert env["MODAL_TOKEN_ID"] == "ak-abc"
        assert env["MODAL_TOKEN_SECRET"] == "as-def"
        assert env["BEAM_API_KEY"] == "sk-ghi"
        assert "blank" not in env

    def test_the_child_does_not_inherit_the_backend_secrets(self):
        """The child gets PATH and HOME, not the DB password or master key.

        This is the leak that would otherwise be invisible: `execve` hands the
        child a copy of the parent's environment, so inheriting means shipping
        the credential master key to the vendor CLI process for no reason.
        """
        import os

        from services.provider_deploy import _child_env

        os.environ["COMFY_DATABASE_URL"] = "postgresql://comfy:hunter2@db/comfy"
        os.environ[MASTER_SECRET_ENV] = "the-master-key"
        try:
            env = _child_env(None)
            assert "COMFY_DATABASE_URL" not in env
            assert MASTER_SECRET_ENV not in env
            assert "PATH" in env
        finally:
            os.environ.pop("COMFY_DATABASE_URL", None)

    def test_output_is_capped_and_says_so(self):
        from services.provider_deploy import MAX_OUTPUT_BYTES, _truncate

        short = b"x" * 100
        assert _truncate(short) == short.decode()
        long_out = b"y" * (MAX_OUTPUT_BYTES + 5000)
        capped = _truncate(long_out)
        assert len(capped) < MAX_OUTPUT_BYTES + 200
        assert "omitted" in capped

    def test_a_timeout_kills_the_child_and_says_the_deploy_may_be_partial(self, monkeypatch, tmp_path):
        """A deploy that outlives its budget must be terminated, not left running.

        The message matters as much as the kill: a Modal deploy killed mid-flight
        can leave the app name pointing at an older revision, so the caller has
        to be told to check rather than left to assume it failed cleanly.
        """
        import pathlib

        from services import provider_deploy

        # A real script that sleeps longer than the budget.
        scripts = tmp_path / "scripts"
        scripts.mkdir()
        script = scripts / "deploy.sh"
        # `exec`, not a bare `sleep`: without it bash forks a child that keeps
        # stdout open, so terminate() kills the shell and `communicate()`
        # then blocks on the grandchild for the full grace period.
        script.write_text("#!/usr/bin/env bash\nexec sleep 30\n")

        monkeypatch.setattr(provider_deploy, "repo_root", lambda: pathlib.Path(tmp_path))

        with pytest.raises(provider_deploy.DeployError) as excinfo:
            asyncio.run(
                provider_deploy.run_deploy("llm", timeout=1.0, dry_run=False)
            )
        assert "partial state" in str(excinfo.value)

    def test_deploys_are_serialised(self):
        """Two concurrent deploys of one app name race; the lock prevents that."""
        from services.provider_deploy import _deploy_lock

        assert _deploy_lock is not None
