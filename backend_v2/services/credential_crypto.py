"""At-rest encryption for `Provider.credentials`.

Credentials used to live only in `.env`, which the API cannot serve: the file is
protected by the OS boundary and never crosses into a response. Moving them into
the database so the Providers UI can manage them changes that — `credentials`
becomes a column the API holds, one accidental `**provider.credentials` away from
being returned to any caller that reaches the app. Encrypting the column keeps
the database useful to an attacker who dumps it without being useful to the API.

ONE master key in `COMFY_CREDENTIAL_SECRET` decrypts every provider's
credentials. That is the deliberate trade: N raw tokens in `.env` means N things
to rotate and N things to leak, while one master key means one. The secret itself
has to stay in the environment (or a Docker secret) precisely because a key
stored beside the data it protects protects nothing.

The envelope is a plain dict so the column stays a `JSONColumn` and no migration
has to change its type:

    {"__enc__": "<fernet token>", "v": 1}

Plaintext dicts written before this existed still load — `decrypt_credentials`
passes them through untouched. That is what makes the migration a backfill rather
than a cutover, and what lets a deployment upgrade before the operator has chosen
a secret.

WHEN NO SECRET IS SET, encryption is off and credentials are stored as they
always were. Failing startup instead would break every existing deployment on
upgrade for a security control they did not ask for yet. The cost of that choice
is that it must be *visible*: `encryption_status()` reports it, and the Providers
UI surfaces it, so "your tokens are plaintext in the database" is something the
operator can see rather than something they have to know.
"""

import base64
import hashlib
import hmac
import os
from typing import Any

from infrastructure.logging import get_logger

logger = get_logger("services.credential_crypto")

#: Marks a dict as an encrypted envelope rather than a plaintext credential bag.
#: Prefixed so it cannot collide with a real credential key, and namespaced
#: because the alternative — guessing whether a dict is ciphertext — is how a
#: credential named `v` or `enc` silently decrypts to nothing.
ENVELOPE_KEY = "__enc__"
ENVELOPE_VERSION = 1

#: The environment variable holding the master secret.
MASTER_SECRET_ENV = "COMFY_CREDENTIAL_SECRET"

_warned_disabled = False


class CredentialDecryptionError(RuntimeError):
    """Stored credentials could not be decrypted.

    Raised rather than swallowed: a provider whose token cannot be read looks
    exactly like a provider with no token, and the failure then surfaces as a
    confusing 401 from Modal hours later. The distinction matters when the cause
    is a rotated key.
    """


def _derive_key(secret: str) -> bytes:
    """A 32-byte urlsafe-base64 key from an arbitrary-length secret.

    SHA-256 of the raw secret, not the secret itself: users paste whatever they
    have, and Fernet requires exactly 32 bytes. The domain separator stops this
    digest from ever being usable as a key in any other context that derives one
    from the same passphrase.
    """
    digest = hashlib.sha256(f"tnhfantasy/credential-crypto/v1\x00{secret}".encode("utf-8")).digest()
    return base64.urlsafe_b64encode(digest)


def get_master_secret() -> str | None:
    """The configured master secret, or None when encryption is disabled."""
    return (os.getenv("COMFY_CREDENTIAL_SECRET") or "").strip() or None


def encryption_status() -> dict[str, Any]:
    """What the UI shows on the credentials panel.

    ``enabled`` False means plaintext at rest, and the reason is spelled out
    rather than left to be inferred from behaviour.
    """
    configured = get_master_secret()
    return {
        "enabled": configured is not None,
        "env_var": MASTER_SECRET_ENV,
        "algorithm": "fernet",
        "detail": (
            f"Credentials are encrypted at rest with the key in {MASTER_SECRET_ENV}."
            if configured
            else (
                f"{MASTER_SECRET_ENV} is not set, so credentials are stored as "
                f"plaintext in the providers table. Set it and re-save each "
                f"provider's credentials to encrypt them."
            )
        ),
    }


def is_encrypted(stored: Any) -> bool:
    return isinstance(stored, dict) and ENVELOPE_KEY in stored


