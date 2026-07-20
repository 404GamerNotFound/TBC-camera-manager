from __future__ import annotations

import base64
import hashlib
import hmac
import os
import secrets
from dataclasses import dataclass
from functools import lru_cache

from cryptography.fernet import Fernet, InvalidToken
from cryptography.hazmat.primitives import hashes
from cryptography.hazmat.primitives.kdf.hkdf import HKDF


HASH_NAME = "pbkdf2_sha256"
DEFAULT_ITERATIONS = 310_000

ENCRYPTED_PREFIX = "enc:v1:"
_HKDF_SALT = b"tbc-camera-manager-secret-encryption"
_HKDF_INFO = b"tbc-secret-v1"


class SecretDecryptionError(RuntimeError):
    """Raised when an encrypted secret cannot be decrypted with the current key."""


@dataclass(frozen=True)
class PasswordHash:
    algorithm: str
    iterations: int
    salt: bytes
    digest: bytes


def _b64encode(value: bytes) -> str:
    return base64.urlsafe_b64encode(value).decode("ascii").rstrip("=")


def _b64decode(value: str) -> bytes:
    padded = value + "=" * (-len(value) % 4)
    return base64.urlsafe_b64decode(padded.encode("ascii"))


def hash_password(password: str, *, iterations: int = DEFAULT_ITERATIONS) -> str:
    salt = os.urandom(16)
    digest = hashlib.pbkdf2_hmac("sha256", password.encode("utf-8"), salt, iterations)
    return f"{HASH_NAME}${iterations}${_b64encode(salt)}${_b64encode(digest)}"


def parse_password_hash(stored_hash: str) -> PasswordHash:
    algorithm, iterations, salt, digest = stored_hash.split("$", 3)
    if algorithm != HASH_NAME:
        raise ValueError(f"unsupported password hash algorithm: {algorithm}")
    return PasswordHash(
        algorithm=algorithm,
        iterations=int(iterations),
        salt=_b64decode(salt),
        digest=_b64decode(digest),
    )


def verify_password(password: str, stored_hash: str) -> bool:
    try:
        parsed = parse_password_hash(stored_hash)
    except (ValueError, TypeError):
        return False
    candidate = hashlib.pbkdf2_hmac(
        "sha256",
        password.encode("utf-8"),
        parsed.salt,
        parsed.iterations,
    )
    return hmac.compare_digest(candidate, parsed.digest)


def generate_api_key() -> str:
    return "tbc_" + secrets.token_urlsafe(32)


def generate_csrf_token() -> str:
    return secrets.token_urlsafe(32)


def hash_api_key(key: str) -> str:
    return hashlib.sha256(key.encode("utf-8")).hexdigest()


def verify_api_key(key: str, stored_hash: str) -> bool:
    if not key or not stored_hash:
        return False
    return hmac.compare_digest(hash_api_key(key), stored_hash)


@lru_cache(maxsize=8)
def _fernet_for_key(secret_key: str) -> Fernet:
    derived = HKDF(
        algorithm=hashes.SHA256(),
        length=32,
        salt=_HKDF_SALT,
        info=_HKDF_INFO,
    ).derive(secret_key.encode("utf-8"))
    return Fernet(base64.urlsafe_b64encode(derived))


def encrypt_secret(secret_key: str, plaintext: str | None) -> str | None:
    """Encrypt a secret value for storage. Empty/None values pass through unchanged."""
    if not plaintext:
        return plaintext
    token = _fernet_for_key(secret_key).encrypt(plaintext.encode("utf-8"))
    return ENCRYPTED_PREFIX + token.decode("ascii")


def decrypt_secret(secret_key: str, value: str | None) -> str | None:
    """Decrypt a secret value read from storage.

    Values without the encrypted-value prefix are returned unchanged - this
    is what lets pre-existing plaintext secrets keep working until they are
    re-encrypted in place.
    """
    if not value or not value.startswith(ENCRYPTED_PREFIX):
        return value
    token = value[len(ENCRYPTED_PREFIX):].encode("ascii")
    try:
        return _fernet_for_key(secret_key).decrypt(token).decode("utf-8")
    except InvalidToken as exc:
        raise SecretDecryptionError(
            "Unable to decrypt stored secret - the TBC_SECRET_KEY does not match "
            "the key it was encrypted with."
        ) from exc


def is_encrypted_secret(value: str | None) -> bool:
    return bool(value) and value.startswith(ENCRYPTED_PREFIX)


def encrypt_bytes(secret_key: str, data: bytes) -> bytes:
    """Encrypt arbitrary binary data (e.g. a backup archive) with the derived key."""
    return _fernet_for_key(secret_key).encrypt(data)


def decrypt_bytes(secret_key: str, token: bytes) -> bytes:
    try:
        return _fernet_for_key(secret_key).decrypt(token)
    except InvalidToken as exc:
        raise SecretDecryptionError(
            "Unable to decrypt this backup - it was created with a different TBC_SECRET_KEY."
        ) from exc

