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
    ) -> None:
        self.block = block
        self.unavailable = unavailable
        self.narratives = list(narratives or ["The raw figure is supported [E1]."])
        self.judge_issues = list(judge_issues or [])
        self.audit_sequence = list(audit_sequence or [])
        self.verdict = verdict
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


class FakeLightRAG:
    def __init__(
        self, *, document_id: str, passage: str, second_passage: str | None = None
    ) -> None:
        self.document_id = document_id
        self.passage = passage
        self.second_passage = second_passage
        self.queries: list[str] = []
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

    async def query_data(self, query: str, **kwargs: Any) -> RetrievalResult:
        self.queries.append(query)
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
                )
            ]
        )


def _input_text(messages: list[dict[str, str]]) -> str:
    content = messages[-1]["content"] if messages else ""
    start = content.find("<input>\n")
    end = content.find("\n</input>", start)
    if start < 0 or end < 0:
        raise AssertionError("fake extraction could not find the input block")
    return content[start + len("<input>\n") : end]
