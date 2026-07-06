from __future__ import annotations

import json
from pathlib import Path
from collections.abc import Iterator

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
def project_with_intervals(auth_client):
    """Project with loudness, noise-floor, and intervals computed."""
    client, data_root, engine = auth_client

    r = client.post(
        "/projects", json={"name": "Activity test", "fps_num": 24000, "fps_den": 1001},
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

    client.post(f"/projects/{pid}/channels", json={
        "mappings": [
            {"source_angle_id": a1, "channel_index": 0, "speaker_label": "presenter"},
            {"source_angle_id": a2, "channel_index": 0, "speaker_label": "interviewee"},
        ],
    })

    audio_dir = data_root / pid / "audio"
    audio_dir.mkdir(parents=True, exist_ok=True)

    # presenter: speech at 100-400ms, 700-900ms
    # interviewee: speech at 300-600ms
    # hop=20ms, threshold=-40
    p_rms = (
        [-70.0] * 5        # 0-100ms
        + [-10.0] * 15     # 100-400ms speech
        + [-70.0] * 15     # 400-700ms silence
        + [-10.0] * 10     # 700-900ms speech
        + [-70.0] * 5      # 900-1000ms
    )
    i_rms = (
        [-70.0] * 15       # 0-300ms
        + [-10.0] * 15     # 300-600ms speech
        + [-70.0] * 20     # 600-1000ms
    )

    with Session(engine) as session:
        ch_rows = session.execute(
            select(audio_channels).where(audio_channels.c.project_id == pid).order_by(
                audio_channels.c.speaker_label
            )
        ).all()

    loudness = {
        "hop_ms": 20,
        "channels": {
            ch_rows[0].id: {"rms_db": i_rms, "start_ms": 0},  # interviewee
            ch_rows[1].id: {"rms_db": p_rms, "start_ms": 0},  # presenter
        },
    }
    (audio_dir / "loudness.json").write_text(json.dumps(loudness))

    client.post(f"/projects/{pid}/noise-floor")
    client.post(f"/projects/{pid}/intervals")

    return client, data_root, engine, pid


# ── Pure function tests ─────────────────────────────────────────────


def test_activity_timeline_only_silence():
    """No intervals → one segment with empty active list."""
    from autoedit.activity import compute_activity_timeline

    timeline = compute_activity_timeline([], total_duration_ms=10000)
    assert len(timeline) == 1
    assert timeline[0]["start_ms"] == 0
    assert timeline[0]["end_ms"] == 10000
    assert timeline[0]["active"] == []


def test_activity_timeline_single_speaker():
    """One speaker → active throughout their intervals, silent elsewhere."""
    from autoedit.activity import compute_activity_timeline

    intervals = [{
        "channel_id": "ch1",
        "speaker_label": "presenter",
        "intervals": [
            {"start_ms": 1000, "end_ms": 3000},
            {"start_ms": 5000, "end_ms": 6000},
        ],
    }]

    timeline = compute_activity_timeline(intervals)

    # Should have: 0-1000 [], 1000-3000 [presenter], 3000-5000 [], 5000-6000 [presenter]
    assert len(timeline) == 4
    assert timeline[0] == {"start_ms": 0, "end_ms": 1000, "active": []}
    assert timeline[1] == {"start_ms": 1000, "end_ms": 3000, "active": ["presenter"]}
    assert timeline[2] == {"start_ms": 3000, "end_ms": 5000, "active": []}
    assert timeline[3] == {"start_ms": 5000, "end_ms": 6000, "active": ["presenter"]}


def test_activity_timeline_overlap():
    """Simultaneous speech → overlap region with both speakers."""
    from autoedit.activity import compute_activity_timeline

    intervals = [
        {
            "channel_id": "ch1",
            "speaker_label": "presenter",
            "intervals": [{"start_ms": 1000, "end_ms": 5000}],
        },
        {
            "channel_id": "ch2",
            "speaker_label": "interviewee",
            "intervals": [{"start_ms": 3000, "end_ms": 7000}],
        },
    ]

    timeline = compute_activity_timeline(intervals)

    # Expected:
    # 0-1000 []
    # 1000-3000 [presenter]
    # 3000-5000 [interviewee, presenter]
    # 5000-7000 [interviewee]
    assert len(timeline) == 4
    assert timeline[0] == {"start_ms": 0, "end_ms": 1000, "active": []}
    assert timeline[1] == {"start_ms": 1000, "end_ms": 3000, "active": ["presenter"]}
    assert timeline[2] == {"start_ms": 3000, "end_ms": 5000, "active": ["interviewee", "presenter"]}
    assert timeline[3] == {"start_ms": 5000, "end_ms": 7000, "active": ["interviewee"]}


def test_activity_timeline_contiguous():
    """Timeline covers from 0 to max end_ms without gaps."""
    from autoedit.activity import compute_activity_timeline

    intervals = [{
        "channel_id": "ch1",
        "speaker_label": "speaker",
        "intervals": [{"start_ms": 2000, "end_ms": 4000}],
    }]

    timeline = compute_activity_timeline(intervals)

    # Verify contiguous: prev.end_ms == next.start_ms
    for i in range(len(timeline) - 1):
        assert timeline[i]["end_ms"] == timeline[i + 1]["start_ms"]

    # Should cover full range
    assert timeline[0]["start_ms"] == 0
    assert timeline[-1]["end_ms"] == 4000


def test_activity_timeline_merge_identical():
    """Consecutive segments with identical active sets are merged."""
    from autoedit.activity import compute_activity_timeline

    intervals = [{
        "channel_id": "ch1",
        "speaker_label": "speaker",
        "intervals": [
            {"start_ms": 1000, "end_ms": 2000},
            {"start_ms": 2000, "end_ms": 3000},  # contiguous → should merge
        ],
    }]

    timeline = compute_activity_timeline(intervals)

    # Should be: 0-1000 [], 1000-3000 [speaker]
    assert len(timeline) == 2
    assert timeline[1] == {"start_ms": 1000, "end_ms": 3000, "active": ["speaker"]}


def test_activity_timeline_with_total_duration():
    """total_duration_ms extends timeline beyond last interval."""
    from autoedit.activity import compute_activity_timeline

    intervals = [{
        "channel_id": "ch1",
        "speaker_label": "speaker",
        "intervals": [{"start_ms": 100, "end_ms": 200}],
    }]

    timeline = compute_activity_timeline(intervals, total_duration_ms=1000)

    assert len(timeline) == 3
    assert timeline[0] == {"start_ms": 0, "end_ms": 100, "active": []}
    assert timeline[1] == {"start_ms": 100, "end_ms": 200, "active": ["speaker"]}
    assert timeline[2] == {"start_ms": 200, "end_ms": 1000, "active": []}


def test_activity_timeline_active_sorted():
    """Active speaker list is always sorted alphabetically."""
    from autoedit.activity import compute_activity_timeline

    intervals = [
        {
            "channel_id": "ch2",
            "speaker_label": "interviewee",
            "intervals": [{"start_ms": 100, "end_ms": 500}],
        },
        {
            "channel_id": "ch1",
            "speaker_label": "presenter",
            "intervals": [{"start_ms": 200, "end_ms": 400}],
        },
    ]

    timeline = compute_activity_timeline(intervals)
    for seg in timeline:
        assert seg["active"] == sorted(seg["active"])


# ── API route tests ─────────────────────────────────────────────────


def test_activity_route_requires_auth(tmp_path: Path):
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
    response = client.post("/projects/01J00000000000000000000000/activity")
    assert response.status_code == 401


def test_activity_rejects_missing_project(auth_client):
    client, _, _ = auth_client
    response = client.post("/projects/01J00000000000000000000000/activity")
    assert response.status_code == 404


def test_activity_rejects_without_intervals(auth_client):
    """Activity requires speaking_intervals in DB."""
    client, data_root, engine = auth_client
    r = client.post(
        "/projects", json={"name": "No intervals", "fps_num": 24000, "fps_den": 1001},
    )
    pid = r.json()["id"]

    response = client.post(f"/projects/{pid}/activity")
    assert response.status_code == 400


def test_activity_returns_timeline(project_with_intervals):
    """Activity route returns contiguous timeline JSON and writes to disk."""
    client, data_root, engine, pid = project_with_intervals

    response = client.post(f"/projects/{pid}/activity")

    assert response.status_code == 200
    result = response.json()
    assert "timeline" in result
    assert "total_duration_ms" in result
    timeline = result["timeline"]
    assert len(timeline) >= 1

    # Verify contiguity
    for i in range(len(timeline) - 1):
        assert timeline[i]["end_ms"] == timeline[i + 1]["start_ms"]

    # Verify structure
    for seg in timeline:
        assert "start_ms" in seg
        assert "end_ms" in seg
        assert "active" in seg
        assert isinstance(seg["active"], list)
        assert seg["start_ms"] < seg["end_ms"]
        assert seg["active"] == sorted(seg["active"])

    # Verify file on disk
    activity_path = data_root / pid / "audio" / "activity.json"
    assert activity_path.is_file()
    on_disk = json.loads(activity_path.read_text())
    assert "timeline" in on_disk
    assert len(on_disk["timeline"]) == len(timeline)


def test_activity_contains_overlap_region(project_with_intervals):
    """With presenter 100-400ms/700-900ms and interviewee 300-600ms,
    there should be an overlap at 300-400ms with both speakers."""
    client, data_root, engine, pid = project_with_intervals

    response = client.post(f"/projects/{pid}/activity")
    assert response.status_code == 200

    timeline = response.json()["timeline"]

    # Find the overlap segment
    overlaps = [
        seg for seg in timeline
        if len(seg["active"]) == 2
    ]
    assert len(overlaps) >= 1
    assert set(overlaps[0]["active"]) == {"interviewee", "presenter"}
