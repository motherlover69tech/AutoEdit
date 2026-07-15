from __future__ import annotations

import hashlib
from pathlib import Path
from unittest.mock import patch

import pytest
from fastapi.testclient import TestClient
from sqlalchemy import create_engine, select
from sqlalchemy.pool import StaticPool
from sqlalchemy.orm import Session

from autoedit.api import create_app
from autoedit.db.migrate import run_migrations
from autoedit.db.schema import angles


@pytest.fixture
def auth_client(tmp_path: Path, monkeypatch):
    # These tests assert software-encoder (libx264) ffmpeg flags. The app
    # default is h264_vaapi, which emits scale_vaapi/-vaapi_device instead,
    # so pin the software encoder to keep the assertions environment-independent
    # (they previously broke on any host with a /dev/dri node).
    monkeypatch.setenv("PROXY_ENCODER", "libx264")
    monkeypatch.setenv("PROXY_LOW_CRF", "20")
    engine = create_engine(
        "sqlite:///:memory:",
        connect_args={"check_same_thread": False},
        poolclass=StaticPool,
    )
    run_migrations(engine)
    app = create_app(
        engine=engine, data_root=tmp_path, auth_enabled=True,
        operator_password="correct-password", session_secret="test-session-secret",
        public_domain="autoedit.example.com", session_cookie_secure=False,
    )
    client = TestClient(app)
    login = client.post(
        "/auth/login",
        json={"password": "correct-password", "display_name": "Peter"},
    )
    assert login.status_code == 204
    return client, tmp_path, engine


def _seed_angle(client, project_id, data_root, *, label, role, filename, content=b"mock"):
    created = client.post(
        f"/projects/{project_id}/uploads",
        json={
            "filename": filename, "label": label, "role": role,
            "total_bytes": len(content), "total_chunks": 1,
        },
    )
    assert created.status_code == 201
    upload_id = created.json()["upload_id"]
    client.post(f"/upload/{upload_id}/chunk/0", content=content)
    complete = client.post(
        f"/upload/{upload_id}/complete",
        json={
            "sha256": hashlib.sha256(content).hexdigest(),
            "total_bytes": len(content),
        },
    )
    assert complete.status_code == 201
    return complete.json()


@pytest.fixture
def project_with_angle(auth_client):
    client, data_root, engine = auth_client
    resp = client.post(
        "/projects", json={"name": "Proxy low test", "fps_num": 24000, "fps_den": 1001},
    )
    assert resp.status_code == 201
    project_body = resp.json()
    pid = project_body["id"]
    angle = _seed_angle(client, pid, data_root, label="Presenter", role="cam_left", filename="angleA.mp4")
    return project_body, angle, client, data_root, engine


def _mock_ffmpeg():
    from unittest.mock import MagicMock

    def _run(cmd, **kwargs):
        result = MagicMock()
        result.returncode = 0
        result.stdout = ""
        result.stderr = ""
        return result

    return _run


# ── Auth / 404 tests ────────────────────────────────────────────────


def test_proxy_low_route_requires_auth(tmp_path: Path):
    engine = create_engine(
        "sqlite:///:memory:",
        connect_args={"check_same_thread": False}, poolclass=StaticPool,
    )
    run_migrations(engine)
    app = create_app(
        engine=engine, data_root=tmp_path, auth_enabled=True,
        operator_password="correct-password", session_secret="test-session-secret",
        session_cookie_secure=False,
    )
    client = TestClient(app)
    response = client.post("/projects/01J00000000000000000000000/proxy-low")
    assert response.status_code == 401


def test_proxy_low_rejects_missing_project(auth_client):
    client, _, _ = auth_client
    response = client.post("/projects/01J00000000000000000000000/proxy-low")
    assert response.status_code == 404


# ── Low proxy generation tests ──────────────────────────────────────


def test_single_angle_proxy_low_updates_db(project_with_angle):
    project_body, angle, client, data_root, engine = project_with_angle
    pid = project_body["id"]
    aid = angle["id"]

    with patch("autoedit.proxy.run_ffmpeg_watchdog", side_effect=_mock_ffmpeg()):
        response = client.post(f"/projects/{pid}/angles/{aid}/proxy-low")

    assert response.status_code == 200
    result = response.json()
    assert result["angle_id"] == aid
    assert result["proxy_low_path"] is not None
    assert "proxy_low/" in result["proxy_low_path"]

    with Session(engine) as session:
        row = session.execute(select(angles).where(angles.c.id == aid)).one()._mapping
    assert row.proxy_low_path == result["proxy_low_path"]


def test_bulk_proxy_low_generates_for_all_angles(auth_client):
    client, data_root, engine = auth_client
    resp = client.post(
        "/projects", json={"name": "Multi low", "fps_num": 24000, "fps_den": 1001},
    )
    assert resp.status_code == 201
    pid = resp.json()["id"]

    angle_a = _seed_angle(client, pid, data_root, label="A", role="cam_left", filename="a.mp4")
    angle_b = _seed_angle(client, pid, data_root, label="B", role="cam_right", filename="b.mp4")

    with patch("autoedit.proxy.run_ffmpeg_watchdog", side_effect=_mock_ffmpeg()):
        response = client.post(f"/projects/{pid}/proxy-low")

    assert response.status_code == 200
    result = response.json()
    assert len(result["proxies"]) == 2

    proxy_paths = {p["angle_id"]: p["proxy_low_path"] for p in result["proxies"]}
    with Session(engine) as session:
        for angle in [angle_a, angle_b]:
            row = session.execute(
                select(angles).where(angles.c.id == angle["id"])
            ).one()._mapping
            assert row.proxy_low_path == proxy_paths[angle["id"]]
            assert "proxy_low/" in row.proxy_low_path


def test_proxy_low_uses_lower_height_and_previous_normal_crf(project_with_angle):
    project_body, angle, client, data_root, engine = project_with_angle
    pid = project_body["id"]
    aid = angle["id"]

    captured_calls = []

    def _capture(cmd, **kwargs):
        captured_calls.append(cmd)
        from unittest.mock import MagicMock
        result = MagicMock()
        result.returncode = 0
        result.stdout = ""
        result.stderr = ""
        return result

    with patch("autoedit.proxy.run_ffmpeg_watchdog", side_effect=_capture):
        client.post(f"/projects/{pid}/angles/{aid}/proxy-low")

    assert len(captured_calls) == 1
    cmd_str = " ".join(str(c) for c in captured_calls[0])
    assert "scale=-2:360" in cmd_str, f"Expected 360p scale, got: {cmd_str}"
    assert "-crf" in cmd_str and "20" in cmd_str, f"Expected CRF 20, got: {cmd_str}"


def test_proxy_low_idempotent(project_with_angle):
    project_body, angle, client, data_root, engine = project_with_angle
    pid = project_body["id"]
    aid = angle["id"]

    with patch("autoedit.proxy.run_ffmpeg_watchdog", side_effect=_mock_ffmpeg()):
        r1 = client.post(f"/projects/{pid}/angles/{aid}/proxy-low")
        r2 = client.post(f"/projects/{pid}/angles/{aid}/proxy-low")

    assert r1.status_code == 200 and r2.status_code == 200
    assert r1.json()["proxy_low_path"] == r2.json()["proxy_low_path"]
