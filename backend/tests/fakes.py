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
    ) -> None:
        self.block = block
        self.unavailable = unavailable
        self.narratives = list(narratives or ["The raw figure is supported [E1]."])
        self.judge_issues = list(judge_issues or [])
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
            output = VerificationOutput(
                verdict="true_but_misleading",
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
                audit_complete=False,
            )
        else:
            raise AssertionError(f"unexpected alias {alias}")
        return output, LLMUsage(tokens_in=10, tokens_out=5)


class FakeLightRAG:
    def __init__(self, *, document_id: str, passage: str) -> None:
        self.document_id = document_id
        self.passage = passage
        self.queries: list[str] = []

    async def query_data(self, query: str, **kwargs: Any) -> RetrievalResult:
        self.queries.append(query)
        return RetrievalResult(
            chunks=[
                RetrievalChunk(
                    content=self.passage,
                    file_path=f"{self.document_id}@v1",
                    chunk_id="chunk-1",
                    score=0.9,
                    order=0,
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
