from __future__ import annotations

import json
from pathlib import Path

from fastapi.testclient import TestClient
from sqlalchemy import create_engine
from sqlalchemy.pool import StaticPool

from autoedit.api import create_app
from autoedit.db.migrate import run_migrations
from autoedit.db.schema import angles, audio_channels
from autoedit.projects import new_ulid
from sqlalchemy.orm import Session


def test_speaker_confirmation_persists_bijection_and_rejects_stale(tmp_path: Path):
    engine = create_engine("sqlite://", connect_args={"check_same_thread": False}, poolclass=StaticPool)
    run_migrations(engine)
    client = TestClient(create_app(engine=engine, data_root=tmp_path, auth_enabled=False))
    project = client.post("/projects", json={"name": "AI", "fps_num": 25, "fps_den": 1}).json()
    pid = project["id"]
    left, right = new_ulid(), new_ulid()
    with Session(engine) as session:
        session.execute(angles.insert(), [
            {"id": left, "project_id": pid, "label": "A", "role": "cam_left", "source_path": "source/a.mp4"},
            {"id": right, "project_id": pid, "label": "B", "role": "cam_right", "source_path": "source/b.mp4"},
        ])
        session.execute(audio_channels.insert(), [
            {"id": new_ulid(), "project_id": pid, "speaker_label": "Alice", "source_angle_id": left, "channel_index": 0},
            {"id": new_ulid(), "project_id": pid, "speaker_label": "Bob", "source_angle_id": right, "channel_index": 0},
        ])
        session.commit()
    artifact = {
        "run_id": "run-one", "timeline_end_ms": 5000,
        "diarization_turns": [
            {"turn_id": "t1", "diarizer_speaker_id": "S0", "start_ms": 0, "end_ms": 500},
            {"turn_id": "t2", "diarizer_speaker_id": "S0", "start_ms": 1000, "end_ms": 1500},
            {"turn_id": "t3", "diarizer_speaker_id": "S1", "start_ms": 2000, "end_ms": 2500},
            {"turn_id": "t4", "diarizer_speaker_id": "S1", "start_ms": 3000, "end_ms": 3500},
        ],
    }
    artifact_path = tmp_path / pid / "audio" / "ai" / "v1" / "result.json"
    artifact_path.parent.mkdir(parents=True)
    artifact_path.write_text(json.dumps(artifact))
    response = client.get(f"/projects/{pid}/speaker-confirmations")
    assert response.status_code == 200
    body = response.json()
    assert all(len(item["snippets"]) == 2 for item in body["labels"])
    payload = {"diarizer_speaker_id": "S0", "speaker_id": "Alice", "camera_id": left, "source_run_id": "run-one", "source_artifact_version": "run-one", "evidence_turn_ids": ["t1", "t2"]}
    assert client.put(f"/projects/{pid}/speaker-confirmations", json=payload).status_code == 200
    assert client.put(f"/projects/{pid}/speaker-confirmations", json={**payload, "diarizer_speaker_id": "S1", "speaker_id": "Alice", "camera_id": right, "evidence_turn_ids": ["t3", "t4"]}).status_code == 409
    artifact["run_id"] = "run-two"
    artifact_path.write_text(json.dumps(artifact))
    assert client.put(f"/projects/{pid}/speaker-confirmations", json=payload).status_code == 409
    assert client.get(f"/projects/{pid}/speaker-confirmations").json()["labels"][0]["status"] == "stale"
