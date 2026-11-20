"""The relevance cut over LightRAG candidates (DECISIONS.md D68, docs/RETRIEVAL_FINDINGS.md).

Stock LightRAG returns most of a small corpus for almost any query: its cosine floor
(``COSINE_THRESHOLD``, 0.2) lies below every passage, the graph leg brings chunks along
whatever their similarity, and ``/query/data`` reports no scores. LightRAG stays stock
(AGENTS.md invariant 7), so the cut happens here, after retrieval:

1. every candidate passage is scored by the cosine similarity between the scoring text and
   the passage, both embedded with the corpus embedding model through the gateway
   (invariant 8);
2. a passage is kept when its score reaches the absolute ``floor`` *and* lies within
   ``margin`` of the best score in the same retrieval.

The floor is what turns an off-corpus query into "no matching document"; the margin
removes the flat tail of unrelated documents behind a clear match. Checks, research and
the diagnostic ``/retrieval`` page call the same ``RelevantRetriever`` with the same
settings, so the page keeps showing what a check would see.

Passage vectors depend only on the text and the embedding model, so they are cached in
``chunk_embeddings``; after the first query only the query itself is embedded.
"""

from __future__ import annotations

import math
from collections.abc import Sequence
from dataclasses import dataclass, field, replace
from typing import Any, Protocol

from sqlalchemy import select
from sqlalchemy.dialects.postgresql import insert
from sqlalchemy.ext.asyncio import AsyncEngine, AsyncSession, async_sessionmaker

from app.core.config import Settings
from app.core.ids import sha256_text, utcnow
from app.db.models import ChunkEmbedding, Setting
from app.llm.aliases import FS_EMBEDDING
from app.retrieval.lightrag import LightRAGClient, RetrievalChunk, RetrievalResult
from app.services.source_refs import parse_source

PURPOSE = "retrieval_relevance"
_BATCH = 16


class Embedder(Protocol):
    async def embed_many(
        self,
        texts: list[str],
        *,
        data_class: str,
        purpose: str,
        user_id: str | None = None,
    ) -> list[list[float]]: ...


@dataclass(frozen=True)
class RelevancePolicy:
    floor: float
    margin: float


def cosine(left: Sequence[float], right: Sequence[float]) -> float:
    dot = sum(a * b for a, b in zip(left, right, strict=True))
    norm = math.sqrt(sum(a * a for a in left)) * math.sqrt(sum(b * b for b in right))
    return dot / norm if norm else 0.0


def relevance_cut(scores: Sequence[float], policy: RelevancePolicy) -> list[bool]:
    """Return, per score, whether the passage is relevant enough to keep.

    Pure: the floor is absolute, the margin is relative to the best score of the same
    retrieval. An empty or all-below-floor list keeps nothing.
    """
    if not scores:
        return []
    threshold = max(policy.floor, max(scores) - policy.margin)
    return [score >= threshold for score in scores]


@dataclass(frozen=True)
class RelevantResult:
    """A LightRAG result after the cut; ``chunks`` carry our score, best first."""

    chunks: list[RetrievalChunk]
    entities: list[dict[str, Any]]
    relationships: list[dict[str, Any]]
    policy: RelevancePolicy
    top_score: float | None = None
    cut_chunks: int = 0
    cut_entities: int = 0
    cut_relationships: int = 0
    raw: RetrievalResult | None = field(default=None, repr=False)


class RelevanceScorer:
    """Scores passages against a text with the corpus embedding model, cached per passage."""

    def __init__(self, embedder: Embedder, engine: AsyncEngine) -> None:
        self._embedder = embedder
        self._sessions = async_sessionmaker(engine, expire_on_commit=False, autoflush=False)

    async def score(
        self, text: str, passages: Sequence[str], *, user_id: str | None = None
    ) -> list[float]:
        if not passages:
            return []
        [query_vector] = await self._embedder.embed_many(
            [text], data_class="user_input", purpose=PURPOSE, user_id=user_id
        )
        vectors = await self._passage_vectors(passages, user_id=user_id)
        return [round(cosine(query_vector, vector), 4) for vector in vectors]

    async def _passage_vectors(
        self, passages: Sequence[str], *, user_id: str | None
    ) -> list[list[float]]:
        hashes = [sha256_text(passage) for passage in passages]
        async with self._sessions() as session:
            model_key = await _model_key(session)
            rows = (
                await session.execute(
                    select(ChunkEmbedding.content_hash, ChunkEmbedding.embedding).where(
                        ChunkEmbedding.model_key == model_key,
                        ChunkEmbedding.content_hash.in_(set(hashes)),
                    )
                )
            ).all()
            known: dict[str, list[float]] = {row[0]: [float(v) for v in row[1]] for row in rows}
            missing: dict[str, str] = {}
            for content_hash, passage in zip(hashes, passages, strict=True):
                if content_hash not in known:
                    missing.setdefault(content_hash, passage)
            items = list(missing.items())
            for start in range(0, len(items), _BATCH):
                batch = items[start : start + _BATCH]
                vectors = await self._embedder.embed_many(
                    [passage for _hash, passage in batch],
                    data_class="own_corpus",
                    purpose=PURPOSE,
                    user_id=user_id,
                )
                now = utcnow()
                for (content_hash, _passage), vector in zip(batch, vectors, strict=True):
                    known[content_hash] = vector
                    await session.execute(
                        insert(ChunkEmbedding)
                        .values(
                            content_hash=content_hash,
                            model_key=model_key,
                            embedding=vector,
                            created_at=now,
                        )
                        .on_conflict_do_nothing()
                    )
            if missing:
                await session.commit()
        return [known[content_hash] for content_hash in hashes]


