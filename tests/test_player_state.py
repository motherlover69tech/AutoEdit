from __future__ import annotations

import json
from datetime import datetime
from pathlib import Path

import pytest
from fastapi.testclient import TestClient
from sqlalchemy import create_engine
from sqlalchemy.orm import Session
from sqlalchemy.pool import StaticPool

from autoedit.api import create_app
from autoedit.db.migrate import run_migrations
from autoedit.db.schema import angles, audio_channels, cuts
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
        json={"name": "Player Test", "fps_num": 24000, "fps_den": 1001},
    )
    assert response.status_code == 201
    return response.json()["id"]


def _seed_player_project(
    client: TestClient,
    data_root: Path,
    engine,
    *,
    include_program_audio: bool = True,
    include_rough_cut: bool = True,
) -> dict:
    project_id = _create_project(client)
    project_dir = data_root / project_id
    (project_dir / "proxy").mkdir(parents=True, exist_ok=True)
    (project_dir / "proxy_low").mkdir(parents=True, exist_ok=True)
    (project_dir / "audio").mkdir(parents=True, exist_ok=True)

    angle_a = new_ulid()
    angle_b = new_ulid()
    angle_without_proxy = new_ulid()

    (project_dir / "proxy" / f"{angle_a}.proxy.mp4").write_bytes(b"main-a")
    (project_dir / "proxy_low" / f"{angle_a}.proxy.mp4").write_bytes(b"low-a")
    (project_dir / "proxy" / f"{angle_b}.proxy.mp4").write_bytes(b"main-b")
    if include_program_audio:
        (project_dir / "audio" / "program.m4a").write_bytes(b"program")

    cdl = {
        "version": 1,
        "project_id": project_id,
        "fps": {"num": 24000, "den": 1001},
        "audio": {"channels": ["Peter", "Guest"]},
        "clips": [
            {
                "angle_id": angle_a,
                "src_in_ms": 0,
                "timeline_in_ms": 0,
                "dur_ms": 2000,
                "reason": "speaker:Peter",
            },
            {
                "angle_id": angle_b,
                "src_in_ms": 1900,
                "timeline_in_ms": 2000,
                "dur_ms": 2000,
                "reason": "speaker:Guest",
            },
        ],
        "luts": {"active": None},
    }

    with Session(engine) as session:
        session.execute(
            angles.insert(),
            [
                {
                    "id": angle_a,
                    "project_id": project_id,
                    "label": "Presenter",
                    "role": "cam_left",
                    "source_path": "source/presenter.mp4",
                    "proxy_path": f"proxy/{angle_a}.proxy.mp4",
                    "proxy_low_path": f"proxy_low/{angle_a}.proxy.mp4",
                    "sync_offset_ms": 0,
                },
                {
                    "id": angle_b,
                    "project_id": project_id,
                    "label": "Guest",
                    "role": "cam_right",
                    "source_path": "source/guest.mp4",
                    "proxy_path": f"proxy/{angle_b}.proxy.mp4",
                    "proxy_low_path": None,
                    "sync_offset_ms": 100,
                },
                {
                    "id": angle_without_proxy,
                    "project_id": project_id,
                    "label": "Wide missing proxy",
                    "role": "wide",
                    "source_path": "source/wide.mp4",
                    "proxy_path": None,
                    "proxy_low_path": None,
                    "sync_offset_ms": 0,
                },
            ],
        )
        session.execute(
            audio_channels.insert(),
            [
                {
                    "id": new_ulid(),
                    "project_id": project_id,
                    "speaker_label": "Peter",
                    "source_angle_id": angle_b,
                    "channel_index": 0,
                    "wav_path": "audio/ch_peter.wav",
                },
                {
                    "id": new_ulid(),
                    "project_id": project_id,
                    "speaker_label": "Guest",
                    "source_angle_id": angle_b,
                    "channel_index": 1,
                    "wav_path": "audio/ch_guest.wav",
                },
            ],
        )
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

    return {
        "project_id": project_id,
        "angle_a": angle_a,
        "angle_b": angle_b,
        "angle_without_proxy": angle_without_proxy,
        "cdl": cdl,
    }


def test_player_state_missing_project_returns_404(app_context):
    client, _, _ = app_context

    response = client.get(f"/projects/{MISSING_PROJECT_ID}/player-state")

    assert response.status_code == 404
    assert response.json()["detail"] == "project not found"


def test_player_state_requires_auth_when_enabled(tmp_path: Path):
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

    response = client.get(f"/projects/{MISSING_PROJECT_ID}/player-state")

    assert response.status_code == 401
    assert response.json() == {"detail": "authentication required"}


def test_player_state_without_rough_cut_returns_400(app_context):
    client, data_root, engine = app_context
    seeded = _seed_player_project(client, data_root, engine, include_rough_cut=False)

    response = client.get(f"/projects/{seeded['project_id']}/player-state")

    assert response.status_code == 400
    assert response.json()["detail"] == "rough cut not found — run /cut first"


