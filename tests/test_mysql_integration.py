from pathlib import Path
import os

import pytest
from fastapi.testclient import TestClient
from sqlalchemy import URL, create_engine, inspect
from sqlalchemy.pool import NullPool

from autoedit.api import create_app
from autoedit.db.migrate import run_migrations


def _mysql_test_url() -> URL | str | None:
    if explicit_url := os.getenv("AUTOEDIT_MYSQL_TEST_URL"):
        return explicit_url

    required = ["DB_HOST", "DB_PORT", "DB_NAME", "DB_USER", "DB_PASSWORD"]
    if not all(os.getenv(name) for name in required):
        return None

    return URL.create(
        "mysql+pymysql",
        username=os.environ["DB_USER"],
        password=os.environ["DB_PASSWORD"],
        host=os.environ["DB_HOST"],
        port=int(os.environ["DB_PORT"]),
        database=os.environ["DB_NAME"],
    )


MYSQL_TEST_URL = _mysql_test_url()


@pytest.mark.skipif(
    not MYSQL_TEST_URL,
    reason="set AUTOEDIT_MYSQL_TEST_URL or DB_HOST/DB_PORT/DB_NAME/DB_USER/DB_PASSWORD",
)
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
