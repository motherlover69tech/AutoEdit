from __future__ import annotations

import json
from pathlib import Path

import pytest
from fastapi.testclient import TestClient
from sqlalchemy import create_engine, select
from sqlalchemy.pool import StaticPool
from sqlalchemy.orm import Session

from autoedit.api import create_app
from autoedit.db.migrate import run_migrations
from autoedit.db.schema import angles, audio_channels, speaking_intervals
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
def project_with_loudness(auth_client):
    """Project with 2 audio_channels, loudness.json on disk, and noise floor computed."""
    client, data_root, engine = auth_client

    r = client.post(
        "/projects", json={"name": "Interval test", "fps_num": 24000, "fps_den": 1001},
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

    with Session(engine) as session:
        ch_rows = session.execute(
            select(audio_channels).where(audio_channels.c.project_id == pid)
        ).all()

    # Write loudness.json with realistic envelope: silence then speech
    audio_dir = data_root / pid / "audio"
    audio_dir.mkdir(parents=True, exist_ok=True)

    # 1 second total at 20ms hop = 50 samples
    # presenter: silence, then speech at 200-600ms, then silence
    p_rms = [-70.0] * 10 + [-10.0, -8.0, -9.0, -10.0, -11.0] * 4 + [-70.0] * 20
    # interviewee: silence, then speech at 400-800ms, then silence
    i_rms = [-70.0] * 20 + [-12.0, -10.0, -11.0, -12.0, -13.0] * 4 + [-70.0] * 10

    loudness = {
        "hop_ms": 20,
        "channels": {
            ch_rows[0].id: {"rms_db": p_rms, "start_ms": 0},
            ch_rows[1].id: {"rms_db": i_rms, "start_ms": 0},
        },
    }
    (audio_dir / "loudness.json").write_text(json.dumps(loudness))

    # Compute noise floors for both channels
    client.post(f"/projects/{pid}/noise-floor")

    return client, data_root, engine, pid, ch_rows


# ── Pure function tests ─────────────────────────────────────────────


def test_intervals_detect_speech_above_threshold():
    """Frames above threshold are grouped into intervals."""
    from autoedit.intervals import compute_speaking_intervals

    # 50 samples at 20ms = 1000ms. Speech in the middle.
    rms_db = [-70.0] * 10 + [-10.0] * 20 + [-70.0] * 20
    intervals = compute_speaking_intervals(rms_db, hop_ms=20, threshold_db=-40)

    assert len(intervals) == 1
    assert intervals[0]["start_ms"] == 10 * 20  # 200ms
    assert intervals[0]["end_ms"] == 30 * 20    # 600ms
    assert intervals[0]["mean_db"] < -5
    assert intervals[0]["peak_db"] > -15


def test_intervals_silence_drops_below_threshold():
    """All-silence envelope produces no intervals."""
    from autoedit.intervals import compute_speaking_intervals

    rms_db = [-70.0] * 100
    intervals = compute_speaking_intervals(rms_db, hop_ms=20, threshold_db=-40)
    assert len(intervals) == 0


def test_intervals_hangover_merges_short_gaps():
    """A 200ms gap at 300ms hangover should NOT split the interval."""
    from autoedit.intervals import compute_speaking_intervals

    # 50 samples at 20ms = 1000ms.
    # 100-300ms speech, 300-500ms gap (200ms = 10 samples), 500-800ms speech
    rms_db = (
        [-70.0] * 5          # 0-100ms silence
        + [-10.0] * 10       # 100-300ms speech
        + [-70.0] * 10       # 300-500ms gap (200ms)
        + [-10.0] * 15       # 500-800ms speech
        + [-70.0] * 10       # 800-1000ms silence
    )

    # Default hangover = 300ms (15 hops). 200ms (10 hops) should be bridged.
    intervals = compute_speaking_intervals(rms_db, hop_ms=20, threshold_db=-40, hangover_ms=300)

    assert len(intervals) == 1
    assert intervals[0]["start_ms"] == 100
    assert intervals[0]["end_ms"] == 800


def test_intervals_long_gap_splits():
    """A 400ms gap at 300ms hangover SHOULD split the interval."""
    from autoedit.intervals import compute_speaking_intervals

    # 400ms gap = 20 samples at 20ms
    rms_db = (
        [-70.0] * 5          # 0-100ms silence
        + [-10.0] * 10       # 100-300ms speech
        + [-70.0] * 20       # 300-700ms gap (400ms)
        + [-10.0] * 10       # 700-900ms speech
        + [-70.0] * 5        # 900-1000ms silence
    )

    intervals = compute_speaking_intervals(rms_db, hop_ms=20, threshold_db=-40, hangover_ms=300)

    assert len(intervals) == 2
    assert intervals[0]["start_ms"] == 100
    assert intervals[0]["end_ms"] == 300
    assert intervals[1]["start_ms"] == 700
    assert intervals[1]["end_ms"] == 900


def test_intervals_drops_short_bursts():
    """Bursts shorter than min_duration_ms (150ms default) are dropped."""
    from autoedit.intervals import compute_speaking_intervals

    # 60ms burst = 3 samples at 20ms. Default min_duration = 150ms (7.5 hops).
    rms_db = (
        [-70.0] * 5
        + [-10.0] * 3        # 60ms burst (should be dropped)
        + [-70.0] * 20
        + [-10.0] * 10       # 200ms speech (should be kept)
        + [-70.0] * 12
    )

    intervals = compute_speaking_intervals(rms_db, hop_ms=20, threshold_db=-40, min_duration_ms=150)

    assert len(intervals) == 1
    assert intervals[0]["start_ms"] == 28 * 20  # 560ms
    assert intervals[0]["end_ms"] == 38 * 20    # 760ms


def test_intervals_empty_input():
    from autoedit.intervals import compute_speaking_intervals
    assert compute_speaking_intervals([], hop_ms=20, threshold_db=-40) == []


def test_intervals_custom_parameters():
    """Custom hangover and min_duration change behavior."""
    from autoedit.intervals import compute_speaking_intervals

    # 250ms gap with 200ms hangover → should split
    rms_db = (
        [-70.0] * 5
        + [-10.0] * 10       # 200ms speech
        + [-70.0] * 13       # ~260ms gap (13 * 20ms)
        + [-10.0] * 10       # 200ms speech
        + [-70.0] * 12
    )

    # hangover=200ms (10 hops), gap=13 hops → should split
    intervals = compute_speaking_intervals(rms_db, hop_ms=20, threshold_db=-40, hangover_ms=200)
    assert len(intervals) == 2

    # hangover=300ms (15 hops), gap=13 hops → should merge
    intervals2 = compute_speaking_intervals(rms_db, hop_ms=20, threshold_db=-40, hangover_ms=300)
    assert len(intervals2) == 1


def test_intervals_preserves_mean_and_peak():
    """Mean and peak dB are correctly recorded."""
    from autoedit.intervals import compute_speaking_intervals

    rms_db = [-70.0] * 5 + [-8.0, -10.0, -12.0, -10.0, -8.0] + [-70.0] * 40
    intervals = compute_speaking_intervals(
        rms_db, hop_ms=20, threshold_db=-40, min_duration_ms=80,
    )

    assert len(intervals) == 1
    assert intervals[0]["peak_db"] == pytest.approx(-8.0, abs=0.1)
    assert intervals[0]["mean_db"] == pytest.approx(-9.6, abs=0.5)


def test_intervals_start_ms_offset():
    """start_ms parameter shifts all output times."""
    from autoedit.intervals import compute_speaking_intervals

    rms_db = [-70.0] * 10 + [-10.0] * 10 + [-70.0] * 30
    intervals = compute_speaking_intervals(rms_db, hop_ms=20, threshold_db=-40, start_ms=5000)

    assert len(intervals) == 1
    assert intervals[0]["start_ms"] == 5000 + 200  # 5000 + 10*20
    assert intervals[0]["end_ms"] == 5000 + 400    # 5000 + 20*20


# ── API route tests ─────────────────────────────────────────────────


def test_intervals_route_requires_auth(tmp_path: Path):
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
    response = client.post("/projects/01J00000000000000000000000/intervals")
    assert response.status_code == 401


def test_intervals_rejects_missing_project(auth_client):
    client, _, _ = auth_client
    response = client.post("/projects/01J00000000000000000000000/intervals")
    assert response.status_code == 404


def test_intervals_rejects_without_loudness(auth_client):
    client, data_root, engine = auth_client
    r = client.post(
        "/projects", json={"name": "No loudness", "fps_num": 24000, "fps_den": 1001},
    )
    pid = r.json()["id"]

    response = client.post(f"/projects/{pid}/intervals")
    assert response.status_code == 400


def test_intervals_rejects_without_noise_floor(auth_client):
    """Intervals requires noise_floor_db and vad_threshold_db on audio_channels."""
    client, data_root, engine = auth_client
    r = client.post(
        "/projects", json={"name": "No floor", "fps_num": 24000, "fps_den": 1001},
    )
    pid = r.json()["id"]

    a1 = new_ulid()
    with Session(engine) as session:
        session.execute(angles.insert().values(
            id=a1, project_id=pid, label="A", role="cam_left",
            source_path="source/a.mp4", sync_offset_ms=0,
        ))
        session.commit()

    client.post(f"/projects/{pid}/channels", json={
        "mappings": [
            {"source_angle_id": a1, "channel_index": 0, "speaker_label": "presenter"},
            {"source_angle_id": a1, "channel_index": 1, "speaker_label": "interviewee"},
        ],
    })

    # Write loudness.json but do NOT run noise-floor
    audio_dir = data_root / pid / "audio"
    audio_dir.mkdir(parents=True, exist_ok=True)
    with Session(engine) as session:
        ch_rows = session.execute(
            select(audio_channels).where(audio_channels.c.project_id == pid)
        ).all()
    loudness = {
        "hop_ms": 20,
        "channels": {
            ch_rows[0].id: {"rms_db": [-70.0] * 50, "start_ms": 0},
            ch_rows[1].id: {"rms_db": [-70.0] * 50, "start_ms": 0},
        },
    }
    (audio_dir / "loudness.json").write_text(json.dumps(loudness))

    response = client.post(f"/projects/{pid}/intervals")
    assert response.status_code == 400


def test_intervals_populates_speaking_intervals_table(project_with_loudness):
    """Intervals route writes to the speaking_intervals DB table."""
    client, data_root, engine, pid, ch_rows = project_with_loudness

    response = client.post(f"/projects/{pid}/intervals")

    assert response.status_code == 200
    result = response.json()
    assert "intervals" in result
    assert "channel_count" in result
    assert result["channel_count"] == 2

    # Verify DB rows
    with Session(engine) as session:
        db_rows = session.execute(
            select(speaking_intervals).where(
                speaking_intervals.c.channel_id.in_([ch.id for ch in ch_rows])
            ).order_by(speaking_intervals.c.channel_id, speaking_intervals.c.start_ms)
        ).all()

    assert len(db_rows) >= 1

    for row in db_rows:
        assert row.start_ms >= 0
        assert row.end_ms > row.start_ms
        assert row.mean_db is not None
        assert row.peak_db is not None
        assert isinstance(row.start_ms, int)
        assert isinstance(row.end_ms, int)


def test_intervals_idempotent(project_with_loudness):
    """Running intervals twice should replace old rows, not duplicate."""
    client, data_root, engine, pid, ch_rows = project_with_loudness

    r1 = client.post(f"/projects/{pid}/intervals")
    assert r1.status_code == 200

    with Session(engine) as session:
        count1 = session.execute(
            select(speaking_intervals).where(
                speaking_intervals.c.channel_id.in_([ch.id for ch in ch_rows])
            )
        ).all()

    r2 = client.post(f"/projects/{pid}/intervals")
    assert r2.status_code == 200

    with Session(engine) as session:
        count2 = session.execute(
            select(speaking_intervals).where(
                speaking_intervals.c.channel_id.in_([ch.id for ch in ch_rows])
            )
        ).all()

    # Idempotent: same number of rows (old ones deleted before re-insert)
    assert len(count2) == len(count1)
