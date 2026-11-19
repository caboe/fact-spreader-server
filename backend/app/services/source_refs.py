"""Resolve our LightRAG ``file_source`` values back to an approved document version.

LightRAG stores the source we give it as ``<document_id>@v<version>``.  A retrieval
response can contain chunks, entities and relationships from an older source while an
asynchronous deletion is still running, so every caller must resolve the source against
the application database before exposing it.
"""

from __future__ import annotations

import re

_SOURCE_RE = re.compile(r"(doc_[A-Za-z0-9]+)@v(\d+)")


def parse_source(file_path: str | None) -> tuple[str, int] | None:
    if not file_path:
        return None
    match = _SOURCE_RE.search(file_path)
    if match is None:
        return None
    return match.group(1), int(match.group(2))
