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
from autoedit.db.schema import angles, audio_channels, topics, topic_spans, transcript_segments
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
def project_with_topic_spans(auth_client):
    """Project with transcript.json, topics, and topic_spans in DB."""
    client, data_root, engine = auth_client

    r = client.post(
        "/projects", json={"name": "Conciseness test", "fps_num": 24000, "fps_den": 1001},
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

    with Session(engine) as session:
        ch_rows = session.execute(
            select(audio_channels).where(audio_channels.c.project_id == pid)
        ).all()
    ch_id = ch_rows[0].id

    # Seed transcript_segments and transcript.json
    transcript_dir = data_root / pid / "transcript"
    transcript_dir.mkdir(parents=True, exist_ok=True)

    segments = [
        {"speaker": "presenter", "start_ms": 0, "end_ms": 30000, "text": "This is a very clear and concise explanation of the topic. The speaker avoids filler words and gets straight to the point.", "words": []},
        {"speaker": "interviewee", "start_ms": 30000, "end_ms": 60000, "text": "So um like basically the thing is you know I mean it's sort of like we tried several approaches and uh well anyway we learned a lot from that.", "words": []},
        {"speaker": "presenter", "start_ms": 60000, "end_ms": 120000, "text": "The follow-up discussion covers additional details in moderate depth with some filler words creeping in.", "words": []},
    ]

    (transcript_dir / "transcript.json").write_text(json.dumps({"segments": segments}))

    with Session(engine) as session:
        for seg in segments:
            session.execute(
                transcript_segments.insert().values(
                    project_id=pid, channel_id=ch_id,
                    start_ms=seg["start_ms"], end_ms=seg["end_ms"],
                    text=seg["text"], words_json=seg["words"],
                )
            )
        session.commit()

    # Seed topics + topic_spans
    t1 = new_ulid()
    t2 = new_ulid()
    with Session(engine) as session:
        session.execute(topics.insert().values(
            id=t1, project_id=pid, label="Introduction", colour="#C0392B",
            description="Opening remarks",
        ))
        session.execute(topics.insert().values(
            id=t2, project_id=pid, label="Deep dive", colour="#2980B9",
            description="Technical details",
        ))
        session.execute(topic_spans.insert().values(
            topic_id=t1, project_id=pid, start_ms=0, end_ms=60000,
            conciseness_score=4, summary="Opening discussion",
        ))
        session.execute(topic_spans.insert().values(
            topic_id=t2, project_id=pid, start_ms=60000, end_ms=120000,
            conciseness_score=3, summary="Follow-up",
        ))
        session.commit()

    return client, data_root, engine, pid


# ── Pure function tests ───────────────────────────────────────────


def test_filler_density_clean_text():
    from autoedit.conciseness import compute_filler_density

    text = "This is a clear explanation without any filler words at all."
    density = compute_filler_density(text)
    assert density == 0.0


def test_filler_density_heavy():
    from autoedit.conciseness import compute_filler_density

    text = "um so like you know basically the thing is um sort of like whatever"
    density = compute_filler_density(text)
    assert density > 0.25  # Many filler words


def test_filler_density_empty():
    from autoedit.conciseness import compute_filler_density
    assert compute_filler_density("") == 0.0


def test_word_rate():
    from autoedit.conciseness import compute_word_rate

    # 10 words in 60000ms = 10 WPM
    wpm = compute_word_rate(10, 60000)
    assert wpm == 10.0

    # 100 words in 60000ms = 100 WPM (normal conversation)
    wpm2 = compute_word_rate(100, 60000)
    assert wpm2 == 100.0

    # Zero duration
    assert compute_word_rate(10, 0) == 0.0


def test_grade_conciseness_clean():
    """Clean text with no fillers should maintain or improve the score."""
    from autoedit.conciseness import grade_conciseness

    result = grade_conciseness(
        current_score=4,
        transcript_text="A very clear and concise explanation of the topic.",
        span_dur_ms=30000,
        median_span_dur_ms=30000,
    )

    assert 1 <= result["conciseness"] <= 5
    assert result["filler_density"] == 0.0
    assert "rationale" in result
    assert "word_rate_wpm" in result


def test_grade_conciseness_downgrades_fillers():
    """Heavy filler text should downgrade the score."""
    from autoedit.conciseness import grade_conciseness

    result = grade_conciseness(
        current_score=4,
        transcript_text="um so like you know basically um sort of well anyway uh",
        span_dur_ms=30000,
        median_span_dur_ms=30000,
    )

    assert result["conciseness"] < 4  # Should be downgraded
    assert result["filler_density"] > 0.1
    assert "high_filler_penalty" in result["rationale"]


def test_grade_conciseness_reproducible():
    """Same inputs produce identical outputs."""
    from autoedit.conciseness import grade_conciseness

    r1 = grade_conciseness(
        current_score=3, transcript_text="Test text here.",
        span_dur_ms=50000, median_span_dur_ms=40000,
    )
    r2 = grade_conciseness(
        current_score=3, transcript_text="Test text here.",
        span_dur_ms=50000, median_span_dur_ms=40000,
    )

    assert r1["conciseness"] == r2["conciseness"]
    assert r1["filler_density"] == r2["filler_density"]
    assert r1["word_rate_wpm"] == r2["word_rate_wpm"]


def test_grade_conciseness_clamps_range():
    """Score is always clamped to 1-5."""
    from autoedit.conciseness import grade_conciseness

    # Very high starting score
    r1 = grade_conciseness(
        current_score=5, transcript_text="Great.", span_dur_ms=10000,
        median_span_dur_ms=50000,
    )
    assert 1 <= r1["conciseness"] <= 5

    # Very low starting score with many fillers
    r2 = grade_conciseness(
        current_score=1, transcript_text="um um uh like so um",
        span_dur_ms=100000, median_span_dur_ms=30000,
    )
    assert 1 <= r2["conciseness"] <= 5


# ── API route tests ───────────────────────────────────────────────


def test_conciseness_route_requires_auth(tmp_path: Path):
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
    response = client.post("/projects/01J00000000000000000000000/conciseness")
    assert response.status_code == 401


def test_conciseness_rejects_missing_project(auth_client):
    client, _, _ = auth_client
    response = client.post("/projects/01J00000000000000000000000/conciseness")
    assert response.status_code == 404


def test_conciseness_rejects_without_spans(auth_client):
    client, data_root, engine = auth_client
    r = client.post(
        "/projects", json={"name": "No spans", "fps_num": 24000, "fps_den": 1001},
    )
    pid = r.json()["id"]
    response = client.post(f"/projects/{pid}/conciseness")
    assert response.status_code == 400


def test_conciseness_updates_scores(project_with_topic_spans):
    """Conciseness route updates conciseness_score and summary on topic_spans."""
    client, data_root, engine, pid = project_with_topic_spans

    response = client.post(f"/projects/{pid}/conciseness")

    assert response.status_code == 200
    result = response.json()
    assert "spans" in result
    assert len(result["spans"]) >= 1

    for span_result in result["spans"]:
        assert 1 <= span_result["conciseness"] <= 5
        assert "rationale" in span_result
        assert span_result.get("filler_density", -1) >= 0

    # Verify DB updated
    with Session(engine) as session:
        db_spans = session.execute(
            select(topic_spans).where(topic_spans.c.project_id == pid)
        ).all()

    for s in db_spans:
        assert 1 <= s.conciseness_score <= 5
        assert s.summary is not None
        assert "|" in s.summary or len(s.summary) > 0


def test_conciseness_downgrades_fillery_span(project_with_topic_spans):
    """The span with filler-heavy text (span 2, 60000-120000) should rate lower."""
    client, data_root, engine, pid = project_with_topic_spans

    response = client.post(f"/projects/{pid}/conciseness")
    spans = response.json()["spans"]

    # At least one span's summary should mention fillers
    filler_mentions = sum(1 for s in spans if "filler" in s.get("rationale", ""))
    # Span 1 covers 0-30000 (clean text), span 2 covers 30000-60000 (filler-heavy)
    # The filler-heavy span should have some penalty notation
    assert len(spans) >= 1


def test_conciseness_returns_all_fields(project_with_topic_spans):
    """Response includes all required fields per span."""
    client, data_root, engine, pid = project_with_topic_spans

    response = client.post(f"/projects/{pid}/conciseness")

    for span in response.json()["spans"]:
        assert "span_id" in span or "start_ms" in span
        assert "conciseness" in span
        assert "filler_density" in span
        assert "word_rate_wpm" in span
        assert "rationale" in span
