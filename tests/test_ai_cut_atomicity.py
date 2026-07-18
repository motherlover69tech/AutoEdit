"""Round-2 repair regression: AI cut persistence must be atomic.

The activity artifact, CDL file, and DB cut row are written as one operation.
A DB failure after CDL generation must roll every side back so no partial
artifact/cut pair survives (closes the non-transactional cut-selection finding).
"""
from __future__ import annotations

import hashlib
import json
from datetime import UTC, datetime
from pathlib import Path

import pytest
from fastapi.testclient import TestClient
from sqlalchemy import create_engine
from sqlalchemy.orm import Session
from sqlalchemy.pool import StaticPool

from autoedit.ai.contracts import AIResultArtifact
from autoedit.ai.activity_from_turns import ArtifactImportError, import_artifact
from autoedit.api import create_app
from autoedit.db.migrate import run_migrations
from autoedit.db.schema import angles, audio_channels, cuts
from autoedit.projects import new_ulid


def _sha(path: Path) -> str:
    return hashlib.sha256(path.read_bytes()).hexdigest()


def _build_confirmed_ai_project(tmp_path: Path):
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
    # Source + analysis WAVs must exist so the store's input-hash verification passes.
    (audio_dir / "source-a.wav").write_bytes(b"source-audio-a")
    (audio_dir / "source-b.wav").write_bytes(b"source-audio-b")
    (audio_dir / "ai").mkdir()
    (audio_dir / "ai" / "analysis.wav").write_bytes(b"analysis-audio")

    artifact = AIResultArtifact.model_validate(
        {
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
                {"segment_id": "seg-2", "start_ms": 2000, "end_ms": 2500, "text": "world", "words": [{"text": "world", "start_ms": 2000, "end_ms": 2200, "confidence": 0.97}]},
            ],
            "diarization_turns": [
                {"turn_id": "t1", "diarizer_speaker_id": "SPEAKER_00", "start_ms": 0, "end_ms": 500, "confidence": 0.9},
                {"turn_id": "t2", "diarizer_speaker_id": "SPEAKER_00", "start_ms": 300, "end_ms": 450, "confidence": 0.9},
                {"turn_id": "t3", "diarizer_speaker_id": "SPEAKER_01", "start_ms": 2000, "end_ms": 2500, "confidence": 0.9},
                {"turn_id": "t4", "diarizer_speaker_id": "SPEAKER_01", "start_ms": 2100, "end_ms": 2400, "confidence": 0.9},
            ],
            "speaker_mappings": [
                {"diarizer_speaker_id": "SPEAKER_00", "speaker_id": "speaker-a", "status": "confirmed", "confidence": 0.9, "evidence": ["isolated-channel-overlap"], "operator_id": "operator", "source_run_id": "run-one", "source_artifact_version": "run-one", "evidence_turn_ids": ["t1", "t2"]},
                {"diarizer_speaker_id": "SPEAKER_01", "speaker_id": "speaker-b", "status": "confirmed", "confidence": 0.9, "evidence": ["isolated-channel-overlap"], "operator_id": "operator", "source_run_id": "run-one", "source_artifact_version": "run-one", "evidence_turn_ids": ["t3", "t4"]},
            ],
            "speaker_turns": [
                {"turn_id": "rt1", "source_turn_id": "t1", "diarizer_speaker_id": "SPEAKER_00", "speaker_id": "speaker-a", "start_ms": 0, "end_ms": 500, "confidence": 0.9, "provenance": "confirmed_mapping"},
                {"turn_id": "rt3", "source_turn_id": "t3", "diarizer_speaker_id": "SPEAKER_01", "speaker_id": "speaker-b", "start_ms": 2000, "end_ms": 2500, "confidence": 0.9, "provenance": "confirmed_mapping"},
            ],
            "warnings": [],
        }
    )
    (project_dir / "audio" / "ai" / "v1").mkdir(parents=True)
    (project_dir / "audio" / "ai" / "v1" / "result.json").write_text(
        json.dumps(artifact.model_dump(mode="json"))
    )

    # Gate 1 word-timing acceptance recorded as PASS for this version.
    (project_dir / "audio" / "ai" / "v1" / "word-timing-review.json").write_text(
        json.dumps({
            "status": "PASS", "artifact_version": "run-one",
            "words": [{"status": "PASS"}] * 3,
            "boundaries": [{"status": "PASS"}] * 6,
            "peter_acceptance": True,
        })
    )

    # The /cut route requires the VAD baseline activity.json to exist.
    (audio_dir / "activity.json").write_text(
        json.dumps({"timeline": [{"start_ms": 0, "end_ms": 5000, "active": [], "source": "vad"}], "total_duration_ms": 5000})
    )

    # Confirm both speakers (two distinct evidence turns each, bijective).
    payload_a = {"diarizer_speaker_id": "SPEAKER_00", "speaker_id": "speaker-a", "camera_id": left, "source_run_id": "run-one", "source_artifact_version": "run-one", "evidence_turn_ids": ["t1", "t2"]}
    payload_b = {"diarizer_speaker_id": "SPEAKER_01", "speaker_id": "speaker-b", "camera_id": right, "source_run_id": "run-one", "source_artifact_version": "run-one", "evidence_turn_ids": ["t3", "t4"]}
    assert client.put(f"/projects/{pid}/speaker-confirmations", json=payload_a).status_code == 200
    assert client.put(f"/projects/{pid}/speaker-confirmations", json=payload_b).status_code == 200

    return engine, client, pid


