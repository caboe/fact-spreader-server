"""Deterministic, translated substance prose (PURPOSE §3.13, invariant 3).

The persona writes only the narrative. These templates build the verdict label, the
overall bottom line and the refusal text in the four supported response languages.
"""

from __future__ import annotations

from app.contracts.enums import Verdict

_VERDICT_LABELS: dict[str, dict[Verdict, str]] = {
    "en": {
        Verdict.TRUE: "True",
        Verdict.TRUE_BUT_MISLEADING: "True, but misleading",
        Verdict.PARTIALLY_FALSE: "Partly false",
        Verdict.FALSE: "False",
        Verdict.CONTESTED: "Contested",
        Verdict.INSUFFICIENT_EVIDENCE: "Insufficient evidence",
        Verdict.NOT_CHECKABLE: "Not checkable",
    },
    "de": {
        Verdict.TRUE: "Richtig",
        Verdict.TRUE_BUT_MISLEADING: "Richtig, aber irreführend",
        Verdict.PARTIALLY_FALSE: "Teilweise falsch",
        Verdict.FALSE: "Falsch",
        Verdict.CONTESTED: "Umstritten",
        Verdict.INSUFFICIENT_EVIDENCE: "Nicht ausreichend belegt",
        Verdict.NOT_CHECKABLE: "Nicht überprüfbar",
    },
    "fr": {
        Verdict.TRUE: "Vrai",
        Verdict.TRUE_BUT_MISLEADING: "Vrai, mais trompeur",
        Verdict.PARTIALLY_FALSE: "Partiellement faux",
        Verdict.FALSE: "Faux",
        Verdict.CONTESTED: "Contesté",
        Verdict.INSUFFICIENT_EVIDENCE: "Preuves insuffisantes",
        Verdict.NOT_CHECKABLE: "Non vérifiable",
    },
    "es": {
        Verdict.TRUE: "Verdadero",
        Verdict.TRUE_BUT_MISLEADING: "Verdadero, pero engañoso",
        Verdict.PARTIALLY_FALSE: "Parcialmente falso",
        Verdict.FALSE: "Falso",
        Verdict.CONTESTED: "En disputa",
        Verdict.INSUFFICIENT_EVIDENCE: "Pruebas insuficientes",
        Verdict.NOT_CHECKABLE: "No verificable",
    },
}

_OVERALL: dict[str, dict[Verdict, str]] = {
    "en": {
        Verdict.TRUE: "The approved corpus supports the claim as stated.",
        Verdict.TRUE_BUT_MISLEADING: "The core is supported, but essential context is missing.",
        Verdict.PARTIALLY_FALSE: "Some material parts are supported; others are not.",
        Verdict.FALSE: "The approved corpus contradicts the claim.",
        Verdict.CONTESTED: "Approved sources contradict each other on this claim.",
        Verdict.INSUFFICIENT_EVIDENCE: "The approved corpus does not settle this claim.",
        Verdict.NOT_CHECKABLE: "The input contains no checkable factual statement.",
    },
    "de": {
        Verdict.TRUE: "Der freigegebene Korpus stützt die Aussage so, wie sie formuliert ist.",
        Verdict.TRUE_BUT_MISLEADING: "Der Kern ist belegt, aber wesentlicher Kontext fehlt.",
        Verdict.PARTIALLY_FALSE: "Einige wesentliche Teile sind belegt, andere nicht.",
        Verdict.FALSE: "Der freigegebene Korpus widerspricht der Aussage.",
        Verdict.CONTESTED: "Freigegebene Quellen widersprechen sich bei dieser Aussage.",
        Verdict.INSUFFICIENT_EVIDENCE: "Der freigegebene Korpus entscheidet die Aussage nicht.",
        Verdict.NOT_CHECKABLE: "Die Eingabe enthält keine prüfbare Tatsachenbehauptung.",
    },
    "fr": {
        Verdict.TRUE: "Le corpus approuvé soutient l'affirmation telle qu'elle est formulée.",
        Verdict.TRUE_BUT_MISLEADING: "Le fond est étayé, mais un contexte essentiel manque.",
        Verdict.PARTIALLY_FALSE: "Certaines parties essentielles sont étayées, d'autres non.",
        Verdict.FALSE: "Le corpus approuvé contredit l'affirmation.",
        Verdict.CONTESTED: "Des sources approuvées se contredisent sur cette affirmation.",
        Verdict.INSUFFICIENT_EVIDENCE: "Le corpus approuvé ne tranche pas cette affirmation.",
        Verdict.NOT_CHECKABLE: "L'entrée ne contient aucune affirmation factuelle vérifiable.",
    },
    "es": {
        Verdict.TRUE: "El corpus aprobado respalda la afirmación tal como está formulada.",
        Verdict.TRUE_BUT_MISLEADING: "El núcleo está respaldado, pero falta contexto esencial.",
        Verdict.PARTIALLY_FALSE: "Algunas partes esenciales están respaldadas y otras no.",
        Verdict.FALSE: "El corpus aprobado contradice la afirmación.",
        Verdict.CONTESTED: "Fuentes aprobadas se contradicen sobre esta afirmación.",
        Verdict.INSUFFICIENT_EVIDENCE: "El corpus aprobado no resuelve esta afirmación.",
        Verdict.NOT_CHECKABLE: "La entrada no contiene ninguna afirmación fáctica verificable.",
    },
}

