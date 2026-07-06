from __future__ import annotations

import io
from pathlib import Path

import pytest
from fastapi.testclient import TestClient
from sqlalchemy import create_engine
from sqlalchemy.pool import StaticPool

from autoedit.api import create_app
from autoedit.db.migrate import run_migrations

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
        json={"name": "LUT Test", "fps_num": 24000, "fps_den": 1001},
    )
    assert response.status_code == 201
    return response.json()["id"]


# ── Upload tests ──────────────────────────────────────────────

def test_lut_upload_requires_auth(tmp_path: Path):
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
    response = client.post(f"/projects/{MISSING_PROJECT_ID}/luts")
    assert response.status_code == 401


def test_lut_upload_missing_project_returns_404(app_context):
    client, _, _ = app_context
    response = client.post(
        f"/projects/{MISSING_PROJECT_ID}/luts",
        files={"file": ("test.cube", io.BytesIO(b"data"), "application/octet-stream")},
    )
    assert response.status_code == 404


def test_lut_upload_rejects_non_cube_extension(app_context):
    client, _, _ = app_context
    project_id = _create_project(client)
    response = client.post(
        f"/projects/{project_id}/luts",
        files={"file": ("test.png", io.BytesIO(b"data"), "image/png")},
    )
    assert response.status_code == 400
    assert "cube" in response.json()["detail"].lower()


def test_lut_upload_rejects_invalid_cube_content(app_context):
    client, _, _ = app_context
    project_id = _create_project(client)
    response = client.post(
        f"/projects/{project_id}/luts",
        files={"file": ("bad.cube", io.BytesIO(b"not a valid cube file"), "application/octet-stream")},
    )
    assert response.status_code == 400
    assert "cube" in response.json()["detail"].lower()


def test_lut_upload_accepts_valid_cube(app_context):
    client, data_root, _ = app_context
    project_id = _create_project(client)

    response = client.post(
        f"/projects/{project_id}/luts",
        files={"file": ("test.cube", io.BytesIO(MINIMAL_CUBE.encode()), "application/octet-stream")},
    )
    assert response.status_code == 201
    body = response.json()
    assert body["filename"] == "test.cube"
    assert body["size"] == 2
    assert "title" in body

    # File exists on disk
    lut_path = data_root / project_id / "luts" / "test.cube"
    assert lut_path.is_file()


def test_lut_upload_with_filename(app_context):
    client, data_root, _ = app_context
    project_id = _create_project(client)

    response = client.post(
        f"/projects/{project_id}/luts",
        files={"file": ("my_grade.cube", io.BytesIO(MINIMAL_CUBE.encode()), "application/octet-stream")},
    )
    assert response.status_code == 201
    assert response.json()["filename"] == "my_grade.cube"

    lut_path = data_root / project_id / "luts" / "my_grade.cube"
    assert lut_path.is_file()


def test_lut_upload_rejects_path_traversal_filename(app_context):
    client, _, _ = app_context
    project_id = _create_project(client)

    response = client.post(
        f"/projects/{project_id}/luts",
        files={"file": ("../escape.cube", io.BytesIO(MINIMAL_CUBE.encode()), "application/octet-stream")},
    )
    assert response.status_code == 400


# ── List tests ────────────────────────────────────────────────

def test_lut_list_requires_auth(tmp_path: Path):
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
    response = client.get(f"/projects/{MISSING_PROJECT_ID}/luts")
    assert response.status_code == 401


def test_lut_list_missing_project_returns_404(app_context):
    client, _, _ = app_context
    response = client.get(f"/projects/{MISSING_PROJECT_ID}/luts")
    assert response.status_code == 404


def test_lut_list_returns_uploaded_luts(app_context):
    client, _, _ = app_context
    project_id = _create_project(client)

    # Upload two LUTs
    client.post(
        f"/projects/{project_id}/luts",
        files={"file": ("a.cube", io.BytesIO(MINIMAL_CUBE.encode()), "application/octet-stream")},
    )
    client.post(
        f"/projects/{project_id}/luts",
        files={"file": ("b.cube", io.BytesIO(MINIMAL_CUBE.encode()), "application/octet-stream")},
    )

    response = client.get(f"/projects/{project_id}/luts")
    assert response.status_code == 200
    body = response.json()
    assert len(body["luts"]) == 2
    filenames = {lut["filename"] for lut in body["luts"]}
    assert filenames == {"a.cube", "b.cube"}
    assert body["active"] is None  # No LUT active by default


def test_lut_list_empty_project(app_context):
    client, _, _ = app_context
    project_id = _create_project(client)

    response = client.get(f"/projects/{project_id}/luts")
    assert response.status_code == 200
    body = response.json()
    assert body["luts"] == []
    assert body["active"] is None


# ── Activate tests ────────────────────────────────────────────

