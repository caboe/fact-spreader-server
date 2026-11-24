# SPDX-License-Identifier: AGPL-3.0-or-later
"""Synthetic extraction benchmarks for URL PDFs, HTML pages and scanned PDFs.

This is a development measurement, not part of the regular test suite. It generates its
fixtures locally so the numbers are reproducible and no publisher content is copied. The
optional candidate dependencies are intentionally kept out of the application lockfile:

    mkdir -p .local/bench-deps
    python3 -m pip install --target .local/bench-deps \
        reportlab trafilatura rapidocr_onnxruntime pypdfium2 pillow numpy
    PYTHONPATH="$PWD/.local/bench-deps:$PWD/backend" \
        backend/.venv/bin/python tests/eval/extraction/benchmark.py

The baseline uses the application's current extractors. Candidates are only measured; the
script never writes to the application's database or calls a model.
"""

from __future__ import annotations

import argparse
import asyncio
import importlib
import json
import re
import statistics
import sys
import tempfile
import time
from pathlib import Path
from typing import Any

ROOT = Path(__file__).resolve().parents[3]
sys.path.insert(0, str(ROOT / "backend"))

from app.core.config import Settings  # noqa: E402
from app.services import documents as documents_service  # noqa: E402
from app.services.image_input import ImageExtraction  # noqa: E402
from app.services.input_reader import (  # noqa: E402
    UrlFetchError,
    _extract,
    _extract_html,
    read_file_bytes,
)

HTML_ARTICLE = """<!doctype html>
<html><head><title>Housing report</title>
<meta name="author" content="Fixture Desk">
<meta property="article:published_time" content="2025-06-01">
<script>window.tracker = 'not content';</script>
</head><body>
<header><nav>Home | Politics | About</nav></header>
<div class="cookie-banner">We use cookies. Accept all.</div>
<main><article>
<h1>Rents rose sharply</h1>
<p>Rents rose by 4 percent in 2025.</p>
<h2>Regional detail</h2>
<ul><li>Berlin: 5 percent</li><li>Munich: 3 percent</li></ul>
<table><tr><th>City</th><th>Change</th></tr>
<tr><td>Berlin</td><td>5%</td></tr><tr><td>Munich</td><td>3%</td></tr></table>
</article></main>
<footer>Subscribe to our newsletter. Imprint.</footer>
</body></html>"""

HTML_JS_SHELL = """<!doctype html><html><head><title>Loading</title></head>
<body><div id="root"></div><script src="/app.js"></script></body></html>"""

EXPECTED_ARTICLE = [
    "Rents rose by 4 percent in 2025.",
    "Berlin: 5 percent",
    "Munich: 3 percent",
]
EXPECTED_TABLE = ["City", "Change", "Berlin", "5%", "Munich", "3%"]
EXPECTED_BOILERPLATE = ["Home", "Politics", "About", "We use cookies", "Subscribe", "Imprint"]
EXPECTED_OCR = [
    "SCANNED HOUSING REPORT",
    "Rents rose by 4 percent in 2025.",
    "Berlin: 5 percent",
]


def _optional(name: str) -> Any | None:
    try:
        return importlib.import_module(name)
    except ImportError:
        return None


def _contains(text: str, needle: str) -> bool:
    return needle.casefold() in text.casefold()


def _coverage(text: str, needles: list[str]) -> float:
    if not needles:
        return 0.0
    return sum(_contains(text, needle) for needle in needles) / len(needles)


def _compact(text: str) -> str:
    return re.sub(r"[^a-z0-9%]", "", text.casefold())


def _compact_coverage(text: str, needles: list[str]) -> float:
    if not needles:
        return 0.0
    actual = _compact(text)
    return sum(_compact(needle) in actual for needle in needles) / len(needles)


def _heading_count(text: str) -> int:
    return len(re.findall(r"(?m)^#{1,6}\s+\S", text))


def _list_count(text: str) -> int:
    return len(re.findall(r"(?m)^\s*[-*+]\s+\S", text))


def _levenshtein(left: str, right: str) -> int:
    previous = list(range(len(right) + 1))
    for row, left_char in enumerate(left, start=1):
        current = [row]
        for column, right_char in enumerate(right, start=1):
            current.append(
                min(
                    current[-1] + 1,
                    previous[column] + 1,
                    previous[column - 1] + (left_char != right_char),
                )
            )
        previous = current
    return previous[-1]


