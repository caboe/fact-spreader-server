"""Evidence translations are display context only (PURPOSE §3.9)."""

from __future__ import annotations

from typing import Any, TypeVar, cast

from app.pipeline.translation import TranslationItem, TranslationOutput, translate_evidence
from pydantic import BaseModel

from tests.unit.test_gate import make_evidence

T = TypeVar("T", bound=BaseModel)


class FakeTranslator:
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
    ) -> tuple[T, Any]:
        assert output_model is TranslationOutput
        return (
            cast(
                T,
                TranslationOutput(
                    translations=[
                        TranslationItem(evidence_id="E1", text="Original bleibt maßgeblich.")
                    ]
                ),
            ),
            None,
        )


async def test_german_evidence_gets_a_labelled_translation() -> None:
    evidence = make_evidence("E1")
    evidence.passage_language = "de"
    count = await translate_evidence(
        FakeTranslator(), [evidence], target_language="en", user_id=None
    )
    assert count == 1
    assert evidence.passage_translation is not None
    assert evidence.passage_translation.machine is True
    assert evidence.passage_translation.text == "Original bleibt maßgeblich."
    assert evidence.passage == "Passage for E1"
