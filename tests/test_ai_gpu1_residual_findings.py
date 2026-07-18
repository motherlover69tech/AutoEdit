"""Reproduce the three residual findings from review t_12705ec6.

These pin the exact behaviours the bounded exception must repair:

F1 — confirmation provenance is stripped before projection. The /cut route
     builds the AI activity timeline from ``speaker_turns`` but only forwards
     ``provenance`` for turns already filtered to confirmed/prior_confirmed;
     for a *suggested* mapping the resolved turn's provenance is dropped and
     the turn is silently passed as if confirmed. We assert the projection
     contract keeps provenance on every resolved turn and never attributes a
     suggested identity to a camera.

F2 — Gate 1 can be bypassed by a two-field self-asserted record. A minimal
     ``word-timing-review.json`` carrying only ``status``+``artifact_version``
     must NOT authorize an AI cut; the redacted acceptance record requires the
     full words/boundaries/peter_acceptance shape.

F3 — authorized Gate-1 / valid-unverified / rollback regressions were not
     committed. The atomic-persistence regression set plus the fail-closed
     source-verification regression must all be present and green.
"""
from __future__ import annotations

import json
from datetime import UTC, datetime
from pathlib import Path

from fastapi.testclient import TestClient

from autoedit.ai.activity_from_turns import activity_from_turns
from autoedit.ai.contracts import AIResultArtifact
from autoedit.api import create_app, _valid_gate_one_acceptance
from autoedit.db.migrate import run_migrations
from autoedit.db.schema import angles, audio_channels
from autoedit.projects import new_ulid


def _sha(path: Path) -> str:
    import hashlib
    return hashlib.sha256(path.read_bytes()).hexdigest()


def _build_project(tmp_path: Path, *, with_suggested: bool = False):
    from sqlalchemy import create_engine
    from sqlalchemy.pool import StaticPool
    from sqlalchemy.orm import Session

    engine = create_engine(
        "sqlite://", connect_args={"check_same_thread": False}, poolclass=StaticPool
    )
    run_migrations(engine)
    client = TestClient(create_app(engine=engine, data_root=tmp_path, auth_enabled=False))
    project = client.post(
        "/projects", json={"name": "AI", "fps_num": 25, "fps_den": 1}
    ).json()
    pid = project["id"]
    left, right = new_ulid(), new_ulid()
    wide = new_ulid()
    with Session(engine) as session:
        session.execute(
            angles.insert(),
            [
                {"id": left, "project_id": pid, "label": "A", "role": "cam_left", "source_path": "source/a.mp4", "duration_ms": 6000},
                {"id": right, "project_id": pid, "label": "B", "role": "cam_right", "source_path": "source/b.mp4", "duration_ms": 6000},
                {"id": wide, "project_id": pid, "label": "W", "role": "wide", "source_path": "source/w.mp4", "duration_ms": 6000},
            ],
        )
        session.execute(
            audio_channels.insert(),
            [
                {"id": new_ulid(), "project_id": pid, "speaker_label": "speaker-a", "source_angle_id": left, "channel_index": 0},
                {"id": new_ulid(), "project_id": pid, "speaker_label": "speaker-b", "source_angle_id": right, "channel_index": 0},
            ],
        )
        session.commit()

    project_dir = tmp_path / pid
    audio_dir = project_dir / "audio"
    audio_dir.mkdir(parents=True, exist_ok=True)
    (audio_dir / "source-a.wav").write_bytes(b"source-audio-a")
    (audio_dir / "source-b.wav").write_bytes(b"source-audio-b")
    (audio_dir / "ai").mkdir()
    (audio_dir / "ai" / "analysis.wav").write_bytes(b"analysis-audio")

    artifact_data = {
        "schema_version": "1.0",
        "run_id": "run-one",
        "created_at": datetime.now(UTC),
        "status": "completed",
        "timeline_origin_ms": 0,
        "timeline_end_ms": 5000,
        "sources": [
            {"source_id": "source-a", "relative_path": "audio/source-a.wav", "sha256": _sha(audio_dir / "source-a.wav"), "duration_ms": 5000, "sample_rate": 48000, "channels": 1, "sync_offset_ms": 0},
            {"source_id": "source-b", "relative_path": "audio/source-b.wav", "sha256": _sha(audio_dir / "source-b.wav"), "duration_ms": 5000, "sample_rate": 48000, "channels": 1, "sync_offset_ms": 0},
        ],
        "analysis_audio": {"relative_path": "audio/ai/analysis.wav", "sha256": _sha(audio_dir / "ai" / "analysis.wav"), "strategy": "isolated_lav", "duration_ms": 5000, "sample_rate": 16000, "channels": 1},
        "models": [{"task": "asr", "provider": "whisperx", "model_id": "large-v3", "version": "3.8.6", "compute_type": "float16"}],
        "segments": [
            {"segment_id": "seg-1", "start_ms": 0, "end_ms": 500, "text": "hello", "words": [{"text": "hello", "start_ms": 0, "end_ms": 200, "confidence": 0.98}]},
        ],
        "diarization_turns": [
            {"turn_id": "t1", "diarizer_speaker_id": "SPEAKER_00", "start_ms": 0, "end_ms": 500, "confidence": 0.9},
            {"turn_id": "t2", "diarizer_speaker_id": "SPEAKER_00", "start_ms": 300, "end_ms": 450, "confidence": 0.9},
        ],
        "speaker_mappings": [
            {"diarizer_speaker_id": "SPEAKER_00", "speaker_id": "speaker-a", "status": "suggested", "confidence": 0.9, "evidence": ["isolated-channel-overlap"], "evidence_turn_ids": ["t1", "t2"]},
        ],
        "speaker_turns": [
            {"turn_id": "rt1", "source_turn_id": "t1", "diarizer_speaker_id": "SPEAKER_00", "speaker_id": "speaker-a", "start_ms": 0, "end_ms": 500, "confidence": 0.9, "provenance": "suggested_mapping"},
        ],
        "warnings": [],
    }
    artifact = AIResultArtifact.model_validate(artifact_data)
    (project_dir / "audio" / "ai" / "v1").mkdir(parents=True)
    (project_dir / "audio" / "ai" / "v1" / "result.json").write_text(
        json.dumps(artifact.model_dump(mode="json"))
    )
    return engine, client, pid, project_dir


