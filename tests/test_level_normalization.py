from __future__ import annotations

import json
from pathlib import Path

import pytest
from fastapi.testclient import TestClient
from sqlalchemy import create_engine, select
from sqlalchemy.orm import Session
from sqlalchemy.pool import StaticPool

from autoedit.api import create_app
from autoedit.db.migrate import run_migrations
from autoedit.db.schema import angles, audio_channels
from autoedit.projects import new_ulid


@pytest.fixture
def auth_client(tmp_path: Path):
    engine = create_engine(
        "sqlite:///:memory:",
        connect_args={"check_same_thread": False},
        poolclass=StaticPool,
    )
    run_migrations(engine)
    app = create_app(
        engine=engine,
        data_root=tmp_path,
        auth_enabled=True,
        operator_password="pw",
        session_secret="secret",
        public_domain="autoedit.example.com",
        session_cookie_secure=False,
    )
    client = TestClient(app)
    login = client.post("/auth/login", json={"password": "pw", "display_name": "P"})
    assert login.status_code == 204
    return client, tmp_path, engine


@pytest.fixture
def project_with_thresholds(auth_client):
    client, data_root, engine = auth_client
    r = client.post(
        "/projects", json={"name": "Level norm test", "fps_num": 24000, "fps_den": 1001},
    )
    assert r.status_code == 201
    pid = r.json()["id"]

    a1 = new_ulid()
    a2 = new_ulid()
    with Session(engine) as session:
        session.execute(angles.insert().values(
            id=a1, project_id=pid, label="Presenter", role="cam_left",
            source_path="source/presenter.mp4", sync_offset_ms=0,
        ))
        session.execute(angles.insert().values(
            id=a2, project_id=pid, label="Interviewee", role="cam_right",
            source_path="source/interviewee.mp4", sync_offset_ms=0,
        ))
        session.commit()

    r = client.post(f"/projects/{pid}/channels", json={
        "mappings": [
            {"source_angle_id": a1, "channel_index": 0, "speaker_label": "presenter"},
            {"source_angle_id": a2, "channel_index": 0, "speaker_label": "interviewee"},
        ],
    })
    assert r.status_code == 201

    with Session(engine) as session:
        rows = session.execute(
            select(audio_channels).where(audio_channels.c.project_id == pid)
        ).all()
        for row in rows:
            threshold = -42.0 if row.speaker_label == "presenter" else -52.0
            session.execute(
                audio_channels.update()
                .where(audio_channels.c.id == row.id)
                .values(noise_floor_db=threshold - 8.0, vad_threshold_db=threshold)
            )
        session.commit()

    return client, data_root, engine, pid


# ── Pure function tests ─────────────────────────────────────────────


def test_level_normalization_aligns_channel_thresholds():
    from autoedit.level_normalization import compute_level_normalization

    result = compute_level_normalization([
        {"id": "hot", "speaker_label": "presenter", "vad_threshold_db": -42.0},
        {"id": "quiet", "speaker_label": "interviewee", "vad_threshold_db": -52.0},
    ])

    assert result["target_threshold_db"] == pytest.approx(-47.0)
    assert result["channels"]["hot"]["gain_db"] == pytest.approx(-5.0)
    assert result["channels"]["quiet"]["gain_db"] == pytest.approx(5.0)


# ── API route tests ─────────────────────────────────────────────────


def test_level_normalization_route_requires_auth(tmp_path: Path):
    engine = create_engine(
        "sqlite:///:memory:",
        connect_args={"check_same_thread": False},
        poolclass=StaticPool,
    )
    run_migrations(engine)
    app = create_app(
        engine=engine,
        data_root=tmp_path,
        auth_enabled=True,
        operator_password="pw",
        session_secret="secret",
        session_cookie_secure=False,
    )
    client = TestClient(app)
    response = client.post("/projects/01J00000000000000000000000/level-normalization")
    assert response.status_code == 401


def test_level_normalization_route_writes_analysis_gain_file(project_with_thresholds):
    client, data_root, engine, pid = project_with_thresholds

    response = client.post(f"/projects/{pid}/level-normalization")

    assert response.status_code == 200
    result = response.json()
    assert result["strategy"] == "vad_threshold_alignment_v1"
    assert len(result["channels"]) == 2

    path = data_root / pid / "audio" / "level_normalization.json"
    assert path.is_file()
    on_disk = json.loads(path.read_text())
    assert on_disk["channels"] == result["channels"]


def test_level_normalization_rejects_missing_thresholds(auth_client):
    client, _, engine = auth_client
    r = client.post(
        "/projects", json={"name": "No thresholds", "fps_num": 24000, "fps_den": 1001},
    )
    pid = r.json()["id"]
    a1 = new_ulid()
    a2 = new_ulid()
    with Session(engine) as session:
        session.execute(angles.insert().values(
            id=a1, project_id=pid, label="Presenter", role="cam_left",
            source_path="source/presenter.mp4", sync_offset_ms=0,
        ))
        session.execute(angles.insert().values(
            id=a2, project_id=pid, label="Interviewee", role="cam_right",
            source_path="source/interviewee.mp4", sync_offset_ms=0,
        ))
        session.commit()
    r = client.post(f"/projects/{pid}/channels", json={
        "mappings": [
            {"source_angle_id": a1, "channel_index": 0, "speaker_label": "presenter"},
            {"source_angle_id": a2, "channel_index": 0, "speaker_label": "interviewee"},
        ],
    })
    assert r.status_code == 201

    response = client.post(f"/projects/{pid}/level-normalization")
    assert response.status_code == 400
    assert "noise-floor" in response.json()["detail"]
