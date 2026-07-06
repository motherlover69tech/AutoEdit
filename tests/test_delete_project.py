"""Tests for DELETE /projects/{id} endpoint with safety switch."""

from __future__ import annotations

from pathlib import Path
import pytest
from fastapi.testclient import TestClient
from sqlalchemy import create_engine, text
from sqlalchemy.pool import StaticPool

from autoedit.api import create_app
from autoedit.db.migrate import run_migrations


@pytest.fixture
def auth_client(tmp_path: Path):
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
    resp = client.post("/auth/login", json={"password": "pw", "display_name": "T"})
    assert resp.status_code == 204
    return client, tmp_path, engine


def test_delete_requires_confirm(auth_client):
    """DELETE without ?confirm=DELETE returns 400."""
    client, _, _ = auth_client
    resp = client.post("/projects", json={"name": "Test", "fps_num": 25, "fps_den": 1})
    pid = resp.json()["id"]
    resp = client.delete(f"/projects/{pid}")
    assert resp.status_code == 400
    assert "confirm=DELETE" in resp.json()["detail"]


def test_delete_requires_exact_confirm(auth_client):
    """DELETE with wrong confirm value returns 400."""
    client, _, _ = auth_client
    resp = client.post("/projects", json={"name": "Test", "fps_num": 25, "fps_den": 1})
    pid = resp.json()["id"]
    resp = client.delete(f"/projects/{pid}?confirm=yes")
    assert resp.status_code == 400
    resp = client.delete(f"/projects/{pid}?confirm=delete")
    assert resp.status_code == 400


def test_delete_project_succeeds(auth_client):
    """DELETE with ?confirm=DELETE removes project."""
    client, data_root, engine = auth_client
    resp = client.post("/projects", json={"name": "To Delete", "fps_num": 25, "fps_den": 1})
    pid = resp.json()["id"]
    assert resp.status_code == 201

    # Create project directory
    (data_root / pid).mkdir(parents=True, exist_ok=True)

    resp = client.delete(f"/projects/{pid}?confirm=DELETE")
    assert resp.status_code == 200
    data = resp.json()
    assert data["deleted"] == pid
    assert data["name"] == "To Delete"

    # Project gone from DB
    resp = client.get(f"/projects/{pid}")
    assert resp.status_code == 404

    # Project directory removed from disk
    assert not (data_root / pid).exists()


def test_delete_removes_from_list(auth_client):
    """Deleted project no longer appears in project list."""
    client, _, _ = auth_client
    resp = client.post("/projects", json={"name": "Keep", "fps_num": 25, "fps_den": 1})
    keep_id = resp.json()["id"]
    resp = client.post("/projects", json={"name": "Remove", "fps_num": 24000, "fps_den": 1001})
    remove_id = resp.json()["id"]

    # Verify both exist
    resp = client.get("/projects")
    ids = [p["id"] for p in resp.json()["projects"]]
    assert keep_id in ids
    assert remove_id in ids

    # Delete one
    resp = client.delete(f"/projects/{remove_id}?confirm=DELETE")
    assert resp.status_code == 200

    # Verify only keep remains
    resp = client.get("/projects")
    ids = [p["id"] for p in resp.json()["projects"]]
    assert keep_id in ids
    assert remove_id not in ids


def test_delete_nonexistent_returns_404(auth_client):
    """DELETE non-existent project returns 404."""
    client, _, _ = auth_client
    resp = client.delete("/projects/01J00000000000000000000000?confirm=DELETE")
    assert resp.status_code == 404


def test_delete_requires_auth(tmp_path: Path):
    """DELETE without auth returns 401."""
    engine = create_engine(
        "sqlite:///:memory:",
        connect_args={"check_same_thread": False},
        poolclass=StaticPool,
    )
    run_migrations(engine)
    app = create_app(engine=engine, data_root=tmp_path, auth_enabled=True,
                     operator_password="pw", session_secret="s",
                     session_cookie_secure=False)
    client = TestClient(app)
    resp = client.delete("/projects/01J00000000000000000000000?confirm=DELETE")
    assert resp.status_code == 401
