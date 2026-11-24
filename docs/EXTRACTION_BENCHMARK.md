# Extraction benchmark

Date: 2026-11-24. Environment: macOS arm64, Python 3.12.2, reportlab 5.1.0,
trafilatura 2.4.0, RapidOCR 1.4.4, pypdfium2 5.15.2. The harness is
`tests/eval/extraction/benchmark.py`; fixtures are synthetic and no model or network call
was made. Runtimes are medians after a warm-up and exclude OCR model initialisation.

## 1. URL PDFs through the file-asset pipeline

Baseline: current URL `_extract` (pypdf text only). Candidate: `read_file_bytes` plus
`parse_pdf_assets`; the figure description is a fake, so its text and latency do not
include a vision model.

| Fixture | Variant | Chars | Markdown table | Table coverage | Figures | Runtime |
| --- | --- | ---: | :---: | ---: | ---: | ---: |
| Table PDF | baseline | 86 | no | 100% | – | 0.71 ms |
| Table PDF | candidate | 177 | yes | 100% | 0 | 5.14 ms |
| Figure-only PDF | baseline | 0 | – | – | 0 | 0.23 ms |
| Figure-only PDF | candidate | 108 | – | – | 1 | 18.22 ms |

The table's cell text survives both ways; only the candidate preserves its structure. The
baseline produces no text for the figure-only PDF, so the current URL path would reject it
with `url_fetch_failed`. The candidate recovers a figure section and would create a
document. The 17 ms candidate time is plumbing only; a real vision call will dominate both
latency and cost, so URL submissions need a budget estimate or a cap before this is enabled
by default.

## 2. HTML main content and structure

One synthetic article with header/nav, cookie banner, article body, list, table and footer.

| Variant | Chars | Article coverage | Boilerplate hits | Headings | List items | Table | Title | Author | Date | Runtime |
| --- | ---: | ---: | ---: | ---: | ---: | :---: | --- | --- | --- | ---: |
| current `_extract_html` | 258 | 100% | 6/6 | 0 | 0 | yes | `Housing report` | – | – | 0.09 ms |
| Trafilatura Markdown | 178 | 100% | 0/6 | 2 | 2 | yes | `Rents rose sharply` | `Fixture Desk` | `2025-06-01` | 0.76 ms |

Trafilatura drops 80 characters of navigation, cookie and footer text while retaining all
article and table tokens, and it preserves headings and list structure. It takes the H1 as
the metadata title instead of `<title>`; the author and publication date come from meta
tags. The JavaScript-only shell yields zero characters in both variants, so this does not
replace the separate JavaScript-rendering question.

## 3. OCR for scan-only PDFs

A clean 150 dpi image-only PDF containing two sentences.

| Variant | Chars | Compact coverage | CER | Render | OCR inference |
| --- | ---: | ---: | ---: | ---: | ---: |
| current pypdf | 0 | 0% | – | – | – |
| pypdfium2 + RapidOCR | 71 | 100% | 2.82% | 8.95 ms | 237.03 ms |

The current URL path raises `url_fetch_failed` for textless PDFs. OCR recovers the content
with one spacing error (`SCANNED HOUSING REPORT` becomes `SCANNEDHOUSINGREPORT`) and all
expected tokens. Engine initialisation was 91.37 ms on this machine and is additional to the
inference time. This is a clean synthetic scan; real scans, skew, multi-column pages and
non-English text need a representative sample before sizing the fallback.

## Interpretation

- **Step 2 is the clearest structural win:** table and figure recovery is already available
  in the file path, but the URL path bypasses it. The main open issues are vision cost,
  latency and the missing URL estimate, not extraction capability.
- **Step 3 is a strong candidate for static pages:** it removes boilerplate and restores
  structure at sub-millisecond cost. The title semantics and table fidelity need checking on
  real pages before adopting Trafilatura as the default.
- **Step 4 works on a clean scan:** OCR recovers otherwise invisible text at roughly 0.27 s
  of inference per page. It should be a fallback for low-text pages, not an unconditional
  first pass, because real scans and model memory change the cost profile.

These numbers are a controlled comparison, not a corpus-wide quality estimate. The next
step is a licensed sample of real pages and PDFs with labelled expected text and structure.