def encrypt_credentials(plaintext: dict[str, Any]) -> dict[str, Any]:
    """Encrypt a credential bag for storage.

    An empty bag stays empty rather than becoming a ciphertext of `{}` — there is
    nothing to protect, and a row that reports "has credentials" when it holds
    none is exactly the kind of thing that makes a provider look configured.
    """
    if not plaintext:
        return {}
    if is_encrypted(plaintext):
        # Already an envelope. Re-wrapping would double-encrypt and make
        # `update()` non-idempotent, so a double-save of the same payload has to
        # be a no-op rather than a second layer.
        return plaintext
    if not get_master_secret():
        return dict(plaintext)

    from cryptography.fernet import Fernet

    token = Fernet(_derive_key(get_master_secret())).encrypt(
        _canonical(plaintext).encode("utf-8")
    )
    return {ENVELOPE_KEY: token.decode("ascii"), "v": ENVELOPE_VERSION}


def decrypt_credentials(stored: Any) -> dict[str, Any]:
    """Decrypt for use, passing plaintext and unknown shapes through.

    Everything above this module sees a plaintext dict, which is why the
    encryption lives at the repository boundary and not in the engines: there is
    exactly one place that knows about envelopes.
    """
    if not stored:
        return {}
    if not is_encrypted(stored):
        # Pre-migration row, or encryption disabled. Either way this is the
        # plaintext bag and passing it through is the correct answer.
        return dict(stored)

    secret = get_master_secret()
    if not secret:
        raise CredentialDecryptionError(
            f"these credentials are encrypted with {MASTER_SECRET_ENV}, which is "
            f"not set. Without that key the token cannot be recovered — re-enter "
            f"it in the Providers UI, or restore the previous environment."
        )

    from cryptography.fernet import Fernet, InvalidToken

    try:
        raw = Fernet(_derive_key(secret)).decrypt(stored[ENVELOPE_KEY].encode("ascii"))
    except InvalidToken as exc:
        # Indistinguishable between "wrong key" and "row was tampered with", and
        # Fernet deliberately does not separate them. Both need a human, so both
        # get the same message.
        raise CredentialDecryptionError(
            "could not decrypt these credentials: the key in "
            f"{MASTER_SECRET_ENV} does not match the one they were written with "
            "(rotated key, or the row was modified outside the app)"
        ) from exc

    import json

    try:
        value = json.loads(raw.decode("utf-8"))
    except (json.JSONDecodeError, UnicodeDecodeError) as exc:
        raise CredentialDecryptionError(
            "decrypted credentials were not readable JSON"
        ) from exc
    return value if isinstance(value, dict) else {}


def _canonical(payload: dict[str, Any]) -> str:
    """Deterministic JSON for a credential bag.

    Sort keys, strip separators. NOT for making ciphertext stable — Fernet uses
    a random IV, so the same bag encrypts to different bytes every time and
    always will. This is for `secrets_differ`, which compares two *plaintext*
    bags; without it, `{"a": 1, "b": 2}` and `{"b": 2, "a": 1}` would read as a
    change and re-encrypt a row nobody touched.
    """
    import json

    return json.dumps(payload, sort_keys=True, separators=(",", ":"), default=str)


def mask_for_display(value: Any) -> str:
    """A hint of a secret, safe to show a UI and safe to log.

    Four characters either side of the middle and nothing at either end: enough
    for a human to confirm "is this the token I pasted", useless to anyone who
    obtains it. Deliberately not a hash — the point is to be recognisable to the
    owner, not verifiable by someone else.
    """
    if value is None:
        return ""
    text = str(value)
    if not text:
        return ""
    if len(text) <= 12:
        return "•" * len(text)
    return f"{text[:4]}{'•' * 8}{text[-4:]}"


def credential_presence(stored: Any) -> dict[str, Any]:
    """Which keys are set, and a masked hint — never the value.

    The whole reason this function exists rather than "return the dict with the
    values blanked": blanking invites a caller to reach for the original, and
    presence is what the UI actually needs to render its state.
    """
    plain = decrypt_credentials(stored)
    return {
        key: {"set": bool(val), "masked": mask_for_display(val) if val else ""}
        for key, val in sorted(plain.items())
    }


def secrets_differ(a: Any, b: Any) -> bool:
    """Constant-time-ish comparison of two stored bags, for change detection."""
    try:
        left, right = decrypt_credentials(a), decrypt_credentials(b)
    except CredentialDecryptionError:
        return True
    return not hmac.compare_digest(_canonical(left), _canonical(right))
