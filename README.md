# PDF ETL Toolkit

PDF ETL Toolkit is a local Streamlit application for assembling PDFs and exporting detected tables as structured data. It supports interactive work on uploaded documents and non-recursive batch extraction from a local directory.

The application is designed for trusted, single-user local operation. It has no authentication, persistent document store, or OCR pipeline.

## Features

- Upload, order, merge, extract pages from, and delete pages from PDFs.
- Preview PDFs in the browser or render individual pages as images.
- Detect tables independently on each page using this preference order:
  1. `pdfplumber`
  2. PyMuPDF
  3. a text-grid heuristic
- Select whole tables, rows, columns, or cells for export.
- Export CSV directly, or create a ZIP containing CSV, JSONL, a manifest, an event log, and optionally XLSX.
- Run the same extraction against the PDFs immediately inside a local directory, with per-file failure reporting and resource limits.

Detection is best-effort. Provider errors are reported separately from a valid "no table found" result. OCR libraries may be detected by the capability display, but scanned-image OCR is not implemented.

## Requirements and installation

The v0.1.0 candidate targets Python 3.10 through 3.13 on Windows and Linux.

```bash
python -m venv .venv
# Windows: .venv\Scripts\activate
# Linux/macOS: source .venv/bin/activate
python -m pip install -r requirements.txt
python -m streamlit run app.py --server.address 127.0.0.1
```

The checked-in Streamlit configuration also binds the app to `127.0.0.1`. Do not expose this application to untrusted network clients: batch mode accepts a server-side directory path and is intended only for trusted local use.

PyMuPDF is distributed under AGPL and commercial licensing options. Users and distributors are responsible for choosing and complying with an appropriate license; this repository's MIT license does not grant rights to PyMuPDF. See the [PyMuPDF licensing documentation](https://pymupdf.readthedocs.io/en/latest/about.html#license-and-copyright).

## Interactive workflow

1. Upload one or more PDFs. Identical content uploaded more than once in the same batch is kept as one document.
2. Reorder documents, merge them, or apply page extraction/deletion operations.
3. Choose a preview mode and inspect a document.
4. Run table detection, select candidates, and select a table/row/column/cell slice.
5. Generate CSV or ZIP output.

Changing or removing source documents, applying page operations, or rerunning detection invalidates selections and generated exports that no longer correspond to the current source.

## Batch workflow and limits

Batch extraction is available without an interactive upload. It scans only the immediate `.pdf` files in the chosen directory and processes them in stable, case-insensitive filename order.

Default limits are:

| Limit | Default |
|---|---:|
| PDF entries | 100 |
| One PDF | 50 MiB |
| Total accepted PDF bytes | 250 MiB |
| Processed pages | 2,000 |

Files are checked before full reads where practical, and reads are bounded to the per-file limit. Symlink and Windows reparse-point directory roots and PDF entries are rejected. Malformed, encrypted, inaccessible, unsupported, or out-of-range files fail independently and appear in the batch report. These limits are conservative controls for the application's in-memory processing model; they are not performance benchmarks or an operating-system sandbox.

## Export contract

CSV rows use these provenance fields followed by explicit data columns:

```text
file_id,page_index,candidate_id,row_index,col_1,col_2,...
```

The detected first row is retained as data. It is not silently promoted to a header. Batch exports add `seq` and `source_filename` before the `col_N` columns.

CSV and XLSX exports prefix formula-like text with an apostrophe when a value begins, after whitespace or control characters, with `=`, `+`, `-`, or `@`. Negative numeric values such as `-12.5` remain numeric-looking text. JSONL retains the extracted source text. This is a defensive policy for common spreadsheet clients, not universal protection for every importer.

For identical input bytes, options, provider outputs, and dependency versions, CSV, JSONL, XLSX, and ZIP output is byte-reproducible. ZIP member order, timestamps, permissions, and compression settings are fixed. Runtime UI timestamps remain available in memory but are omitted from reproducible structured exports.

## Capability behavior

- `pypdf` supplies ordinary PDF parsing and document transformations.
- PyMuPDF supplies image previews, table detection fallback, and a PDF transformation fallback.
- `pdfplumber` is the preferred table detector.
- `openpyxl` supplies optional XLSX output.

If a table provider fails to initialize or fails on a page, detection continues with the next provider for the affected page. A table found on one page does not suppress fallback on another page.

## Development

Install the development requirements and run the tests:

```bash
python -m pip install -r requirements-dev.txt
python -m pytest -q
python tests/smoke_streamlit.py
```

The test suite uses generated PDFs and fabricated table values. GitHub Actions runs the functional suite and a headless Streamlit startup check on Windows and Ubuntu.

## Data and security boundaries

Uploaded bytes and generated outputs live in Streamlit session memory. They are not written to a project database. Browser downloads and the selected batch directory remain under the operator's control.

The toolkit is not a malware scanner, secrets detector, multi-user document service, or general filesystem sandbox. Review source PDFs and generated exports before sharing them.
