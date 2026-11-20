"""Deterministic fakes for the regular integration suite.

The fake LLM implements the same ``chat_structured`` interface as the gateway client, so
the API/worker wiring and the gate are tested without a network call or live spend.
"""

from __future__ import annotations

from typing import Any, TypeVar

from app.llm.aliases import FS_CHAT, FS_EXTRACT, FS_MODERATION, FS_VERIFY
from app.llm.client import LLMError, LLMUsage
from app.pipeline.extraction import ExtractedStatementOut, ExtractionOutput
from app.pipeline.verification import (
    VerificationOutput,
    _ArgumentIssueOut,
    _EvidenceLinkOut,
    _MissingOut,
    _TextWithEvidenceOut,
    _UnverifiableOut,
)
from app.rendering.service import JudgeOutput
from app.retrieval.lightrag import RetrievalChunk, RetrievalResult
from app.services.moderation import ModerationOutput
from pydantic import BaseModel

T = TypeVar("T", bound=BaseModel)


class FakeLLM:
    def __init__(
        self,
        *,
        block: bool = False,
        unavailable: bool = False,
        narratives: list[str] | None = None,
        judge_issues: list[str] | None = None,
        audit_sequence: list[bool] | None = None,
        verdict: str = "true_but_misleading",
        passage_similarity: float = 1.0,
    ) -> None:
        self.block = block
        self.unavailable = unavailable
        self.narratives = list(narratives or ["The raw figure is supported [E1]."])
        self.judge_issues = list(judge_issues or [])
        self.audit_sequence = list(audit_sequence or [])
        self.verdict = verdict
        self.passage_similarity = passage_similarity
        self.verify_calls = 0
        self.calls: list[str] = []

    async def chat_text(
        self,
        *,
        alias: str,
        messages: list[dict[str, str]],
        data_classes: list[str],
        purpose: str,
        user_id: str | None = None,
        max_tokens: int = 1200,
        temperature: float = 0.4,
    ) -> tuple[str, LLMUsage]:
        self.calls.append(alias)
        if self.unavailable:
            raise LLMError(503, "provider_unavailable", "fake provider outage")
        text = self.narratives.pop(0) if self.narratives else "The evidence is insufficient."
        return text, LLMUsage(tokens_in=10, tokens_out=5)

    async def embed(
        self,
        text: str,
        *,
        user_id: str | None = None,
        purpose: str = "semantic_cache",
    ) -> list[float]:
        self.calls.append("embed")
        return [1.0] + [0.0] * 1023

    async def embed_many(
        self,
        texts: list[str],
        *,
        data_class: str,
        purpose: str,
        user_id: str | None = None,
    ) -> list[list[float]]:
        """Queries get ``[1, 0, ...]``; every passage scores ``passage_similarity`` against it."""
        self.calls.append("embed")
        if data_class == "own_corpus":
            return [unit_vector(self.passage_similarity) for _text in texts]
        return [[1.0] + [0.0] * 1023 for _text in texts]

    async def chat_structured(
        self,
        *,
        alias: str,
        messages: list[dict[str, str]],
        output_model: type[T],
        data_classes: list[str],
        purpose: str,
        user_id: str | None = None,
        max_tokens: int = 2048,
    ) -> tuple[T, LLMUsage]:
        self.calls.append(alias)
        if self.unavailable:
            raise LLMError(503, "moderation_unavailable", "fake moderation outage")
        if alias == FS_MODERATION:
            output: Any = ModerationOutput(
                categories=["sexual_minors"] if self.block else [],
                sexual_minors=self.block,
            )
        elif alias == FS_CHAT and output_model is JudgeOutput:
            output = JudgeOutput(passed=not self.judge_issues, issues=self.judge_issues)
        elif alias == FS_EXTRACT:
            text = _input_text(messages)
            output = ExtractionOutput(
                statements=[
                    ExtractedStatementOut(
                        text=text,
                        kind="fact",
                        checkworthy=True,
                        relevance=0.95,
                        scope={
                            "subject": "immigrants",
                            "predicate": "commit more crimes",
                            "geography": "Germany",
                        },
                        topics=["crime_statistics"],
                        domain_tags=["racism"],
                        keywords_high=["crime and migration"],
                        keywords_low=["crime", "migration", "suspect statistics"],
                    )
                ]
            )
        elif alias == FS_VERIFY:
            audit_index = min(self.verify_calls, len(self.audit_sequence) - 1)
            audit_complete = self.audit_sequence[audit_index] if self.audit_sequence else False
            self.verify_calls += 1
            output = VerificationOutput(
                verdict=self.verdict,
                rationale="The raw figure is supported; the conclusion omits age structure [E1].",
                evidence=[
                    _EvidenceLinkOut(
                        id="E1",
                        stance="supports",
                        relevance=0.9,
                        addresses_confounders=["age"],
                    )
                ],
                what_is_true=[
                    _TextWithEvidenceOut(
                        text="Registered suspects are higher in the raw comparison.",
                        evidence=["E1"],
                    )
                ],
                what_is_missing=[
                    _MissingOut(
                        text="The raw comparison does not adjust for age structure.",
                        confounder="age",
                        evidence=["E1"],
                    )
                ],
                what_is_unverifiable=[
                    _UnverifiableOut(text="The exact magnitude is not specified.", reason="other")
                ],
                argument_issues=[
                    _ArgumentIssueOut(
                        pattern="omitted_confounders",
                        explanation="The raw association is presented without age.",
                        evidence=["E1"],
                    )
                ],
                audit_complete=audit_complete,
            )
        else:
            raise AssertionError(f"unexpected alias {alias}")
        return output, LLMUsage(tokens_in=10, tokens_out=5)


