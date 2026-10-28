from __future__ import annotations

from pathlib import Path

from streamlit.testing.v1 import AppTest


APP = Path(__file__).resolve().parents[1] / "app.py"


def _app() -> AppTest:
    return AppTest.from_file(str(APP), default_timeout=30).run()


def test_batch_controls_are_available_without_uploads():
    app = _app()
    assert not app.exception
    assert any(widget.label == "Directory Path" for widget in app.text_input)
    assert any(button.label == "Run Batch Extraction" for button in app.button)


def test_identical_files_in_one_upload_are_deduplicated(plain_pdf):
    app = _app()
    app.get("file_uploader")[0].set_value(
        [
            ("first-name.pdf", plain_pdf, "application/pdf"),
            ("second-name.pdf", plain_pdf, "application/pdf"),
        ]
    ).run()
    assert not app.exception
    assert len(app.session_state["docs"]) == 1
    assert app.session_state["docs"][0]["filename"] == "first-name.pdf"


def test_detection_selection_and_export_transition(grid_pdf):
    app = _app()
    app.get("file_uploader")[0].upload("grid.pdf", grid_pdf, "application/pdf").run()
    [button for button in app.button if button.label == "Run Detection"][0].click().run()
    assert not app.exception
    assert app.session_state["detections"]

    [checkbox for checkbox in app.checkbox if checkbox.label == "Select"][0].set_value(True).run()
    generate = [button for button in app.button if button.label == "Generate Export"]
    assert generate
    generate[0].click().run()
    doc_id = app.session_state["docs"][0]["doc_id"]
    assert app.session_state["interactive_export_result"][doc_id]["data"]


def test_remove_document_clears_derived_state(grid_pdf):
    app = _app()
    app.get("file_uploader")[0].upload("grid.pdf", grid_pdf, "application/pdf").run()
    [button for button in app.button if button.label == "Run Detection"][0].click().run()
    doc_id = app.session_state["docs"][0]["doc_id"]
    app.session_state["confirmed_slices"] = {f"{doc_id}|0": True}
    app.session_state["slice_config"] = {
        f"{doc_id}|0": {"mode": "table", "row": None, "column": None}
    }
    app.session_state["interactive_export_result"] = {doc_id: {"data": b"stale"}}

    [button for button in app.button if button.label == "Remove"][0].click().run()
    assert doc_id not in app.session_state["doc_bytes"]
    assert doc_id not in app.session_state["detections"]
    assert f"{doc_id}|0" not in app.session_state["confirmed_slices"]
    assert f"{doc_id}|0" not in app.session_state["slice_config"]
    assert doc_id not in app.session_state["interactive_export_result"]


def test_failed_batch_clears_previous_output(tmp_path):
    app = _app()
    app.session_state["batch_export_result"] = {"data": b"stale"}
    directory = [widget for widget in app.text_input if widget.label == "Directory Path"][0]
    directory.set_value(str(tmp_path / "missing")).run()
    [button for button in app.button if button.label == "Run Batch Extraction"][0].click().run()
    assert app.session_state["batch_export_result"] == {}
    assert any("inaccessible" in error.value for error in app.error)
