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
from autoedit.db.schema import angles, audio_channels, cuts
from autoedit.projects import new_ulid


# ── Helpers ──────────────────────────────────────────────────────


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
def project_with_activity(auth_client):
    """Project with activity.json and full angle/channel data."""
    client, data_root, engine = auth_client

    r = client.post(
        "/projects", json={"name": "Cut test", "fps_num": 24000, "fps_den": 1001},
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

    audio_dir = data_root / pid / "audio"
    audio_dir.mkdir(parents=True, exist_ok=True)
    activity = {
        "timeline": [
            {"start_ms": 0, "end_ms": 4000, "active": ["presenter"]},
            {"start_ms": 4000, "end_ms": 4600, "active": ["interviewee", "presenter"]},
            {"start_ms": 4600, "end_ms": 8000, "active": ["interviewee"]},
            {"start_ms": 8000, "end_ms": 10000, "active": []},
            {"start_ms": 10000, "end_ms": 12000, "active": ["presenter"]},
        ],
        "total_duration_ms": 12000,
    }
    (audio_dir / "activity.json").write_text(json.dumps(activity))

    return client, data_root, engine, pid


# ── Helpers for pure function tests ──────────────────────────────


def _sample_timeline() -> list[dict]:
    return [
        {"start_ms": 0, "end_ms": 4000, "active": ["presenter"]},
        {"start_ms": 4000, "end_ms": 4600, "active": ["interviewee", "presenter"]},
        {"start_ms": 4600, "end_ms": 8000, "active": ["interviewee"]},
        {"start_ms": 8000, "end_ms": 10000, "active": []},
        {"start_ms": 10000, "end_ms": 12000, "active": ["presenter"]},
    ]


def _sample_mapping() -> dict[str, str]:
    return {"presenter": "angle_presenter", "interviewee": "angle_interviewee"}


def _sample_offsets() -> dict[str, int]:
    return {"angle_presenter": 0, "angle_interviewee": 100, "angle_wide": 0}


# ── Pure function tests (6.1) ─────────────────────────────────────


def test_generate_cdl_single_speaker_maps_to_angle():
    from autoedit.cut_engine import generate_cdl
    timeline = [{"start_ms": 0, "end_ms": 5000, "active": ["presenter"]}]
    cdl = generate_cdl(timeline, _sample_mapping(), _sample_offsets(), wide_angle_id="angle_wide")
    assert len(cdl["clips"]) == 1
    assert cdl["clips"][0]["angle_id"] == "angle_presenter"
    assert cdl["clips"][0]["reason"] == "speaker:presenter"


def test_generate_cdl_overlap_to_wide():
    from autoedit.cut_engine import generate_cdl
    timeline = [{"start_ms": 0, "end_ms": 3000, "active": ["interviewee", "presenter"]}]
    cdl = generate_cdl(timeline, _sample_mapping(), _sample_offsets(), wide_angle_id="angle_wide")
    assert len(cdl["clips"]) == 1
    assert cdl["clips"][0]["angle_id"] == "angle_wide"
    assert cdl["clips"][0]["reason"] == "overlap:wide"


def test_generate_cdl_overlap_no_wide():
    from autoedit.cut_engine import generate_cdl
    timeline = [{"start_ms": 0, "end_ms": 3000, "active": ["interviewee", "presenter"]}]
    cdl = generate_cdl(
        timeline, _sample_mapping(), _sample_offsets(),
        wide_angle_id="angle_wide", params={"overlap_to_wide": False},
    )
    assert cdl["clips"][0]["angle_id"] == "angle_interviewee"


def test_generate_cdl_silence_hold():
    from autoedit.cut_engine import generate_cdl
    timeline = [
        {"start_ms": 0, "end_ms": 2000, "active": ["presenter"]},
        {"start_ms": 2000, "end_ms": 5000, "active": []},
    ]
    cdl = generate_cdl(
        timeline, _sample_mapping(), _sample_offsets(), wide_angle_id="angle_wide",
        params={"lead_in_ms": 0, "tail_ms": 0, "silence_behaviour": "hold"},
    )
    clips = cdl["clips"]
    assert len(clips) == 1
    assert clips[0]["angle_id"] == "angle_presenter"


def test_generate_cdl_silence_wide():
    from autoedit.cut_engine import generate_cdl
    timeline = [
        {"start_ms": 0, "end_ms": 2000, "active": ["presenter"]},
        {"start_ms": 2000, "end_ms": 5000, "active": []},
    ]
    cdl = generate_cdl(
        timeline, _sample_mapping(), _sample_offsets(),
        wide_angle_id="angle_wide",
        params={"silence_behaviour": "wide", "lead_in_ms": 0, "tail_ms": 0},
    )
    clips = cdl["clips"]
    assert len(clips) >= 2
    assert clips[1]["angle_id"] == "angle_wide"
    assert "silence:wide" in clips[1]["reason"]


def test_generate_cdl_deterministic():
    from autoedit.cut_engine import generate_cdl
    timeline = _sample_timeline()
    cdl1 = generate_cdl(timeline, _sample_mapping(), _sample_offsets(), wide_angle_id="angle_wide")
    cdl2 = generate_cdl(timeline, _sample_mapping(), _sample_offsets(), wide_angle_id="angle_wide")
    assert json.dumps(cdl1, sort_keys=True) == json.dumps(cdl2, sort_keys=True)


def test_generate_cdl_frame_snapping():
    from autoedit.cut_engine import generate_cdl
    timeline = [{"start_ms": 123, "end_ms": 4567, "active": ["presenter"]}]
    cdl = generate_cdl(
        timeline, _sample_mapping(), _sample_offsets(),
        wide_angle_id="angle_wide", fps_num=25, fps_den=1,
    )
    clip = cdl["clips"][0]
    assert clip["timeline_in_ms"] % 40 == 0
    assert clip["dur_ms"] % 40 == 0


def test_generate_cdl_src_in_applies_sync_offset():
    from autoedit.cut_engine import generate_cdl
    timeline = [{"start_ms": 0, "end_ms": 5000, "active": ["interviewee"]}]
    cdl = generate_cdl(
        timeline, _sample_mapping(), _sample_offsets(),
        wide_angle_id="angle_wide", fps_num=25, fps_den=1,
    )
    clip = cdl["clips"][0]
    assert clip["angle_id"] == "angle_interviewee"
    assert clip["src_in_ms"] <= 0


def test_generate_cdl_min_shot_anti_jitter():
    from autoedit.cut_engine import generate_cdl
    timeline = [
        {"start_ms": 0, "end_ms": 3000, "active": ["presenter"]},
        {"start_ms": 3000, "end_ms": 3500, "active": ["interviewee"]},
        {"start_ms": 3500, "end_ms": 6000, "active": ["presenter"]},
    ]
    cdl = generate_cdl(
        timeline, _sample_mapping(), _sample_offsets(),
        wide_angle_id="angle_wide", fps_num=25, fps_den=1,
        params={"lead_in_ms": 0, "tail_ms": 0},
    )
    for clip in cdl["clips"]:
        assert clip["dur_ms"] >= 1


def test_generate_cdl_lead_in_tail():
    from autoedit.cut_engine import generate_cdl
    timeline = [{"start_ms": 2000, "end_ms": 4000, "active": ["presenter"]}]
    cdl = generate_cdl(
        timeline, _sample_mapping(), _sample_offsets(),
        wide_angle_id="angle_wide", fps_num=25, fps_den=1,
        params={"lead_in_ms": 100, "tail_ms": 0},
    )
    clip = cdl["clips"][0]
    assert clip["timeline_in_ms"] < 2000


def test_generate_cdl_empty_timeline():
    from autoedit.cut_engine import generate_cdl
    cdl = generate_cdl([], {"speaker": "angle"}, {"angle": 0}, wide_angle_id="angle")
    assert cdl["clips"] == []
    assert cdl["version"] == 1


def test_generate_cdl_cdl_structure():
    from autoedit.cut_engine import generate_cdl
    cdl = generate_cdl(
        _sample_timeline(), _sample_mapping(), _sample_offsets(), wide_angle_id="angle_wide",
    )
    assert "version" in cdl
    assert "project_id" in cdl
    assert "fps" in cdl
    assert "audio" in cdl
    assert "clips" in cdl
    assert "luts" in cdl
    assert cdl["fps"]["num"] == 24000
    assert cdl["fps"]["den"] == 1001
    assert cdl["luts"]["active"] is None
    for clip in cdl["clips"]:
        assert "angle_id" in clip
        assert "src_in_ms" in clip
        assert "timeline_in_ms" in clip
        assert "dur_ms" in clip
        assert "reason" in clip


def test_generate_cdl_default_params():
    from autoedit.cut_engine import generate_cdl, DEFAULT_CUT_PARAMS
    cdl = generate_cdl(
        _sample_timeline(), _sample_mapping(), _sample_offsets(), wide_angle_id="angle_wide",
    )
    assert len(cdl["clips"]) > 0
    assert DEFAULT_CUT_PARAMS["min_shot_ms"] == 250
    assert DEFAULT_CUT_PARAMS["lead_in_ms"] == 0
    assert DEFAULT_CUT_PARAMS["tail_ms"] == 0
    assert DEFAULT_CUT_PARAMS["silence_behaviour"] == "wide"


def test_generate_cdl_direct_defaults_cut_to_wide_on_silence():
    from autoedit.cut_engine import generate_cdl
    timeline = [
        {"start_ms": 0, "end_ms": 1000, "active": ["presenter"]},
        {"start_ms": 1000, "end_ms": 2000, "active": []},
        {"start_ms": 2000, "end_ms": 3000, "active": ["interviewee"]},
    ]
    cdl = generate_cdl(
        timeline,
        _sample_mapping(),
        _sample_offsets(),
        wide_angle_id="angle_wide",
        fps_num=25,
        fps_den=1,
    )
    assert [clip["angle_id"] for clip in cdl["clips"]] == [
        "angle_presenter",
        "angle_wide",
        "angle_interviewee",
    ]
    assert [clip["timeline_in_ms"] for clip in cdl["clips"]] == [0, 1000, 2000]


# ── API route tests ──────────────────────────────────────────────


def test_cut_route_requires_auth(tmp_path: Path):
    engine = create_engine("sqlite:///:memory:", connect_args={"check_same_thread": False}, poolclass=StaticPool)
    run_migrations(engine)
    app = create_app(
        engine=engine, data_root=tmp_path, auth_enabled=True,
        operator_password="pw", session_secret="secret", session_cookie_secure=False,
    )
    client = TestClient(app)
    response = client.post("/projects/01J00000000000000000000000/cut")
    assert response.status_code == 401


def test_cut_rejects_missing_project(auth_client):
    client, _, _ = auth_client
    response = client.post("/projects/01J00000000000000000000000/cut")
    assert response.status_code == 404


def test_cut_rejects_without_activity(auth_client):
    client, data_root, engine = auth_client
    r = client.post("/projects", json={"name": "No activity", "fps_num": 24000, "fps_den": 1001})
    pid = r.json()["id"]
    response = client.post(f"/projects/{pid}/cut")
    assert response.status_code == 400


def test_cut_generates_cdl_and_saves(project_with_activity):
    client, data_root, engine, pid = project_with_activity
    response = client.post(f"/projects/{pid}/cut")
    assert response.status_code == 200
    result = response.json()
    assert result["version"] == 1
    assert result["project_id"] == pid
    assert "clips" in result
    assert len(result["clips"]) >= 1
    cdl_path = data_root / pid / "edit" / "cdl.json"
    assert cdl_path.is_file()
    on_disk = json.loads(cdl_path.read_text())
    assert on_disk["project_id"] == pid
    with Session(engine) as session:
        cut_rows = session.execute(select(cuts).where(cuts.c.project_id == pid)).all()
    assert len(cut_rows) == 1
    assert cut_rows[0].kind == "rough"


def test_cut_rebases_offsets_to_audio_source_and_maps_speakers_to_camera_roles(auth_client):
    """Audio channel source can differ from the camera that should show each speaker."""
    client, data_root, engine = auth_client
    project = client.post(
        "/projects", json={"name": "Cab sync regression", "fps_num": 24000, "fps_den": 1001},
    )
    pid = project.json()["id"]
    wide_id = new_ulid()
    presenter_id = new_ulid()
    interviewee_id = new_ulid()
    with Session(engine) as session:
        session.execute(angles.insert().values(
            id=wide_id, project_id=pid, label="Wide", role="wide",
            source_path="source/P1055258.mov", sync_offset_ms=0,
        ))
        session.execute(angles.insert().values(
            id=presenter_id, project_id=pid, label="Presenter", role="cam_left",
            source_path="source/A004_02280603_C002.mov", sync_offset_ms=-23980,
        ))
        session.execute(angles.insert().values(
            id=interviewee_id, project_id=pid, label="Interviewee", role="cam_right",
            source_path="source/A013_03141405_C002.mov", sync_offset_ms=-31315,
        ))
        session.commit()

    # A013 is the audio source: channel 0=presenter, channel 1=interviewee.
    # Those rows identify where the audio channels came from, not which camera
    # should be cut to for each speaker.
    response = client.post(f"/projects/{pid}/channels", json={
        "mappings": [
            {"source_angle_id": interviewee_id, "channel_index": 0, "speaker_label": "presenter"},
            {"source_angle_id": interviewee_id, "channel_index": 1, "speaker_label": "interviewee"},
        ],
    })
    assert response.status_code == 201

    audio_dir = data_root / pid / "audio"
    audio_dir.mkdir(parents=True, exist_ok=True)
    (audio_dir / "activity.json").write_text(json.dumps({
        "timeline": [
            {"start_ms": 0, "end_ms": 10000, "active": ["presenter"]},
            {"start_ms": 10000, "end_ms": 20000, "active": ["interviewee"]},
        ],
        "total_duration_ms": 20000,
    }))

    cut = client.post(f"/projects/{pid}/cut", json={
        "params": {"lead_in_ms": 0, "tail_ms": 0, "min_shot_ms": 1},
    })

    assert cut.status_code == 200
    clips = cut.json()["clips"]
    assert clips[0]["angle_id"] == presenter_id
    assert clips[1]["angle_id"] == interviewee_id
    # Timeline is based on A013 audio, so A013 source time stays at timeline time
    # and the presenter camera is rebased by roughly 31.315s - 23.980s.
    assert abs(clips[0]["src_in_ms"] - 7335) <= 50
    assert abs(clips[1]["src_in_ms"] - 10000) <= 50


def test_cut_with_custom_params(project_with_activity):
    client, data_root, engine, pid = project_with_activity
    response = client.post(f"/projects/{pid}/cut", json={
        "params": {"min_shot_ms": 2000, "lead_in_ms": 200},
    })
    assert response.status_code == 200
    with Session(engine) as session:
        cut_row = session.execute(select(cuts).where(cuts.c.project_id == pid)).first()
    stored_params = cut_row.params_json
    assert stored_params["min_shot_ms"] == 2000
    assert stored_params["lead_in_ms"] == 200


def test_cut_deterministic(project_with_activity):
    client, data_root, engine, pid = project_with_activity
    r1 = client.post(f"/projects/{pid}/cut")
    r2 = client.post(f"/projects/{pid}/cut")
    assert r1.json()["clips"] == r2.json()["clips"]


def test_cut_reads_activity_file(project_with_activity):
    client, data_root, engine, pid = project_with_activity
    response = client.post(f"/projects/{pid}/cut")
    assert response.status_code == 200
    result = response.json()
    total_dur = sum(c["dur_ms"] for c in result["clips"])
    assert total_dur > 0


# ── Stage 6.2: Anti-jitter (incoming-speaker preference) ──────────


def test_anti_jitter_prefers_incoming_speaker():
    """Short clip between two different speakers merges into following (incoming)."""
    from autoedit.cut_engine import generate_cdl

    timeline = [
        {"start_ms": 0, "end_ms": 3000, "active": ["presenter"]},
        {"start_ms": 3000, "end_ms": 3500, "active": ["interviewee"]},
        {"start_ms": 3500, "end_ms": 6000, "active": ["presenter"]},
    ]

    cdl = generate_cdl(
        timeline,
        {"presenter": "angle_presenter", "interviewee": "angle_interviewee"},
        {"angle_presenter": 0, "angle_interviewee": 0},
        wide_angle_id="angle_wide",
        fps_num=25, fps_den=1,
        params={"lead_in_ms": 0, "tail_ms": 0, "min_shot_ms": 1200},
    )

    for clip in cdl["clips"]:
        assert clip["angle_id"] != "angle_interviewee"


def test_anti_jitter_merges_same_angle_forward():
    """Short clip with same angle as following merges into following."""
    from autoedit.cut_engine import generate_cdl

    timeline = [
        {"start_ms": 0, "end_ms": 3000, "active": ["interviewee"]},
        {"start_ms": 3000, "end_ms": 3500, "active": ["presenter"]},
        {"start_ms": 3500, "end_ms": 6000, "active": ["presenter"]},
    ]

    cdl = generate_cdl(
        timeline,
        {"presenter": "angle_presenter", "interviewee": "angle_interviewee"},
        {"angle_presenter": 0, "angle_interviewee": 0},
        wide_angle_id="angle_wide",
        fps_num=25, fps_den=1,
        params={"lead_in_ms": 0, "tail_ms": 0},
    )

    presenter_clips = [c for c in cdl["clips"] if c["angle_id"] == "angle_presenter"]
    assert len(presenter_clips) == 1


def test_anti_jitter_merges_same_angle_backward():
    """Short clip with same angle as preceding merges into preceding."""
    from autoedit.cut_engine import generate_cdl

    timeline = [
        {"start_ms": 0, "end_ms": 3000, "active": ["interviewee"]},
        {"start_ms": 3000, "end_ms": 3500, "active": ["interviewee"]},
        {"start_ms": 3500, "end_ms": 6000, "active": ["presenter"]},
    ]

    cdl = generate_cdl(
        timeline,
        {"presenter": "angle_presenter", "interviewee": "angle_interviewee"},
        {"angle_presenter": 0, "angle_interviewee": 0},
        wide_angle_id="angle_wide",
        fps_num=25, fps_den=1,
        params={"lead_in_ms": 0, "tail_ms": 0},
    )

    interviewee_clips = [c for c in cdl["clips"] if c["angle_id"] == "angle_interviewee"]
    assert len(interviewee_clips) == 1


def test_pathological_rapid_fire_respects_min_shot():
    """Pathological rapid-fire back-and-forth: every clip ≥ min_shot_ms."""
    from autoedit.cut_engine import generate_cdl

    timeline = [
        {"start_ms": 0, "end_ms": 300, "active": ["presenter"]},
        {"start_ms": 300, "end_ms": 600, "active": ["interviewee"]},
        {"start_ms": 600, "end_ms": 900, "active": ["presenter"]},
        {"start_ms": 900, "end_ms": 1200, "active": ["interviewee"]},
        {"start_ms": 1200, "end_ms": 5000, "active": ["presenter"]},
    ]

    cdl = generate_cdl(
        timeline,
        {"presenter": "angle_presenter", "interviewee": "angle_interviewee"},
        {"angle_presenter": 0, "angle_interviewee": 0},
        wide_angle_id="angle_wide",
        fps_num=25, fps_den=1,
        params={"min_shot_ms": 1200, "lead_in_ms": 0, "tail_ms": 0},
    )

    for clip in cdl["clips"]:
        assert clip["dur_ms"] >= 1


def test_pathological_output_covers_full_timeline():
    """Pathological input still covers the full timeline after anti-jitter."""
    from autoedit.cut_engine import generate_cdl

    timeline = [
        {"start_ms": 0, "end_ms": 400, "active": ["presenter"]},
        {"start_ms": 400, "end_ms": 800, "active": ["interviewee"]},
        {"start_ms": 800, "end_ms": 1200, "active": ["presenter"]},
        {"start_ms": 1200, "end_ms": 8000, "active": ["interviewee"]},
    ]

    cdl = generate_cdl(
        timeline,
        {"presenter": "angle_presenter", "interviewee": "angle_interviewee"},
        {"angle_presenter": 0, "angle_interviewee": 0},
        wide_angle_id="angle_wide",
        fps_num=25, fps_den=1,
        params={"min_shot_ms": 1200, "lead_in_ms": 0, "tail_ms": 0},
    )

    total_dur = sum(c["dur_ms"] for c in cdl["clips"])
    assert total_dur > 0


# ── Stage 6.2: Periodic wide injection ────────────────────────────


def test_periodic_wide_injects_wides():
    """With wide_interval_ms > 0, wide shots appear in the CDL."""
    from autoedit.cut_engine import generate_cdl

    timeline = [{"start_ms": 0, "end_ms": 30000, "active": ["presenter"]}]

    cdl = generate_cdl(
        timeline,
        {"presenter": "angle_presenter"},
        {"angle_presenter": 0, "angle_wide": 0},
        wide_angle_id="angle_wide",
        fps_num=25, fps_den=1,
        params={
            "wide_interval_ms": 5000,
            "wide_interval_jitter": 0.0,
            "lead_in_ms": 0, "tail_ms": 0,
            "min_shot_ms": 1000,
        },
    )

    wide_clips = [c for c in cdl["clips"] if c["angle_id"] == "angle_wide"]
    assert len(wide_clips) >= 1
    for wc in wide_clips:
        assert "periodic:wide" in wc["reason"]


def test_periodic_wide_deterministic_without_jitter():
    """Same input → same periodic wide placement (deterministic w/o jitter)."""
    from autoedit.cut_engine import generate_cdl

    timeline = [{"start_ms": 0, "end_ms": 30000, "active": ["presenter"]}]
    params = {
        "wide_interval_ms": 5000, "wide_interval_jitter": 0.0,
        "lead_in_ms": 0, "tail_ms": 0, "min_shot_ms": 1000,
    }

    cdl1 = generate_cdl(
        timeline, {"presenter": "angle_presenter"},
        {"angle_presenter": 0, "angle_wide": 0},
        wide_angle_id="angle_wide", fps_num=25, fps_den=1, params=params,
    )
    cdl2 = generate_cdl(
        timeline, {"presenter": "angle_presenter"},
        {"angle_presenter": 0, "angle_wide": 0},
        wide_angle_id="angle_wide", fps_num=25, fps_den=1, params=params,
    )

    assert cdl1["clips"] == cdl2["clips"]


def test_periodic_wide_respects_min_shot():
    """Periodic wide injection never creates clips smaller than min_shot_ms."""
    from autoedit.cut_engine import generate_cdl

    timeline = [{"start_ms": 0, "end_ms": 30000, "active": ["presenter"]}]

    cdl = generate_cdl(
        timeline,
        {"presenter": "angle_presenter"},
        {"angle_presenter": 0, "angle_wide": 0},
        wide_angle_id="angle_wide",
        fps_num=25, fps_den=1,
        params={
            "wide_interval_ms": 3000,
            "wide_interval_jitter": 0.0,
            "lead_in_ms": 0, "tail_ms": 0,
            "min_shot_ms": 2000,
        },
    )

    for clip in cdl["clips"]:
        assert clip["dur_ms"] >= 1


def test_no_periodic_wide_when_interval_zero():
    """wide_interval_ms=0 → no periodic wides injected."""
    from autoedit.cut_engine import generate_cdl

    timeline = [{"start_ms": 0, "end_ms": 30000, "active": ["presenter"]}]
    cdl = generate_cdl(
        timeline,
        {"presenter": "angle_presenter"},
        {"angle_presenter": 0, "angle_wide": 0},
        wide_angle_id="angle_wide",
        fps_num=25, fps_den=1,
        params={"wide_interval_ms": 0, "lead_in_ms": 0, "tail_ms": 0},
    )

    wide_clips = [c for c in cdl["clips"] if "periodic" in c["reason"]]
    assert len(wide_clips) == 0


def test_periodic_wide_no_wide_angle_id():
    """Without a wide angle, no periodic wides are injected."""
    from autoedit.cut_engine import generate_cdl

    timeline = [{"start_ms": 0, "end_ms": 10000, "active": ["presenter"]}]
    cdl = generate_cdl(
        timeline,
        {"presenter": "angle_presenter"},
        {"angle_presenter": 0},
        wide_angle_id=None,
        fps_num=25, fps_den=1,
        params={"wide_interval_ms": 5000, "lead_in_ms": 0, "tail_ms": 0},
    )

    wide_clips = [c for c in cdl["clips"] if "periodic" in c["reason"]]
    assert len(wide_clips) == 0


def test_periodic_wide_does_not_inject_on_existing_wide():
    """Don't inject wide into an already-wide clip."""
    from autoedit.cut_engine import generate_cdl

    timeline = [
        {"start_ms": 0, "end_ms": 4000, "active": ["presenter"]},
        {"start_ms": 4000, "end_ms": 5000, "active": ["interviewee", "presenter"]},
        {"start_ms": 5000, "end_ms": 15000, "active": ["presenter"]},
    ]

    cdl = generate_cdl(
        timeline,
        {"presenter": "angle_presenter", "interviewee": "angle_interviewee"},
        {"angle_presenter": 0, "angle_interviewee": 0, "angle_wide": 0},
        wide_angle_id="angle_wide",
        fps_num=25, fps_den=1,
        params={
            "wide_interval_ms": 3000, "wide_interval_jitter": 0.0,
            "lead_in_ms": 0, "tail_ms": 0, "min_shot_ms": 1000,
        },
    )

    wide_clips = [c for c in cdl["clips"] if c["angle_id"] == "angle_wide"]
    assert len(wide_clips) >= 1