class FakeEmbedder:
    """Deterministic embeddings for the relevance cut (DECISIONS.md D68).

    ``vectors`` maps an exact text to its vector; any other text gets ``default``. A test
    therefore sets the similarity of each passage to the query by choosing two vectors.
    """

    def __init__(
        self,
        vectors: dict[str, list[float]] | None = None,
        *,
        default: list[float] | None = None,
    ) -> None:
        self.vectors = dict(vectors or {})
        self.default = default or ([1.0] + [0.0] * 1023)
        self.batches: list[tuple[str, list[str]]] = []

    async def embed_many(
        self,
        texts: list[str],
        *,
        data_class: str,
        purpose: str,
        user_id: str | None = None,
    ) -> list[list[float]]:
        self.batches.append((data_class, list(texts)))
        return [self.vectors.get(text, self.default) for text in texts]


def unit_vector(similarity: float) -> list[float]:
    """A 1024-d unit vector whose cosine with ``[1, 0, ...]`` is ``similarity``."""
    return [similarity, (1.0 - similarity * similarity) ** 0.5] + [0.0] * 1022


class FakeLightRAG:
    def __init__(
        self, *, document_id: str, passage: str, second_passage: str | None = None
    ) -> None:
        self.document_id = document_id
        self.passage = passage
        self.second_passage = second_passage
        self.queries: list[str] = []
        self.query_calls: list[dict[str, Any]] = []
        self.entities: list[dict[str, Any]] = []
        self.relationships: list[dict[str, Any]] = []
        self.inserted: list[dict[str, str]] = []
        self.deleted: list[str] = []

    async def insert_text(self, *, content: str, file_source: str, title: str) -> dict[str, Any]:
        self.inserted.append({"content": content, "file_source": file_source, "title": title})
        return {"status": "ok"}

    async def wait_until_idle(self, timeout_seconds: int = 900) -> bool:
        return True

    async def delete_documents(self, doc_ids: list[str]) -> dict[str, Any]:
        self.deleted.extend(doc_ids)
        return {"status": "ok"}

    async def document_status(self) -> dict[str, Any]:
        return {
            "statuses": {
                "processed": [
                    {"id": f"doc-lightrag-{index}", "file_path": entry["file_source"]}
                    for index, entry in enumerate(self.inserted)
                ]
            }
        }

    async def wait_until_sources_absent(
        self, file_sources: list[str], *, timeout_seconds: float = 300.0
    ) -> bool:
        return True

    async def delete_by_file_source(self, file_sources: list[str]) -> int:
        wanted = set(file_sources)
        payload = await self.document_status()
        ids = [
            entry["id"]
            for entry in payload["statuses"]["processed"]
            if entry["file_path"] in wanted
        ]
        if ids:
            await self.delete_documents(ids)
        return len(ids)

    async def query_data(self, query: str, **kwargs: Any) -> RetrievalResult:
        self.queries.append(query)
        self.query_calls.append(kwargs)
        content = (
            self.passage
            if len(self.queries) == 1 or self.second_passage is None
            else self.second_passage
        )
        return RetrievalResult(
            chunks=[
                RetrievalChunk(
                    content=content,
                    file_path=f"{self.document_id}@v1",
                    chunk_id=f"chunk-{len(self.queries)}",
                    score=0.9,
                    order=len(self.queries) - 1,
                    raw={"reference_id": str(len(self.queries))},
                )
            ],
            entities=self.entities,
            relationships=self.relationships,
        )


def _input_text(messages: list[dict[str, str]]) -> str:
    content = messages[-1]["content"] if messages else ""
    start = content.find("<input>\n")
    end = content.find("\n</input>", start)
    if start < 0 or end < 0:
        raise AssertionError("fake extraction could not find the input block")
    return content[start + len("<input>\n") : end]
