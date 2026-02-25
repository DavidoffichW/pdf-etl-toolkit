# pdf-etl-toolkit

A deterministic, workflow-oriented PDF ingestion and ETL utility built as a single Streamlit application.

This project focuses on **controlled document transformation** rather than freeform editing:
- ingest PDFs
- reorder and merge
- preview PDFs via image rendering
- extract tables and export structured outputs (capability-dependent)

The application is designed to **degrade gracefully** depending on which Python libraries are available on a user machine.

---

## Key Principles

- **Deterministic outputs**: predictable behavior, stable ordering, auditable selection inputs.
- **Ephemeral run**: no persistent server-side workspace; outputs are produced for download.
- **Capability-aware**: features enable/disable automatically based on installed dependencies.
- **Single command run**: `streamlit run app.py`

---

## Current Feature Surface (Implemented)

### Document handling
- Upload multiple PDFs
- Arrange document order
- Merge into a single PDF
- Download merged PDF

### Preview
- PDF preview via iframe for “normal” PDFs
- Heavy-PDF fallback to image-based preview (single-page) with:
  - working Prev/Next navigation
  - page jump
  - zoom (visual scale)
  - sharpness (render resolution)
  - margins control
  - “Fit” reset

### Environment & capabilities
- Capabilities detection and UI exposure (feature gating)

> Note: The preview layer is explicitly designed to be replaceable in a future Django + FastAPI implementation where PDF.js and multi-format viewers will be feasible.

---

## Planned / Not Yet Implemented (Roadmap)

These are requirements that are **explicitly planned**, but should be treated as **not implemented** until confirmed in code:

- Batch ETL pipeline: input a directory path with multiple PDFs and run a deterministic extraction across all files
- Internal in-memory rename/ordering (e.g., logical `1.pdf`, `2.pdf`, …) to guarantee extraction order
- Cross-PDF extraction: same page + same table index + same (row, col) slice across all PDFs → single consolidated CSV output
- Stronger table selection UX: selecting table index among tables on a page with preview confirmation

---

## Repository Structure

```text
pdf-etl-toolkit/
  app.py
  requirements.txt
  README.md
  src/
    capabilities.py
    detection_ui.py
    engine.py
    export.py
    export_ui.py
    extract.py
    ordering.py
    preview.py
    runplan.py
    state.py
    utils.py
    workspace.py
```

---

## Installation (Windows)

### 1) Create and activate a virtual environment

From `cmd.exe`:

```bat
cd path\to\pdf-etl-toolkit
python -m venv venv
venv\Scripts\activate
```

### 2) Install dependencies

```bat
pip install -r requirements.txt
```

### 3) Run the app

```bat
streamlit run app.py
```

---

## Installation (Linux / macOS)

```bash
python -m venv venv
source venv/bin/activate
pip install -r requirements.txt
streamlit run app.py
```

---

## Capability Model (Graceful Degradation)

The app exposes features depending on what is available:

* `pypdf` → basic PDF reading/merging
* `pymupdf (fitz)` → robust page rendering for image preview (recommended)
* `pdfplumber` → table detection/extraction provider
* `pandas` → DataFrame-based processing and structured export

If a capability is missing:

* the UI shows the feature as disabled or warns that installation is required
* the rest of the app remains functional

---

## Usage Guide

### 1) Upload and manage documents

* Upload one or more PDFs.
* Arrange order as required (document order affects merged output).
* Merge and download the merged PDF.

### 2) Preview

* Choose preview mode:

  * **PDF (iframe)** for normal PDFs
  * **Images (single-page)** for heavy or problematic PDFs
* In image preview:

  * Use Prev/Next or Page input
  * Zoom controls visual scaling
  * Sharpness controls render resolution
  * Margins adjust whitespace inside the preview container
  * Fit resets Zoom and Margins to defaults

### 3) Extraction / Export

* Table extraction and export depend on installed providers.
* Ensure `pdfplumber` and `pandas` are installed for table-driven CSV outputs.

---

## Troubleshooting

### Preview works for some PDFs but blank for others

* Heavy publisher PDFs can fail in browser-native PDF viewers when embedded.
* Switch preview renderer to **Images (single-page)** (requires `pymupdf`).

### “Duplicate widget key” errors

* Streamlit requires globally unique widget keys per render.
* Keys must be suffixed by context (e.g., per tab) to avoid collisions.

### Streamlit warns about `use_container_width`

* Streamlit is deprecating `use_container_width`.
* Use `st.image(..., width="stretch")` instead.

### Install failures on locked-down machines

* Prefer wheel installs where possible.
* If `pymupdf` is problematic, the app will still run, but preview fallback will be reduced.

---

## Security / Data Handling

* **Ephemeral run model**: the app does not require persistent storage as part of the intended workflow.
* Files are handled in memory or temporary runtime context.
* Outputs are provided for **download-only**.

If you need persistent document storage, multi-user access, and audit trails:

* this is planned for a future Django + FastAPI architecture.
