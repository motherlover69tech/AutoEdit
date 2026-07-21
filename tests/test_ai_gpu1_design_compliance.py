"""Independent DESIGN_COMPLIANCE verification for the three residual findings.

These are the exact behaviours the authorized bounded exception must prove.
Run against current HEAD. All must pass for DESIGN_COMPLIANCE_PASS.
"""
from __future__ import annotations

import hashlib
import json
import tempfile
from datetime import UTC, datetime
from pathlib import Path

import pytest
from fastapi.testclient import TestClient
from sqlalchemy import create_engine
from sqlalchemy.orm import Session
from sqlalchemy.pool import StaticPool

from autoedit.ai.activity_from_turns import activity_from_turns
from autoedit.ai.contracts import AIResultArtifact
from autoedit.api import create_app, _valid_gate_one_acceptance
from autoedit.db.migrate import run_migrations
from autoedit.db.schema import angles, audio_channels, cuts
from autoedit.projects import new_ulid


def _sha(path: Path) -> str:
    return hashlib.sha256(path.read_bytes()).hexdigest()


def _build(tmp_path: Path, *, confirmed: bool):
    engine = create_engine("sqlite://", connect_args={"check_same_thread": False}, poolclass=StaticPool)
    run_migrations(engine)
    client = TestClient(create_app(engine=engine, data_root=tmp_path, auth_enabled=False))
    project = client.post("/projects", json={"name": "AI", "fps_num": 25, "fps_den": 1}).json()
    pid = project["id"]
    left, right, wide = new_ulid(), new_ulid(), new_ulid()
    with Session(engine) as session:
        session.execute(angles.insert(), [
            {"id": left, "project_id": pid, "label": "A", "role": "cam_left", "source_path": "source/a.mp4", "duration_ms": 6000},
            {"id": right, "project_id": pid, "label": "B", "role": "cam_right", "source_path": "source/b.mp4", "duration_ms": 6000},
            {"id": wide, "project_id": pid, "label": "W", "role": "wide", "source_path": "source/w.mp4", "duration_ms": 6000},
        ])
        session.execute(audio_channels.insert(), [
            {"id": new_ulid(), "project_id": pid, "speaker_label": "speaker-a", "source_angle_id": left, "channel_index": 0},
            {"id": new_ulid(), "project_id": pid, "speaker_label": "speaker-b", "source_angle_id": right, "channel_index": 0},
        ])
        session.commit()

    project_dir = tmp_path / pid
    audio_dir = project_dir / "audio"
    audio_dir.mkdir(parents=True, exist_ok=True)
    (audio_dir / "source-a.wav").write_bytes(b"source-audio-a")
    (audio_dir / "source-b.wav").write_bytes(b"source-audio-b")
    (audio_dir / "ai").mkdir()
    (audio_dir / "ai" / "analysis.wav").write_bytes(b"analysis-audio")

    mapping_status = "confirmed" if confirmed else "suggested"
    provenance = "confirmed_mapping" if confirmed else "suggested_mapping"
    artifact = AIResultArtifact.model_validate({
        "schema_version": "1.0", "run_id": "run-one", "created_at": datetime.now(UTC), "status": "completed",
        "timeline_origin_ms": 0, "timeline_end_ms": 5000,
        "sources": [
            {"source_id": "source-a", "relative_path": "audio/source-a.wav", "sha256": _sha(audio_dir / "source-a.wav"), "duration_ms": 5000, "sample_rate": 48000, "channels": 1, "sync_offset_ms": 0},
            {"source_id": "source-b", "relative_path": "audio/source-b.wav", "sha256": _sha(audio_dir / "source-b.wav"), "duration_ms": 5000, "sample_rate": 48000, "channels": 1, "sync_offset_ms": 0},
        ],
        "analysis_audio": {"relative_path": "audio/ai/analysis.wav", "sha256": _sha(audio_dir / "ai" / "analysis.wav"), "strategy": "isolated_lav", "duration_ms": 5000, "sample_rate": 16000, "channels": 1},
        "models": [{"task": "asr", "provider": "whisperx", "model_id": "large-v3", "version": "3.8.6", "compute_type": "float16"}],
        "segments": [{"segment_id": "seg-1", "start_ms": 0, "end_ms": 500, "text": "hello", "words": [{"text": "hello", "start_ms": 0, "end_ms": 200, "confidence": 0.98}]}],
        "diarization_turns": [
            {"turn_id": "t1", "diarizer_speaker_id": "SPEAKER_00", "start_ms": 0, "end_ms": 500, "confidence": 0.9},
            {"turn_id": "t2", "diarizer_speaker_id": "SPEAKER_00", "start_ms": 300, "end_ms": 450, "confidence": 0.9},
            {"turn_id": "t3", "diarizer_speaker_id": "SPEAKER_01", "start_ms": 2000, "end_ms": 2500, "confidence": 0.9},
            {"turn_id": "t4", "diarizer_speaker_id": "SPEAKER_01", "start_ms": 2100, "end_ms": 2400, "confidence": 0.9},
        ],
        "speaker_mappings": [
            {"diarizer_speaker_id": "SPEAKER_00", "speaker_id": "speaker-a", "status": mapping_status, "confidence": 0.9, "evidence": ["e"], "evidence_turn_ids": ["t1", "t2"]},
            {"diarizer_speaker_id": "SPEAKER_01", "speaker_id": "speaker-b", "status": mapping_status, "confidence": 0.9, "evidence": ["e"], "evidence_turn_ids": ["t3", "t4"]},
        ],
        "speaker_turns": [
            {"turn_id": "rt1", "source_turn_id": "t1", "diarizer_speaker_id": "SPEAKER_00", "speaker_id": "speaker-a", "start_ms": 0, "end_ms": 500, "confidence": 0.9, "provenance": provenance},
            {"turn_id": "rt3", "source_turn_id": "t3", "diarizer_speaker_id": "SPEAKER_01", "speaker_id": "speaker-b", "start_ms": 2000, "end_ms": 2500, "confidence": 0.9, "provenance": provenance},
        ],
        "warnings": [],
    })
    (project_dir / "audio" / "ai" / "v1").mkdir(parents=True)
    (project_dir / "audio" / "ai" / "v1" / "result.json").write_text(json.dumps(artifact.model_dump(mode="json")))
    (audio_dir / "activity.json").write_text(json.dumps({"timeline": [{"start_ms": 0, "end_ms": 5000, "active": [], "source": "vad"}], "total_duration_ms": 5000}))
    return engine, client, pid, project_dir, left, right


