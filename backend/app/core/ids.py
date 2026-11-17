"""ULID-based identifiers, timestamps and text normalization (PROTOCOL §1)."""

from __future__ import annotations

import hashlib
import unicodedata
from datetime import UTC, datetime

from ulid import ULID


def utcnow() -> datetime:
    return datetime.now(UTC)


def new_id(prefix: str) -> str:
    """Return ``<prefix>_<ULID>``. Prefixes are the stable part; the rest is opaque."""
    return f"{prefix}_{ULID()}"


def normalize_text(text: str) -> str:
    """NFC, LF line endings and trimmed ends.

    Hashes and spans refer to this normalized text. We do not collapse internal
    whitespace because that would move spans without telling the caller.
    """
    return unicodedata.normalize("NFC", text.replace("\r\n", "\n").replace("\r", "\n")).strip()


def sha256_text(text: str) -> str:
    return f"sha256:{hashlib.sha256(normalize_text(text).encode('utf-8')).hexdigest()}"


def sha256_bytes(data: bytes) -> str:
    return f"sha256:{hashlib.sha256(data).hexdigest()}"


def code_point_span(haystack: str, needle: str) -> tuple[int, int] | None:
    """Locate ``needle`` in ``haystack``; both are Python strings (code points)."""
    start = haystack.find(needle)
    if start < 0:
        return None
    return start, start + len(needle)