def test_player_state_without_program_audio_returns_400(app_context):
    client, data_root, engine = app_context
    seeded = _seed_player_project(client, data_root, engine, include_program_audio=False)

    response = client.get(f"/projects/{seeded['project_id']}/player-state")

    assert response.status_code == 400
    assert response.json()["detail"] == "program audio not found — run /program-audio first"


def test_player_state_returns_frontend_bootstrap_payload(app_context):
    client, data_root, engine = app_context
    seeded = _seed_player_project(client, data_root, engine)

    response = client.get(f"/projects/{seeded['project_id']}/player-state")

    assert response.status_code == 200
    body = response.json()
    assert body["project"] == {
        "id": seeded["project_id"],
        "name": "Player Test",
        "fps_num": 24000,
        "fps_den": 1001,
    }
    assert body["audio"] == {
        "program_url": f"/projects/{seeded['project_id']}/media/audio/program.m4a"
    }
    assert body["quality_default"] == "proxy"
    assert body["cut"]["name"] == "Rough cut"
    assert body["cut"]["clips"] == seeded["cdl"]["clips"]

    returned_ids = {angle["id"] for angle in body["angles"]}
    assert returned_ids == {seeded["angle_a"], seeded["angle_b"]}
    assert seeded["angle_without_proxy"] not in returned_ids

    angles_by_id = {angle["id"]: angle for angle in body["angles"]}
    angle_a = angles_by_id[seeded["angle_a"]]
    assert angle_a == {
        "id": seeded["angle_a"],
        "label": "Presenter",
        "role": "cam_left",
        "proxy_url": f"/projects/{seeded['project_id']}/media/proxy/{seeded['angle_a']}.proxy.mp4",
        "proxy_low_url": f"/projects/{seeded['project_id']}/media/proxy_low/{seeded['angle_a']}.proxy.mp4",
        "sync_offset_ms": 0,
        "source_time_offset_ms": -100,
    }

    angle_b = angles_by_id[seeded["angle_b"]]
    assert angle_b["id"] == seeded["angle_b"]
    assert angle_b["proxy_url"] == f"/projects/{seeded['project_id']}/media/proxy/{seeded['angle_b']}.proxy.mp4"
    assert "proxy_low_url" not in angle_b
    assert angle_b["sync_offset_ms"] == 100
    assert angle_b["source_time_offset_ms"] == 0


def test_player_state_uses_latest_rough_cut_without_sorting_cdl_payload(app_context):
    client, data_root, engine = app_context
    seeded = _seed_player_project(client, data_root, engine)
    latest_cdl = {
        **seeded["cdl"],
        "clips": [
            {
                "angle_id": seeded["angle_a"],
                "src_in_ms": 0,
                "timeline_in_ms": 0,
                "dur_ms": 1000,
                "reason": "latest:rough",
            }
        ],
    }

    with Session(engine) as session:
        session.execute(
            cuts.insert().values(
                id=new_ulid(),
                project_id=seeded["project_id"],
                name="Latest rough cut",
                kind="rough",
                params_json={"min_shot_ms": 900},
                cdl_json=latest_cdl,
                created_at=datetime(2030, 1, 1, 12, 0, 0),
            )
        )
        session.commit()

    response = client.get(f"/projects/{seeded['project_id']}/player-state")

    assert response.status_code == 200
    body = response.json()
    assert body["cut"]["name"] == "Latest rough cut"
    assert body["cut"]["clips"] == latest_cdl["clips"]


def test_player_state_urls_do_not_expose_data_root(app_context):
    client, data_root, engine = app_context
    seeded = _seed_player_project(client, data_root, engine)

    response = client.get(f"/projects/{seeded['project_id']}/player-state")

    assert response.status_code == 200
    serialized = response.text
    assert str(data_root) not in serialized
    assert "/data" not in serialized
    assert "/source/" not in serialized
    assert f"/projects/{seeded['project_id']}/media/" in serialized


def test_player_state_exposes_projected_activity_additively(app_context):
    client, data_root, engine = app_context
    seeded = _seed_player_project(client, data_root, engine)
    activity_path = data_root / seeded["project_id"] / "audio" / "ai" / "v1" / "activity-whisperx.json"
    activity_path.parent.mkdir(parents=True)
    activity = {
        "source": "whisperx",
        "artifact_version": "run-one",
        "total_duration_ms": 4000,
        "timeline": [{"start_ms": 0, "end_ms": 4000, "active": [], "mapping_status": "unresolved", "authority_status": "unresolved", "unresolved": True}],
    }
    activity_path.write_text(json.dumps(activity))

    body = client.get(f"/projects/{seeded['project_id']}/player-state").json()

    assert body["projected_activity"] == activity
    assert body["cut"]["clips"] == seeded["cdl"]["clips"]
