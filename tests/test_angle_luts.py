from __future__ import annotations

import io
from pathlib import Path

import pytest
from fastapi.testclient import TestClient
from sqlalchemy import create_engine
from sqlalchemy.orm import Session
from sqlalchemy.pool import StaticPool

from autoedit.api import create_app
from autoedit.db.migrate import run_migrations
from autoedit.db.schema import angles, cuts
from autoedit.projects import new_ulid

MISSING_PROJECT_ID = "01J00000000000000000000000"

MINIMAL_CUBE = (
    'TITLE "Test LUT"\n'
    "LUT_3D_SIZE 2\n"
    "0.0 0.0 0.0\n"
    "0.0 0.0 1.0\n"
    "0.0 1.0 0.0\n"
    "0.0 1.0 1.0\n"
    "1.0 0.0 0.0\n"
    "1.0 0.0 1.0\n"
    "1.0 1.0 0.0\n"
    "1.0 1.0 1.0\n"
)

CUBE_B = (
    'TITLE "LUT B"\n'
    "LUT_3D_SIZE 2\n"
    "0.1 0.1 0.1\n"
    "0.1 0.1 1.0\n"
    "0.1 1.0 0.0\n"
    "0.1 1.0 1.0\n"
    "1.0 0.1 0.0\n"
    "1.0 0.1 1.0\n"
    "1.0 1.0 0.1\n"
    "1.0 1.0 1.0\n"
)


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
        json={"name": "Angle LUT Test", "fps_num": 24000, "fps_den": 1001},
    )
    assert response.status_code == 201
    return response.json()["id"]


# ── Assign angle LUT ────────────────────────────────────────

def test_assign_lut_to_angle(app_context):
    client, data_root, _ = app_context
    project_id = _create_project(client)
    # Upload a LUT
    client.post(
        f"/projects/{project_id}/luts",
        files={"file": ("grade.cube", io.BytesIO(MINIMAL_CUBE.encode()), "application/octet-stream")},
    )

    response = client.post(
        f"/projects/{project_id}/luts/assign",
        json={"angle_id": "01ABCDEFGHIJKLMNOPQRSTUV", "filename": "grade.cube"},
    )
    assert response.status_code == 200
    assert response.json()["angle_luts"]["01ABCDEFGHIJKLMNOPQRSTUV"] == "grade.cube"


def test_assign_lut_requires_existing_lut(app_context):
    client, _, _ = app_context
    project_id = _create_project(client)

    response = client.post(
        f"/projects/{project_id}/luts/assign",
        json={"angle_id": "01ABCDEFGHIJKLMNOPQRSTUV", "filename": "nonexistent.cube"},
    )
    assert response.status_code == 400
    assert "not found" in response.json()["detail"].lower()


def test_assign_lut_requires_missing_project_404(app_context):
    client, _, _ = app_context
    response = client.post(
        f"/projects/{MISSING_PROJECT_ID}/luts/assign",
        json={"angle_id": "01ABCDEFGHIJKLMNOPQRSTUV", "filename": "test.cube"},
    )
    assert response.status_code == 404


def test_unassign_angle_lut(app_context):
    client, data_root, _ = app_context
    project_id = _create_project(client)
    angle_id = "01ABCDEFGHIJKLMNOPQRSTUV"
    client.post(
        f"/projects/{project_id}/luts",
        files={"file": ("grade.cube", io.BytesIO(MINIMAL_CUBE.encode()), "application/octet-stream")},
    )
    client.post(
        f"/projects/{project_id}/luts/assign",
        json={"angle_id": angle_id, "filename": "grade.cube"},
    )

    response = client.post(
        f"/projects/{project_id}/luts/unassign",
        json={"angle_id": angle_id},
    )
    assert response.status_code == 200
    assert angle_id not in response.json()["angle_luts"]


def test_unassign_nonexistent_angle_is_noop(app_context):
    client, data_root, _ = app_context
    project_id = _create_project(client)

    response = client.post(
        f"/projects/{project_id}/luts/unassign",
        json={"angle_id": "01ABCDEFGHIJKLMNOPQRSTUV"},
    )
    assert response.status_code == 200


# ── Global LUT library ──────────────────────────────────────

def test_global_lut_upload(app_context):
    client, data_root, _ = app_context
    (data_root / "luts").mkdir(parents=True, exist_ok=True)

    response = client.post(
        "/luts",
        files={"file": ("universal.cube", io.BytesIO(MINIMAL_CUBE.encode()), "application/octet-stream")},
    )
    assert response.status_code == 201
    assert response.json()["filename"] == "universal.cube"
    assert (data_root / "luts" / "universal.cube").is_file()


def test_global_lut_list(app_context):
    client, data_root, _ = app_context
    (data_root / "luts").mkdir(parents=True, exist_ok=True)
    client.post(
        "/luts",
        files={"file": ("a.cube", io.BytesIO(MINIMAL_CUBE.encode()), "application/octet-stream")},
    )
    client.post(
        "/luts",
        files={"file": ("b.cube", io.BytesIO(CUBE_B.encode()), "application/octet-stream")},
    )

    response = client.get("/luts")
    assert response.status_code == 200
    names = {lut["filename"] for lut in response.json()["luts"]}
    assert names == {"a.cube", "b.cube"}


