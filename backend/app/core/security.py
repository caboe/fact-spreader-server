"""Passwords, token hashing, encryption at rest and CSRF helpers (AGENTS.md 15)."""

from __future__ import annotations

import base64
import hashlib
import hmac
import secrets

from argon2 import PasswordHasher
from argon2.exceptions import VerifyMismatchError
from cryptography.fernet import Fernet, InvalidToken

PASSWORD_HASHER = PasswordHasher()
API_KEY_PREFIX = "fc_live_"
DEVICE_TOKEN_PREFIX = "fc_dev_"
INTERNAL_KEY_PREFIX = "fc_int_"


class SecretBox:
    """Encrypt provider keys at rest with a key derived from the deployment secret."""

    def __init__(self, material: bytes) -> None:
        key = hashlib.sha256(material).digest()
        self._fernet = Fernet(base64.urlsafe_b64encode(key))

    def encrypt(self, plaintext: str) -> bytes:
        return self._fernet.encrypt(plaintext.encode("utf-8"))

    def decrypt(self, token: bytes) -> str:
        try:
            return self._fernet.decrypt(token).decode("utf-8")
        except InvalidToken as exc:
            raise ValueError(
                "encrypted value cannot be decrypted with this APP_SECRET_KEY"
            ) from exc


def hash_password(password: str) -> str:
    return PASSWORD_HASHER.hash(password)


def verify_password(password: str, password_hash: str) -> bool:
    try:
        return PASSWORD_HASHER.verify(password_hash, password)
    except VerifyMismatchError:
        return False


def new_api_key() -> tuple[str, str, str]:
    """Return ``(plaintext, prefix-for-display, sha256-hex)``."""
    token = f"{API_KEY_PREFIX}{secrets.token_urlsafe(32)}"
    return token, token[:16], hash_token(token)


def new_device_token() -> tuple[str, str, str]:
    token = f"{DEVICE_TOKEN_PREFIX}{secrets.token_urlsafe(32)}"
    return token, token[:16], hash_token(token)


def hash_token(token: str) -> str:
    return hashlib.sha256(token.encode("utf-8")).hexdigest()


def constant_time_equals(left: str, right: str) -> bool:
    return hmac.compare_digest(left.encode("utf-8"), right.encode("utf-8"))


def new_csrf_token() -> str:
    return secrets.token_urlsafe(32)
