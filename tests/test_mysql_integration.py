from pathlib import Path
import os

import pytest
from fastapi.testclient import TestClient
from sqlalchemy import create_engine, inspect
from sqlalchemy.pool import NullPool

from autoedit.api import create_app
from autoedit.db.migrate import run_migrations


MYSQL_TEST_URL = os.getenv("AUTOEDIT_MYSQL_TEST_URL")


@pytest.mark.skipif(not MYSQL_TEST_URL, reason="AUTOEDIT_MYSQL_TEST_URL is not set")
def test_stage_3_1_flow_against_mysql(tmp_path: Path):
    engine = create_engine(MYSQL_TEST_URL, poolclass=NullPool)

    run_migrations(engine)
    run_migrations(engine)

    inspector = inspect(engine)
    assert "projects" in inspector.get_table_names()
    assert "jobs" in inspector.get_table_names()

    app = create_app(engine=engine, data_root=tmp_path)
    with TestClient(app) as client:
        response = client.post(
            "/projects",
            json={"name": "MySQL gate", "fps_num": 24000, "fps_den": 1001},
        )
        assert response.status_code == 201
        project = response.json()

        project_dir = tmp_path / project["id"]
        assert (project_dir / "project.json").is_file()
        assert (project_dir / "source").is_dir()
        assert (project_dir / "proxy_low").is_dir()

        get_response = client.get(f"/projects/{project['id']}")
        assert get_response.status_code == 200
        assert get_response.json() == project

    engine.dispose()
