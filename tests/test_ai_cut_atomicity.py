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
    # Required by the public player-state endpoint used to verify selection.
    (audio_dir / "program.m4a").write_bytes(b"program-audio")
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
    _seed_prior_vad_cut(engine, tmp_path, pid)
    prior_bytes = (tmp_path / pid / "edit" / "cdl.json").read_bytes()
    prior_player_cut = _selected_player_cut(client, pid)
    # In production the DB error becomes a 500 via FastAPI's handler; the
    # helper below uses that same non-raising TestClient behavior.
    activity_path = tmp_path / pid / "audio" / "ai" / "v1" / "activity-whisperx.json"
    cdl_path = tmp_path / pid / "edit" / "cdl_whisperx_run-one.json"

    # Force the DB cut-row insert to fail AFTER activity/CDL are computed.
    real_insert = cuts.insert

    def _failing_insert(*args, **kwargs):
        raise RuntimeError("simulated DB failure")

    cuts.insert = staticmethod(_failing_insert)
    try:
        _assert_failed_publication(engine, client, tmp_path, pid, prior_bytes, prior_player_cut)
    finally:
        cuts.insert = real_insert

    # No partial artifact/cut pair may survive the failure.
    assert not activity_path.exists(), "activity-whisperx.json must not be written on DB failure"
    assert not cdl_path.exists(), "CDL file must not be written on DB failure"
    with Session(engine) as session:
        rows = session.execute(cuts.select().where(cuts.c.project_id == pid)).all()
    assert [(row._mapping["kind"], row._mapping["name"]) for row in rows] == [("rough", "Prior VAD")]


def _seed_prior_vad_cut(engine, tmp_path: Path, pid: str) -> None:
    prior_cdl = {"version": 1, "analysis_source": "vad", "clips": [{"angle_id": "prior", "timeline_in_ms": 0, "src_in_ms": 0, "dur_ms": 5000}]}
    edit_dir = tmp_path / pid / "edit"
    edit_dir.mkdir(parents=True, exist_ok=True)
    (edit_dir / "cdl.json").write_text(json.dumps(prior_cdl) + "\n")
    with Session(engine) as session:
        session.execute(cuts.insert().values(id=new_ulid(), project_id=pid, name="Prior VAD", kind="rough", params_json={"profile": "vad"}, cdl_json=prior_cdl))
        session.commit()


def _assert_prior_vad_preserved(engine, client, tmp_path: Path, pid: str) -> None:
    cdl_path = tmp_path / pid / "edit" / "cdl.json"
    assert json.loads(cdl_path.read_text())["analysis_source"] == "vad"
    with Session(engine) as session:
        rows = session.execute(cuts.select().where(cuts.c.project_id == pid).order_by(cuts.c.kind)).all()
    assert [(row._mapping["kind"], row._mapping["name"]) for row in rows] == [("rough", "Prior VAD")]


def _selected_player_cut(client, pid: str) -> dict:
    response = client.get(f"/projects/{pid}/player-state")
    assert response.status_code == 200, response.text
    return response.json()["cut"]


def _assert_failed_publication(
    engine, client, tmp_path: Path, pid: str, prior_bytes: bytes, prior_player_cut: dict
) -> None:
    response = TestClient(client.app, raise_server_exceptions=False).post(
        f"/projects/{pid}/cut", json={}
    )
    assert response.status_code == 500, response.text
    assert (tmp_path / pid / "edit" / "cdl.json").read_bytes() == prior_bytes
    assert _selected_player_cut(client, pid) == prior_player_cut
    with Session(engine) as session:
        rows = session.execute(cuts.select().where(cuts.c.project_id == pid)).all()
    assert not any(row._mapping["kind"] == "ai" for row in rows)
    rough = next(row._mapping for row in rows if row._mapping["kind"] == "rough")
    assert rough["name"] == "Prior VAD"
    assert rough["cdl_json"]["analysis_source"] == "vad"


def test_ai_cut_candidate_cdl_write_failure_preserves_prior_vad(tmp_path: Path, monkeypatch: pytest.MonkeyPatch):
    engine, client, pid = _build_confirmed_ai_project(tmp_path)
    _seed_prior_vad_cut(engine, tmp_path, pid)
    prior_bytes = (tmp_path / pid / "edit" / "cdl.json").read_bytes()
    prior_player_cut = _selected_player_cut(client, pid)
    original = Path.write_text

    def fail_candidate(path: Path, data: str, *args, **kwargs):
        if "cdl_whisperx" in path.name:
            raise OSError("simulated candidate CDL write failure")
        return original(path, data, *args, **kwargs)

    monkeypatch.setattr(Path, "write_text", fail_candidate)
    _assert_failed_publication(engine, client, tmp_path, pid, prior_bytes, prior_player_cut)


