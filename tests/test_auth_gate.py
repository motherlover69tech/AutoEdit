from pathlib import Path

import pytest
from fastapi.testclient import TestClient
from sqlalchemy import create_engine
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
        operator_password="correct-password",
        session_secret="test-session-secret",
        public_domain="autoedit.example.com",
        login_max_failures=3,
        login_lockout_seconds=300,
        session_cookie_secure=False,
    )
    return TestClient(app), tmp_path


def login(client: TestClient, display_name: str = "Peter"):
    return client.post(
        "/auth/login",
        json={"password": "correct-password", "display_name": display_name},
    )


def test_health_is_public_when_auth_enabled(auth_client):
    client, _ = auth_client

    response = client.get("/health")

    assert response.status_code == 200
    assert response.json() == {"status": "ok"}


def test_acme_challenge_path_bypasses_auth(auth_client):
    client, _ = auth_client

    response = client.get("/.well-known/acme-challenge/test-token")

    assert response.status_code != 401


def test_project_routes_require_session(auth_client):
    client, _ = auth_client

    response = client.post(
        "/projects",
        json={"name": "Private", "fps_num": 24000, "fps_den": 1001},
    )

    assert response.status_code == 401
    assert response.json() == {"detail": "authentication required"}


def test_login_sets_httponly_cookie_and_authenticated_project_create_works(auth_client):
    client, data_root = auth_client

    login_response = login(client, display_name="Peter Reviewer")

    assert login_response.status_code == 204
    set_cookie = login_response.headers["set-cookie"]
    assert "autoedit_session=" in set_cookie
    assert "HttpOnly" in set_cookie
    assert "samesite=lax" in set_cookie.lower()

    response = client.post(
        "/projects",
        json={"name": "Authenticated", "fps_num": 24000, "fps_den": 1001},
    )

    assert response.status_code == 201
    body = response.json()
    assert (data_root / body["id"] / "project.json").is_file()


def test_auth_me_returns_display_name_from_session(auth_client):
    client, _ = auth_client
    login_response = login(client, display_name="Remote Reviewer")
    assert login_response.status_code == 204

    response = client.get("/auth/me")

    assert response.status_code == 200
    assert response.json() == {"display_name": "Remote Reviewer"}


def test_failed_logins_trigger_lockout(auth_client):
    client, _ = auth_client

    for _ in range(3):
        response = client.post(
            "/auth/login",
            json={"password": "wrong", "display_name": "Peter"},
        )
        assert response.status_code == 401

    locked = client.post(
        "/auth/login",
        json={"password": "correct-password", "display_name": "Peter"},
    )

    assert locked.status_code == 429
    assert locked.json() == {"detail": "too many failed login attempts"}


def test_origin_locked_to_public_domain(auth_client):
    client, _ = auth_client

    bad_origin = client.get("/health", headers={"Origin": "https://evil.example"})
    assert bad_origin.status_code == 403
    assert bad_origin.json() == {"detail": "origin not allowed"}

    good_origin = client.get("/health", headers={"Origin": "https://autoedit.example.com"})
    assert good_origin.status_code == 200