def _normalise_for_cer(text: str) -> str:
    return " ".join(re.sub(r"[^a-z0-9% ]", " ", text.casefold()).split())


def _cer(expected: str, actual: str) -> float:
    expected = _normalise_for_cer(expected)
    actual = _normalise_for_cer(actual)
    if not expected:
        return 0.0
    return _levenshtein(expected, actual) / len(expected)


def _timed(function: Any) -> tuple[Any, float]:
    started = time.perf_counter()
    value = function()
    return value, round((time.perf_counter() - started) * 1000, 2)


def _timed_median(function: Any, iterations: int) -> tuple[Any, float]:
    """Warm the imports up once, then report the median of several runs."""
    function()
    times: list[float] = []
    value: Any = None
    for _ in range(iterations):
        started = time.perf_counter()
        value = function()
        times.append((time.perf_counter() - started) * 1000)
    return value, round(statistics.median(times), 2)


def _build_table_pdf(path: Path) -> None:
    from reportlab.lib import colors
    from reportlab.lib.pagesizes import A4
    from reportlab.lib.styles import getSampleStyleSheet
    from reportlab.platypus import Paragraph, SimpleDocTemplate, Spacer, Table, TableStyle

    doc = SimpleDocTemplate(str(path), pagesize=A4)
    style = getSampleStyleSheet()["BodyText"]
    table = Table(
        [["City", "Change"], ["Berlin", "5%"], ["Munich", "3%"]],
        colWidths=[120, 120],
    )
    table.setStyle(
        TableStyle(
            [
                ("GRID", (0, 0), (-1, -1), 1, colors.black),
                ("BACKGROUND", (0, 0), (-1, 0), colors.lightgrey),
            ]
        )
    )
    doc.build(
        [
            Paragraph("Regional rent report", style),
            Spacer(1, 12),
            table,
            Spacer(1, 12),
            Paragraph("Rents rose by 4 percent in 2025.", style),
        ]
    )


def _build_figure_pdf(path: Path) -> None:
    from PIL import Image, ImageDraw, ImageFont

    image = Image.new("RGB", (960, 560), "white")
    draw = ImageDraw.Draw(image)
    try:
        font = ImageFont.truetype("/System/Library/Fonts/Supplemental/Arial.ttf", 34)
    except OSError:
        font = ImageFont.load_default()
    draw.text((60, 40), "Registered suspects by age", font=font, fill="black")
    for index, height in enumerate((120, 220, 300, 180)):
        x = 100 + index * 150
        draw.rectangle((x, 460 - height, x + 90, 460), fill="#248f8a")
        draw.text((x + 15, 475), f"{index + 1}", font=font, fill="black")
    image.save(path, "PDF", resolution=144)


def _build_scan_pdf(path: Path) -> None:
    from PIL import Image, ImageDraw, ImageFont

    image = Image.new("RGB", (1400, 900), "white")
    draw = ImageDraw.Draw(image)
    font_paths = (
        "/System/Library/Fonts/Supplemental/Arial.ttf",
        "/System/Library/Fonts/Helvetica.ttc",
        "/Library/Fonts/Arial.ttf",
    )
    font = None
    for candidate in font_paths:
        if Path(candidate).exists():
            font = ImageFont.truetype(candidate, 42)
            break
    if font is None:
        font = ImageFont.load_default()
    draw.text((80, 100), "SCANNED HOUSING REPORT", font=font, fill="black")
    draw.text((80, 210), "Rents rose by 4 percent in 2025.", font=font, fill="black")
    draw.text((80, 300), "Berlin: 5 percent", font=font, fill="black")
    image.save(path, "PDF", resolution=150)


