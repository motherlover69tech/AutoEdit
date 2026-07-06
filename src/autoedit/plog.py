"""
Pipeline event logger for AUTOEDIT.

Writes structured log lines to both stdout (visible in Docker logs) and
a project-specific pipeline.log on disk.  Also maintains a per-stage error
registry so the progress endpoint can surface what went wrong.

Usage:
    from autoedit.plog import PipelineLogger

    plog = PipelineLogger(project_dir, project_id)
    with plog.stage("sync"):
        # do work
        plog.cmd("ffmpeg", ["ffmpeg", "-i", src, ...])
    # On exception: error is captured and stored automatically.
"""

from __future__ import annotations

import json
import logging
import subprocess
import time
from contextlib import contextmanager
from datetime import datetime, timezone
from pathlib import Path
from typing import Sequence

# Shared stdout logger — one per process, project context added per-message.
_LOGGER = logging.getLogger("autoedit.pipeline")
_LOGGER.setLevel(logging.DEBUG)
_LOGGER.propagate = False
if not _LOGGER.handlers:
    _h = logging.StreamHandler()
    _h.setLevel(logging.DEBUG)
    _h.setFormatter(logging.Formatter(
        "%(asctime)s [%(levelname)-7s] %(message)s",
        datefmt="%Y-%m-%dT%H:%M:%S",
    ))
    _LOGGER.addHandler(_h)

ERRORS_FILE = "pipeline.errors.json"
LOG_FILE = "pipeline.log"


class PipelineLogger:
    """Per-project pipeline logger with stage tracking and error capture."""

    def __init__(self, project_dir: str | Path, project_id: str) -> None:
        self._project_dir = Path(project_dir)
        self._project_id = project_id
        self._log_path = self._project_dir / LOG_FILE
        self._errors_path = self._project_dir / ERRORS_FILE
        self._errors: dict[str, dict] = self._load_errors()

    # ── Public API ──────────────────────────────────────────────────

    def info(self, message: str) -> None:
        self._emit("INFO", message)

    def warning(self, message: str) -> None:
        self._emit("WARN", message)

    def error(self, message: str) -> None:
        self._emit("ERROR", message)

    def cmd(self, label: str, argv: Sequence[str]) -> None:
        """Log an external command invocation."""
        cmd_str = " ".join(str(a) for a in argv)
        self._emit("CMD", f"{label}: {cmd_str}")

    def cmd_result(self, returncode: int, stderr: str = "", stdout: str = "") -> None:
        """Log command result."""
        parts = [f"exit={returncode}"]
        if stderr:
            tail = stderr.strip().split("\n")[-3:]
            parts.append("stderr: " + " | ".join(tail))
        self._emit("CMD", " ".join(parts))

    @contextmanager
    def stage(self, stage_key: str, label: str = ""):
        """Context manager that logs stage start/end and captures errors.

        On successful exit, clears any previous error for this stage.
        On exception, stores the error and re-raises.
        """
        self._emit("STAGE", f"BEGIN {stage_key}  {label}".rstrip())
        t0 = time.monotonic()
        try:
            yield
        except Exception as exc:
            elapsed = time.monotonic() - t0
            self._emit("STAGE", f"FAIL {stage_key}  {elapsed:.1f}s  {exc}")
            self._store_error(stage_key, str(exc))
            raise
        else:
            elapsed = time.monotonic() - t0
            self._emit("STAGE", f"END  {stage_key}  {elapsed:.1f}s")
            self._clear_error(stage_key)

    def get_errors(self) -> dict[str, dict]:
        """Return per-stage error map for the progress endpoint."""
        return dict(self._errors)

    def record_error(self, stage_key: str, message: str) -> None:
        """Persist a stage error outside the stage context manager."""
        self._store_error(stage_key, message)

    # ── Internals ───────────────────────────────────────────────────

    def _emit(self, level: str, message: str) -> None:
        ts = datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%S.%f")[:23] + "Z"
        line = f"{ts} [{level:<5}] {self._project_id[:8]} {message}\n"

        # stdout
        _LOGGER.info(line.rstrip())

        # file
        try:
            self._log_path.parent.mkdir(parents=True, exist_ok=True)
            with open(self._log_path, "a") as f:
                f.write(line)
        except OSError:
            pass  # Don't break the pipeline for log write failures

    def _load_errors(self) -> dict[str, dict]:
        if self._errors_path.is_file():
            try:
                return json.loads(self._errors_path.read_text())
            except (json.JSONDecodeError, OSError):
                pass
        return {}

    def _store_error(self, stage_key: str, message: str) -> None:
        self._errors[stage_key] = {
            "message": message,
            "ts": datetime.now(timezone.utc).isoformat(),
        }
        self._write_errors()

    def _clear_error(self, stage_key: str) -> None:
        if stage_key in self._errors:
            del self._errors[stage_key]
            self._write_errors()

    def _write_errors(self) -> None:
        try:
            self._errors_path.parent.mkdir(parents=True, exist_ok=True)
            self._errors_path.write_text(json.dumps(self._errors, indent=2))
        except OSError:
            pass


def run_cmd(argv: Sequence[str], *, timeout: int = 300) -> subprocess.CompletedProcess:
    """Run a subprocess synchronously and raise RuntimeError on failure."""
    try:
        result = subprocess.run(argv, capture_output=True, text=True, timeout=timeout)
    except FileNotFoundError as exc:
        raise RuntimeError(f"executable not found: {argv[0]}") from exc
    if result.returncode != 0:
        tail = result.stderr.strip().split("\n")[-5:]
        detail = " | ".join(tail) if tail else f"exit code {result.returncode}"
        raise RuntimeError(f"{argv[0]} failed: {detail}")
    return result
