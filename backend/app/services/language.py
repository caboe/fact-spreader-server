"""Language detection and response-language resolution (PURPOSE §3.9).

Lingua knows more languages than the supported set; that is required so that "unsupported"
is recognisable instead of silently treated as English.
"""

from __future__ import annotations

from dataclasses import dataclass

from lingua import Language, LanguageDetector, LanguageDetectorBuilder

from app.core.errors import AppError

_LANGUAGES = {
    Language.ENGLISH: "en",
    Language.GERMAN: "de",
    Language.FRENCH: "fr",
    Language.SPANISH: "es",
    Language.ITALIAN: "it",
    Language.PORTUGUESE: "pt",
    Language.DUTCH: "nl",
    Language.POLISH: "pl",
    Language.TURKISH: "tr",
    Language.ARABIC: "ar",
    Language.RUSSIAN: "ru",
    Language.CHINESE: "zh",
}


@dataclass(frozen=True)
class LanguageDecision:
    detected: str
    response: str
    unsupported: bool


class LanguageService:
    def __init__(self, supported: list[str], default: str = "en") -> None:
        self.supported = tuple(supported)
        self.default = default
        self._detector: LanguageDetector = (
            LanguageDetectorBuilder.from_languages(*_LANGUAGES.keys())
            .with_preloaded_language_models()
            .build()
        )

    def detect(self, text: str) -> str:
        if len(text.strip()) < 12:
            return self.default
        language = self._detector.detect_language_of(text)
        if language is None:
            return self.default
        return _LANGUAGES.get(language, self.default)

    def resolve(self, text: str, requested: str | None) -> LanguageDecision:
        detected = self.detect(text)
        if requested is not None:
            if requested not in self.supported:
                raise AppError(
                    422,
                    "unsupported_response_language",
                    f"Response language {requested!r} is not supported.",
                )
            return LanguageDecision(detected=detected, response=requested, unsupported=False)
        if detected in self.supported:
            return LanguageDecision(detected=detected, response=detected, unsupported=False)
        return LanguageDecision(detected=detected, response=self.default, unsupported=True)
