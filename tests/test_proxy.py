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
from autoedit.config import Settings
from autoedit.db.migrate import run_migrations
from autoedit.db.schema import angles
from autoedit.proxy import generate_proxy


# ── Fixtures ─────────────────────────────────────────────────────────


@pytest.fixture
def auth_client(tmp_path: Path, monkeypatch):
    # These tests assert software-encoder (libx264) ffmpeg flags. The app
    # default is h264_vaapi, which emits scale_vaapi/-vaapi_device instead,
    # so pin the software encoder to keep the assertions environment-independent
    # (they previously broke on any host with a /dev/dri node).
    monkeypatch.setenv("PROXY_ENCODER", "libx264")
    monkeypatch.setenv("PROXY_CRF", "16")
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
        operator_password="correct-password",
        session_secret="test-session-secret",
        public_domain="autoedit.example.com",
        session_cookie_secure=False,
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
            "filename": filename,
            "label": label,
            "role": role,
            "total_bytes": len(content),
            "total_chunks": 1,
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
    """Project with one uploaded angle. Returns (project_body, angle_body, client, data_root, engine)."""
    client, data_root, engine = auth_client
    resp = client.post(
        "/projects",
        json={"name": "Proxy test", "fps_num": 24000, "fps_den": 1001},
    )
    assert resp.status_code == 201
    project_body = resp.json()
    pid = project_body["id"]

    angle = _seed_angle(
        client, pid, data_root,
        label="Presenter", role="cam_left", filename="angleA.mp4",
    )
    return project_body, angle, client, data_root, engine


@pytest.fixture
def project_with_angles(auth_client):
    """Project with two uploaded angles."""
    client, data_root, engine = auth_client
    resp = client.post(
        "/projects",
        json={"name": "Multi-proxy test", "fps_num": 24000, "fps_den": 1001},
    )
    assert resp.status_code == 201
    project_body = resp.json()
    pid = project_body["id"]

    angle_a = _seed_angle(
        client, pid, data_root,
        label="Presenter", role="cam_left", filename="angleA.mp4",
    )
    angle_b = _seed_angle(
        client, pid, data_root,
        label="Interviewee", role="cam_right", filename="angleB.mp4",
    )
    return project_body, [angle_a, angle_b], client, data_root, engine


def _mock_ffmpeg(ffprobe=False):
    """Return a MagicMock for subprocess.run that simulates ffmpeg success."""
    from unittest.mock import MagicMock

    def _run(cmd, **kwargs):
        result = MagicMock()
        result.returncode = 0
        result.stdout = ""
        result.stderr = ""
        return result

    return _run


# ── Auth / 404 tests ────────────────────────────────────────────────


def test_proxy_route_requires_auth(tmp_path: Path):
    engine = create_engine(
        "sqlite:///:memory:",
        connect_args={"check_same_thread": False},
        poolclass=StaticPool,
    )
    run_migrations(engine)
    app = create_app(
        engine=engine, data_root=tmp_path, auth_enabled=True,
        operator_password="correct-password", session_secret="test-session-secret",
        session_cookie_secure=False,
    )
    client = TestClient(app)

    response = client.post(
        "/projects/01J00000000000000000000000/proxy",
    )
    assert response.status_code == 401


def test_proxy_rejects_missing_project(auth_client):
    client, _, _ = auth_client
    response = client.post("/projects/01J00000000000000000000000/proxy")
    assert response.status_code == 404


def test_proxy_rejects_missing_angle(auth_client):
    client, _, _ = auth_client
    resp = client.post(
        "/projects",
        json={"name": "Test", "fps_num": 24000, "fps_den": 1001},
    )
    pid = resp.json()["id"]

    response = client.post(f"/projects/{pid}/angles/01J00000000000000000000000/proxy")
    assert response.status_code == 404


# ── Proxy generation tests ──────────────────────────────────────────


def test_single_angle_proxy_updates_db(project_with_angle):
    """POST /projects/{pid}/angles/{aid}/proxy generates proxy and updates angles row."""
    project_body, angle, client, data_root, engine = project_with_angle
    pid = project_body["id"]
    aid = angle["id"]

    with patch("autoedit.proxy.run_ffmpeg_watchdog", side_effect=_mock_ffmpeg()):
        response = client.post(f"/projects/{pid}/angles/{aid}/proxy")

    assert response.status_code == 200
    result = response.json()
    assert result["angle_id"] == aid
    assert result["proxy_path"] is not None
    assert "proxy/" in result["proxy_path"]

    with Session(engine) as session:
        row = session.execute(select(angles).where(angles.c.id == aid)).one()._mapping
    assert row.proxy_path == result["proxy_path"]


