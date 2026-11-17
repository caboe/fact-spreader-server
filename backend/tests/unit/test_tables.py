"""HTML tables become Markdown in the shared reader (IMPLEMENT Phase 4)."""

from __future__ import annotations

from app.core.config import Settings
from app.services.input_reader import read_file_bytes


def test_an_html_table_becomes_a_markdown_table() -> None:
    html = (
        b"<html><head><title>Table page</title></head><body>"
        b"<p>Introduction.</p>"
        b"<table><tr><th>Year</th><th>Rate</th></tr>"
        b"<tr><td>2024</td><td>5,200</td></tr></table></body></html>"
    )
    text, title = read_file_bytes(
        filename="table.html", content_type="text/html", data=html, settings=Settings()
    )
    assert title == "Table page"
    assert "Introduction." in text
    assert "| Year | Rate |" in text
    assert "| --- | --- |" in text
    assert "| 2024 | 5,200 |" in text