def test_lut_activate_sets_active_lut(app_context):
    client, _, _ = app_context
    project_id = _create_project(client)

    client.post(
        f"/projects/{project_id}/luts",
        files={"file": ("my.cube", io.BytesIO(MINIMAL_CUBE.encode()), "application/octet-stream")},
    )

    response = client.post(
        f"/projects/{project_id}/luts/activate",
        json={"filename": "my.cube"},
    )
    assert response.status_code == 200
    assert response.json()["default"] == "my.cube"


def test_lut_activate_rejects_nonexistent_lut(app_context):
    client, _, _ = app_context
    project_id = _create_project(client)

    response = client.post(
        f"/projects/{project_id}/luts/activate",
        json={"filename": "nonexistent.cube"},
    )
    assert response.status_code == 400


def test_lut_deactivate_clears_active(app_context):
    client, _, _ = app_context
    project_id = _create_project(client)

    client.post(
        f"/projects/{project_id}/luts",
        files={"file": ("my.cube", io.BytesIO(MINIMAL_CUBE.encode()), "application/octet-stream")},
    )
    client.post(
        f"/projects/{project_id}/luts/activate",
        json={"filename": "my.cube"},
    )

    response = client.post(f"/projects/{project_id}/luts/deactivate")
    assert response.status_code == 200
    assert response.json()["default"] is None


# ── Player-state integration ─────────────────────────────────

def test_player_state_includes_active_lut(app_context):
    client, data_root, engine = app_context
    project_id = _create_project(client)
    project_dir = data_root / project_id
    (project_dir / "proxy").mkdir(exist_ok=True)
    (project_dir / "proxy_low").mkdir(exist_ok=True)
    (project_dir / "audio").mkdir(exist_ok=True)
    (project_dir / "audio" / "program.m4a").write_bytes(b"audio")

    from autoedit.db.schema import angles, cuts
    from autoedit.projects import new_ulid
    from sqlalchemy.orm import Session

    angle_id = new_ulid()
    with Session(engine) as session:
        session.execute(
            angles.insert().values(
                id=angle_id,
                project_id=project_id,
                label="Cam A",
                role="cam_left",
                source_path="source/a.mp4",
                proxy_path=f"proxy/{angle_id}.proxy.mp4",
            )
        )
        (project_dir / "proxy" / f"{angle_id}.proxy.mp4").write_bytes(b"proxy")
        session.execute(
            cuts.insert().values(
                id=new_ulid(),
                project_id=project_id,
                name="Rough",
                kind="rough",
                params_json={},
                cdl_json={
                    "version": 1,
                    "clips": [{"angle_id": angle_id, "src_in_ms": 0, "timeline_in_ms": 0, "dur_ms": 1000}],
                },
            )
        )
        session.commit()

    # Upload and activate a LUT
    client.post(
        f"/projects/{project_id}/luts",
        files={"file": ("grade.cube", io.BytesIO(MINIMAL_CUBE.encode()), "application/octet-stream")},
    )
    client.post(f"/projects/{project_id}/luts/activate", json={"filename": "grade.cube"})

    response = client.get(f"/projects/{project_id}/player-state")
    assert response.status_code == 200
    body = response.json()
    assert "active_lut" in body
    assert body["active_lut"]["filename"] == "grade.cube"
    assert body["active_lut"]["size"] == 2
    assert body["active_lut"]["title"] == "Test LUT"
    assert body["active_lut"]["url"].endswith("/grade.cube")


def test_player_state_no_active_lut_when_none(app_context):
    client, data_root, engine = app_context
    project_id = _create_project(client)
    project_dir = data_root / project_id
    (project_dir / "proxy").mkdir(exist_ok=True)
    (project_dir / "proxy_low").mkdir(exist_ok=True)
    (project_dir / "audio").mkdir(exist_ok=True)
    (project_dir / "audio" / "program.m4a").write_bytes(b"audio")

    from autoedit.db.schema import angles, cuts
    from autoedit.projects import new_ulid
    from sqlalchemy.orm import Session

    angle_id = new_ulid()
    with Session(engine) as session:
        session.execute(
            angles.insert().values(
                id=angle_id,
                project_id=project_id,
                label="Cam A",
                role="cam_left",
                source_path="source/a.mp4",
                proxy_path=f"proxy/{angle_id}.proxy.mp4",
            )
        )
        (project_dir / "proxy" / f"{angle_id}.proxy.mp4").write_bytes(b"proxy")
        session.execute(
            cuts.insert().values(
                id=new_ulid(),
                project_id=project_id,
                name="Rough",
                kind="rough",
                params_json={},
                cdl_json={
                    "version": 1,
                    "clips": [{"angle_id": angle_id, "src_in_ms": 0, "timeline_in_ms": 0, "dur_ms": 1000}],
                },
            )
        )
        session.commit()

    response = client.get(f"/projects/{project_id}/player-state")
    assert response.status_code == 200
    body = response.json()
    assert body["active_lut"] is None
