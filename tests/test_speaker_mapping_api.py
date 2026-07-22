"""Phase 6 roadmap coverage: speaker mapping projection, snippets, and regeneration gates."""
from __future__ import annotations

import json
import shutil
import subprocess
from pathlib import Path

import pytest
from fastapi.testclient import TestClient
from sqlalchemy import create_engine, select
from sqlalchemy.orm import Session
from sqlalchemy.pool import StaticPool

from autoedit.api import create_app
from autoedit.db.migrate import run_migrations
from autoedit.db.schema import angles, audio_channels, cuts
from autoedit.projects import new_ulid


def _project(tmp_path: Path, *, mappings: list[dict] | None = None, run_id: str = "run-one"):
    engine = create_engine("sqlite://", connect_args={"check_same_thread": False}, poolclass=StaticPool)
    run_migrations(engine)
    client = TestClient(create_app(engine=engine, data_root=tmp_path, auth_enabled=False))
    pid = client.post("/projects", json={"name": "Mapping", "fps_num": 25, "fps_den": 1}).json()["id"]
    left, right, wide = (new_ulid() for _ in range(3))
    with Session(engine) as session:
        session.execute(angles.insert(), [
            {"id": left, "project_id": pid, "label": "A", "role": "cam_left", "source_path": "source/a.mp4"},
            {"id": right, "project_id": pid, "label": "B", "role": "cam_right", "source_path": "source/b.mp4"},
            {"id": wide, "project_id": pid, "label": "Wide", "role": "wide", "source_path": "source/w.mp4"},
        ])
        session.execute(audio_channels.insert(), [
            {"id": new_ulid(), "project_id": pid, "speaker_label": "Alice", "source_angle_id": left, "channel_index": 0},
            {"id": new_ulid(), "project_id": pid, "speaker_label": "Bob", "source_angle_id": right, "channel_index": 0},
        ])
        session.commit()
    project_dir = tmp_path / pid
    artifact = {
        "run_id": run_id, "timeline_end_ms": 5000,
        "diarization_turns": [
            {"turn_id": "t1", "diarizer_speaker_id": "S0", "start_ms": 0, "end_ms": 500},
            {"turn_id": "t2", "diarizer_speaker_id": "S0", "start_ms": 1000, "end_ms": 1500},
            {"turn_id": "t3", "diarizer_speaker_id": "S1", "start_ms": 2000, "end_ms": 2500},
            {"turn_id": "t4", "diarizer_speaker_id": "S1", "start_ms": 3000, "end_ms": 3500},
        ],
        "speaker_mappings": mappings or [],
    }
    artifact_path = project_dir / "audio" / "ai" / "v1" / "result.json"
    artifact_path.parent.mkdir(parents=True)
    artifact_path.write_text(json.dumps(artifact))
    return engine, client, pid, project_dir, left, right, wide


def test_get_projects_bounded_urls_statuses_suggestions_and_allowlist(tmp_path: Path):
    mappings = [
        {"diarizer_speaker_id": "S0", "speaker_id": "Alice", "status": "suggested", "confidence": 0.876},
        {"diarizer_speaker_id": "S1", "speaker_id": "Bob", "status": "suggested", "confidence": None},
    ]
    engine, client, pid, project_dir, left, right, _wide = _project(tmp_path, mappings=mappings)
    body = client.get(f"/projects/{pid}/speaker-confirmations").json()
    assert {item["status"] for item in body["labels"]} == {"suggested"}
    first, second = body["labels"]
    assert first["suggested_speaker_id"] == "Alice"
    assert first["suggested_camera_id"] == left
    assert first["confidence"] == pytest.approx(0.876)
    assert second["suggested_speaker_id"] == "Bob"
    assert second["suggested_camera_id"] == right
    assert second["confidence"] is None
    assert first["snippets"][0]["url"].endswith("start_ms=0&end_ms=500")
    forbidden = {"text", "transcript", "path", "relative_path", "sha256", "hash", "model_id", "prompt", "token"}
    assert not forbidden.intersection(first)
    assert not forbidden.intersection(first["snippets"][0])

    payload = {"diarizer_speaker_id": "S0", "speaker_id": "Alice", "camera_id": left,
               "source_run_id": "run-one", "source_artifact_version": "run-one", "evidence_turn_ids": ["t1", "t2"]}
    assert client.put(f"/projects/{pid}/speaker-confirmations", json=payload).status_code == 200
    assert client.put(f"/projects/{pid}/speaker-confirmations", json=payload).status_code == 200
    assert client.get(f"/projects/{pid}/speaker-confirmations").json()["labels"][0]["status"] == "confirmed"
    stale = json.loads((project_dir / "audio/ai/v1/result.json").read_text())
    stale["run_id"] = "run-two"
    (project_dir / "audio/ai/v1/result.json").write_text(json.dumps(stale))
    labels = client.get(f"/projects/{pid}/speaker-confirmations").json()["labels"]
    assert next(item for item in labels if item["diarizer_speaker_id"] == "S0")["status"] == "stale"
    assert client.put(f"/projects/{pid}/speaker-confirmations", json=payload).status_code == 409


