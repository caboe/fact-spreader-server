"""Research summaries are released only with citations and an independent judge (PROTOCOL §5.2)."""

from __future__ import annotations

from typing import Any, TypeVar

import pytest
from app.contracts.api import ResearchDocument, ResearchDocumentSummary, ResearchPassage
from app.llm.client import LLMUsage
from app.services.research import (
    ResearchService,
    _SummaryJudgeOutput,
    _SummaryOutput,
    _SummarySentence,
)
from pydantic import BaseModel

T = TypeVar("T", bound=BaseModel)


class FakeSummaryLLM:
    def __init__(self, *, judge: _SummaryJudgeOutput, citations: list[str] | None = None) -> None:
        self.judge = judge
        self.citations = citations if citations is not None else ["R1"]
        self.calls: list[str] = []

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
        self.calls.append(purpose)
        usage = LLMUsage(tokens_in=10, tokens_out=5)
        if output_model is _SummaryOutput:
            return (
                _SummaryOutput(
                    sentences=[
                        _SummarySentence(
                            text="Registered suspects are higher in the raw comparison.",
                            citations=self.citations,
                        )
                    ]
                ),
                usage,
            )
        if output_model is _SummaryJudgeOutput:
            return self.judge, usage
        raise AssertionError(f"unexpected output model {output_model}")


def make_document(*, redistribution: str = "full") -> ResearchDocument:
    return ResearchDocument(
        document=ResearchDocumentSummary(
            id="doc_1",
            title="Fixture report",
            publisher="Fixture Office",
            source_quality="A",
            language="en",
            license="CC BY 4.0",
            redistribution=redistribution,
        ),
        passages=[
            ResearchPassage(
                evidence_id="psg_1",
                passage="Registered suspects are higher in the raw comparison.",
                passage_language="en",
            )
        ],
    )


def service_with(llm: FakeSummaryLLM) -> ResearchService:
    service: Any = ResearchService(session=None, retriever=None, llm=llm)
    return service


@pytest.mark.asyncio
async def test_a_cited_summary_supported_by_the_judge_is_released() -> None:
    llm = FakeSummaryLLM(judge=_SummaryJudgeOutput(passed=True))
    summary = await service_with(llm)._summary("immigrants crime", "en", [make_document()])

    assert summary is not None
    assert summary.citations[0].evidence_ids == ["psg_1"]
    assert "judge_support" in summary.consistency.checks
    assert llm.calls == ["research_summary", "research_summary_judge"]


@pytest.mark.asyncio
async def test_a_summary_the_judge_rejects_is_withheld() -> None:
    llm = FakeSummaryLLM(judge=_SummaryJudgeOutput(passed=False, unsupported_sentences=[1]))
    with pytest.raises(ValueError, match="judge rejected"):
        await service_with(llm)._summary("immigrants crime", "en", [make_document()])


@pytest.mark.asyncio
async def test_a_summary_without_citations_is_withheld_before_the_judge() -> None:
    llm = FakeSummaryLLM(judge=_SummaryJudgeOutput(passed=True), citations=[])
    with pytest.raises(ValueError, match="uncited"):
        await service_with(llm)._summary("immigrants crime", "en", [make_document()])
    assert llm.calls == ["research_summary"]


@pytest.mark.asyncio
async def test_a_long_quotation_from_a_metadata_only_source_is_withheld() -> None:
    document = make_document(redistribution="metadata_only")
    document.passages[0].passage = "short"
    llm = FakeSummaryLLM(judge=_SummaryJudgeOutput(passed=True))
    llm.citations = ["R1"]

    async def quoted(*args: Any, **kwargs: Any) -> Any:
        return (
            _SummaryOutput(
                sentences=[
                    _SummarySentence(
                        text='The source says "' + ("word " * 60).strip() + '".',
                        citations=["R1"],
                    )
                ]
            ),
            LLMUsage(tokens_in=1, tokens_out=1),
        )

    llm.chat_structured = quoted  # type: ignore[method-assign]
    with pytest.raises(ValueError, match="metadata-only"):
        await service_with(llm)._summary("immigrants crime", "en", [document])
