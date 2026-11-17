"""Semantic cache over normalized claims for the fast path (IMPLEMENT Phase 3).

The cache stores one embedding per full result, scoped to the corpus version. A hit is
only a preliminary answer: the caller still enqueues the full check and the full result
becomes a new version. Raw SQL is used for the vector column because asyncpg does not
register the pgvector codec for the ORM session; the literal is cast by Postgres.
"""

from __future__ import annotations

import logging
from datetime import datetime

from sqlalchemy import text
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.ids import new_id
from app.db.models import Result
from app.llm.client import LLMClient

logger = logging.getLogger(__name__)


def _vector_literal(values: list[float]) -> str:
    return "[" + ",".join(f"{value:.7f}" for value in values) + "]"


async def lookup(
    session: AsyncSession,
    llm: LLMClient,
    *,
    claim: str,
    language: str,
    corpus_version: str,
    threshold: float,
    user_id: str | None,
) -> tuple[Result, float] | None:
    embedding = await llm.embed(claim, user_id=user_id)
    row = (
        await session.execute(
            text(
                """
                SELECT result_id, 1 - (embedding <=> CAST(:embedding AS vector)) AS similarity
                FROM claim_cache
                WHERE corpus_version = :corpus_version AND language = :language
                ORDER BY embedding <=> CAST(:embedding AS vector)
                LIMIT 1
                """
            ),
            {
                "embedding": _vector_literal(embedding),
                "corpus_version": corpus_version,
                "language": language,
            },
        )
    ).first()
    if row is None or float(row.similarity) < threshold:
        return None
    result = await session.get(Result, row.result_id)
    if result is None or result.deleted:
        return None
    return result, float(row.similarity)


async def remember(
    session: AsyncSession,
    llm: LLMClient,
    *,
    claim: str,
    language: str,
    corpus_version: str,
    result_id: str,
    user_id: str | None,
) -> None:
    try:
        embedding = await llm.embed(claim, user_id=user_id)
    except Exception:
        logger.warning("semantic_cache_embedding_failed")
        return
    await session.execute(
        text(
            """
            DELETE FROM claim_cache
            WHERE normalized_text = :text AND corpus_version = :corpus_version
              AND language = :language
            """
        ),
        {"text": claim, "corpus_version": corpus_version, "language": language},
    )
    await session.execute(
        text(
            """
            INSERT INTO claim_cache
                (id, normalized_text, embedding, result_id, corpus_version, language, created_at)
            VALUES
                (:id, :text, CAST(:embedding AS vector), :result_id, :corpus_version,
                 :language, :created_at)
            """
        ),
        {
            "id": new_id("cache"),
            "text": claim,
            "embedding": _vector_literal(embedding),
            "result_id": result_id,
            "corpus_version": corpus_version,
            "language": language,
            "created_at": datetime.now().astimezone(),
        },
    )
