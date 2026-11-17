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
