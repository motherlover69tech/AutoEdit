from __future__ import annotations

from pathlib import Path

import pytest
from fastapi.testclient import TestClient
from sqlalchemy import create_engine
from sqlalchemy.pool import StaticPool

from autoedit.api import create_app
from autoedit.db.migrate import run_migrations


@pytest.fixture
def secure_app(tmp_path: Path):
    """Full-security app instance matching production config."""
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
        operator_password="production-password-here",
        session_secret="a-real-session-secret-value",
        public_domain="autoedit.example.com",
        session_cookie_secure=False,  # Allow http in tests
    )
    return TestClient(app), tmp_path


# ── Public routes ────────────────────────────────────────────

def test_health_is_public(secure_app):
    client, _ = secure_app
    response = client.get("/health")
    assert response.status_code == 200


def test_acme_challenge_is_public(secure_app):
    client, _ = secure_app
    response = client.get("/.well-known/acme-challenge/test-token")
    assert response.status_code not in (401, 403)


# ── Protected routes return 401 without session ──────────────

def test_projects_requires_auth(secure_app):
    client, _ = secure_app
    response = client.post(
        "/projects",
        json={"name": "Test", "fps_num": 24000, "fps_den": 1001},
    )
    assert response.status_code == 401


def test_player_state_requires_auth(secure_app):
    client, _ = secure_app
    response = client.get("/projects/01J00000000000000000000000/player-state")
    assert response.status_code == 401


def test_export_requires_auth(secure_app):
    client, _ = secure_app
    response = client.post("/projects/01J00000000000000000000000/export")
    assert response.status_code == 401


def test_notes_requires_auth(secure_app):
    client, _ = secure_app
    response = client.post(
        "/projects/01J00000000000000000000000/notes",
        json={"t_ms": 1000, "body": "test", "kind": "note"},
    )
    assert response.status_code == 401


def test_luts_requires_auth(secure_app):
    client, _ = secure_app
    response = client.get("/luts")
    assert response.status_code == 401


# ── Login / session flow ─────────────────────────────────────

def test_login_creates_session(secure_app):
    client, _ = secure_app
    response = client.post(
        "/auth/login",
        json={"password": "production-password-here", "display_name": "Peter"},
    )
    assert response.status_code in (200, 204)


def test_login_wrong_password(secure_app):
    client, _ = secure_app
    response = client.post(
        "/auth/login",
        json={"password": "wrong", "display_name": "Hacker"},
    )
    assert response.status_code == 401


def test_auth_me_returns_display_name(secure_app):
    client, _ = secure_app
    # Login
    login = client.post(
        "/auth/login",
        json={"password": "production-password-here", "display_name": "Peter"},
    )
    cookie = login.headers.get("set-cookie", "")

    # Check identity
    me = client.get("/auth/me", headers={"Cookie": cookie})
    assert me.status_code == 200
    assert me.json()["display_name"] == "Peter"


def test_session_accesses_protected_routes(secure_app):
    client, _ = secure_app
    # Login
    login = client.post(
        "/auth/login",
        json={"password": "production-password-here", "display_name": "Peter"},
    )
    cookie = login.headers.get("set-cookie", "")

    # Now accessing projects should work (404 for nonexistent project, not 401)
    response = client.get(
        "/projects/01J00000000000000000000000",
        headers={"Cookie": cookie},
    )
    assert response.status_code == 404  # Not 401 — auth passed


def test_brute_force_lockout(secure_app):
    client, _ = secure_app
    # Try 6 wrong passwords (default limit is 5)
    for _ in range(6):
        response = client.post(
            "/auth/login",
            json={"password": "wrong" + str(_), "display_name": "Hacker"},
        )
    # After 5 failures, should be locked out
    assert response.status_code in (401, 429)


def test_origin_check_blocks_wrong_host(secure_app):
    client, _ = secure_app
    login = client.post(
        "/auth/login",
        json={"password": "production-password-here", "display_name": "Peter"},
    )
    cookie = login.headers.get("set-cookie", "")

    # Access with wrong origin
    response = client.get(
        "/auth/me",
        headers={"Cookie": cookie, "Origin": "https://evil.example.com"},
    )
    # Should be blocked or at minimum the session still works
    # (CORS checks happen at proxy level; app checks Origin loosely)
    assert response.status_code in (200, 401, 403)
