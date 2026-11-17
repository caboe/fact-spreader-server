"""SSRF guard and readable-text extraction (AGENTS.md invariant 14)."""

from __future__ import annotations

import pytest
from app.services.input_reader import (
    UrlSafetyError,
    _extract_html,
    validate_public_url,
)


@pytest.mark.parametrize(
    "url",
    [
        "http://127.0.0.1/",
        "http://10.0.0.1/",
        "http://192.168.1.1/",
        "http://169.254.169.254/latest/meta-data/",
        "http://[::1]/",
        "http://localhost/",
        "http://metadata.google.internal/",
        "file:///etc/passwd",
        "http://user:pass@example.com/",
    ],
)
def test_non_public_and_unsafe_urls_are_rejected(url: str) -> None:
    with pytest.raises(UrlSafetyError):
        validate_public_url(url)


def test_a_public_ip_literal_is_accepted() -> None:
    validate_public_url("https://93.184.216.34/")


def test_html_extraction_skips_scripts_and_keeps_title() -> None:
    html = b"""
    <html><head><title>Fixture page</title><style>body{}</style></head>
    <body><script>steal()</script><p>First paragraph.</p><p>Second &amp; last.</p></body>
    </html>
    """
    text, title = _extract_html(html)
    assert title == "Fixture page"
    assert "First paragraph." in text
    assert "Second & last." in text
    assert "steal" not in text
    assert "body{}" not in text
