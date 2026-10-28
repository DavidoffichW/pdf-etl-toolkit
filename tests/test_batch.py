from __future__ import annotations

import csv
import json
import os
from io import StringIO

import pytest

from engine import BatchLimits, Engine


def _run(engine: Engine, directory, *, limits: BatchLimits | None = None, output="csv"):
    return engine.batch_extract_directory_result(
        directory_path=str(directory),
        page_1b=1,
        table_index_1b=1,
        slice_mode="table",
        row_1b=None,
        col_1b=None,
        export_format=output,
        include_xlsx=output == "zip",
        limits=limits,
    )


def test_batch_order_is_stable_and_reported(plan, grid_pdf, tmp_path):
    (tmp_path / "z.pdf").write_bytes(grid_pdf)
    (tmp_path / "A.pdf").write_bytes(grid_pdf)
    first = _run(Engine(plan), tmp_path)
    second = _run(Engine(plan), tmp_path)

    assert first.data == second.data
    assert first.report == second.report
    assert first.success_count == 2
    assert first.failure_count == 0
    rows = list(csv.reader(StringIO(first.data.decode("utf-8"))))
    source_column = rows[0].index("source_filename")
    observed = []
    for row in rows[1:]:
        if row[source_column] not in observed:
            observed.append(row[source_column])
    assert observed == ["A.pdf", "z.pdf"]
    assert str(tmp_path) not in first.report.decode("utf-8")


def test_batch_isolates_malformed_and_encrypted_files(plan, grid_pdf, encrypted_pdf, tmp_path):
    (tmp_path / "a-good.pdf").write_bytes(grid_pdf)
    (tmp_path / "b-bad.pdf").write_bytes(b"not a PDF")
    (tmp_path / "c-encrypted.pdf").write_bytes(encrypted_pdf)

    result = _run(Engine(plan), tmp_path, output="zip")
    assert result.success_count == 1
    assert result.failure_count == 2
    by_name = {item.filename: item for item in result.files}
    assert by_name["a-good.pdf"].status == "OK"
    assert by_name["b-bad.pdf"].status == "FAILED"
    assert by_name["c-encrypted.pdf"].status == "FAILED"
    assert json.loads(result.report)["bytes_read"] == sum(path.stat().st_size for path in tmp_path.iterdir())


def test_batch_rejects_too_many_files_before_processing(plan, grid_pdf, tmp_path):
    (tmp_path / "a.pdf").write_bytes(grid_pdf)
    (tmp_path / "b.pdf").write_bytes(grid_pdf)
    with pytest.raises(ValueError, match="limit is 1"):
        _run(Engine(plan), tmp_path, limits=BatchLimits(max_files=1))


def test_batch_rejects_total_size_before_processing(plan, grid_pdf, tmp_path):
    (tmp_path / "a.pdf").write_bytes(grid_pdf)
    (tmp_path / "b.pdf").write_bytes(grid_pdf)
    with pytest.raises(ValueError, match="total limit"):
        _run(
            Engine(plan),
            tmp_path,
            limits=BatchLimits(max_total_bytes=len(grid_pdf) * 2 - 1),
        )


def test_batch_rejects_oversized_file_before_read(plan, grid_pdf, tmp_path):
    (tmp_path / "large.pdf").write_bytes(grid_pdf)
    result = _run(
        Engine(plan),
        tmp_path,
        limits=BatchLimits(max_file_bytes=len(grid_pdf) - 1),
    )
    assert result.bytes_read == 0
    assert result.success_count == 0
    assert result.failure_count == 1
    assert "per-file limit" in result.files[0].message


def test_batch_enforces_processed_page_limit(plan, grid_pdf, tmp_path):
    (tmp_path / "two-pages.pdf").write_bytes(grid_pdf)
    result = _run(Engine(plan), tmp_path, limits=BatchLimits(max_pages=1))
    assert result.success_count == 0
    assert result.failure_count == 1
    assert "page batch limit" in result.files[0].message


def test_batch_rejects_symlinked_pdf_when_supported(plan, grid_pdf, tmp_path):
    target = tmp_path / "real.pdf"
    target.write_bytes(grid_pdf)
    link = tmp_path / "linked.pdf"
    try:
        link.symlink_to(target)
    except OSError as exc:
        pytest.skip(f"file symlinks unavailable: {exc}")

    result = _run(Engine(plan), tmp_path)
    by_name = {item.filename: item for item in result.files}
    assert by_name["real.pdf"].status == "OK"
    assert by_name["linked.pdf"].status == "FAILED"
    assert "symlink or reparse point" in by_name["linked.pdf"].message


def test_batch_rejects_symlinked_directory_when_supported(plan, tmp_path):
    source = tmp_path / "source"
    source.mkdir()
    link = tmp_path / "link"
    try:
        link.symlink_to(source, target_is_directory=True)
    except OSError as exc:
        pytest.skip(f"directory symlinks unavailable: {exc}")

    with pytest.raises(ValueError, match="symlink or reparse point"):
        _run(Engine(plan), link)
