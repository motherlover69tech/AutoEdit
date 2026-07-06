from __future__ import annotations

from pathlib import Path

import pytest
from fastapi.testclient import TestClient
from sqlalchemy import create_engine, select
from sqlalchemy.orm import Session
from sqlalchemy.pool import StaticPool

from autoedit.api import create_app
from autoedit.db.migrate import run_migrations
from autoedit.db.schema import users


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
        session_cookie_secure=False,
    )
    client = TestClient(app)
    login = client.post(
        "/auth/login",
        json={"password": "correct-password", "display_name": "Peter"},
    )
    assert login.status_code == 204
    return client


def test_admin_can_create_user_and_user_can_login(auth_client):
    created = auth_client.post(
        "/users",
        json={
            "username": "reviewer-a",
            "password": "password123",
            "display_name": "Reviewer A",
            "role": "reviewer",
        },
    )
    assert created.status_code == 201
    body = created.json()
    assert body["username"] == "reviewer-a"
    assert body["display_name"] == "Reviewer A"
    assert body["role"] == "reviewer"
    assert "pw_hash" not in body

    auth_client.post("/auth/logout")
    login = auth_client.post(
        "/auth/login",
        json={
            "username": "reviewer-a",
            "password": "password123",
            "display_name": "ignored",
        },
    )
    assert login.status_code == 204
    session = auth_client.get("/auth/session")
    assert session.status_code == 200
    assert session.json() == {
        "display_name": "Reviewer A",
        "username": "reviewer-a",
        "role": "reviewer",
    }


def test_reviewer_cannot_create_users(auth_client):
    auth_client.post(
        "/users",
        json={
            "username": "reviewer-b",
            "password": "password123",
            "display_name": "Reviewer B",
            "role": "reviewer",
        },
    )
    auth_client.post("/auth/logout")
    auth_client.post(
        "/auth/login",
        json={
            "username": "reviewer-b",
            "password": "password123",
            "display_name": "ignored",
        },
    )

    response = auth_client.post(
        "/users",
        json={
            "username": "blocked",
            "password": "password123",
            "display_name": "Blocked",
            "role": "reviewer",
        },
    )

    assert response.status_code == 403
    assert response.json() == {"detail": "admin role required"}


def test_empty_users_table_gets_peter_admin_on_operator_login(tmp_path: Path):
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
        operator_username="peter",
        operator_display_name="Peter",
        session_secret="test-session-secret",
        session_cookie_secure=False,
    )
    client = TestClient(app)
    with Session(engine) as session:
        assert session.execute(select(users)).first() is None

    login = client.post(
        "/auth/login",
        json={
            "username": "peter",
            "password": "correct-password",
            "display_name": "Ignored",
        },
    )

    assert login.status_code == 204
    with Session(engine) as session:
        row = session.execute(select(users).where(users.c.username == "peter")).one()._mapping
    assert row.username == "peter"
    assert row.display_name == "Peter"
    assert row.role == "admin"


def test_operator_username_peter_uses_operator_password(auth_client):
    auth_client.post("/auth/logout")

    login = auth_client.post(
        "/auth/login",
        json={
            "username": "peter",
            "password": "correct-password",
            "display_name": "Ignored",
        },
    )

    assert login.status_code == 204
    session = auth_client.get("/auth/session")
    assert session.status_code == 200
    assert session.json() == {
        "display_name": "Peter",
        "username": "peter",
        "role": "admin",
    }


def test_wrong_username_does_not_use_operator_password(auth_client):
    auth_client.post("/auth/logout")

    response = auth_client.post(
        "/auth/login",
        json={
            "username": "not-peter",
            "password": "correct-password",
            "display_name": "Ignored",
        },
    )

    assert response.status_code == 401


def test_app_shell_routes_serve_style_guide_ui(auth_client):
    for path in ("/", "/ingest", "/users/manage"):
        response = auth_client.get(path, headers={"Accept": "text/html"})
        assert response.status_code == 200
        assert "Voices" in response.text
        assert "/web/app.js" in response.text
        assert "/web/styles.css" in response.text
