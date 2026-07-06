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
from autoedit.db.schema import angles, audio_channels, transcript_segments, topics, topic_spans
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
def project_with_transcript(auth_client):
    """Project with transcript.json and transcript_segments in DB."""
    client, data_root, engine = auth_client

    r = client.post(
        "/projects", json={"name": "Topic test", "fps_num": 24000, "fps_den": 1001},
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

    # Write transcript.json and seed transcript_segments
    transcript_dir = data_root / pid / "transcript"
    transcript_dir.mkdir(parents=True, exist_ok=True)

    segments = []
    # 2 minutes of mock transcript (~60s per speaker)
    pos = 0
    for i in range(8):
        seg = {
            "speaker": "presenter" if i % 2 == 0 else "interviewee",
            "start_ms": pos,
            "end_ms": pos + 15000,
            "text": f"Segment {i} text content for topic testing purposes.",
            "words": [],
        }
        segments.append(seg)
        pos += 15000

    (transcript_dir / "transcript.json").write_text(
        json.dumps({"segments": segments})
    )

    for ch in ch_rows:
        for seg in segments:
            if seg["speaker"] != ch.speaker_label:
                continue
            session.execute(
                transcript_segments.insert().values(
                    project_id=pid,
                    channel_id=ch.id,
                    start_ms=seg["start_ms"],
                    end_ms=seg["end_ms"],
                    text=seg["text"],
                    words_json=seg["words"],
                )
            )
    session.commit()

    return client, data_root, engine, pid


# ── Pure function tests ───────────────────────────────────────────


def test_mock_segment_topics_non_overlapping():
    """All spans must be non-overlapping."""
    from autoedit.topics import mock_segment_topics

    segments = [
        {"speaker": "presenter", "start_ms": 0, "end_ms": 10000, "text": "Hello."},
        {"speaker": "interviewee", "start_ms": 10000, "end_ms": 20000, "text": "Hi."},
    ]

    result = mock_segment_topics(segments)
    spans = result["spans"]

    for i in range(len(spans) - 1):
        assert spans[i]["end_ms"] <= spans[i + 1]["start_ms"]


def test_mock_segment_topics_covers_full_range():
    """Spans cover >95% of the transcript duration."""
    from autoedit.topics import mock_segment_topics

    segments = [
        {"speaker": "presenter", "start_ms": 0, "end_ms": 60000, "text": "Long segment."},
    ]

    result = mock_segment_topics(segments)
    spans = result["spans"]

    assert len(spans) >= 1
    total_covered = sum(s["end_ms"] - s["start_ms"] for s in spans)
    assert total_covered >= 0.95 * 60000


def test_mock_segment_topics_conciseness_range():
    """All conciseness scores are 1-5."""
    from autoedit.topics import mock_segment_topics

    segments = [
        {"speaker": "presenter", "start_ms": 0, "end_ms": 10000, "text": "Test."},
    ]

    result = mock_segment_topics(segments)
    for topic in result["topics"]:
        assert 1 <= topic["conciseness"] <= 5


def test_mock_segment_topics_empty_input():
    from autoedit.topics import mock_segment_topics

    result = mock_segment_topics([])
    assert result["topics"] == []
    assert result["spans"] == []


def test_mock_segment_topics_has_required_fields():
    from autoedit.topics import mock_segment_topics

    segments = [
        {"speaker": "presenter", "start_ms": 0, "end_ms": 30000, "text": "Test."},
    ]

    result = mock_segment_topics(segments)

    for topic in result["topics"]:
        assert "label" in topic
        assert "colour" in topic
        assert "summary" in topic
        assert "start_ms" in topic
        assert "end_ms" in topic
        assert "conciseness" in topic
        assert topic["colour"].startswith("#")


# ── API route tests ───────────────────────────────────────────────


def test_segment_topics_route_requires_auth(tmp_path: Path):
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
    response = client.post("/projects/01J00000000000000000000000/segment-topics")
    assert response.status_code == 401


def test_segment_topics_rejects_missing_project(auth_client):
    client, _, _ = auth_client
    response = client.post("/projects/01J00000000000000000000000/segment-topics")
    assert response.status_code == 404


def test_segment_topics_rejects_without_transcript(auth_client):
    client, data_root, engine = auth_client
    r = client.post(
        "/projects", json={"name": "No transcript", "fps_num": 24000, "fps_den": 1001},
    )
    pid = r.json()["id"]
    response = client.post(f"/projects/{pid}/segment-topics")
    assert response.status_code == 400


def test_segment_topics_populates_db(project_with_transcript):
    """Segment-topics writes to topics and topic_spans tables."""
    client, data_root, engine, pid = project_with_transcript

    with patch("autoedit.topics.mock_segment_topics") as mock_fn:
        mock_fn.return_value = {
            "topics": [
                {"label": "Intro", "colour": "#C0392B", "summary": "Starting.", "start_ms": 0, "end_ms": 60000, "conciseness": 4},
                {"label": "Deep dive", "colour": "#2980B9", "summary": "Details.", "start_ms": 60000, "end_ms": 120000, "conciseness": 5},
            ],
            "spans": [
                {"label": "Intro", "start_ms": 0, "end_ms": 60000, "summary": "Starting.", "conciseness": 4},
                {"label": "Deep dive", "start_ms": 60000, "end_ms": 120000, "summary": "Details.", "conciseness": 5},
            ],
        }

        response = client.post(f"/projects/{pid}/segment-topics")

    assert response.status_code == 200
    result = response.json()
    assert "topics" in result
    assert len(result["topics"]) == 2

    # Verify topics table
    with Session(engine) as session:
        topic_rows = session.execute(
            select(topics).where(topics.c.project_id == pid)
        ).all()
    assert len(topic_rows) == 2
    for t in topic_rows:
        assert t.label in ("Intro", "Deep dive")
        assert t.colour.startswith("#")

    # Verify topic_spans table
    with Session(engine) as session:
        span_rows = session.execute(
            select(topic_spans).where(topic_spans.c.project_id == pid)
        ).all()
    assert len(span_rows) == 2
    for s in span_rows:
        assert s.start_ms >= 0
        assert s.end_ms > s.start_ms
        assert 1 <= s.conciseness_score <= 5


def test_segment_topics_spans_non_overlapping(project_with_transcript):
    """Spans in the response must not overlap."""
    client, data_root, engine, pid = project_with_transcript

    with patch("autoedit.topics.mock_segment_topics") as mock_fn:
        mock_fn.return_value = {
            "topics": [
                {"label": "A", "colour": "#C0392B", "summary": "", "start_ms": 0, "end_ms": 50000, "conciseness": 4},
                {"label": "B", "colour": "#2980B9", "summary": "", "start_ms": 50000, "end_ms": 100000, "conciseness": 3},
            ],
            "spans": [
                {"label": "A", "start_ms": 0, "end_ms": 50000, "summary": "", "conciseness": 4},
                {"label": "B", "start_ms": 50000, "end_ms": 100000, "summary": "", "conciseness": 3},
            ],
        }

        response = client.post(f"/projects/{pid}/segment-topics")

    spans = response.json()["spans"]
    for i in range(len(spans) - 1):
        assert spans[i]["end_ms"] <= spans[i + 1]["start_ms"]


def test_segment_topics_idempotent(project_with_transcript):
    """Running twice replaces old rows, not duplicates."""
    client, data_root, engine, pid = project_with_transcript

    with patch("autoedit.topics.mock_segment_topics") as mock_fn:
        mock_fn.return_value = {
            "topics": [{"label": "A", "colour": "#C0392B", "summary": "", "start_ms": 0, "end_ms": 60000, "conciseness": 4}],
            "spans": [{"label": "A", "start_ms": 0, "end_ms": 60000, "summary": "", "conciseness": 4}],
        }
        r1 = client.post(f"/projects/{pid}/segment-topics")
        assert r1.status_code == 200

    with Session(engine) as session:
        count1 = len(session.execute(select(topics).where(topics.c.project_id == pid)).all())

    with patch("autoedit.topics.mock_segment_topics") as mock_fn:
        mock_fn.return_value = {
            "topics": [{"label": "B", "colour": "#2980B9", "summary": "", "start_ms": 0, "end_ms": 60000, "conciseness": 3}],
            "spans": [{"label": "B", "start_ms": 0, "end_ms": 60000, "summary": "", "conciseness": 3}],
        }
        r2 = client.post(f"/projects/{pid}/segment-topics")
        assert r2.status_code == 200

    with Session(engine) as session:
        count2 = len(session.execute(select(topics).where(topics.c.project_id == pid)).all())

    assert count2 == count1  # Idempotent: same count


def test_segment_topics_writes_json(project_with_transcript):
    """Segment-topics writes transcript/topics.json to disk."""
    client, data_root, engine, pid = project_with_transcript

    with patch("autoedit.topics.mock_segment_topics") as mock_fn:
        mock_fn.return_value = {
            "topics": [{"label": "Test", "colour": "#C0392B", "summary": "T.", "start_ms": 0, "end_ms": 60000, "conciseness": 4}],
            "spans": [{"label": "Test", "start_ms": 0, "end_ms": 60000, "summary": "T.", "conciseness": 4}],
        }

        client.post(f"/projects/{pid}/segment-topics")

    topics_path = data_root / pid / "transcript" / "topics.json"
    assert topics_path.is_file()
    on_disk = json.loads(topics_path.read_text())
    assert "topics" in on_disk
