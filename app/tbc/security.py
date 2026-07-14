from __future__ import annotations

import base64
import hashlib
import hmac
import os
import secrets
from dataclasses import dataclass


HASH_NAME = "pbkdf2_sha256"
DEFAULT_ITERATIONS = 310_000


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


def hash_api_key(key: str) -> str:
    return hashlib.sha256(key.encode("utf-8")).hexdigest()


def verify_api_key(key: str, stored_hash: str) -> bool:
    if not key or not stored_hash:
        return False
    return hmac.compare_digest(hash_api_key(key), stored_hash)