async def _model_key(session: AsyncSession) -> str:
    """The corpus embedding model the gateway has locked, or the alias before the first call."""
    lock = await session.get(Setting, "corpus.embedding_model")
    value = lock.value if lock is not None and isinstance(lock.value, dict) else {}
    model_id = value.get("model_id")
    return str(model_id) if model_id else FS_EMBEDDING


class RelevantRetriever:
    """LightRAG ``/query/data`` followed by the relevance cut; the one retrieval path."""

    def __init__(
        self, lightrag: LightRAGClient, scorer: RelevanceScorer, policy: RelevancePolicy
    ) -> None:
        self.lightrag = lightrag
        self.scorer = scorer
        self.policy = policy

    async def retrieve(
        self,
        query: str,
        *,
        relevance_text: str | None = None,
        user_id: str | None = None,
        **query_kwargs: Any,
    ) -> RelevantResult:
        """Retrieve for ``query`` and keep what is relevant to ``relevance_text``.

        ``relevance_text`` defaults to the query. The check pipeline passes the statement
        itself, so the LLM-generated keywords it appends to the LightRAG query widen the
        candidate set but do not move the cut.
        """
        result = await self.lightrag.query_data(query, **query_kwargs)
        chunks = [chunk for chunk in result.chunks if chunk.content.strip()]
        scores = await self.scorer.score(
            relevance_text or query, [chunk.content for chunk in chunks], user_id=user_id
        )
        keep = relevance_cut(scores, self.policy)
        kept = sorted(
            (
                replace(chunk, score=score)
                for chunk, score, keep_it in zip(chunks, scores, keep, strict=True)
                if keep_it
            ),
            key=lambda chunk: chunk.score or 0.0,
            reverse=True,
        )
        kept_sources = {
            source for chunk in kept if (source := parse_source(chunk.file_path)) is not None
        }
        entities, cut_entities = _graph_for(result.entities, kept_sources)
        relationships, cut_relationships = _graph_for(result.relationships, kept_sources)
        return RelevantResult(
            chunks=kept,
            entities=entities,
            relationships=relationships,
            policy=self.policy,
            top_score=max(scores) if scores else None,
            cut_chunks=len(chunks) - len(kept),
            cut_entities=cut_entities,
            cut_relationships=cut_relationships,
            raw=result,
        )


def _graph_for(
    items: list[dict[str, Any]], kept_sources: set[tuple[str, int]]
) -> tuple[list[dict[str, Any]], int]:
    """Keep a graph record only if one of its source documents kept a passage.

    A record's ``file_path`` can name several sources (LightRAG joins them with
    ``<SEP>``). Without this, the graph leg would still show documents the cut removed.
    """
    kept: list[dict[str, Any]] = []
    for item in items:
        file_path = item.get("file_path")
        sources = {
            source
            for part in (file_path.split("<SEP>") if isinstance(file_path, str) else [])
            if (source := parse_source(part)) is not None
        }
        if sources & kept_sources:
            kept.append(item)
    return kept, len(items) - len(kept)


def policy_from(settings: Settings) -> RelevancePolicy:
    return RelevancePolicy(
        floor=settings.retrieval_relevance_floor,
        margin=settings.retrieval_relevance_margin,
    )


def build_retriever(
    settings: Settings, *, lightrag: LightRAGClient, embedder: Embedder, engine: AsyncEngine
) -> RelevantRetriever:
    return RelevantRetriever(lightrag, RelevanceScorer(embedder, engine), policy_from(settings))
