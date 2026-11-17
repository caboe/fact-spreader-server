"""Upload hardening: magic bytes, ZIP traversal, symlinks and bombs (IMPLEMENT Phase 9)."""

from __future__ import annotations

import io
import zipfile

import pytest
from app.core.config import Settings
from app.services.batches import sanitise_zip
from app.services.input_reader import UrlFetchError, read_file_bytes


def _zip(entries: list[tuple[str, bytes, int | None]]) -> bytes:
    buffer = io.BytesIO()
    with zipfile.ZipFile(buffer, "w", compression=zipfile.ZIP_DEFLATED) as archive:
        for name, data, mode in entries:
            info = zipfile.ZipInfo(name)
            info.compress_type = zipfile.ZIP_DEFLATED
            if mode is not None:
                info.external_attr = mode << 16
            archive.writestr(info, data)
    return buffer.getvalue()


def test_zip_traversal_absolute_paths_and_symlinks_are_skipped() -> None:
    payload = _zip(
        [
            ("report.md", b"# safe", None),
            ("../escape.md", b"# escape", None),
            ("/absolute.md", b"# absolute", None),
            ("link.md", b"/etc/passwd", 0o120777),
        ]
    )
    files, warnings = sanitise_zip(payload, Settings(upload_max_bytes=10_000))
    assert [name for name, _data, _media in files] == ["report.md"]
    assert any("unsafe path" in warning for warning in warnings)
    assert any("symlink" in warning for warning in warnings)


def test_a_zip_bomb_entry_is_skipped_by_its_uncompressed_size() -> None:
    bomb = b"0" * 5_000_000
    payload = _zip([("bomb.bin", bomb, None), ("ok.md", b"# ok", None)])
    files, warnings = sanitise_zip(payload, Settings(upload_max_bytes=10_000))
    assert [name for name, _data, _media in files] == ["ok.md"]
    assert any("oversized" in warning for warning in warnings)


def test_a_png_renamed_as_markdown_is_not_decoded_as_text() -> None:
    png = b"\x89PNG\r\n\x1a\n" + b"0" * 32
    with pytest.raises(UrlFetchError, match="vision path"):
        read_file_bytes(
            filename="notes.md",
            content_type="text/markdown",
            data=png,
            settings=Settings(),
        )


def test_a_pdf_with_a_wrong_extension_is_parsed_by_its_magic_bytes() -> None:
    from pypdf import PdfWriter

    buffer = io.BytesIO()
    writer = PdfWriter()
    writer.add_blank_page(width=200, height=200)
    writer.write(buffer)
    text, title = read_file_bytes(
        filename="report.md",
        content_type="text/markdown",
        data=buffer.getvalue(),
        settings=Settings(),
    )
    assert text == ""
    assert title is None


def test_normal_markdown_still_reads() -> None:
    text, title = read_file_bytes(
        filename="report.md",
        content_type="text/markdown",
        data=b"# Heading\n\nBody",
        settings=Settings(),
    )
    assert text.startswith("# Heading")
    assert title is None