def test_bulk_proxy_generates_for_all_angles(project_with_angles):
    """POST /projects/{pid}/proxy generates proxies for all angles."""
    project_body, angle_list, client, data_root, engine = project_with_angles
    pid = project_body["id"]

    with patch("autoedit.proxy.run_ffmpeg_watchdog", side_effect=_mock_ffmpeg()):
        response = client.post(f"/projects/{pid}/proxy")

    assert response.status_code == 200
    result = response.json()
    assert len(result["proxies"]) == 2

    proxy_paths = {p["angle_id"]: p["proxy_path"] for p in result["proxies"]}
    with Session(engine) as session:
        for angle in angle_list:
            row = session.execute(
                select(angles).where(angles.c.id == angle["id"])
            ).one()._mapping
            assert row.proxy_path == proxy_paths[angle["id"]]
            assert "proxy/" in row.proxy_path


def test_proxy_uses_correct_ffmpeg_args(project_with_angle):
    """Verify the ffmpeg command uses the expected parameters."""
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
        client.post(f"/projects/{pid}/angles/{aid}/proxy")

    assert len(captured_calls) == 1
    cmd = captured_calls[0]
    cmd_str = " ".join(str(c) for c in cmd)

    assert "-c:v" in cmd or "--" in cmd_str  # encoder flag
    assert "-g" in cmd  # GOP flag
    assert "-an" in cmd  # no audio
    assert "-movflags" in cmd or "+faststart" in cmd_str  # faststart
    assert "-vf" in cmd and "scale" in " ".join(cmd)  # scale filter
    assert "-crf" in cmd and cmd[cmd.index("-crf") + 1] == "16"


def test_proxy_quality_defaults_promote_previous_normal_quality_to_low():
    settings = Settings(_env_file=None)

    assert settings.proxy_crf == 16
    assert settings.proxy_low_crf == 20

    repo_root = Path(__file__).parents[1]
    compose = (repo_root / "docker-compose.yml").read_text()
    env_example = (repo_root / ".env.example").read_text()
    assert "PROXY_CRF: ${PROXY_CRF:-16}" in compose
    assert "PROXY_LOW_CRF: ${PROXY_LOW_CRF:-20}" in compose
    assert "PROXY_CRF=16" in env_example
    assert "PROXY_LOW_CRF=20" in env_example


def test_generate_proxy_uses_vaapi_hw_decode_and_encode_args():
    """h264_vaapi should request VAAPI device, hardware decode, scale, and encode."""
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
        generate_proxy(
            "/tmp/source.mp4",
            "/tmp/proxy.mp4",
            encoder="h264_vaapi",
            gop=12,
            height=720,
            crf=23,
        )

    assert len(captured_calls) == 1
    cmd = captured_calls[0]

    assert cmd[:2] == ["ffmpeg", "-y"]
    assert "-vaapi_device" in cmd
    assert "/dev/dri/renderD128" in cmd
    assert "-hwaccel" in cmd and "vaapi" in cmd
    assert "-hwaccel_output_format" in cmd and "vaapi" in cmd
    assert cmd[cmd.index("-c:v") + 1] == "h264_vaapi"
    assert "scale_vaapi=w=-2:h=720" in " ".join(cmd)
    assert "-qp" in cmd and "23" in cmd
    assert "-an" in cmd


def test_proxy_idempotent(project_with_angle):
    """Generating proxy twice produces the same proxy_path."""
    project_body, angle, client, data_root, engine = project_with_angle
    pid = project_body["id"]
    aid = angle["id"]

    with patch("autoedit.proxy.run_ffmpeg_watchdog", side_effect=_mock_ffmpeg()):
        r1 = client.post(f"/projects/{pid}/angles/{aid}/proxy")
        r2 = client.post(f"/projects/{pid}/angles/{aid}/proxy")

    assert r1.status_code == 200
    assert r2.status_code == 200
    assert r1.json()["proxy_path"] == r2.json()["proxy_path"]


def test_proxy_route_for_single_angle_requires_auth(tmp_path: Path):
    engine = create_engine(
        "sqlite:///:memory:",
        connect_args={"check_same_thread": False},
        poolclass=StaticPool,
    )
    run_migrations(engine)
    app = create_app(
        engine=engine, data_root=tmp_path, auth_enabled=True,
        operator_password="correct-password", session_secret="test-session-secret",
        session_cookie_secure=False,
    )
    client = TestClient(app)

    response = client.post(
        "/projects/01J00000000000000000000000/angles/01J00000000000000000000000/proxy",
    )
    assert response.status_code == 401
