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
from autoedit.db.schema import (
    angles, audio_channels, topics, topic_spans, cuts,
    speaking_intervals,
)
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
def project_with_sub_edit_data(auth_client):
    """Project with activity.json, topic_spans, and speaking_intervals."""
    client, data_root, engine = auth_client

    r = client.post(
        "/projects", json={"name": "Sub-edit test", "fps_num": 24000, "fps_den": 1001},
    )
    pid = r.json()["id"]

    a_wide = new_ulid()
    a_presenter = new_ulid()
    a_interviewee = new_ulid()
    with Session(engine) as session:
        session.execute(angles.insert().values(
            id=a_wide, project_id=pid, label="Wide", role="wide",
            source_path="source/wide.mp4", sync_offset_ms=0,
        ))
        session.execute(angles.insert().values(
            id=a_presenter, project_id=pid, label="Presenter", role="cam_left",
            source_path="source/presenter.mp4", sync_offset_ms=0,
        ))
        session.execute(angles.insert().values(
            id=a_interviewee, project_id=pid, label="Interviewee", role="cam_right",
            source_path="source/interviewee.mp4", sync_offset_ms=100,
        ))
        session.commit()

    client.post(f"/projects/{pid}/channels", json={
        "mappings": [
            {"source_angle_id": a_presenter, "channel_index": 0, "speaker_label": "presenter"},
            {"source_angle_id": a_interviewee, "channel_index": 0, "speaker_label": "interviewee"},
        ],
    })

    # Seed activity.json covering 0-30000ms
    audio_dir = data_root / pid / "audio"
    audio_dir.mkdir(parents=True, exist_ok=True)
    activity = {
        "timeline": [
            {"start_ms": 0, "end_ms": 10000, "active": ["presenter"]},
            {"start_ms": 10000, "end_ms": 15000, "active": ["interviewee"]},
            {"start_ms": 15000, "end_ms": 20000, "active": ["interviewee", "presenter"]},
            {"start_ms": 20000, "end_ms": 25000, "active": ["interviewee"]},
            {"start_ms": 25000, "end_ms": 30000, "active": ["presenter"]},
        ],
    }
    (audio_dir / "activity.json").write_text(json.dumps(activity))

    # Seed topics + topic_spans
    t1 = new_ulid()
    t2 = new_ulid()
    t3 = new_ulid()
    with Session(engine) as session:
        session.execute(topics.insert().values(
            id=t1, project_id=pid, label="Introduction", colour="#C0392B",
        ))
        session.execute(topics.insert().values(
            id=t2, project_id=pid, label="Deep dive", colour="#2980B9",
        ))
        session.execute(topics.insert().values(
            id=t3, project_id=pid, label="Off-topic", colour="#7F8C8D",
        ))
        session.execute(topic_spans.insert().values(
            topic_id=t1, project_id=pid, start_ms=0, end_ms=10000,
            conciseness_score=4, summary="Intro",
        ))
        session.execute(topic_spans.insert().values(
            topic_id=t2, project_id=pid, start_ms=10000, end_ms=20000,
            conciseness_score=5, summary="Deep",
        ))
        session.execute(topic_spans.insert().values(
            topic_id=t3, project_id=pid, start_ms=20000, end_ms=30000,
            conciseness_score=2, summary="Off",
        ))
        session.commit()

    return client, data_root, engine, pid


# ── Pure function tests ───────────────────────────────────────────


def test_select_topic_ranges_by_labels():
    from autoedit.sub_edit import select_topic_ranges

    spans = [
        {"label": "A", "start_ms": 0, "end_ms": 5000},
        {"label": "B", "start_ms": 5000, "end_ms": 10000},
        {"label": "A", "start_ms": 10000, "end_ms": 15000},
    ]

    ranges = select_topic_ranges(spans, labels=["A"])
    assert len(ranges) == 2  # two ranges: 0-5000 and 10000-15000 (B in between)
    assert ranges[0] == (0, 5000)
    assert ranges[1] == (10000, 15000)