_REFUSAL: dict[str, str] = {
    "en": "This input cannot be checked because it contains sexual content involving minors.",
    "de": (
        "Diese Eingabe kann nicht geprüft werden, weil sie sexuelle Inhalte "
        "mit Minderjährigen enthält."
    ),
    "fr": (
        "Cette entrée ne peut pas être vérifiée car elle contient du contenu sexuel "
        "impliquant des mineurs."
    ),
    "es": "Esta entrada no se puede verificar porque contiene contenido sexual con menores.",
}

_UNSUPPORTED_NOTICE: dict[str, str] = {
    "en": "The input language is not supported; the report is in English.",
    "de": "Die Sprache der Eingabe wird nicht unterstützt; der Bericht ist auf Englisch.",
    "fr": "La langue de l'entrée n'est pas prise en charge ; le rapport est en anglais.",
    "es": "El idioma de la entrada no es compatible; el informe está en inglés.",
}

_CONFOUNDER_LABELS: dict[str, dict[str, str]] = {
    "en": {
        "age": "Age structure",
        "sex": "Sex ratio",
        "ses": "Socioeconomic status",
        "reporting": "Reporting behaviour",
        "urbanisation": "Urbanisation",
        "suspects_vs_convictions": "Suspects vs. convictions",
        "part_time_share": "Part-time share",
        "participation": "Labour-force participation",
        "household_vs_individual": "Household vs. individual perspective",
        "annual_vs_weekly": "Annual vs. weekly hours",
    },
    "de": {
        "age": "Altersstruktur",
        "sex": "Geschlechterverteilung",
        "ses": "Sozioökonomischer Status",
        "reporting": "Anzeigeverhalten",
        "urbanisation": "Stadt-Land-Verteilung",
        "suspects_vs_convictions": "Tatverdächtige statt Verurteilte",
        "part_time_share": "Teilzeitquote",
        "participation": "Erwerbsbeteiligung",
        "household_vs_individual": "Haushalts- statt Personenperspektive",
        "annual_vs_weekly": "Jahres- statt Wochenarbeitszeit",
    },
}


def verdict_label(verdict: Verdict, language: str) -> str:
    return _VERDICT_LABELS.get(language, _VERDICT_LABELS["en"]).get(
        verdict, verdict.value.replace("_", " ")
    )


def overall_explanation(verdict: Verdict, language: str) -> str:
    return _OVERALL.get(language, _OVERALL["en"]).get(verdict, verdict.value)