def test_ai_cut_partial_staging_write_leaves_no_temp_file(tmp_path: Path, monkeypatch: pytest.MonkeyPatch):
    engine, client, pid = _build_confirmed_ai_project(tmp_path)
    _seed_prior_vad_cut(engine, tmp_path, pid)
    original = Path.write_text

    def fail_after_partial_write(path: Path, data: str, *args, **kwargs):
        if "cdl_whisperx" in path.name:
            original(path, data[:8], *args, **kwargs)
            raise OSError("simulated partial candidate CDL write failure")
        return original(path, data, *args, **kwargs)

    monkeypatch.setattr(Path, "write_text", fail_after_partial_write)
    response = TestClient(client.app, raise_server_exceptions=False).post(f"/projects/{pid}/cut", json={})
    assert response.status_code >= 500
    assert not list((tmp_path / pid / "edit").glob("cdl_whisperx_*.tmp"))
    _assert_prior_vad_preserved(engine, client, tmp_path, pid)


def test_ai_cut_activity_write_failure_preserves_prior_vad(tmp_path: Path, monkeypatch: pytest.MonkeyPatch):
    engine, client, pid = _build_confirmed_ai_project(tmp_path)
    _seed_prior_vad_cut(engine, tmp_path, pid)
    prior_bytes = (tmp_path / pid / "edit" / "cdl.json").read_bytes()
    prior_player_cut = _selected_player_cut(client, pid)
    original = Path.write_text

    def fail_activity(path: Path, data: str, *args, **kwargs):
        if "activity-whisperx" in path.name:
            raise OSError("simulated activity write failure")
        return original(path, data, *args, **kwargs)

    monkeypatch.setattr(Path, "write_text", fail_activity)
    _assert_failed_publication(engine, client, tmp_path, pid, prior_bytes, prior_player_cut)


def test_ai_cut_replace_failure_preserves_prior_vad(tmp_path: Path, monkeypatch: pytest.MonkeyPatch):
    engine, client, pid = _build_confirmed_ai_project(tmp_path)
    _seed_prior_vad_cut(engine, tmp_path, pid)
    original = Path.replace

    def fail_activity_replace(path: Path, target: str | Path, *args, **kwargs):
        if "activity-whisperx" in str(target):
            raise OSError("simulated activity replace failure")
        return original(path, target, *args, **kwargs)

    monkeypatch.setattr(Path, "replace", fail_activity_replace)
    response = TestClient(client.app, raise_server_exceptions=False).post(f"/projects/{pid}/cut", json={})
    assert response.status_code >= 500
    _assert_prior_vad_preserved(engine, client, tmp_path, pid)


def test_ai_cut_persists_all_sides_on_success(tmp_path: Path):
    engine, client, pid = _build_confirmed_ai_project(tmp_path)
    _seed_prior_vad_cut(engine, tmp_path, pid)
    prior_bytes = (tmp_path / pid / "edit" / "cdl.json").read_bytes()
    prior_player_cut = _selected_player_cut(client, pid)
    response = client.post(f"/projects/{pid}/cut", json={})
    assert response.status_code == 200, response.text
    cdl = response.json()
    assert cdl["analysis_source"] == "whisperx"
    assert cdl["conditions"] == {
        "missing_wide": False,
        "unresolved": False,
        "low_confidence": False,
        "overlap": False,
        "off_camera": False,
    }

    activity_path = tmp_path / pid / "audio" / "ai" / "v1" / "activity-whisperx.json"
    cdl_path = tmp_path / pid / "edit" / "cdl_whisperx_run-one.json"
    assert activity_path.is_file(), "activity artifact must be published on success"
    assert cdl_path.is_file(), "CDL file must be published on success"
    assert (tmp_path / pid / "edit" / "cdl.json").read_bytes() == prior_bytes
    assert _selected_player_cut(client, pid) == prior_player_cut
    with Session(engine) as session:
        rows = session.execute(
            cuts.select().where(cuts.c.project_id == pid).order_by(cuts.c.kind.desc())
        ).all()
    assert [row._mapping["kind"] for row in rows] == ["rough", "ai"]
    ai_row = next(row._mapping for row in rows if row._mapping["kind"] == "ai")
    # Persistence must retain the complete candidate, not only fields needed
    # for angle selection. Compare every clip with the API response.
    assert ai_row["cdl_json"]["clips"] == cdl["clips"]
    persisted_clip = ai_row["cdl_json"]["clips"][0]
    # The DB JSON must be a lossless copy of the API clip object, including
    # projection authority/status and all explicit safety-condition flags.
    assert persisted_clip == cdl["clips"][0]
    assert {
        "src_in_ms", "timeline_in_ms", "dur_ms", "reason", "reason_code",
        "source", "mapping_status", "authority_status", "confidence",
        "unresolved", "low_confidence", "overlap", "off_camera", "missing_wide",
        "projection",
    } <= persisted_clip.keys()
    assert persisted_clip["projection"]["start_ms"] == 0
    assert persisted_clip["projection"]["end_ms"] == 500