def test_get_needs_confirmation_and_optimistic_version_and_evidence_contract(tmp_path: Path):
    engine, client, pid, _project_dir, left, _right, _wide = _project(tmp_path)
    assert client.get(f"/projects/{pid}/speaker-confirmations").json()["labels"][0]["status"] == "needs_confirmation"
    base = {"diarizer_speaker_id": "S0", "speaker_id": "Alice", "camera_id": left,
            "source_run_id": "run-one", "source_artifact_version": "run-one"}
    assert client.put(f"/projects/{pid}/speaker-confirmations", json={**base, "evidence_turn_ids": ["t1"]}).status_code == 400
    payload = {**base, "evidence_turn_ids": ["t1", "t2"]}
    assert client.put(f"/projects/{pid}/speaker-confirmations", json=payload).status_code == 200
    assert client.put(f"/projects/{pid}/speaker-confirmations", json={**payload, "expected_version": 99}).status_code == 409


def test_whisperx_regeneration_precondition_is_409_and_does_not_change_state(tmp_path: Path):
    engine, client, pid, project_dir, _left, _right, _wide = _project(tmp_path)
    (project_dir / "audio/ai/v1/result.json").unlink()
    audio = project_dir / "audio"
    audio.mkdir(exist_ok=True)
    (audio / "activity.json").write_text(json.dumps({"timeline": [{"start_ms": 0, "end_ms": 5000, "active": []}], "total_duration_ms": 5000}))
    before = list((project_dir / "edit").glob("*")) if (project_dir / "edit").exists() else []
    response = client.post(f"/projects/{pid}/cut", json={"analysis_source": "whisperx"})
    assert response.status_code == 409
    assert not list((project_dir / "edit").glob("*")) if (project_dir / "edit").exists() else True
    with Session(engine) as session:
        assert session.execute(select(cuts).where(cuts.c.project_id == pid)).all() == []
    assert before == []
    assert client.post(f"/projects/{pid}/cut", json={"analysis_source": "vad"}).status_code == 200


def test_bounded_program_audio_media_and_validation(tmp_path: Path):
    if not shutil.which("ffmpeg") or not shutil.which("ffprobe"):
        pytest.fail("ffmpeg and ffprobe are required for TEST-P6-002")
    _engine, client, pid, project_dir, _left, _right, _wide = _project(tmp_path)
    audio = project_dir / "audio"
    audio.mkdir(exist_ok=True)
    program = audio / "program.m4a"
    subprocess.run(["ffmpeg", "-hide_banner", "-loglevel", "error", "-f", "lavfi", "-i", "sine=frequency=440:duration=5", "-c:a", "aac", "-y", str(program)], check=True)
    whole = client.get(f"/projects/{pid}/media/audio/program.m4a")
    assert whole.status_code == 200 and whole.headers["content-type"].startswith("audio/mp4")
    bounded = client.get(f"/projects/{pid}/media/audio/program.m4a?start_ms=1000&end_ms=2500")
    assert bounded.status_code == 200 and bounded.headers["content-type"].startswith("audio/mp4")
    excerpt = project_dir / "audio/snippets/program-1000-2500.m4a"
    probe = subprocess.run(["ffprobe", "-v", "error", "-show_entries", "format=duration", "-of", "csv=p=0", str(excerpt)], check=True, capture_output=True, text=True)
    assert 1.2 < float(probe.stdout.strip()) < 1.8
    assert client.get(f"/projects/{pid}/media/audio/program.m4a?start_ms=2000&end_ms=1000").status_code == 400
    assert client.get(f"/projects/{pid}/media/audio/program.m4a?start_ms=0&end_ms=6000").status_code == 400
    assert client.get(f"/projects/{pid}/media/audio/../program.m4a?start_ms=0&end_ms=100").status_code in {400, 404}
    assert client.get(f"/projects/{pid}/media/audio/secret.wav").status_code == 404
    assert not (project_dir / "source" / "program.m4a").exists()