def refusal_text(language: str) -> str:
    return _REFUSAL.get(language, _REFUSAL["en"])


def unsupported_language_notice(language: str) -> str:
    return _UNSUPPORTED_NOTICE.get(language, _UNSUPPORTED_NOTICE["en"])


def confounder_label(confounder: str, language: str) -> str:
    labels = _CONFOUNDER_LABELS.get(language, _CONFOUNDER_LABELS["en"])
    return labels.get(
        confounder,
        _CONFOUNDER_LABELS["en"].get(confounder, confounder.replace("_", " ")),
    )


_FALLBACK_HEADINGS: dict[str, dict[str, str]] = {
    "en": {
        "true": "What is true",
        "missing": "What is missing",
        "unverifiable": "What is not verifiable",
        "evidence": "Evidence",
    },
    "de": {
        "true": "Was stimmt",
        "missing": "Was fehlt",
        "unverifiable": "Was nicht überprüfbar ist",
        "evidence": "Belege",
    },
    "fr": {
        "true": "Ce qui est vrai",
        "missing": "Ce qui manque",
        "unverifiable": "Ce qui n'est pas vérifiable",
        "evidence": "Preuves",
    },
    "es": {
        "true": "Lo que es cierto",
        "missing": "Lo que falta",
        "unverifiable": "Lo que no se puede verificar",
        "evidence": "Pruebas",
    },
}


def fallback_heading(key: str, language: str) -> str:
    return _FALLBACK_HEADINGS.get(language, _FALLBACK_HEADINGS["en"]).get(
        key, _FALLBACK_HEADINGS["en"][key]
    )


_FALLBACK_WARNINGS: dict[str, dict[str, str]] = {
    "en": {
        "consistency_fallback": ("The persona narrative was replaced by the deterministic report."),
        "output_moderation_replaced": ("Output moderation replaced the persona narrative."),
    },
    "de": {
        "consistency_fallback": (
            "Die Persona-Erzählung wurde durch den deterministischen Bericht ersetzt."
        ),
        "output_moderation_replaced": ("Die Ausgabemoderation hat die Persona-Erzählung ersetzt."),
    },
    "fr": {
        "consistency_fallback": (
            "Le récit de la persona a été remplacé par le rapport déterministe."
        ),
        "output_moderation_replaced": (
            "La modération de la sortie a remplacé le récit de la persona."
        ),
    },
    "es": {
        "consistency_fallback": (
            "La narración de la persona se sustituyó por el informe determinista."
        ),
        "output_moderation_replaced": (
            "La moderación de la salida sustituyó la narración de la persona."
        ),
    },
}


def fallback_warning(key: str, language: str) -> str:
    return _FALLBACK_WARNINGS.get(language, _FALLBACK_WARNINGS["en"]).get(
        key, _FALLBACK_WARNINGS["en"].get(key, key)
    )


_NO_MATCHING_RATIONALE: dict[str, str] = {
    "en": "No approved passage matched this statement.",
    "de": "Kein freigegebener Beleg passt zu dieser Aussage.",
    "fr": "Aucun passage approuvé ne correspond à cette affirmation.",
    "es": "Ningún pasaje aprobado coincide con esta afirmación.",
}

_GATE_FALLBACK: dict[str, str] = {
    "en": "A source was found, but it did not meet the evidence gate.",
    "de": "Es wurde eine Quelle gefunden, aber sie erfüllt die Evidenzanforderung nicht.",
    "fr": "Une source a été trouvée, mais elle ne satisfait pas au seuil de preuve.",
    "es": "Se encontró una fuente, pero no cumple el umbral de evidencia.",
}


def no_matching_rationale(language: str) -> str:
    return _NO_MATCHING_RATIONALE.get(language, _NO_MATCHING_RATIONALE["en"])


def gate_fallback_text(language: str) -> str:
    return _GATE_FALLBACK.get(language, _GATE_FALLBACK["en"])
