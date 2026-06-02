import json
from pathlib import Path

import pytest
from fastapi.testclient import TestClient
from sqlalchemy import create_engine
from sqlalchemy.pool import StaticPool

from autoedit.api import create_app
from autoedit.db.migrate import run_migrations


@pytest.fixture
def client(tmp_path: Path):
    engine = create_engine(
        "sqlite:///:memory:",
        connect_args={"check_same_thread": False},
        poolclass=StaticPool,
    )
    run_migrations(engine)
    app = create_app(engine=engine, data_root=tmp_path)
    return TestClient(app), tmp_path


def test_health_endpoint(client):
    test_client, _ = client
    response = test_client.get("/health")
    assert response.status_code == 200
    assert response.json() == {"status": "ok"}


def test_create_project_creates_db_row_tree_and_project_json(client):
    test_client, data_root = client

    response = test_client.post(
        "/projects",
        json={"name": "Clapton interview", "fps_num": 24000, "fps_den": 1001},
    )

    assert response.status_code == 201
    body = response.json()
    assert len(body["id"]) == 26
    assert body["name"] == "Clapton interview"
    assert body["status"] == "created"
    assert body["fps_num"] == 24000
    assert body["fps_den"] == 1001
    assert body["timeline_origin_ms"] == 0
    assert body["config_json"] == {}

    project_dir = data_root / body["id"]
    assert project_dir.is_dir()
    for subdir in ["source", "proxy", "proxy_low", "audio", "transcript", "edit", "luts"]:
        assert (project_dir / subdir).is_dir(), subdir

    manifest = json.loads((project_dir / "project.json").read_text())
    assert manifest == body

    get_response = test_client.get(f"/projects/{body['id']}")
    assert get_response.status_code == 200
    assert get_response.json() == body


@pytest.mark.parametrize(
    "payload",
    [
        {"name": "Bad", "fps_num": 0, "fps_den": 1001},
        {"name": "Bad", "fps_num": 24000, "fps_den": 0},
        {"name": "Bad", "fps_num": "24000", "fps_den": 1001},
        {"name": "Bad", "fps_num": 24000, "fps_den": "1001"},
        {"name": "Bad", "fps_num": 24000},
        {"name": "", "fps_num": 24000, "fps_den": 1001},
    ],
)
def test_create_project_rejects_invalid_input(client, payload):
    test_client, _ = client
    response = test_client.post("/projects", json=payload)
    assert response.status_code == 400


def test_get_project_returns_404_for_missing_project(client):
    test_client, _ = client
    response = test_client.get("/projects/01J00000000000000000000000")
    assert response.status_code == 404
