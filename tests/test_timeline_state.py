from __future__ import annotations

import json
from pathlib import Path

import pytest
from fastapi.testclient import TestClient
from sqlalchemy import create_engine
from sqlalchemy.orm import Session
from sqlalchemy.pool import StaticPool

from autoedit.api import create_app
from autoedit.db.migrate import run_migrations
from autoedit.db.schema import angles, audio_channels, cuts, projects, topics, topic_spans
from autoedit.projects import new_ulid

MISSING_PROJECT_ID = "01J00000000000000000000000"


@pytest.fixture
def app_context(tmp_path: Path):
    engine = create_engine(
        "sqlite:///:memory:",
        connect_args={"check_same_thread": False},
        poolclass=StaticPool,
    )
    run_migrations(engine)
    app = create_app(engine=engine, data_root=tmp_path, auth_enabled=False)
    return TestClient(app), tmp_path, engine


def _create_project(client: TestClient) -> str:
    response = client.post(
        "/projects",
        json={"name": "Timeline Test", "fps_num": 24000, "fps_den": 1001},
    )
    assert response.status_code == 201
    return response.json()["id"]


def _seed_timeline_project(
    client: TestClient,
    data_root: Path,
    engine,
    *,
    include_summary: bool = True,
    include_rough_cut: bool = True,
    include_loudness: bool = False,
) -> dict:
    project_id = _create_project(client)
    project_dir = data_root / project_id
    transcript_dir = project_dir / "transcript"
    transcript_dir.mkdir(parents=True, exist_ok=True)
    audio_dir = project_dir / "audio"
    audio_dir.mkdir(parents=True, exist_ok=True)

    angle_a = new_ulid()
    angle_b = new_ulid()
    angle_wide = new_ulid()

    with Session(engine) as session:
        session.execute(
            angles.insert(),
            [
                {
                    "id": angle_a,
                    "project_id": project_id,
                    "label": "Presenter",
                    "role": "cam_left",
                    "source_path": "source/a.mp4",
                    "proxy_path": "proxy/a.mp4",
                    "sync_offset_ms": 0,
                },
                {
                    "id": angle_b,
                    "project_id": project_id,
                    "label": "Guest",
                    "role": "cam_right",
                    "source_path": "source/b.mp4",
                    "proxy_path": "proxy/b.mp4",
                    "sync_offset_ms": 100,
                },
                {
                    "id": angle_wide,
                    "project_id": project_id,
                    "label": "Wide",
                    "role": "wide",
                    "source_path": "source/wide.mp4",
                    "proxy_path": "proxy/wide.mp4",
                    "sync_offset_ms": 0,
                },
            ],
        )
        session.commit()

    cdl = {
        "version": 1,
        "project_id": project_id,
        "fps": {"num": 24000, "den": 1001},
        "clips": [
            {"angle_id": angle_a, "src_in_ms": 0, "timeline_in_ms": 0, "dur_ms": 2000, "reason": "speaker:Peter"},
            {"angle_id": angle_b, "src_in_ms": 1900, "timeline_in_ms": 2000, "dur_ms": 2000, "reason": "speaker:Guest"},
        ],
    }

    with Session(engine) as session:
        if include_rough_cut:
            session.execute(
                cuts.insert().values(
                    id=new_ulid(),
                    project_id=project_id,
                    name="Rough cut",
                    kind="rough",
                    params_json={"min_shot_ms": 1200},
                    cdl_json=cdl,
                )
            )
        session.commit()

    summary = {
        "topics": [
            {
                "label": "Introduction",
                "colour": "#e6194b",
                "spans": [
                    {"start_ms": 0, "end_ms": 1500, "conciseness": 4, "summary": "Opening remarks"},
                ],
                "speaker_time_ms": {"Peter": 1500},
            },
            {
                "label": "Main Discussion",
                "colour": "#3cb44b",
                "spans": [
                    {"start_ms": 1500, "end_ms": 4000, "conciseness": 3, "summary": "Core topic"},
                ],
                "speaker_time_ms": {"Guest": 2500},
            },
        ],
        "totals": {
            "speaker_time_ms": {"Peter": 1500, "Guest": 2500},
            "talk_overlap_ms": 0,
            "silence_ms": 0,
        },
    }

    if include_summary:
        summary_path = transcript_dir / "summary.json"
        summary_path.write_text(json.dumps(summary))

    if include_loudness:
        loudness_path = audio_dir / "loudness.json"
        loudness_path.write_text(json.dumps({
            "hop_ms": 20,
            "channels": {
                "ch_peter": {"rms_db": [-60, -55, -12, -10, -12, -55, -60], "start_ms": 0},
                "ch_guest": {"rms_db": [-60, -58, -14, -12, -14, -58, -60], "start_ms": 0},
            },
        }))

    return {
        "project_id": project_id,
        "angle_a": angle_a,
        "angle_b": angle_b,
        "angle_wide": angle_wide,
        "cdl": cdl,
        "summary": summary,
    }