# ── Finding 1: confirmation provenance is never stripped before projection ──
def test_dc_f1_suggested_maps_to_safe_wide_not_camera():
    tmp = Path(tempfile.mkdtemp())
    _engine, _client, _pid, project_dir, _left, _right = _build(tmp, confirmed=False)
    artifact = json.loads((project_dir / "audio" / "ai" / "v1" / "result.json").read_text())
    turns = [
        {"start_ms": int(t["start_ms"]), "end_ms": int(t["end_ms"]), "speaker_id": t["speaker_id"],
         "confidence": t.get("confidence"), "mapping_status": "suggested", "provenance": t.get("provenance")}
        for t in artifact["speaker_turns"]
    ]
    timeline = activity_from_turns(turns, timeline_end_ms=int(artifact["timeline_end_ms"]), confidence_threshold=0.5)
    assert not any(seg.get("active") for seg in timeline), "suggested identity must not be camera-attributed"
    assert any(seg.get("safe_wide") for seg in timeline), "suggested identity must route to safe wide"


def test_dc_f1_provenance_field_required_on_resolved_turn_contract():
    # A ResolvedSpeakerTurn missing provenance must fail strict contract validation.
    with pytest.raises(Exception):
        AIResultArtifact.model_validate({
            "schema_version": "1.0", "run_id": "r", "created_at": datetime.now(UTC), "status": "completed",
            "timeline_origin_ms": 0, "timeline_end_ms": 100,
            "sources": [{"source_id": "s", "relative_path": "audio/x.wav", "sha256": "0" * 64, "duration_ms": 100, "sample_rate": 16000, "channels": 1, "sync_offset_ms": 0}],
            "analysis_audio": {"relative_path": "audio/y.wav", "sha256": "0" * 64, "strategy": "isolated_lav", "duration_ms": 100, "sample_rate": 16000, "channels": 1},
            "models": [{"task": "asr", "provider": "whisperx", "model_id": "m", "version": "v"}],
            "speaker_turns": [
                {"turn_id": "rt", "source_turn_id": "t", "diarizer_speaker_id": "S0", "speaker_id": "spk", "start_ms": 0, "end_ms": 100, "confidence": 0.9}
            ],
        })


# ── Finding 2: Gate 1 cannot be bypassed by a two-field self-asserted record ──
def test_dc_f2_minimal_two_field_record_rejected():
    assert _valid_gate_one_acceptance({"status": "PASS", "artifact_version": "run-one"}, "run-one") is False


def test_dc_f2_version_mismatch_rejected():
    full = {"status": "PASS", "artifact_version": "run-one", "words": [{"status": "PASS"}] * 3,
            "boundaries": [{"status": "PASS"}] * 6, "peter_acceptance": True}
    assert _valid_gate_one_acceptance(full, "run-two") is False


