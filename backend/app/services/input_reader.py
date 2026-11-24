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
    raw_bytes: bytes | None = None


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
        effective_type = sniff_media_type(response.content, content_type)
        text, title = _extract(response.content, effective_type)
        if not text.strip():
            raise UrlFetchError("The URL produced no readable text.")
        return FetchedDocument(
            url=current,
            text=text.strip(),
            title=title,
            content_type=effective_type,
            size_bytes=len(response.content),
            raw_bytes=response.content,
        )
    raise UrlFetchError("The URL redirected too many times.")


def _normalise_media_type(value: str | None) -> str:
    return (value or "").split(";", 1)[0].strip().lower()


def _image_media_type(data: bytes) -> str | None:
    if data.startswith(b"\x89PNG\r\n\x1a\n"):
        return "image/png"
    if data.startswith(b"\xff\xd8\xff"):
        return "image/jpeg"
    if data.startswith((b"GIF87a", b"GIF89a")):
        return "image/gif"
    if len(data) >= 12 and data[:4] == b"RIFF" and data[8:12] == b"WEBP":
        return "image/webp"
    return None


def _looks_like_pdf(data: bytes) -> bool:
    # The PDF header may follow a byte-order mark or a small amount of junk.
    return b"%PDF-" in data[:1024]


def _looks_like_html(data: bytes) -> bool:
    head = data[:1024].lstrip(b"\xef\xbb\xbf\x00\t\n\r ")
    lowered = head.lower()
    return (
        lowered.startswith((b"<!doctype html", b"<html", b"<head", b"<body", b"<article", b"<main"))
        or b"<html" in lowered
    )


def sniff_media_type(data: bytes, declared: str | None = None) -> str:
    """Return the effective media type, preferring content signatures over headers.

    Servers routinely serve PDFs as ``application/octet-stream`` or HTML as
    ``text/plain``. Trusting the header there sends binary data through the text decoder
    and stores binary garbage as document content. Magic bytes are cheap and decisive for
    the formats this reader supports; the declared type remains the fallback.
    """
    normalized = _normalise_media_type(declared)
    if _looks_like_pdf(data):
        return "application/pdf"
    image = _image_media_type(data)
    if image is not None:
        return image
    if _looks_like_html(data):
        return "text/html"
    if normalized == "application/xhtml+xml":
        return "text/html"
    return normalized or "application/octet-stream"


def read_file_bytes(
    *, filename: str, content_type: str, data: bytes, settings: Settings
) -> tuple[str, str | None]:
    """Parse an uploaded check file. The file is subject matter, never a corpus document."""
    if len(data) > settings.upload_max_bytes:
        raise UrlFetchError("The uploaded file is too large.")
    media = _normalise_media_type(content_type)
    effective = sniff_media_type(data, media)
    suffix = filename.rsplit(".", 1)[-1].lower() if "." in filename else ""
    # Magic bytes win over a user-supplied name or content type.
    if effective.startswith("image/") or media.startswith("image/"):
        raise UrlFetchError("Image uploads need the vision path, which is not wired yet.")
    if suffix in {"png", "jpg", "jpeg", "webp", "gif"}:
        raise UrlFetchError("Image uploads need the vision path, which is not wired yet.")
    if effective == "application/pdf":
        return _extract_pdf(data), None
    if effective == "text/html":
        return _extract_html(data)
    if media in {"application/pdf", "application/x-pdf"} or suffix == "pdf":
        return _extract_pdf(data), None
    if suffix in {"html", "htm"}:
        return _extract_html(data)
    if (
        media in {"application/vnd.openxmlformats-officedocument.wordprocessingml.document"}
        or suffix == "docx"
    ):
        return _extract_docx(data), None
    for encoding in ("utf-8", "utf-16", "latin-1"):
        try:
            return data.decode(encoding), None
        except UnicodeDecodeError:
            continue
    return data.decode("utf-8", errors="replace"), None


def _extract_docx(content: bytes) -> str:
    try:
        from docx import Document as DocxDocument
    except ImportError as exc:  # pragma: no cover - dependency is pinned
        raise UrlFetchError("DOCX support is not installed.") from exc
    try:
        document = DocxDocument(BytesIO(content))
    except Exception as exc:
        raise UrlFetchError("The DOCX could not be parsed.") from exc
    blocks = [paragraph.text for paragraph in document.paragraphs if paragraph.text.strip()]
    for table in document.tables:
        for row in table.rows:
            blocks.append(" | ".join(cell.text.strip() for cell in row.cells))
    return "\n\n".join(blocks)


def _extract(content: bytes, content_type: str) -> tuple[str, str | None]:
    effective = sniff_media_type(content, content_type)
    if effective == "application/pdf":
        return _extract_pdf(content), None
    if effective == "text/html" or effective.endswith("+html"):
        return _extract_html(content)
    if effective.startswith("image/"):
        raise UrlFetchError("The URL points to an image, which is not supported.")
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


def _markdown_table(rows: list[list[str]]) -> str | None:
    cleaned = [
        [" ".join(cell.split()).replace("|", "\\|") for cell in row]
        for row in rows
        if any(cell.strip() for cell in row)
    ]
    if not cleaned:
        return None
    width = max(len(row) for row in cleaned)
    padded = [row + [""] * (width - len(row)) for row in cleaned]
    lines = ["| " + " | ".join(padded[0]) + " |"]
    lines.append("| " + " | ".join(["---"] * width) + " |")
    for row in padded[1:]:
        lines.append("| " + " | ".join(row) + " |")
    return "\n".join(lines)


def _html_tables(decoded: str) -> tuple[str, list[str]]:
    """Replace HTML tables with Markdown blocks and return the remaining HTML."""
    try:
        from lxml import etree  # type: ignore[import-untyped]
        from lxml import html as lxml_html
    except ImportError:  # pragma: no cover - pinned dependency
        return decoded, []
    try:
        tree = lxml_html.fromstring(decoded)
    except (ValueError, etree.ParserError):
        return decoded, []
    tables: list[str] = []
    for table in tree.xpath("//table"):
        rows: list[list[str]] = []
        for row in table.xpath(".//tr"):
            cells = row.xpath("./th|./td")
            if cells:
                rows.append([cell.text_content() for cell in cells])
        markdown = _markdown_table(rows)
        if markdown:
            tables.append(markdown)
        parent = table.getparent()
        if parent is not None:
            parent.remove(table)
    return etree.tostring(tree, encoding="unicode", method="html"), tables


def _extract_html(content: bytes) -> tuple[str, str | None]:
    for encoding in ("utf-8", "latin-1"):
        try:
            decoded = content.decode(encoding)
            break
        except UnicodeDecodeError:
            continue
    else:
        decoded = content.decode("utf-8", errors="replace")
    cleaned, tables = _html_tables(decoded)
    parser = _TextExtractor()
    parser.feed(cleaned)
    title = " ".join(" ".join(parser.title_parts).split()) or None
    text = parser.text()
    if tables:
        text += "\n\n" + "\n\n".join(tables)
    return text, title