# ── Contract / auth tests ──────────────────────────────────────────────

def test_timeline_state_missing_project_returns_404(app_context):
    client, _, _ = app_context
    response = client.get(f"/projects/{MISSING_PROJECT_ID}/timeline-state")
    assert response.status_code == 404
    assert response.json()["detail"] == "project not found"


def test_timeline_state_requires_auth_when_enabled(tmp_path: Path):
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
    response = client.get(f"/projects/{MISSING_PROJECT_ID}/timeline-state")
    assert response.status_code == 401


def test_timeline_state_without_rough_cut_returns_400(app_context):
    client, data_root, engine = app_context
    seeded = _seed_timeline_project(client, data_root, engine, include_rough_cut=False)
    response = client.get(f"/projects/{seeded['project_id']}/timeline-state")
    assert response.status_code == 400
    assert "rough cut" in response.json()["detail"]


def test_timeline_state_without_summary_returns_400(app_context):
    client, data_root, engine = app_context
    seeded = _seed_timeline_project(client, data_root, engine, include_summary=False)
    response = client.get(f"/projects/{seeded['project_id']}/timeline-state")
    assert response.status_code == 400
    assert "summary" in response.json()["detail"]


# ── Happy path ─────────────────────────────────────────────────────────

def test_timeline_state_returns_cdl_and_summary(app_context):
    client, data_root, engine = app_context
    seeded = _seed_timeline_project(client, data_root, engine)

    response = client.get(f"/projects/{seeded['project_id']}/timeline-state")
    assert response.status_code == 200
    body = response.json()

    # CDL clips present
    assert "cdl_clips" in body
    assert len(body["cdl_clips"]) == 2
    assert body["cdl_clips"][0]["angle_id"] == seeded["angle_a"]
    assert body["cdl_clips"][0]["timeline_in_ms"] == 0
    assert body["cdl_clips"][0]["dur_ms"] == 2000

    # Total duration from last clip end
    assert body["total_duration_ms"] == 4000

    # Summary topics present
    assert "summary" in body
    assert len(body["summary"]["topics"]) == 2
    assert body["summary"]["topics"][0]["label"] == "Introduction"
    assert body["summary"]["topics"][0]["colour"] == "#e6194b"

    # Angles mapping present with deterministic colours
    assert "angles" in body
    assert seeded["angle_a"] in body["angles"]
    assert body["angles"][seeded["angle_a"]]["label"] == "Presenter"
    assert body["angles"][seeded["angle_a"]]["role"] == "cam_left"
    assert "colour" in body["angles"][seeded["angle_a"]]


def test_timeline_state_angle_colours_are_deterministic(app_context):
    client, data_root, engine = app_context
    seeded = _seed_timeline_project(client, data_root, engine)

    response1 = client.get(f"/projects/{seeded['project_id']}/timeline-state")
    response2 = client.get(f"/projects/{seeded['project_id']}/timeline-state")

    assert response1.json()["angles"] == response2.json()["angles"]


def test_timeline_state_does_not_expose_data_root(app_context):
    client, data_root, engine = app_context
    seeded = _seed_timeline_project(client, data_root, engine)

    response = client.get(f"/projects/{seeded['project_id']}/timeline-state")
    assert response.status_code == 200
    serialized = response.text
    assert str(data_root) not in serialized
    assert "/data" not in serialized
    assert "/source/" not in serialized


def test_timeline_state_includes_loudness_when_present(app_context):
    client, data_root, engine = app_context
    seeded = _seed_timeline_project(client, data_root, engine, include_loudness=True)

    response = client.get(f"/projects/{seeded['project_id']}/timeline-state")
    assert response.status_code == 200
    body = response.json()
    assert "loudness" in body
    assert body["loudness"]["hop_ms"] == 20
    assert "ch_peter" in body["loudness"]["channels"]


def test_timeline_state_excludes_loudness_when_absent(app_context):
    client, data_root, engine = app_context
    seeded = _seed_timeline_project(client, data_root, engine, include_loudness=False)

    response = client.get(f"/projects/{seeded['project_id']}/timeline-state")
    assert response.status_code == 200
    body = response.json()
    assert "loudness" not in body


def test_timeline_state_total_duration_from_last_clip(app_context):
    client, data_root, engine = app_context
    seeded = _seed_timeline_project(client, data_root, engine)

    response = client.get(f"/projects/{seeded['project_id']}/timeline-state")
    assert response.status_code == 200
    body = response.json()

    last_clip = body["cdl_clips"][-1]
    expected = last_clip["timeline_in_ms"] + last_clip["dur_ms"]
    assert body["total_duration_ms"] == expected
