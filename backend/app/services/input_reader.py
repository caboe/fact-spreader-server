"""SSRF-guarded URL reader for check inputs (AGENTS.md invariant 14, PURPOSE §3.1).

A URL submitted for checking is subject matter, never a corpus document. The guard resolves
the host before connecting, rejects non-public addresses and private DNS answers, validates
redirect targets again, caps the body and extracts readable text without executing scripts.
"""

from __future__ import annotations

import asyncio
import ipaddress
import socket
from dataclasses import dataclass
from html.parser import HTMLParser
from io import BytesIO
from urllib.parse import urljoin, urlparse

import httpx

from app.core.config import Settings
from app.core.http import OutboundHTTP


class UrlSafetyError(ValueError):
    pass


class UrlFetchError(RuntimeError):
    pass


@dataclass(frozen=True)
class FetchedDocument:
    url: str
    text: str
    title: str | None
    content_type: str
    size_bytes: int


def validate_public_url(url: str) -> None:
    parsed = urlparse(url)
    if parsed.scheme not in {"http", "https"}:
        raise UrlSafetyError("Only http and https URLs are accepted.")
    if not parsed.hostname:
        raise UrlSafetyError("The URL has no hostname.")
    if parsed.username or parsed.password:
        raise UrlSafetyError("Credentials in a URL are not accepted.")
    host = parsed.hostname.lower()
    if host in {"localhost", "localhost.localdomain"} or host.endswith(".local"):
        raise UrlSafetyError("Local hostnames are not accepted.")
    if host in {"metadata.google.internal", "metadata.google.com"}:
        raise UrlSafetyError("Cloud metadata hosts are not accepted.")
    port = parsed.port or (443 if parsed.scheme == "https" else 80)
    addresses: list[ipaddress.IPv4Address | ipaddress.IPv6Address] = []
    try:
        literal = ipaddress.ip_address(host)
        addresses = [literal]
    except ValueError:
        try:
            infos = socket.getaddrinfo(host, port, type=socket.SOCK_STREAM)
        except socket.gaierror as exc:
            raise UrlSafetyError("The hostname could not be resolved.") from exc
        for info in infos:
            try:
                addresses.append(ipaddress.ip_address(info[4][0]))
            except ValueError:
                continue
    if not addresses:
        raise UrlSafetyError("The hostname has no IP address.")
    for address in addresses:
        if not address.is_global:
            raise UrlSafetyError("The URL resolves to a non-public address.")


async def fetch_readable(url: str, settings: Settings) -> FetchedDocument:
    await asyncio.to_thread(validate_public_url, url)
    current = url
    http = OutboundHTTP(timeout=settings.url_fetch_timeout_seconds, retries=0)
    for _ in range(4):
        try:
            response = await http.request(
                "GET",
                current,
                headers={"User-Agent": "FactSpreader/0.1 (+https://fact-spreader.org)"},
            )
        except httpx.HTTPError as exc:
            raise UrlFetchError(f"The URL could not be fetched: {type(exc).__name__}.") from exc
        if response.is_redirect:
            location = response.headers.get("Location")
            if not location:
                raise UrlFetchError("The URL redirected without a location.")
            current = urljoin(current, location)
            await asyncio.to_thread(validate_public_url, current)
            continue
        if response.status_code >= 400:
            raise UrlFetchError(f"The URL returned HTTP {response.status_code}.")
        if len(response.content) > settings.url_fetch_max_bytes:
            raise UrlFetchError("The URL response is too large.")
        content_type = response.headers.get("Content-Type", "").split(";", 1)[0].strip().lower()
        text, title = _extract(response.content, content_type)
        if not text.strip():
            raise UrlFetchError("The URL produced no readable text.")
        return FetchedDocument(
            url=current,
            text=text.strip(),
            title=title,
            content_type=content_type or "application/octet-stream",
            size_bytes=len(response.content),
        )
    raise UrlFetchError("The URL redirected too many times.")


def _extract(content: bytes, content_type: str) -> tuple[str, str | None]:
    if content_type in {"application/pdf", "application/x-pdf"}:
        return _extract_pdf(content), None
    if content_type in {"text/html", "application/xhtml+xml"} or content_type.endswith("+html"):
        return _extract_html(content)
    for encoding in ("utf-8", "utf-16", "latin-1"):
        try:
            return content.decode(encoding), None
        except UnicodeDecodeError:
            continue
    return content.decode("utf-8", errors="replace"), None


def _extract_pdf(content: bytes) -> str:
    try:
        from pypdf import PdfReader
    except ImportError as exc:  # pragma: no cover - dependency is pinned
        raise UrlFetchError("PDF support is not installed.") from exc
    try:
        reader = PdfReader(BytesIO(content))
        pages = [page.extract_text() or "" for page in reader.pages]
    except Exception as exc:
        raise UrlFetchError("The PDF could not be parsed.") from exc
    return "\n\n".join(page for page in pages if page.strip())


class _TextExtractor(HTMLParser):
    def __init__(self) -> None:
        super().__init__(convert_charrefs=True)
        self.parts: list[str] = []
        self.title_parts: list[str] = []
        self._skip_depth = 0
        self._in_title = False

    def handle_starttag(self, tag: str, attrs: list[tuple[str, str | None]]) -> None:
        lowered = tag.lower()
        if lowered in {"script", "style", "noscript", "template", "svg"}:
            self._skip_depth += 1
        elif lowered == "title":
            self._in_title = True
        elif lowered in {"p", "div", "br", "li", "tr", "h1", "h2", "h3", "h4", "section"}:
            self.parts.append("\n")

    def handle_endtag(self, tag: str) -> None:
        lowered = tag.lower()
        if lowered in {"script", "style", "noscript", "template", "svg"} and self._skip_depth:
            self._skip_depth -= 1
        elif lowered == "title":
            self._in_title = False

    def handle_data(self, data: str) -> None:
        if self._skip_depth:
            return
        cleaned = " ".join(data.split())
        if not cleaned:
            return
        if self._in_title:
            self.title_parts.append(cleaned)
        else:
            self.parts.append(cleaned)
            self.parts.append(" ")

    def text(self) -> str:
        joined = "".join(self.parts)
        lines = [" ".join(line.split()) for line in joined.splitlines()]
        return "\n".join(line for line in lines if line)


def _extract_html(content: bytes) -> tuple[str, str | None]:
    for encoding in ("utf-8", "latin-1"):
        try:
            decoded = content.decode(encoding)
            break
        except UnicodeDecodeError:
            continue
    else:
        decoded = content.decode("utf-8", errors="replace")
    parser = _TextExtractor()
    parser.feed(decoded)
    title = " ".join(" ".join(parser.title_parts).split()) or None
    return parser.text(), title