def _step2(table_pdf: Path, figure_pdf: Path) -> dict[str, Any]:
    settings = Settings()
    table_bytes = table_pdf.read_bytes()
    figure_bytes = figure_pdf.read_bytes()

    async def fake_vision(_llm: Any, _prepared: Any, *, user_id: str | None) -> ImageExtraction:
        return ImageExtraction(
            text="Chart labels: age groups 1 to 4",
            description="A bar chart of registered suspects by age group.",
        )

    original_vision = documents_service.extract_image_text
    documents_service.extract_image_text = fake_vision
    try:

        def candidate(data: bytes) -> tuple[str, int, int]:
            text, _title = read_file_bytes(
                filename="fixture.pdf",
                content_type="application/pdf",
                data=data,
                settings=settings,
            )
            tables, figures, sections, _pages = asyncio.run(
                documents_service.parse_pdf_assets(data, settings=settings, user_id=None)
            )
            return (
                "\n\n".join(part for part in [text, tables, *sections] if part.strip()),
                len(figures),
                1 if tables.strip() else 0,
            )

        iterations = 5
        table_baseline, table_baseline_ms = _timed_median(
            lambda: _extract(table_bytes, "application/pdf")[0], iterations
        )
        (table_candidate, table_figures, table_tables), table_candidate_ms = _timed_median(
            lambda: candidate(table_bytes), iterations
        )
        figure_baseline, figure_baseline_ms = _timed_median(
            lambda: _extract(figure_bytes, "application/pdf")[0], iterations
        )
        (figure_candidate, figure_figures, figure_tables), figure_candidate_ms = _timed_median(
            lambda: candidate(figure_bytes), iterations
        )
    finally:
        documents_service.extract_image_text = original_vision

    return {
        "iterations": 5,
        "table_pdf": {
            "baseline": {
                "chars": len(table_baseline),
                "table_markdown": "| City | Change |" in table_baseline,
                "table_coverage": _coverage(table_baseline, EXPECTED_TABLE),
                "runtime_ms": table_baseline_ms,
            },
            "candidate": {
                "chars": len(table_candidate),
                "table_markdown": "| City | Change |" in table_candidate,
                "table_coverage": _coverage(table_candidate, EXPECTED_TABLE),
                "tables": table_tables,
                "figures": table_figures,
                "runtime_ms": table_candidate_ms,
            },
        },
        "figure_pdf": {
            "baseline": {
                "chars": len(figure_baseline),
                "succeeds": bool(figure_baseline.strip()),
                "runtime_ms": figure_baseline_ms,
            },
            "candidate": {
                "chars": len(figure_candidate),
                "succeeds": bool(figure_candidate.strip()),
                "figures": figure_figures,
                "tables": figure_tables,
                "runtime_ms": figure_candidate_ms,
            },
        },
    }


def _step3() -> dict[str, Any]:
    baseline_text, baseline_title = _extract_html(HTML_ARTICLE.encode("utf-8"))
    baseline_text, baseline_ms = _timed_median(
        lambda: _extract_html(HTML_ARTICLE.encode("utf-8"))[0], 5
    )
    trafilatura = _optional("trafilatura")

    static: dict[str, Any] = {
        "baseline": {
            "chars": len(baseline_text),
            "article_coverage": _coverage(baseline_text, EXPECTED_ARTICLE),
            "table_coverage": _coverage(baseline_text, EXPECTED_TABLE),
            "table_markdown": "| City |" in baseline_text,
            "boilerplate_hits": sum(
                _contains(baseline_text, item) for item in EXPECTED_BOILERPLATE
            ),
            "headings": _heading_count(baseline_text),
            "list_items": _list_count(baseline_text),
            "title": baseline_title,
            "author": None,
            "date": None,
            "runtime_ms": baseline_ms,
        }
    }
    if trafilatura is not None:

        def extract_candidate() -> str:
            return (
                trafilatura.extract(
                    HTML_ARTICLE,
                    output_format="markdown",
                    include_tables=True,
                    include_links=False,
                    include_images=False,
                    url="https://example.org/article",
                )
                or ""
            )

        candidate_text, candidate_ms = _timed_median(extract_candidate, 5)
        metadata = trafilatura.extract_metadata(HTML_ARTICLE)
        static["trafilatura"] = {
            "chars": len(candidate_text),
            "article_coverage": _coverage(candidate_text, EXPECTED_ARTICLE),
            "table_coverage": _coverage(candidate_text, EXPECTED_TABLE),
            "table_markdown": "| City |" in candidate_text,
            "boilerplate_hits": sum(
                _contains(candidate_text, item) for item in EXPECTED_BOILERPLATE
            ),
            "headings": _heading_count(candidate_text),
            "list_items": _list_count(candidate_text),
            "title": getattr(metadata, "title", None),
            "author": getattr(metadata, "author", None),
            "date": getattr(metadata, "date", None),
            "runtime_ms": candidate_ms,
        }
    else:
        static["trafilatura"] = {"skipped": "trafilatura is not installed"}

    js_text, _js_title = _extract_html(HTML_JS_SHELL.encode("utf-8"))
    js_candidate = ""
    if trafilatura is not None:
        js_candidate = (
            trafilatura.extract(
                HTML_JS_SHELL,
                output_format="markdown",
                include_tables=True,
                include_links=False,
                include_images=False,
                url="https://example.org/app",
            )
            or ""
        )
    return {
        "iterations": 5,
        "static_article": static,
        "js_shell": {
            "baseline_chars": len(js_text),
            "trafilatura_chars": len(js_candidate),
            "note": (
                "Both static extractors return no article text; "
                "JavaScript rendering is a separate measure."
            ),
        },
    }


