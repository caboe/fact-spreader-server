"""Batch metadata sidecars map per-file metadata (IMPLEMENT Phase 4)."""

from __future__ import annotations

from app.services.batches import parse_metadata_sidecar


def test_a_csv_sidecar_maps_title_license_and_lists() -> None:
    data = (
        b"filename,title,license,authors,domain_tags,publication_date\n"
        b"report.pdf,Annual report,CC-BY-4.0,Ada;Grace,economics;poverty,2024-04-09\n"
    )
    parsed = parse_metadata_sidecar(data, "metadata.csv")
    assert parsed["report.pdf"].title == "Annual report"
    assert parsed["report.pdf"].license == "CC-BY-4.0"
    assert parsed["report.pdf"].authors == ["Ada", "Grace"]
    assert parsed["report.pdf"].domain_tags == ["economics", "poverty"]
    assert parsed["report.pdf"].publication_date.isoformat() == "2024-04-09"


def test_a_json_sidecar_maps_by_filename() -> None:
    data = b'{"report.pdf": {"title": "JSON title", "language": "de"}}'
    parsed = parse_metadata_sidecar(data, "metadata.json")
    assert parsed["report.pdf"].title == "JSON title"
    assert parsed["report.pdf"].language == "de"


def test_an_invalid_sidecar_is_ignored() -> None:
    assert parse_metadata_sidecar(b"not json or csv", "metadata.csv") == {}


async def test_retrying_an_image_document_returns_a_warning_instead_of_raising() -> None:
    """A retry that cannot parse the stored bytes must stay a per-file result, not a 500."""
    from types import SimpleNamespace

    from app.core.config import Settings
    from app.services.documents import retry_failed_document

    document = SimpleNamespace(
        title="scan.png",
        content_hash="hash",
        language="en",
        license=None,
        source_quality="D",
        state="failed",
        warnings=[],
        updated_at=None,
    )
    version = SimpleNamespace(
        raw_bytes=b"not-an-image",
        raw_media_type="image/png",
        file_path="scan.png",
        content_md="",
        content_hash="hash",
        size_bytes=0,
    )
    warning = await retry_failed_document(
        None,  # type: ignore[arg-type]
        document=document,  # type: ignore[arg-type]
        version=version,  # type: ignore[arg-type]
        settings=Settings(),
    )
    assert warning is not None
    assert warning.code == "parse_warning"
    assert "vision path" in warning.message
