# Extraction benchmarks

Synthetic, reproducible measurements for the three extraction improvements discussed in the
URL-document review:

1. routing URL PDFs through the file-upload asset pipeline (tables and figures),
2. extracting the main HTML article instead of flattening the whole DOM,
3. OCR fallback for scan-only PDFs.

The fixtures are generated locally. No publisher content, network request or model call is
involved. This is a development tool, not part of `make verify` and not a production
benchmark.

## Run

The optional candidate dependencies are deliberately not in the application lockfile:

```bash
mkdir -p .local/bench-deps
python3 -m pip install --target .local/bench-deps \
  reportlab trafilatura rapidocr_onnxruntime pypdfium2 pillow numpy
PYTHONPATH="$PWD/.local/bench-deps:$PWD/backend" \
  backend/.venv/bin/python tests/eval/extraction/benchmark.py
```

The JSON result is written to `.local/extraction-benchmark.json`. `reportlab` is required
for the PDF fixtures; `trafilatura` and `rapidocr_onnxruntime` are optional and reported as
skipped when absent. The script warms the extractors once and reports median runtimes;
OCR inference time excludes engine and model initialisation.

## Fixtures and metrics

- **Table PDF:** one page with a grid table and a sentence. Baseline is the current URL
  `_extract` (pypdf text only). Candidate is `read_file_bytes` plus `parse_pdf_assets` with a
  fake vision function. Metrics: characters, whether a Markdown table exists, table-token
  coverage, runtime.
- **Figure-only PDF:** one page containing a generated bar chart. Baseline is the current
  URL extractor; candidate is the same asset pipeline. Metrics: characters, success, figure
  count. The fake vision description measures plumbing only, not model quality or cost.
- **HTML article:** header/nav, cookie banner, article with heading, list and table, footer.
  Baseline is `_extract_html`; candidate is Trafilatura with Markdown output and tables.
  Metrics: article coverage, boilerplate hits (lower is better), heading/list counts, table
  retention, title/author/date and runtime. A JavaScript-only shell is included to show
  that neither static extractor renders it.
- **Scanned PDF:** an image-only page with two sentences. Baseline is pypdf; candidate is
  pypdfium2 rendering plus RapidOCR. Metrics: characters, compact token coverage, character
  error rate, render/inference time. This is a clean synthetic scan, not a hard real-world
  scan.

## Limits

One fixture per case cannot represent the web. The numbers compare approaches under
controlled conditions; they do not predict the corpus-wide gain. Before adopting a
candidate, run the same harness on a licensed, representative sample of real pages and
PDFs, including poor scans, multi-column layouts, cookie walls and non-English text.
