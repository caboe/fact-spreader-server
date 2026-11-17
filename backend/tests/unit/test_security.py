"""Secrets, hashing and encryption at rest (AGENTS.md invariant 15)."""

from __future__ import annotations

from app.core.security import (
    SecretBox,
    constant_time_equals,
    hash_password,
    hash_token,
    new_api_key,
    new_csrf_token,
    verify_password,
)


def test_password_hash_roundtrip_and_rejection() -> None:
    hashed = hash_password("correct horse battery staple")
    assert verify_password("correct horse battery staple", hashed)
    assert not verify_password("wrong", hashed)


def test_secret_box_roundtrip_and_wrong_key() -> None:
    box = SecretBox(b"a" * 32)
    encrypted = box.encrypt("sk-provider-secret")
    assert encrypted != b"sk-provider-secret"
    assert box.decrypt(encrypted) == "sk-provider-secret"
    other = SecretBox(b"b" * 32)
    try:
        other.decrypt(encrypted)
    except ValueError:
        pass
    else:
        raise AssertionError("another key must not decrypt the value")


def test_api_key_is_prefixed_and_stored_hashed() -> None:
    plaintext, prefix, digest = new_api_key()
    assert plaintext.startswith("fc_live_")
    assert prefix.startswith("fc_live_")
    assert digest == hash_token(plaintext)
    assert plaintext not in digest


def test_constant_time_equals() -> None:
    assert constant_time_equals("abc", "abc")
    assert not constant_time_equals("abc", "abd")


def test_csrf_tokens_are_not_repeated() -> None:
    assert new_csrf_token() != new_csrf_token()


def test_sexual_minors_floor_blocks_explicit_material_not_discussion() -> None:
    from app.services.moderation import sexual_minors_floor

    assert sexual_minors_floor("Explicit sexual content involving a minor.")
    assert sexual_minors_floor("Sexual images of a 12-year-old child.")
    assert not sexual_minors_floor("Research on child sexual abuse prevention.")
    assert not sexual_minors_floor("A 12-year-old child was reported missing.")
