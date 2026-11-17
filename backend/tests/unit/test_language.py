"""Language detection and the unsupported-language fallback (PURPOSE §3.9)."""

from __future__ import annotations

import pytest
from app.core.errors import AppError
from app.services.language import LanguageService


@pytest.fixture(scope="module")
def service() -> LanguageService:
    return LanguageService(["en", "de", "fr", "es"])


@pytest.mark.parametrize(
    ("text", "expected"),
    [
        ("The average weekly working hours in Germany are particularly low.", "en"),
        ("Die durchschnittliche Wochenarbeitszeit in Deutschland ist besonders niedrig.", "de"),
        ("Le temps de travail hebdomadaire moyen en Allemagne est particulièrement faible.", "fr"),
        ("La jornada laboral media en Alemania es especialmente baja.", "es"),
    ],
)
def test_detects_the_four_supported_languages(
    service: LanguageService, text: str, expected: str
) -> None:
    assert service.detect(text) == expected


def test_unsupported_input_falls_back_to_english(service: LanguageService) -> None:
    decision = service.resolve(
        "Il tempo di lavoro medio in Germania e particolarmente basso.", None
    )
    assert decision.unsupported is True
    assert decision.response == "en"


def test_explicit_unsupported_language_is_rejected(service: LanguageService) -> None:
    with pytest.raises(AppError) as exc:
        service.resolve("hello", "it")
    assert exc.value.code == "unsupported_response_language"
