from __future__ import annotations

import json
from pathlib import Path

import numpy as np
import pytest
from fastapi.testclient import TestClient
from sqlalchemy import create_engine, select
from sqlalchemy.pool import StaticPool
from sqlalchemy.orm import Session

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
        engine=engine, data_root=tmp_path, auth_enabled=True,
        operator_password="pw", session_secret="secret",
        public_domain="autoedit.example.com", session_cookie_secure=False,
    )
    client = TestClient(app)
    login = client.post("/auth/login", json={"password": "pw", "display_name": "P"})
    assert login.status_code == 204
    return client, tmp_path, engine


@pytest.fixture
def project_with_channels(auth_client):
    """Project with 2 audio_channels and a loudness.json on disk."""
    client, data_root, engine = auth_client

    r = client.post(
        "/projects", json={"name": "NF test", "fps_num": 24000, "fps_den": 1001},
    )
    pid = r.json()["id"]

    a1 = new_ulid()
    a2 = new_ulid()
    with Session(engine) as session:
        session.execute(angles.insert().values(
            id=a1, project_id=pid, label="A", role="cam_left",
            source_path="source/a.mp4", sync_offset_ms=0,
        ))
        session.execute(angles.insert().values(
            id=a2, project_id=pid, label="B", role="cam_right",
            source_path="source/b.mp4", sync_offset_ms=0,
        ))
        session.commit()

    r = client.post(f"/projects/{pid}/channels", json={
        "mappings": [
            {"source_angle_id": a1, "channel_index": 0, "speaker_label": "presenter"},
            {"source_angle_id": a2, "channel_index": 0, "speaker_label": "interviewee"},
        ],
    })
    assert r.status_code == 201

    # Get channel IDs
    with Session(engine) as session:
        ch_rows = session.execute(
            select(audio_channels).where(audio_channels.c.project_id == pid)
        ).all()

    # Write loudness.json directly
    audio_dir = data_root / pid / "audio"
    audio_dir.mkdir(parents=True, exist_ok=True)
    loudness = {
        "hop_ms": 20,
        "channels": {
            ch_rows[0].id: {
                "rms_db": [-60.0, -62.0, -58.0, -12.0, -8.0, -10.0, -65.0],
                "start_ms": 0,
            },
            ch_rows[1].id: {
                "rms_db": [-55.0, -53.0, -57.0, -15.0, -10.0, -12.0, -56.0],
                "start_ms": 0,
            },
        },
    }
    (audio_dir / "loudness.json").write_text(json.dumps(loudness))

    return client, data_root, engine, pid


# ── Pure function tests ─────────────────────────────────────────────


def test_compute_noise_floor_10th_percentile():
    from autoedit.noise_floor import compute_noise_floor

    # Values: 10 values, 10th percentile is the 1st lowest
    rms_db = [-60, -55, -50, -45, -40, -35, -30, -25, -20, -10]
    floor, threshold = compute_noise_floor(rms_db, margin_db=8)

    # 10th percentile of 10 values: index 1 (0-indexed) = -55
    # Using linear interpolation: rank 1 = -55
    assert floor == pytest.approx(-55, abs=2)
    assert threshold == pytest.approx(-47, abs=2)  # -55 + 8


def test_compute_noise_floor_all_similar():
    from autoedit.noise_floor import compute_noise_floor

    rms_db = [-52.0] * 100
    floor, threshold = compute_noise_floor(rms_db, margin_db=8)
    assert floor == pytest.approx(-52, abs=1)
    assert threshold == pytest.approx(-44, abs=1)


def test_compute_noise_floor_silence():
    from autoedit.noise_floor import compute_noise_floor

    rms_db = [-100.0] * 50
    floor, threshold = compute_noise_floor(rms_db, margin_db=8)
    assert floor == pytest.approx(-100, abs=1)
    assert threshold == pytest.approx(-92, abs=1)


def test_compute_noise_floor_custom_margin():
    from autoedit.noise_floor import compute_noise_floor

    rms_db = [-50.0] * 100
    _, t1 = compute_noise_floor(rms_db, margin_db=8)
    _, t2 = compute_noise_floor(rms_db, margin_db=12)
    assert t2 > t1  # Higher margin = higher threshold


# ── API route tests ─────────────────────────────────────────────────


def test_noise_floor_route_requires_auth(tmp_path: Path):
    engine = create_engine(
        "sqlite:///:memory:",
        connect_args={"check_same_thread": False}, poolclass=StaticPool,
    )
    run_migrations(engine)
    app = create_app(
        engine=engine, data_root=tmp_path, auth_enabled=True,
        operator_password="pw", session_secret="secret", session_cookie_secure=False,
    )
    client = TestClient(app)
    response = client.post("/projects/01J00000000000000000000000/noise-floor")
    assert response.status_code == 401


def test_noise_floor_rejects_missing_project(auth_client):
    client, _, _ = auth_client
    response = client.post("/projects/01J00000000000000000000000/noise-floor")
    assert response.status_code == 404


def test_noise_floor_updates_db(project_with_channels):
    client, data_root, engine, pid = project_with_channels

    response = client.post(f"/projects/{pid}/noise-floor")

    assert response.status_code == 200
    result = response.json()
    assert "channels" in result
    assert len(result["channels"]) == 2

    with Session(engine) as session:
        rows = session.execute(
            select(audio_channels).where(audio_channels.c.project_id == pid)
        ).all()

    for row in rows:
        assert row.noise_floor_db is not None
        assert row.vad_threshold_db is not None
        assert row.vad_threshold_db > row.noise_floor_db
        assert isinstance(row.noise_floor_db, float)
        assert isinstance(row.vad_threshold_db, float)


def test_noise_floor_rejects_project_without_loudness(auth_client):
    client, data_root, engine = auth_client
    r = client.post(
        "/projects", json={"name": "No loudness", "fps_num": 24000, "fps_den": 1001},
    )
    pid = r.json()["id"]

    response = client.post(f"/projects/{pid}/noise-floor")
    assert response.status_code == 400
