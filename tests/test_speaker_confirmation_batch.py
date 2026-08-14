from __future__ import annotations

import json
from pathlib import Path

from fastapi.testclient import TestClient
from sqlalchemy import create_engine, select
from sqlalchemy.orm import Session
from sqlalchemy.pool import StaticPool

from autoedit.api import create_app
from autoedit.db.migrate import run_migrations
from autoedit.db.schema import angles, audio_channels, speaker_confirmations
from autoedit.projects import new_ulid


def _project(tmp_path: Path):
    engine = create_engine(
        "sqlite://", connect_args={"check_same_thread": False}, poolclass=StaticPool
    )
    run_migrations(engine)
    client = TestClient(create_app(engine=engine, data_root=tmp_path, auth_enabled=False))
    pid = client.post(
        "/projects", json={"name": "Batch mapping", "fps_num": 25, "fps_den": 1}
    ).json()["id"]
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
        "run_id": "run-one",
        "timeline_end_ms": 5000,
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
    return engine, client, pid, left, right


def _single(label: str, speaker: str, camera: str, turns: list[str]):
    return {
        "diarizer_speaker_id": label,
        "speaker_id": speaker,
        "camera_id": camera,
        "source_run_id": "run-one",
        "source_artifact_version": "run-one",
        "evidence_turn_ids": turns,
    }


def _rows(engine, pid: str):
    with Session(engine) as session:
        rows = session.execute(
            select(speaker_confirmations)
            .where(speaker_confirmations.c.project_id == pid)
            .order_by(speaker_confirmations.c.diarizer_speaker_id)
        ).all()
    return [dict(row._mapping) for row in rows]


def test_complete_two_row_swap_is_one_atomic_batch_and_incomplete_batch_rolls_back(tmp_path: Path):
    engine, client, pid, left, right = _project(tmp_path)
    assert client.put(
        f"/projects/{pid}/speaker-confirmations",
        json=_single("S0", "Alice", left, ["t1", "t2"]),
    ).status_code == 200
    assert client.put(
        f"/projects/{pid}/speaker-confirmations",
        json=_single("S1", "Bob", right, ["t3", "t4"]),
    ).status_code == 200
    before = _rows(engine, pid)

    incomplete = client.put(
        f"/projects/{pid}/speaker-confirmations/batch",
        json={
            "source_run_id": "run-one",
            "source_artifact_version": "run-one",
            "mappings": [{
                "diarizer_speaker_id": "S0",
                "speaker_id": "Bob",
                "camera_id": right,
                "evidence_turn_ids": ["t1", "t2"],
                "expected_version": 1,
            }],
        },
    )
    assert incomplete.status_code in {400, 409}
    assert _rows(engine, pid) == before

    legacy_one_row_swap = client.put(
        f"/projects/{pid}/speaker-confirmations",
        json={
            **_single("S0", "Bob", right, ["t1", "t2"]),
            "expected_version": 1,
        },
    )
    assert legacy_one_row_swap.status_code == 409
    assert _rows(engine, pid) == before

    missing_versions = client.put(
        f"/projects/{pid}/speaker-confirmations/batch",
        json={
            "source_run_id": "run-one",
            "source_artifact_version": "run-one",
            "mappings": [
                {
                    "diarizer_speaker_id": "S0",
                    "speaker_id": "Bob",
                    "camera_id": right,
                    "evidence_turn_ids": ["t1", "t2"],
                },
                {
                    "diarizer_speaker_id": "S1",
                    "speaker_id": "Alice",
                    "camera_id": left,
                    "evidence_turn_ids": ["t3", "t4"],
                },
            ],
        },
    )
    assert missing_versions.status_code == 409
    assert _rows(engine, pid) == before

    swapped = client.put(
        f"/projects/{pid}/speaker-confirmations/batch",
        json={
            "source_run_id": "run-one",
            "source_artifact_version": "run-one",
            "mappings": [
                {
                    "diarizer_speaker_id": "S0",
                    "speaker_id": "Bob",
                    "camera_id": right,
                    "evidence_turn_ids": ["t1", "t2"],
                    "expected_version": 1,
                },
                {
                    "diarizer_speaker_id": "S1",
                    "speaker_id": "Alice",
                    "camera_id": left,
                    "evidence_turn_ids": ["t3", "t4"],
                    "expected_version": 1,
                },
            ],
        },
    )
    assert swapped.status_code == 200, swapped.text
    rows = _rows(engine, pid)
    assert [(row["diarizer_speaker_id"], row["speaker_id"], row["camera_id"], row["version"]) for row in rows] == [
        ("S0", "Bob", right, 2),
        ("S1", "Alice", left, 2),
    ]


def test_new_run_batch_preserves_stale_history_without_version_or_bijection_conflict(
    tmp_path: Path,
):
    engine, client, pid, left, right = _project(tmp_path)
    for payload in (
        _single("S0", "Alice", left, ["t1", "t2"]),
        _single("S1", "Bob", right, ["t3", "t4"]),
    ):
        assert client.put(
            f"/projects/{pid}/speaker-confirmations", json=payload
        ).status_code == 200

    artifact_path = tmp_path / pid / "audio" / "ai" / "v1" / "result.json"
    artifact = json.loads(artifact_path.read_text())
    artifact["run_id"] = "run-two"
    artifact_path.write_text(json.dumps(artifact))

    response = client.put(
        f"/projects/{pid}/speaker-confirmations/batch",
        json={
            "source_run_id": "run-two",
            "source_artifact_version": "run-two",
            "mappings": [
                {
                    "diarizer_speaker_id": "S0",
                    "speaker_id": "Bob",
                    "camera_id": right,
                    "evidence_turn_ids": ["t1", "t2"],
                    "expected_version": None,
                },
                {
                    "diarizer_speaker_id": "S1",
                    "speaker_id": "Alice",
                    "camera_id": left,
                    "evidence_turn_ids": ["t3", "t4"],
                    "expected_version": None,
                },
            ],
        },
    )
    assert response.status_code == 200, response.text
    rows = _rows(engine, pid)
    assert len(rows) == 4
    assert {
        (row["source_artifact_version"], row["diarizer_speaker_id"], row["speaker_id"])
        for row in rows
    } == {
        ("run-one", "S0", "Alice"),
        ("run-one", "S1", "Bob"),
        ("run-two", "S0", "Bob"),
        ("run-two", "S1", "Alice"),
    }
    current = client.get(f"/projects/{pid}/speaker-confirmations")
    assert current.status_code == 200, current.text
    assert {
        (item["diarizer_speaker_id"], item["confirmation"]["speaker_id"])
        for item in current.json()["labels"]
    } == {("S0", "Bob"), ("S1", "Alice")}