def test_select_topic_ranges_exclude():
    from autoedit.sub_edit import select_topic_ranges

    spans = [
        {"label": "A", "start_ms": 0, "end_ms": 5000},
        {"label": "B", "start_ms": 5000, "end_ms": 10000},
        {"label": "C", "start_ms": 10000, "end_ms": 15000},
    ]

    ranges = select_topic_ranges(spans, exclude_labels=["B"])
    assert len(ranges) == 2  # two ranges: 0-5000 (A) and 10000-15000 (C)


def test_select_topic_ranges_empty():
    from autoedit.sub_edit import select_topic_ranges

    assert select_topic_ranges([], labels=["X"]) == []


def test_extract_activity_ranges():
    from autoedit.sub_edit import extract_activity_ranges

    timeline = [
        {"start_ms": 0, "end_ms": 5000, "active": ["presenter"]},
        {"start_ms": 5000, "end_ms": 10000, "active": ["interviewee"]},
        {"start_ms": 10000, "end_ms": 15000, "active": ["presenter"]},
    ]

    result = extract_activity_ranges(timeline, [(0, 10000)])

    assert len(result) == 2
    assert result[0]["start_ms"] == 0
    assert result[1]["end_ms"] == 10000


def test_extract_activity_ranges_excludes_partial():
    """Segments that partially overlap are excluded."""
    from autoedit.sub_edit import extract_activity_ranges

    timeline = [
        {"start_ms": 0, "end_ms": 5000, "active": ["presenter"]},
        {"start_ms": 3000, "end_ms": 8000, "active": ["interviewee"]},  # crosses boundary
        {"start_ms": 8000, "end_ms": 10000, "active": ["presenter"]},
    ]

    result = extract_activity_ranges(timeline, [(0, 5000)])

    # Only the first segment is fully inside 0-5000
    assert len(result) == 1
    assert result[0]["start_ms"] == 0


def test_rebase_timeline():
    from autoedit.sub_edit import rebase_timeline

    segments = [
        {"start_ms": 5000, "end_ms": 8000, "active": ["presenter"]},
        {"start_ms": 8000, "end_ms": 12000, "active": ["interviewee"]},
    ]

    result = rebase_timeline(segments)

    assert result[0]["start_ms"] == 0
    assert result[0]["end_ms"] == 3000
    assert result[1]["start_ms"] == 3000
    assert result[1]["end_ms"] == 7000


def test_rebase_timeline_empty():
    from autoedit.sub_edit import rebase_timeline
    assert rebase_timeline([]) == []


def test_fill_to_duration():
    from autoedit.sub_edit import fill_to_duration

    spans = [
        {"label": "A", "start_ms": 0, "end_ms": 5000, "conciseness": 4},
        {"label": "B", "start_ms": 5000, "end_ms": 15000, "conciseness": 3},
        {"label": "C", "start_ms": 15000, "end_ms": 30000, "conciseness": 5},
    ]

    # Have 5s of A, want 15s total → should add B (10s) to reach 15s
    result = fill_to_duration([(0, 5000)], spans, target_secs=15)

    total = sum(e - s for s, e in result)
    assert total >= 14000  # close to 15000ms target


# ── API route tests ───────────────────────────────────────────────


def test_sub_edit_route_requires_auth(tmp_path: Path):
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
    response = client.post("/projects/01J00000000000000000000000/sub-edit")
    assert response.status_code == 401


def test_sub_edit_rejects_missing_project(auth_client):
    client, _, _ = auth_client
    response = client.post("/projects/01J00000000000000000000000/sub-edit", json={
        "name": "test", "kind": "manual", "mode": "custom_ranges",
        "ranges": [{"start_ms": 0, "end_ms": 1000}],
    })
    assert response.status_code == 404


def test_sub_edit_rejects_without_activity(auth_client):
    client, data_root, engine = auth_client
    r = client.post(
        "/projects", json={"name": "No activity", "fps_num": 24000, "fps_den": 1001},
    )
    pid = r.json()["id"]
    response = client.post(f"/projects/{pid}/sub-edit")
    assert response.status_code == 400


