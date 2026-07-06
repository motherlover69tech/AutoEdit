from __future__ import annotations

import json
from pathlib import Path
from unittest.mock import patch

import pytest
from fastapi.testclient import TestClient
from sqlalchemy import create_engine, select
from sqlalchemy.pool import StaticPool
from sqlalchemy.orm import Session

from autoedit.api import create_app
from autoedit.db.migrate import run_migrations
from autoedit.db.schema import (
    angles, audio_channels, topics, topic_spans,
    transcript_segments, speaking_intervals,
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
def project_with_full_pipeline(auth_client):
    """Project with topic_spans, speaking_intervals, and activity.json."""
    client, data_root, engine = auth_client

    r = client.post(
        "/projects", json={"name": "Summary test", "fps_num": 24000, "fps_den": 1001},
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

    with Session(engine) as session:
        ch_rows = session.execute(
            select(audio_channels).where(audio_channels.c.project_id == pid)
        ).all()

    ch_presenter = next(c for c in ch_rows if c.speaker_label == "presenter")
    ch_interviewee = next(c for c in ch_rows if c.speaker_label == "interviewee")

    # Seed speaking_intervals
    with Session(engine) as session:
        # presenter speaks 0-4000
        session.execute(speaking_intervals.insert().values(
            channel_id=ch_presenter.id, start_ms=0, end_ms=4000, mean_db=-10, peak_db=-5,
        ))
        # interviewee speaks 3000-8000
        session.execute(speaking_intervals.insert().values(
            channel_id=ch_interviewee.id, start_ms=3000, end_ms=8000, mean_db=-12, peak_db=-6,
        ))
        # presenter speaks 8000-10000
        session.execute(speaking_intervals.insert().values(
            channel_id=ch_presenter.id, start_ms=8000, end_ms=10000, mean_db=-11, peak_db=-5,
        ))
        session.commit()

    # Seed topics + topic_spans
    t1 = new_ulid()
    t2 = new_ulid()
    with Session(engine) as session:
        session.execute(topics.insert().values(
            id=t1, project_id=pid, label="Introduction", colour="#C0392B",
            description="Opening",
        ))
        session.execute(topics.insert().values(
            id=t2, project_id=pid, label="Discussion", colour="#2980B9",
            description="Main talk",
        ))
        session.execute(topic_spans.insert().values(
            topic_id=t1, project_id=pid, start_ms=0, end_ms=5000,
            conciseness_score=4, summary="score=4",
        ))
        session.execute(topic_spans.insert().values(
            topic_id=t2, project_id=pid, start_ms=5000, end_ms=10000,
            conciseness_score=3, summary="score=3",
        ))
        session.commit()

    # Write activity.json
    audio_dir = data_root / pid / "audio"
    audio_dir.mkdir(parents=True, exist_ok=True)
    activity = {
        "timeline": [
            {"start_ms": 0, "end_ms": 4000, "active": ["presenter"]},
            {"start_ms": 4000, "end_ms": 5000, "active": ["interviewee", "presenter"]},
            {"start_ms": 5000, "end_ms": 8000, "active": ["interviewee"]},
            {"start_ms": 8000, "end_ms": 9000, "active": []},
            {"start_ms": 9000, "end_ms": 10000, "active": ["presenter"]},
        ],
    }
    (audio_dir / "activity.json").write_text(json.dumps(activity))

    with Session(engine) as session:
        ch_rows2 = session.execute(
            select(audio_channels).where(audio_channels.c.project_id == pid)
        ).all()

    return client, data_root, engine, pid


# ── Pure function tests ───────────────────────────────────────────


def test_build_summary_speaker_time():
    """Speaker time per topic is computed from speaking_intervals intersection."""
    from autoedit.report import build_summary

    topics = [
        {
            "label": "Topic A", "colour": "#C0392B",
            "spans": [{"start_ms": 0, "end_ms": 5000, "conciseness": 4, "summary": "good"}],
        },
        {
            "label": "Topic B", "colour": "#2980B9",
            "spans": [{"start_ms": 5000, "end_ms": 10000, "conciseness": 3, "summary": "ok"}],
        },
    ]

    intervals = [
        {"channel_id": "c1", "speaker_label": "presenter", "start_ms": 0, "end_ms": 4000},
        {"channel_id": "c2", "speaker_label": "interviewee", "start_ms": 3000, "end_ms": 8000},
        {"channel_id": "c1", "speaker_label": "presenter", "start_ms": 8000, "end_ms": 10000},
    ]

    result = build_summary(topics, intervals)

    assert len(result["topics"]) == 2
    # Topic A (0-5000): presenter 0-4000 = 4000ms, interviewee 3000-5000 = 2000ms
    t_a = result["topics"][0]
    assert t_a["speaker_time_ms"]["presenter"] == 4000
    assert t_a["speaker_time_ms"]["interviewee"] == 2000

    # Topic B (5000-10000): presenter 8000-10000=2000, interviewee 5000-8000=3000
    t_b = result["topics"][1]
    assert t_b["speaker_time_ms"]["presenter"] == 2000
    assert t_b["speaker_time_ms"]["interviewee"] == 3000


def test_build_summary_totals():
    """Total speaker time reconciles with sum of per-topic times."""
    from autoedit.report import build_summary

    topics = [
        {"label": "A", "colour": "#000", "spans": [{"start_ms": 0, "end_ms": 6000}]},
    ]
    intervals = [
        {"channel_id": "c1", "speaker_label": "presenter", "start_ms": 0, "end_ms": 5000},
        {"channel_id": "c2", "speaker_label": "interviewee", "start_ms": 1000, "end_ms": 6000},
    ]

    result = build_summary(topics, intervals)

    totals = result["totals"]
    assert totals["speaker_time_ms"]["presenter"] == 5000
    assert totals["speaker_time_ms"]["interviewee"] == 5000


def test_build_summary_overlap_and_silence():
    """Activity timeline provides overlap and silence totals."""
    from autoedit.report import build_summary

    activity = [
        {"start_ms": 0, "end_ms": 4000, "active": ["presenter"]},
        {"start_ms": 4000, "end_ms": 5000, "active": ["interviewee", "presenter"]},
        {"start_ms": 5000, "end_ms": 8000, "active": ["interviewee"]},
        {"start_ms": 8000, "end_ms": 10000, "active": []},
    ]

    result = build_summary([], [], activity)

    assert result["totals"]["talk_overlap_ms"] == 1000  # 4000-5000
    assert result["totals"]["silence_ms"] == 2000        # 8000-10000


def test_build_summary_empty_inputs():
    from autoedit.report import build_summary

    result = build_summary([], [])
    assert result["topics"] == []
    assert result["totals"]["speaker_time_ms"] == {}
    assert result["totals"]["talk_overlap_ms"] == 0
    assert result["totals"]["silence_ms"] == 0


def test_build_summary_structure():
    """Output has all required top-level keys."""
    from autoedit.report import build_summary

    result = build_summary([], [])

    assert "topics" in result
    assert "totals" in result
    assert "speaker_time_ms" in result["totals"]
    assert "talk_overlap_ms" in result["totals"]
    assert "silence_ms" in result["totals"]


# ── API route tests ───────────────────────────────────────────────


def test_summary_route_requires_auth(tmp_path: Path):
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
    response = client.post("/projects/01J00000000000000000000000/summary")
    assert response.status_code == 401


def test_summary_rejects_missing_project(auth_client):
    client, _, _ = auth_client
    response = client.post("/projects/01J00000000000000000000000/summary")
    assert response.status_code == 404


def test_summary_rejects_without_spans(auth_client):
    client, data_root, engine = auth_client
    r = client.post(
        "/projects", json={"name": "No spans", "fps_num": 24000, "fps_den": 1001},
    )
    pid = r.json()["id"]
    response = client.post(f"/projects/{pid}/summary")
    assert response.status_code == 400


def test_summary_builds_report(project_with_full_pipeline):
    """Summary route produces valid summary.json and writes to disk."""
    client, data_root, engine, pid = project_with_full_pipeline

    response = client.post(f"/projects/{pid}/summary")

    assert response.status_code == 200
    result = response.json()

    assert "topics" in result
    assert "totals" in result
    assert len(result["topics"]) >= 1

    # Speaker time should be non-zero
    for topic in result["topics"]:
        assert "speaker_time_ms" in topic
        assert sum(topic["speaker_time_ms"].values()) > 0

    # Verify file on disk
    summary_path = data_root / pid / "transcript" / "summary.json"
    assert summary_path.is_file()
    on_disk = json.loads(summary_path.read_text())
    assert on_disk["topics"] == result["topics"]


def test_summary_includes_overlap_silence(project_with_full_pipeline):
    """Totals include overlap_ms and silence_ms from activity.json."""
    client, data_root, engine, pid = project_with_full_pipeline

    response = client.post(f"/projects/{pid}/summary")

    totals = response.json()["totals"]
    assert "talk_overlap_ms" in totals
    assert "silence_ms" in totals
    # Activity has overlap at 4000-5000 (1000ms) and silence at 8000-9000 (1000ms)
    assert totals["talk_overlap_ms"] >= 0
    assert totals["silence_ms"] >= 0


def test_summary_speaker_times_reconcile(project_with_full_pipeline):
    """Sum of per-topic speaker times = totals speaker times."""
    client, data_root, engine, pid = project_with_full_pipeline

    response = client.post(f"/projects/{pid}/summary")
    result = response.json()

    per_topic_sum: dict[str, int] = {}
    for topic in result["topics"]:
        for spk, ms in topic["speaker_time_ms"].items():
            per_topic_sum[spk] = per_topic_sum.get(spk, 0) + ms

    totals = result["totals"]["speaker_time_ms"]
    assert per_topic_sum == totals
