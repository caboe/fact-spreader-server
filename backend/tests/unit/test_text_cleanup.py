"""Publisher footer removal before indexing (DECISIONS.md D67).

The footer is identical across documents; leaving it in the index made generic tails
outrank specific passages for almost every query.
"""

from __future__ import annotations

from app.services.text_cleanup import strip_publisher_footer

PARAGRAPH = (
    "Der Faktencheck selbst: das Frauenschwimmen ist zeitlich begrenzt, betrifft zwei "
    "Bäder und ist offen für alle Frauen.\n(Stand: 18.11.2026)\n"
)
BODY = PARAGRAPH * 4

GERMAN = (
    BODY + "Links\nGeprüfter Post ( archiviert )\ndpa-Faktencheck\nÜber dpa-Faktenchecks\n"
    "Dieser Faktencheck wurde im Rahmen des Facebook/Meta-Programms erstellt.\n"
    "Schon gewusst?\npowered by dpa-newslab | Imprint | Privacy | About:"
)


def test_a_german_footer_is_cut_from_the_heading_onward() -> None:
    cleaned = strip_publisher_footer(GERMAN)
    assert cleaned.startswith("Der Faktencheck selbst")
    assert "dpa-Faktencheck" in cleaned  # the source list above the footer stays
    assert "Über dpa-Faktenchecks" not in cleaned
    assert "dpa-newslab" not in cleaned


def test_the_french_and_dutch_headings_are_cut_too() -> None:
    french = BODY + "Liens\nFact-check de la dpa\nÀ propos des fact-checks de la dpa\nFin."
    dutch = BODY + "Links\nOver dpa-factchecks\nDeze factcheck is geschreven.\n"
    assert "fact-checks de la dpa" not in strip_publisher_footer(french)
    assert "Over dpa-factchecks" not in strip_publisher_footer(dutch)


def test_a_document_without_a_footer_is_returned_unchanged() -> None:
    assert strip_publisher_footer(BODY) == BODY
    assert strip_publisher_footer("") == ""


def test_a_heading_at_the_start_is_document_content_not_a_footer() -> None:
    text = "Über dpa-Faktenchecks wird hier berichtet.\n" + PARAGRAPH * 4
    assert strip_publisher_footer(text) == text
