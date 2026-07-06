from __future__ import annotations

import hashlib
from pathlib import Path

import pytest
from fastapi.testclient import TestClient
from sqlalchemy import create_engine
from sqlalchemy.orm import Session
from sqlalchemy.pool import StaticPool

from autoedit.api import create_app
from autoedit.db.migrate import run_migrations
from autoedit.db.schema import angles, audio_channels
from autoedit.projects import new_ulid


@pytest.fixture
def client_with_media(tmp_path: Path):
    """Create an app with auth disabled and a project with a proxy file on disk."""
    engine = create_engine(
        "sqlite:///:memory:",
        connect_args={"check_same_thread": False},
        poolclass=StaticPool,
    )
    run_migrations(engine)
    app = create_app(engine=engine, data_root=tmp_path, auth_enabled=False)
    client = TestClient(app)

    # Create project
    r = client.post(
        "/projects",
        json={"name": "Media test", "fps_num": 24000, "fps_den": 1001},
    )
    assert r.status_code == 201
    pid = r.json()["id"]

    # Create proxy dir and a test file
    proxy_dir = tmp_path / pid / "proxy"
    proxy_dir.mkdir(parents=True, exist_ok=True)
    test_content = b"0123456789" * 100  # 1000 bytes
    (proxy_dir / "test.proxy.mp4").write_bytes(test_content)

    proxy_low_dir = tmp_path / pid / "proxy_low"
    proxy_low_dir.mkdir(parents=True, exist_ok=True)
    (proxy_low_dir / "test.proxy.mp4").write_bytes(test_content)

    audio_dir = tmp_path / pid / "audio"
    audio_dir.mkdir(parents=True, exist_ok=True)
    (audio_dir / "test.wav").write_bytes(b"audio" * 50)

    angle_id = new_ulid()
    channel_id = new_ulid()
    with Session(engine) as session:
        session.execute(angles.insert().values(
            id=angle_id,
            project_id=pid,
            label="Test",
            role="cam_left",
            source_path="source/test.mp4",
            proxy_path="proxy/test.proxy.mp4",
            proxy_low_path="proxy_low/test.proxy.mp4",
            sync_offset_ms=0,
        ))
        session.execute(audio_channels.insert().values(
            id=channel_id,
            project_id=pid,
            speaker_label="test",
            source_angle_id=angle_id,
            channel_index=0,
            wav_path="audio/test.wav",
        ))
        session.commit()

    return client, tmp_path, engine, pid


@pytest.fixture
def auth_client_with_media(tmp_path: Path):
    """Same as client_with_media but with auth enabled."""
    engine = create_engine(
        "sqlite:///:memory:",
        connect_args={"check_same_thread": False},
        poolclass=StaticPool,
    )
    run_migrations(engine)
    app = create_app(
        engine=engine, data_root=tmp_path, auth_enabled=True,
        operator_password="pw", session_secret="secret",
        session_cookie_secure=False,
    )
    client = TestClient(app)
    login = client.post("/auth/login", json={"password": "pw", "display_name": "P"})
    assert login.status_code == 204

    r = client.post(
        "/projects",
        json={"name": "Auth media test", "fps_num": 24000, "fps_den": 1001},
    )
    assert r.status_code == 201
    pid = r.json()["id"]

    proxy_dir = tmp_path / pid / "proxy"
    proxy_dir.mkdir(parents=True, exist_ok=True)
    (proxy_dir / "test.proxy.mp4").write_bytes(b"secret" * 20)

    with Session(engine) as session:
        session.execute(angles.insert().values(
            id=new_ulid(),
            project_id=pid,
            label="Test",
            role="cam_left",
            source_path="source/test.mp4",
            proxy_path="proxy/test.proxy.mp4",
            sync_offset_ms=0,
        ))
        session.commit()

    return client, tmp_path, engine, pid


# ── Auth tests ──────────────────────────────────────────────────────