def test_global_lut_list_empty(app_context):
    client, data_root, _ = app_context

    response = client.get("/luts")
    assert response.status_code == 200
    assert response.json()["luts"] == []


def test_global_lut_auth(tmp_path: Path):
    engine = create_engine(
        "sqlite:///:memory:",
        connect_args={"check_same_thread": False},
        poolclass=StaticPool,
    )
    run_migrations(engine)
    app = create_app(
        engine=engine, data_root=tmp_path,
        auth_enabled=True, operator_password="pw", session_secret="s",
        session_cookie_secure=False,
    )
    client = TestClient(app)
    assert client.post("/luts").status_code == 401
    assert client.get("/luts").status_code == 401


# ── Player-state with per-angle LUTs ────────────────────────

def _seed_player_with_luts(client, data_root, engine):
    project_id = _create_project(client)
    project_dir = data_root / project_id
    (project_dir / "proxy").mkdir(exist_ok=True)
    (project_dir / "proxy_low").mkdir(exist_ok=True)
    (project_dir / "audio").mkdir(exist_ok=True)
    (project_dir / "audio" / "program.m4a").write_bytes(b"audio")

    angle_a = new_ulid()
    angle_b = new_ulid()

    with Session(engine) as session:
        session.execute(angles.insert(), [
            {"id": angle_a, "project_id": project_id, "label": "Wide", "role": "wide",
             "source_path": "source/a.mp4", "proxy_path": f"proxy/{angle_a}.proxy.mp4"},
            {"id": angle_b, "project_id": project_id, "label": "Close-up", "role": "cam_left",
             "source_path": "source/b.mp4", "proxy_path": f"proxy/{angle_b}.proxy.mp4"},
        ])
        (project_dir / "proxy" / f"{angle_a}.proxy.mp4").write_bytes(b"px")
        (project_dir / "proxy" / f"{angle_b}.proxy.mp4").write_bytes(b"px")
        session.execute(cuts.insert().values(
            id=new_ulid(), project_id=project_id, name="Rough", kind="rough",
            params_json={},
            cdl_json={
                "version": 1,
                "clips": [
                    {"angle_id": angle_a, "src_in_ms": 0, "timeline_in_ms": 0, "dur_ms": 1000},
                    {"angle_id": angle_b, "src_in_ms": 0, "timeline_in_ms": 1000, "dur_ms": 1000},
                ],
            },
        ))
        session.commit()

    # Upload LUTs
    client.post(f"/projects/{project_id}/luts",
        files={"file": ("wide.cube", io.BytesIO(MINIMAL_CUBE.encode()), "application/octet-stream")})
    client.post(f"/projects/{project_id}/luts",
        files={"file": ("cu.cube", io.BytesIO(CUBE_B.encode()), "application/octet-stream")})
    # Assign to angles
    client.post(f"/projects/{project_id}/luts/assign",
        json={"angle_id": angle_a, "filename": "wide.cube"})
    client.post(f"/projects/{project_id}/luts/assign",
        json={"angle_id": angle_b, "filename": "cu.cube"})

    return project_id, angle_a, angle_b


def test_player_state_includes_angle_luts(app_context):
    client, data_root, engine = app_context
    project_id, angle_a, angle_b = _seed_player_with_luts(client, data_root, engine)

    response = client.get(f"/projects/{project_id}/player-state")
    assert response.status_code == 200
    body = response.json()

    assert "angle_luts" in body
    assert body["angle_luts"][angle_a]["filename"] == "wide.cube"
    assert body["angle_luts"][angle_b]["filename"] == "cu.cube"
    assert body["active_lut"] is None  # No default set


def test_player_state_active_lut_as_default(app_context):
    client, data_root, engine = app_context
    project_id, angle_a, angle_b = _seed_player_with_luts(client, data_root, engine)
    # Set a default
    client.post(f"/projects/{project_id}/luts/activate", json={"filename": "wide.cube"})

    response = client.get(f"/projects/{project_id}/player-state")
    assert response.status_code == 200
    body = response.json()
    assert body["active_lut"]["filename"] == "wide.cube"
    # angle_luts still present
    assert body["angle_luts"][angle_a]["filename"] == "wide.cube"
    assert body["angle_luts"][angle_b]["filename"] == "cu.cube"


# ── Legacy activate/deactivate still work ───────────────────

def test_legacy_activate_deactivate_still_work(app_context):
    client, data_root, _ = app_context
    project_id = _create_project(client)
    client.post(f"/projects/{project_id}/luts",
        files={"file": ("x.cube", io.BytesIO(MINIMAL_CUBE.encode()), "application/octet-stream")})

    r = client.post(f"/projects/{project_id}/luts/activate", json={"filename": "x.cube"})
    assert r.status_code == 200
    assert r.json()["default"] == "x.cube"
    # Also accessible via list
    r2 = client.get(f"/projects/{project_id}/luts")
    assert r2.json()["active"] == "x.cube"
    assert r2.json()["default"] == "x.cube"

    r3 = client.post(f"/projects/{project_id}/luts/deactivate")
    assert r3.status_code == 200
    assert r3.json()["default"] is None