def test_confirmed_solo_projection_selects_mapped_close_camera(tmp_path: Path):
    _engine, client, pid = _build_confirmed_ai_project(tmp_path)
    response = client.post(f"/projects/{pid}/cut", json={})
    assert response.status_code == 200, response.text
    clips = response.json()["clips"]
    assert clips[0]["angle_id"] != "wide"
    assert clips[0]["timeline_in_ms"] == 0
    # 500 ms is represented on the canonical frame grid (12 frames at 25 fps).
    assert clips[0]["dur_ms"] == 480
    assert clips[0]["reason_code"] == "speaking"


def test_ai_cut_reports_missing_wide_condition(tmp_path: Path):
    engine, client, pid = _build_confirmed_ai_project(tmp_path)
    with Session(engine) as session:
        session.execute(angles.delete().where(angles.c.project_id == pid, angles.c.role == "wide"))
        session.commit()

    response = client.post(f"/projects/{pid}/cut", json={})
    assert response.status_code == 422
    detail = response.json()["detail"]
    assert "wide angle" in detail["message"]
    assert detail["conditions"]["missing_wide"] is True


def test_ai_cut_reports_low_confidence_condition_in_api_and_persistence(tmp_path: Path):
    engine, client, pid = _build_confirmed_ai_project(tmp_path)
    result_path = tmp_path / pid / "audio" / "ai" / "v1" / "result.json"
    artifact = json.loads(result_path.read_text())
    artifact["speaker_turns"][0]["confidence"] = 0.1
    result_path.write_text(json.dumps(artifact))

    response = client.post(f"/projects/{pid}/cut", json={})
    assert response.status_code == 200, response.text
    cdl = response.json()
    assert cdl["conditions"]["low_confidence"] is True
    low_confidence = next(clip for clip in cdl["clips"] if clip["timeline_in_ms"] == 0)
    assert low_confidence["low_confidence"] is True
    with Session(engine) as session:
        row = session.execute(
            cuts.select().where(cuts.c.project_id == pid, cuts.c.kind == "ai")
        ).one()
    assert row._mapping["cdl_json"]["conditions"]["low_confidence"] is True
    assert row._mapping["cdl_json"]["clips"] == cdl["clips"]


def test_ai_cut_rejects_malformed_artifact_through_api(tmp_path: Path):
    _engine, client, pid = _build_confirmed_ai_project(tmp_path)
    result_path = tmp_path / pid / "audio" / "ai" / "v1" / "result.json"
    result_path.write_text(json.dumps({"schema_version": "1.0", "run_id": "run-one"}))

    response = client.post(f"/projects/{pid}/cut", json={})
    assert response.status_code == 422, response.text
    assert "invalid AI result artifact" in str(response.json()["detail"])


def test_ai_cut_rejects_out_of_range_artifact_through_api(tmp_path: Path):
    _engine, client, pid = _build_confirmed_ai_project(tmp_path)
    result_path = tmp_path / pid / "audio" / "ai" / "v1" / "result.json"
    artifact = json.loads(result_path.read_text())
    artifact["speaker_turns"][0]["start_ms"] = -1
    result_path.write_text(json.dumps(artifact))

    response = client.post(f"/projects/{pid}/cut", json={})
    assert response.status_code == 422, response.text
    assert "invalid AI result artifact" in str(response.json()["detail"])


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