def test_media_route_requires_auth(tmp_path: Path):
    engine = create_engine(
        "sqlite:///:memory:",
        connect_args={"check_same_thread": False},
        poolclass=StaticPool,
    )
    run_migrations(engine)
    app = create_app(
        engine=engine, data_root=tmp_path, auth_enabled=True,
        operator_password="pw", session_secret="secret",
        session_cookie_secure=False,
    )
    client = TestClient(app)

    response = client.get(
        "/projects/01J00000000000000000000000/media/proxy/test.mp4",
    )
    assert response.status_code == 401


# ── Streaming tests ─────────────────────────────────────────────────


def test_media_stream_returns_full_file(client_with_media):
    client, _, _, pid = client_with_media
    response = client.get(f"/projects/{pid}/media/proxy/test.proxy.mp4")
    assert response.status_code == 200
    assert response.content == b"0123456789" * 100


def test_media_stream_handles_range_request(client_with_media):
    client, _, _, pid = client_with_media
    response = client.get(
        f"/projects/{pid}/media/proxy/test.proxy.mp4",
        headers={"Range": "bytes=0-99"},
    )
    assert response.status_code == 206
    assert response.content == b"0123456789" * 10  # first 100 bytes
    assert "Content-Range" in response.headers
    assert response.headers["Content-Range"].startswith("bytes 0-99/1000")


def test_media_stream_handles_open_ended_range(client_with_media):
    client, _, _, pid = client_with_media
    response = client.get(
        f"/projects/{pid}/media/proxy/test.proxy.mp4",
        headers={"Range": "bytes=900-"},
    )
    assert response.status_code == 206
    assert response.content == b"0123456789" * 10  # last 100 bytes
    assert response.headers["Content-Range"] == "bytes 900-999/1000"


def test_media_stream_handles_suffix_range(client_with_media):
    client, _, _, pid = client_with_media
    response = client.get(
        f"/projects/{pid}/media/proxy/test.proxy.mp4",
        headers={"Range": "bytes=-100"},
    )
    assert response.status_code == 206
    assert response.content == b"0123456789" * 10  # last 100 bytes
    assert response.headers["Content-Range"] == "bytes 900-999/1000"


def test_media_stream_serves_audio(client_with_media):
    client, _, _, pid = client_with_media
    response = client.get(f"/projects/{pid}/media/audio/test.wav")
    assert response.status_code == 200
    assert response.content == b"audio" * 50


def test_media_stream_serves_proxy_low(client_with_media):
    client, _, _, pid = client_with_media
    response = client.get(f"/projects/{pid}/media/proxy_low/test.proxy.mp4")
    assert response.status_code == 200
    assert response.content == b"0123456789" * 100


def test_media_stream_rejects_missing_file(client_with_media):
    client, _, _, pid = client_with_media
    response = client.get(f"/projects/{pid}/media/proxy/nonexistent.mp4")
    assert response.status_code == 404


def test_media_stream_rejects_missing_project(client_with_media):
    client, _, _, _ = client_with_media
    response = client.get(
        "/projects/01J00000000000000000000000/media/proxy/test.mp4",
    )
    assert response.status_code == 404


def test_media_stream_rejects_invalid_kind(client_with_media):
    client, _, _, pid = client_with_media
    response = client.get(f"/projects/{pid}/media/source/test.mp4")
    assert response.status_code == 400


def test_media_stream_rejects_path_traversal(client_with_media):
    client, _, _, pid = client_with_media
    response = client.get(
        f"/projects/{pid}/media/proxy/../../../etc/passwd",
    )
    assert response.status_code in {400, 404}


def test_media_stream_rejects_source_access(client_with_media):
    """Source directory should NOT be accessible via the media endpoint."""
    client, tmp_path, _, pid = client_with_media
    source_dir = tmp_path / pid / "source"
    source_dir.mkdir(parents=True, exist_ok=True)
    (source_dir / "test.mp4").write_bytes(b"source content")

    # Try to access via media endpoint (should fail because 'source' is not a valid kind)
    response = client.get(f"/projects/{pid}/media/source/test.mp4")
    assert response.status_code == 400


def test_media_stream_with_auth(auth_client_with_media):
    client, _, _, pid = auth_client_with_media
    response = client.get(f"/projects/{pid}/media/proxy/test.proxy.mp4")
    assert response.status_code == 200
    assert response.content == b"secret" * 20
