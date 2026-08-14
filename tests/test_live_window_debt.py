from __future__ import annotations

import os
from pathlib import Path

from sqlalchemy import create_engine, inspect

from autoedit.ai.gpu_measurement import GPUSample, summarize_gpu_acceptance
from autoedit.db.migrate import run_migrations
from autoedit.db.runtime import configure_mysql_session
from autoedit.ops.dots_completion import DotsOutputObserver


def test_mysql_session_sort_buffer_is_configured_per_connection(monkeypatch):
    callbacks = []

    class Dialect:
        name = "mysql"

    class Engine:
        dialect = Dialect()

    monkeypatch.setattr(
        "autoedit.db.runtime.event.listen",
        lambda engine, event_name, callback: callbacks.append((engine, event_name, callback)),
    )
    engine = Engine()
    configure_mysql_session(engine, sort_buffer_size=16 * 1024 * 1024)
    assert callbacks[0][:2] == (engine, "connect")

    statements = []

    class Cursor:
        def execute(self, statement):
            statements.append(statement)

        def close(self):
            statements.append("closed")

    class Connection:
        def cursor(self):
            return Cursor()

    callbacks[0][2](Connection(), None)
    assert statements == ["SET SESSION sort_buffer_size = 16777216", "closed"]


def test_cuts_schema_has_project_created_id_order_index():
    engine = create_engine("sqlite:///:memory:")
    run_migrations(engine)
    indexes = {item["name"]: item["column_names"] for item in inspect(engine).get_indexes("cuts")}
    assert indexes["ix_cuts_project_created_id"] == ["project_id", "created_at", "id"]


def test_gpu_summary_flags_used_column_transient_and_uses_process_sum():
    samples = [
        GPUSample(0, 32768, 8044, "baseline", process_used_mib=(8044,)),
        GPUSample(250, 32768, 32480, "overlap", process_used_mib=(6898, 8694)),
    ]
    result = summarize_gpu_acceptance(samples)
    assert result["used_column_peak_mib"] == 32480
    assert result["peak_used_mib"] == 15592
    assert result["used_process_discrepancy_count"] == 1
    assert result["samples_with_accounting_anomaly"] == [1]
    assert result["verdict"] == "PASS"


def test_dots_completion_requires_new_stable_output_mtime(tmp_path: Path):
    output = tmp_path / "long.wav"
    output.write_bytes(b"partial")
    initial = output.stat().st_mtime_ns
    observer = DotsOutputObserver(output, submitted_after_mtime_ns=initial)

    assert observer.observe(api_status="completed") is False
    os.utime(output, ns=(initial + 1_000_000_000, initial + 1_000_000_000))
    assert observer.observe(api_status="completed") is False
    assert observer.observe(api_status="completed") is True
    assert observer.completed_at_mtime_ns == initial + 1_000_000_000
