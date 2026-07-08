"""
Pipeline progress tracking for AUTOEDIT.

Defines the canonical pipeline stages (order matters — they are
sequential), computes project readiness from on-disk/DB evidence,
and provides helpers to update project status in the DB.
"""

from __future__ import annotations

import json
from pathlib import Path

from sqlalchemy import Engine, update
from sqlalchemy.orm import Session

from autoedit.db.schema import projects


# ── Canonical pipeline stages in execution order ──────────────────
# Each stage maps to a disk/DB check that proves it completed.
PIPELINE_STAGES = [
    {
        "key": "sync",
        "label": "Sync & proxies",
        "description": "Audio sync, channel extraction, proxy generation",
    },
    {
        "key": "loudness",
        "label": "Loudness envelope",
        "description": "Per-channel RMS energy envelope",
    },
    {
        "key": "noise_floor",
        "label": "Noise floor & threshold",
        "description": "10th-percentile floor + 8dB VAD threshold",
    },
    {
        "key": "level_normalization",
        "label": "Level normalization",
        "description": "Analysis gain offsets for uneven mic levels",
    },
    {
        "key": "diarize",
        "label": "Speaker diarization",
        "description": "Speaker identification from audio",
    },
    {
        "key": "intervals",
        "label": "Speaking intervals",
        "description": "VAD intervals with hangover merge",
    },
    {
        "key": "activity",
        "label": "Activity timeline",
        "description": "Contiguous who-is-active timeline",
    },
    {
        "key": "program_audio",
        "label": "Program audio mixdown",
        "description": "Browser-playable stereo mix",
    },
    {
        "key": "transcribe",
        "label": "Transcription",
        "description": "Per-speaker transcript with word timestamps",
    },
    {
        "key": "segment_topics",
        "label": "Topic segmentation",
        "description": "Non-overlapping topic spans",
    },
    {
        "key": "conciseness",
        "label": "Conciseness grading",
        "description": "Defensible 1-5 scores per span",
    },
    {
        "key": "summary",
        "label": "Summary report",
        "description": "Speaker times, overlap, silence",
    },
    {
        "key": "cut",
        "label": "Rough cut",
        "description": "Deterministic CDL from activity timeline",
    },
]


def compute_progress(
    engine: Engine,
    data_root: str | Path,
    project_id: str,
) -> dict:
    """Return the pipeline progress for a project.

    Each stage gets a status: 'done', 'running', 'queued', or 'error'.
    Stages are ordered; the first non-done stage is 'running'—everything
    after is 'queued'.  'done' requires on-disk and/or DB evidence.

    Also returns the overall project status from the DB.
    """
    from autoedit.projects import get_project

    project = get_project(engine, project_id)
    if project is None:
        raise LookupError("project not found")

    from autoedit.project_paths import project_root

    project_dir = project_root(data_root, project_id)

    stages = []
    all_done = True
    first_missing = True

    for stage_def in PIPELINE_STAGES:
        key = stage_def["key"]
        is_done = _check_stage_done(engine, project_dir, project_id, key)
        if is_done:
            status = "done"
        elif first_missing:
            status = "running" if project.get("status") == "processing" else "queued"
            all_done = False
            first_missing = False
        else:
            status = "queued"
            all_done = False

        stages.append({
            "key": key,
            "label": stage_def["label"],
            "description": stage_def["description"],
            "status": status,
        })

    return {
        "project_id": project_id,
        "status": project.get("status", "created"),
        "stages": _merge_errors(stages, project_dir),
        "ready": all_done,
        "errors": _load_errors(project_dir),
    }


def set_project_status(engine: Engine, project_id: str, status: str) -> None:
    """Update the project status in the DB (atomic, no session leaks)."""
    with Session(engine) as session:
        session.execute(
            update(projects)
            .where(projects.c.id == project_id)
            .values(status=status)
        )
        session.commit()


