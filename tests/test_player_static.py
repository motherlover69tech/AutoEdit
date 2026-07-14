from __future__ import annotations

from pathlib import Path

import pytest
from fastapi.testclient import TestClient
from sqlalchemy import create_engine
from sqlalchemy.pool import StaticPool

from autoedit.api import create_app
from autoedit.db.migrate import run_migrations


@pytest.fixture
def auth_player_client(tmp_path: Path):
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
    return TestClient(app)


def _login(client: TestClient) -> None:
    response = client.post("/auth/login", json={"password": "pw", "display_name": "Peter"})
    assert response.status_code == 204


def _create_project(client: TestClient) -> str:
    response = client.post(
        "/projects",
        json={"name": "Player Shell", "fps_num": 24000, "fps_den": 1001},
    )
    assert response.status_code == 201
    return response.json()["id"]


def test_player_shell_requires_auth(auth_player_client):
    response = auth_player_client.get("/player/01J00000000000000000000000")

    assert response.status_code == 401
    assert response.json() == {"detail": "authentication required"}


def test_authenticated_player_shell_contains_media_elements_and_assets(auth_player_client):
    _login(auth_player_client)
    project_id = _create_project(auth_player_client)

    response = auth_player_client.get(f"/player/{project_id}")

    assert response.status_code == 200
    assert response.headers["content-type"].startswith("text/html")
    html = response.text
    assert 'id="programAudio"' in html
    assert 'id="videoA"' in html
    assert 'id="videoB"' in html
    assert 'id="angleButtons"' in html
    assert 'id="qualitySelect"' in html
    assert 'id="statusText"' in html
    assert 'id="shotReason"' in html
    assert 'id="shotReasonLabel"' in html
    assert 'id="shotReasonDetail"' in html
    assert "player.js" in html
    assert "styles.css" in html


def test_authenticated_static_player_assets_are_served(auth_player_client):
    _login(auth_player_client)

    js_response = auth_player_client.get("/web/player.js")
    css_response = auth_player_client.get("/web/styles.css")

    assert js_response.status_code == 200
    assert "findClipAtTime" in js_response.text
    assert css_response.status_code == 200
    assert ".player-shell" in css_response.text