def test_sub_edit_minus_topic_excludes(project_with_sub_edit_data):
    """Minus Off-topic → CDL contains zero Off-topic-labelled time."""
    client, data_root, engine, pid = project_with_sub_edit_data

    response = client.post(f"/projects/{pid}/sub-edit", json={
    "name": "Minus off-topic",
    "kind": "themed",
    "mode": "minus_topics",
    "exclude_labels": ["Off-topic"],
    "params": {"lead_in_ms": 0, "tail_ms": 0},
    })

    assert response.status_code == 201
    result = response.json()
    assert "cdl" in result
    cdl = result["cdl"]

    # The CDL should only cover 0-20000ms (Off-topic was 20000-30000)
    if cdl["clips"]:
        max_timeline = max(c["timeline_in_ms"] + c["dur_ms"] for c in cdl["clips"])
        # Frame-snapping may add up to 1 frame margin (≤50ms at 24fps)
        assert abs(max_timeline - 20000) <= 100  # tolerance for frame snap

    # Verify cut saved to DB
    with Session(engine) as session:
        cut_rows = session.execute(
            select(cuts).where(cuts.c.project_id == pid)
        ).all()
    assert len(cut_rows) == 1
    assert cut_rows[0].kind == "themed"
    assert cut_rows[0].name == "Minus off-topic"


def test_sub_edit_by_topics(project_with_sub_edit_data):
    """By-topics mode: select specific topics."""
    client, data_root, engine, pid = project_with_sub_edit_data

    response = client.post(f"/projects/{pid}/sub-edit", json={
        "name": "Deep dive only",
        "kind": "themed",
        "mode": "by_topics",
        "topic_labels": ["Deep dive"],
    })

    assert response.status_code == 201
    result = response.json()
    cdl = result["cdl"]

    # Deep dive spans 10000-20000ms → rebased should start at 0
    assert len(cdl["clips"]) >= 1


def test_sub_edit_custom_ranges(project_with_sub_edit_data):
    """Custom ranges mode: explicit time ranges."""
    client, data_root, engine, pid = project_with_sub_edit_data

    response = client.post(f"/projects/{pid}/sub-edit", json={
        "name": "Custom cut",
        "kind": "manual",
        "mode": "custom_ranges",
        "ranges": [{"start_ms": 0, "end_ms": 10000}],
    })

    assert response.status_code == 201
    cdl = response.json()["cdl"]
    assert len(cdl["clips"]) >= 1


def test_sub_edit_saves_cdl_json(project_with_sub_edit_data):
    """Sub-edit writes cdl.json to edit directory."""
    client, data_root, engine, pid = project_with_sub_edit_data

    client.post(f"/projects/{pid}/sub-edit", json={
        "name": "Test sub",
        "kind": "themed",
        "mode": "by_topics",
        "topic_labels": ["Introduction"],
    })

    # Check CDL file exists
    edit_dir = data_root / pid / "edit"
    cdl_files = list(edit_dir.glob("cdl_sub_*.json"))
    assert len(cdl_files) >= 1


def test_sub_edit_selects_correct_ranges(project_with_sub_edit_data):
    """Selecting Introduction → only includes 0-10000ms activity."""
    client, data_root, engine, pid = project_with_sub_edit_data

    response = client.post(f"/projects/{pid}/sub-edit", json={
        "name": "Intro only",
        "kind": "themed",
        "mode": "by_topics",
        "topic_labels": ["Introduction"],
        "params": {"lead_in_ms": 0, "tail_ms": 0},
    })

    cdl = response.json()["cdl"]
    # Rebased timeline: original 0-10000 → starts at 0, ends ~10000
    if cdl["clips"]:
        total_dur = sum(c["dur_ms"] for c in cdl["clips"])
        # Frame-snapping may add up to 1 frame margin
        assert abs(total_dur - 10000) <= 100