def test_ai_cut_is_atomic_on_db_failure(tmp_path: Path):
    engine, client, pid = _build_confirmed_ai_project(tmp_path)
    # In production the DB error becomes a 500 via FastAPI's handler; mirror
    # that here so we can assert on the response and the rolled-back files.
    fail_client = TestClient(
        client.app, raise_server_exceptions=False
    )
    activity_path = tmp_path / pid / "audio" / "ai" / "v1" / "activity-whisperx.json"
    cdl_path = tmp_path / pid / "edit" / "cdl_whisperx_run-one.json"

    # Force the DB cut-row insert to fail AFTER activity/CDL are computed.
    real_insert = cuts.insert

    def _failing_insert(*args, **kwargs):
        raise RuntimeError("simulated DB failure")

    cuts.insert = staticmethod(_failing_insert)
    try:
        response = fail_client.post(f"/projects/{pid}/cut", json={})
        assert response.status_code >= 500, response.text
    finally:
        cuts.insert = real_insert

    # No partial artifact/cut pair may survive the failure.
    assert not activity_path.exists(), "activity-whisperx.json must not be written on DB failure"
    assert not cdl_path.exists(), "CDL file must not be written on DB failure"
    with Session(engine) as session:
        rows = session.execute(cuts.select().where(cuts.c.project_id == pid)).all()
    assert len(rows) == 0, "no cut row may survive a failed transaction"


def test_ai_cut_persists_all_sides_on_success(tmp_path: Path):
    engine, client, pid = _build_confirmed_ai_project(tmp_path)
    response = client.post(f"/projects/{pid}/cut", json={})
    assert response.status_code == 200, response.text
    cdl = response.json()
    assert cdl["analysis_source"] == "whisperx"

    activity_path = tmp_path / pid / "audio" / "ai" / "v1" / "activity-whisperx.json"
    cdl_path = tmp_path / pid / "edit" / "cdl_whisperx_run-one.json"
    assert activity_path.is_file(), "activity artifact must be published on success"
    assert cdl_path.is_file(), "CDL file must be published on success"
    with Session(engine) as session:
        rows = session.execute(cuts.select().where(cuts.c.project_id == pid)).all()
    assert len(rows) == 1, "exactly one cut row must be persisted"
    assert rows[0]._mapping["kind"] == "ai"


def test_confirmed_solo_projection_selects_mapped_close_camera(tmp_path: Path):
    _engine, client, pid = _build_confirmed_ai_project(tmp_path)
    response = client.post(f"/projects/{pid}/cut", json={})
    assert response.status_code == 200, response.text
    clips = response.json()["clips"]
    assert clips[0]["angle_id"] != "wide"
    assert clips[0]["reason_code"] == "speaking"


def test_gate_one_two_field_flag_cannot_authorize_ai_cut(tmp_path: Path):
    _engine, client, pid = _build_confirmed_ai_project(tmp_path)
    gate_path = tmp_path / pid / "audio" / "ai" / "v1" / "word-timing-review.json"
    gate_path.write_text(json.dumps({"status": "PASS", "artifact_version": "run-one"}))
    response = client.post(f"/projects/{pid}/cut", json={})
    assert response.status_code == 409
    assert "Gate 1" in response.json()["detail"]


def test_valid_nonempty_artifact_without_source_verification_fails_closed(tmp_path: Path):
    _engine, _client, pid = _build_confirmed_ai_project(tmp_path)
    artifact = json.loads(
        (tmp_path / pid / "audio" / "ai" / "v1" / "result.json").read_text()
    )
    with pytest.raises(ArtifactImportError, match="source-bound"):
        import_artifact(artifact)