def _check_stage_done(engine, project_dir: Path, project_id: str, key: str) -> bool:
    """Check whether a pipeline stage has completed (disk + DB evidence)."""
    from autoedit.db.schema import (
        audio_channels,
        angles,
        cuts,
        speaking_intervals,
        topic_spans,
    )
    from sqlalchemy import select

    checks = {
        "sync": lambda: _check_sync(project_dir, engine, project_id),
        "loudness": lambda: (project_dir / "audio" / "loudness.json").is_file(),
        "noise_floor": lambda: _check_noise_floor(engine, project_id),
        "level_normalization": lambda: (project_dir / "audio" / "level_normalization.json").is_file(),
        "diarize": lambda: (project_dir / "audio" / "diarization.json").is_file(),
        "intervals": lambda: _check_intervals(engine, project_id),
        "activity": lambda: (project_dir / "audio" / "activity.json").is_file(),
        "program_audio": lambda: (project_dir / "audio" / "program.m4a").is_file(),
        "transcribe": lambda: (project_dir / "transcript" / "transcript.json").is_file(),
        "segment_topics": lambda: _db_has_rows(engine, topic_spans, project_id),
        "conciseness": lambda: _check_conciseness(engine, project_id),
        "summary": lambda: (project_dir / "transcript" / "summary.json").is_file(),
        "cut": lambda: _db_has_rows(engine, cuts, project_id, {"kind": "rough"}),
    }

    checker = checks.get(key)
    if checker is None:
        return False

    try:
        return checker()
    except Exception:
        return False


def _check_sync(project_dir: Path, engine, project_id: str) -> bool:
    """Sync is done when channel WAVs exist and proxies exist for all angles."""
    from sqlalchemy import select
    from autoedit.db.schema import angles, audio_channels

    audio_dir = project_dir / "audio"
    if not audio_dir.is_dir():
        return False

    with Session(engine) as session:
        channels = session.execute(
            select(audio_channels.c.wav_path).where(
                audio_channels.c.project_id == project_id
            )
        ).all()

    has_wavs = any(
        ch.wav_path and (project_dir / ch.wav_path).is_file()
        for ch in channels
    )

    with Session(engine) as session:
        angle_rows = session.execute(
            select(angles.c.proxy_path).where(
                angles.c.project_id == project_id
            )
        ).all()

    has_proxies = all(
        a.proxy_path and (project_dir / a.proxy_path).is_file()
        for a in angle_rows
    ) and len(angle_rows) > 0

    return has_wavs and has_proxies


def _check_noise_floor(engine, project_id: str) -> bool:
    """Noise floor is done when channels have vad_threshold_db set."""
    from sqlalchemy import select
    from autoedit.db.schema import audio_channels

    with Session(engine) as session:
        rows = session.execute(
            select(audio_channels.c.vad_threshold_db).where(
                audio_channels.c.project_id == project_id
            )
        ).all()

    return all(r.vad_threshold_db is not None for r in rows) and len(rows) > 0


def _check_conciseness(engine, project_id: str) -> bool:
    """Conciseness is done when topic_spans have conciseness_score set."""
    from sqlalchemy import select
    from autoedit.db.schema import topic_spans

    with Session(engine) as session:
        rows = session.execute(
            select(topic_spans.c.conciseness_score).where(
                topic_spans.c.project_id == project_id
            )
        ).all()

    return (
        len(rows) > 0
        and all(r.conciseness_score is not None for r in rows)
    )


def _check_intervals(engine, project_id: str) -> bool:
    """Check that speaking_intervals exist for this project via audio_channels join."""
    from sqlalchemy import select
    from autoedit.db.schema import audio_channels, speaking_intervals

    with Session(engine) as session:
        row = session.execute(
            select(speaking_intervals.c.id).where(
                speaking_intervals.c.channel_id.in_(
                    select(audio_channels.c.id).where(
                        audio_channels.c.project_id == project_id
                    )
                )
            )
        ).first()
    return row is not None


def _db_has_rows(engine, table, project_id: str, extra: dict | None = None) -> bool:
    """Check that at least one row exists for the given project."""
    from sqlalchemy import select

    with Session(engine) as session:
        stmt = select(table.c.id).where(table.c.project_id == project_id)
        if extra:
            for col, val in extra.items():
                stmt = stmt.where(getattr(table.c, col) == val)
        return session.execute(stmt).first() is not None


def _load_errors(project_dir: Path) -> dict[str, dict]:
    """Load the per-stage error log if it exists."""
    errors_path = project_dir / "pipeline.errors.json"
    if errors_path.is_file():
        try:
            return json.loads(errors_path.read_text())
        except (json.JSONDecodeError, OSError):
            pass
    return {}


def _merge_errors(stages: list[dict], project_dir: Path) -> list[dict]:
    """Merge per-stage error messages into the stage list."""
    errors = _load_errors(project_dir)
    if not errors:
        return stages
    for stage in stages:
        err = errors.get(stage["key"])
        if err:
            stage["error"] = err.get("message", "")
            stage["status"] = "error"
    return stages