def test_dc_f2_missing_peter_acceptance_rejected():
    partial = {"status": "PASS", "artifact_version": "run-one", "words": [{"status": "PASS"}] * 3,
               "boundaries": [{"status": "PASS"}] * 6}
    assert _valid_gate_one_acceptance(partial, "run-one") is False


def test_dc_f2_stale_confirmation_record_rejected_by_cut_route():
    tmp = Path(tempfile.mkdtemp())
    _engine, client, pid, project_dir, left, right = _build(tmp, confirmed=True)
    # Persist a confirmation bound to a DIFFERENT (stale) version.
    payload = {"diarizer_speaker_id": "SPEAKER_00", "speaker_id": "speaker-a", "camera_id": left,
               "source_run_id": "OLD", "source_artifact_version": "OLD", "evidence_turn_ids": ["t1", "t2"]}
    assert client.put(f"/projects/{pid}/speaker-confirmations", json=payload).status_code == 409
    # No current-version confirmations → cut must be blocked.
    (project_dir / "audio" / "ai" / "v1" / "word-timing-review.json").write_text(json.dumps(
        {"status": "PASS", "artifact_version": "run-one", "words": [{"status": "PASS"}] * 3,
         "boundaries": [{"status": "PASS"}] * 6, "peter_acceptance": True}))
    response = client.post(f"/projects/{pid}/cut", json={"analysis_source": "whisperx"})
    assert response.status_code == 409, response.text


def test_dc_f2_self_asserted_confirmation_with_nonexistent_turns_rejected():
    tmp = Path(tempfile.mkdtemp())
    _engine, client, pid, _project_dir, left, _right = _build(tmp, confirmed=True)
    # Two turn IDs that do not belong to the asserted label.
    payload = {"diarizer_speaker_id": "SPEAKER_00", "speaker_id": "speaker-a", "camera_id": left,
               "source_run_id": "run-one", "source_artifact_version": "run-one",
               "evidence_turn_ids": ["t3", "t4"]}
    assert client.put(f"/projects/{pid}/speaker-confirmations", json=payload).status_code == 400


# ── Finding 3: Gate-1 / valid-unverified / rollback regressions committed ──
def test_dc_f3_atomicity_rollback_on_db_failure():
    tmp = Path(tempfile.mkdtemp())
    engine, client, pid, _project_dir, left, right = _build(tmp, confirmed=True)
    (tmp / pid / "audio" / "ai" / "v1" / "word-timing-review.json").write_text(json.dumps(
        {"status": "PASS", "artifact_version": "run-one", "words": [{"status": "PASS"}] * 3,
         "boundaries": [{"status": "PASS"}] * 6, "peter_acceptance": True}))
    payload_a = {"diarizer_speaker_id": "SPEAKER_00", "speaker_id": "speaker-a", "camera_id": left,
                 "source_run_id": "run-one", "source_artifact_version": "run-one", "evidence_turn_ids": ["t1", "t2"]}
    payload_b = {"diarizer_speaker_id": "SPEAKER_01", "speaker_id": "speaker-b", "camera_id": right,
                 "source_run_id": "run-one", "source_artifact_version": "run-one", "evidence_turn_ids": ["t3", "t4"]}
    assert client.put(f"/projects/{pid}/speaker-confirmations", json=payload_a).status_code == 200
    assert client.put(f"/projects/{pid}/speaker-confirmations", json=payload_b).status_code == 200

    fail_client = TestClient(client.app, raise_server_exceptions=False)
    activity_path = tmp / pid / "audio" / "ai" / "v1" / "activity-whisperx.json"
    cdl_path = tmp / pid / "edit" / "cdl_whisperx_run-one.json"
    real_insert = cuts.insert

    def _failing_insert(*a, **k):
        raise RuntimeError("simulated DB failure")
    cuts.insert = staticmethod(_failing_insert)
    try:
        resp = fail_client.post(f"/projects/{pid}/cut", json={"analysis_source": "whisperx"})
        assert resp.status_code >= 500, resp.text
    finally:
        cuts.insert = real_insert
    assert not activity_path.exists(), "activity artifact must roll back"
    assert not cdl_path.exists(), "CDL must roll back"
    with Session(engine) as session:
        assert len(session.execute(cuts.select().where(cuts.c.project_id == pid)).all()) == 0


def test_dc_f3_valid_unverified_artifact_fails_closed():
    from autoedit.ai.activity_from_turns import ArtifactImportError
    tmp = Path(tempfile.mkdtemp())
    _engine, _client, _pid, project_dir, _l, _r = _build(tmp, confirmed=True)
    artifact = json.loads((project_dir / "audio" / "ai" / "v1" / "result.json").read_text())
    with pytest.raises(ArtifactImportError, match="source-bound"):
        from autoedit.ai.activity_from_turns import import_artifact
        import_artifact(artifact)  # no AIArtifactStore passed → source verification required