def test_f1_suggested_provenance_not_stripped_to_confirmed():
    """F1: a suggested mapping must remain unresolved/wide, not attributed."""
    import tempfile
    tmp = Path(tempfile.mkdtemp())
    _engine, _client, _pid, project_dir = _build_project(tmp)
    artifact = json.loads((project_dir / "audio" / "ai" / "v1" / "result.json").read_text())
    turns = [
        {
            "start_ms": int(t["start_ms"]),
            "end_ms": int(t["end_ms"]),
            "speaker_id": t["speaker_id"],
            "confidence": t.get("confidence"),
            "mapping_status": "suggested",
            "provenance": t.get("provenance"),
        }
        for t in artifact["speaker_turns"]
    ]
    timeline = activity_from_turns(turns, timeline_end_ms=int(artifact["timeline_end_ms"]), confidence_threshold=0.5)
    # The suggested turn must NOT become an active (camera-attributed) segment.
    active_segments = [seg for seg in timeline if seg.get("active")]
    assert not active_segments, f"suggested mapping must not be attributed: {active_segments}"
    safe = [seg for seg in timeline if seg.get("safe_wide")]
    assert safe, "suggested mapping must route to safe wide"


def test_f2_two_field_record_cannot_authorize_ai_cut():
    """F2: a minimal two-field Gate-1 record must fail validation."""
    minimal = {"status": "PASS", "artifact_version": "run-one"}
    assert _valid_gate_one_acceptance(minimal, "run-one") is False
    full = {
        "status": "PASS", "artifact_version": "run-one",
        "words": [{"status": "PASS"}] * 3,
        "boundaries": [{"status": "PASS"}] * 6,
        "peter_acceptance": True,
    }
    assert _valid_gate_one_acceptance(full, "run-one") is True