def _step4(scan_pdf: Path) -> dict[str, Any]:
    data = scan_pdf.read_bytes()
    baseline_text = ""
    baseline_error = None
    try:
        baseline_text, baseline_ms = _timed_median(lambda: _extract(data, "application/pdf")[0], 5)
    except UrlFetchError as exc:
        baseline_text = ""
        baseline_ms = 0.0
        baseline_error = str(exc)

    pdfium = _optional("pypdfium2")
    rapidocr = _optional("rapidocr_onnxruntime")
    numpy = _optional("numpy")
    if pdfium is None or rapidocr is None or numpy is None:
        return {
            "baseline": {"chars": len(baseline_text), "error": baseline_error},
            "ocr": {"skipped": "pypdfium2, numpy or rapidocr_onnxruntime is not installed"},
        }

    render_started = time.perf_counter()
    document = pdfium.PdfDocument(str(scan_pdf))
    page = document[0]
    bitmap = page.render(scale=2.5)
    image = bitmap.to_pil().convert("RGB")
    render_ms = round((time.perf_counter() - render_started) * 1000, 2)

    engine_started = time.perf_counter()
    engine = rapidocr.RapidOCR()
    engine_init_ms = round((time.perf_counter() - engine_started) * 1000, 2)
    engine(numpy.array(image))  # model warm-up, not part of the measured OCR latency
    times: list[float] = []
    result: Any = None
    for _ in range(3):
        started = time.perf_counter()
        result, _elapsed = engine(numpy.array(image))
        times.append((time.perf_counter() - started) * 1000)
    ocr_text = "\n".join(line[1] for line in (result or []))
    return {
        "iterations": 3,
        "baseline": {
            "chars": len(baseline_text),
            "success": bool(baseline_text.strip()),
            "url_would_fail": not bool(baseline_text.strip()),
            "error": baseline_error,
            "runtime_ms": baseline_ms,
        },
        "ocr": {
            "chars": len(ocr_text),
            "coverage_compact": _compact_coverage(ocr_text, EXPECTED_OCR),
            "cer": round(_cer(" ".join(EXPECTED_OCR), ocr_text), 4),
            "render_ms": render_ms,
            "engine_init_ms": engine_init_ms,
            "inference_ms": round(statistics.median(times), 2),
            "text": ocr_text[:1000],
        },
    }


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument(
        "--output", type=Path, default=ROOT / ".local" / "extraction-benchmark.json"
    )
    args = parser.parse_args()

    results: dict[str, Any] = {
        "generated_at": time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime()),
        "fixtures": "synthetic; no network and no model calls",
        "dependencies": {
            "reportlab": bool(_optional("reportlab")),
            "trafilatura": bool(_optional("trafilatura")),
            "pypdfium2": bool(_optional("pypdfium2")),
            "rapidocr_onnxruntime": bool(_optional("rapidocr_onnxruntime")),
        },
    }
    with tempfile.TemporaryDirectory(prefix="fs-extraction-") as directory:
        work = Path(directory)
        table_pdf = work / "table.pdf"
        figure_pdf = work / "figure.pdf"
        scan_pdf = work / "scan.pdf"
        if not results["dependencies"]["reportlab"]:
            raise SystemExit("reportlab is required to generate the PDF fixtures")
        _build_table_pdf(table_pdf)
        _build_figure_pdf(figure_pdf)
        _build_scan_pdf(scan_pdf)
        results["step2_url_pdf_assets"] = _step2(table_pdf, figure_pdf)
        results["step3_html_main_content"] = _step3()
        results["step4_ocr_scanned_pdf"] = _step4(scan_pdf)

    args.output.parent.mkdir(parents=True, exist_ok=True)
    args.output.write_text(
        json.dumps(results, indent=2, ensure_ascii=False) + "\n", encoding="utf-8"
    )
    print(json.dumps(results, indent=2, ensure_ascii=False))
    print(f"\nwrote {args.output}")


if __name__ == "__main__":
    main()
