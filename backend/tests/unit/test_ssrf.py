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


def test_a_redirect_to_a_private_address_is_rejected() -> None:
    import asyncio

    import httpx
    from app.core.config import Settings
    from app.services import input_reader

    class RedirectingHTTP:
        def __init__(self, **_kwargs: object) -> None:
            pass

        async def request(self, method: str, url: str, **_kwargs: object) -> httpx.Response:
            return httpx.Response(
                302,
                headers={"Location": "http://127.0.0.1/internal/llm/v1/chat"},
                request=httpx.Request(method, url),
            )

    original = input_reader.OutboundHTTP
    input_reader.OutboundHTTP = RedirectingHTTP  # type: ignore[assignment]
    try:
        with pytest.raises(input_reader.UrlSafetyError):
            asyncio.run(input_reader.fetch_readable("http://93.184.216.34/", Settings()))
    finally:
        input_reader.OutboundHTTP = original  # type: ignore[assignment]


def test_a_hostname_resolving_to_a_private_address_is_rejected(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    import socket

    from app.services.input_reader import UrlSafetyError, validate_public_url

    def fake_getaddrinfo(host: str, *args: object, **kwargs: object) -> list[tuple]:
        return [
            (socket.AF_INET, socket.SOCK_STREAM, 6, "", ("93.184.216.34", 0)),
            (socket.AF_INET, socket.SOCK_STREAM, 6, "", ("10.0.0.7", 0)),
        ]

    monkeypatch.setattr(socket, "getaddrinfo", fake_getaddrinfo)
    with pytest.raises(UrlSafetyError):
        validate_public_url("https://rebind.test/report")
