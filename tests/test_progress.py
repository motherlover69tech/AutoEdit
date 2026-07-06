"""Tests for pipeline progress tracking and project status transitions."""

from __future__ import annotations

from pathlib import Path
import json
import pytest
from sqlalchemy import create_engine
from sqlalchemy.pool import StaticPool

from autoedit.db.migrate import run_migrations
from autoedit.projects import create_project, get_project
from autoedit.progress import (
    PIPELINE_STAGES,
    compute_progress,
    set_project_status,
)


@pytest.fixture
def engine():
    """In-memory SQLite engine with fresh schema (static pool for shared access)."""
    eng = create_engine(
        "sqlite:///:memory:",
        connect_args={"check_same_thread": False},
        poolclass=StaticPool,
    )
    run_migrations(eng)
    return eng


@pytest.fixture
def tmp_data_root(tmp_path):
    """Temporary data root for project directories."""
    return tmp_path / "data"


@pytest.fixture
def project(engine, tmp_data_root):
    """A freshly created project."""
    return create_project(
        engine,
        tmp_data_root,
        name="Test Project",
        fps_num=25,
        fps_den=1,
    )


class TestProgressModule:
    def test_pipeline_stages_are_ordered(self):
        """PIPELINE_STAGES defines the canonical pipeline order."""
        keys = [s["key"] for s in PIPELINE_STAGES]
        # Verify key stages exist in the right positions
        assert keys.index("sync") < keys.index("loudness")
        assert keys.index("loudness") < keys.index("noise_floor")
        assert keys.index("activity") < keys.index("program_audio")
        assert keys.index("transcribe") < keys.index("segment_topics")
        assert keys.index("summary") < keys.index("cut")
        assert len(keys) == 12

    def test_set_project_status(self, engine, project):
        """set_project_status updates the DB atomically."""
        set_project_status(engine, project["id"], "processing")
        updated = get_project(engine, project["id"])
        assert updated["status"] == "processing"

        set_project_status(engine, project["id"], "ready")
        updated = get_project(engine, project["id"])
        assert updated["status"] == "ready"

        set_project_status(engine, project["id"], "error")
        updated = get_project(engine, project["id"])
        assert updated["status"] == "error"

    def test_compute_progress_fresh_project(self, engine, tmp_data_root, project):
        """A fresh project has all stages queued and status 'created'."""
        from autoedit.project_paths import create_project_tree

        create_project_tree(tmp_data_root, project["id"])

        progress = compute_progress(engine, tmp_data_root, project["id"])
        assert progress["project_id"] == project["id"]
        assert progress["status"] == "created"
        assert progress["ready"] is False
        assert len(progress["stages"]) == 12

        # First stage should be 'queued' (not 'running' since status is 'created')
        # All stages should be 'queued'
        for stage in progress["stages"]:
            assert stage["status"] == "queued", f"{stage['key']} should be queued"

    def test_compute_progress_processing(self, engine, tmp_data_root, project):
        """When status is 'processing', first undone stage shows as 'running'."""
        from autoedit.project_paths import create_project_tree

        create_project_tree(tmp_data_root, project["id"])
        set_project_status(engine, project["id"], "processing")

        progress = compute_progress(engine, tmp_data_root, project["id"])
        assert progress["status"] == "processing"
        assert progress["stages"][0]["status"] == "running"
        # All subsequent stages should be 'queued'
        for stage in progress["stages"][1:]:
            assert stage["status"] == "queued", f"{stage['key']} should be queued"

    def test_compute_progress_not_found(self, engine, tmp_data_root):
        """compute_progress raises LookupError for nonexistent project."""
        with pytest.raises(LookupError):
            compute_progress(engine, tmp_data_root, "NONEXISTENT_PROJECT_ID_XX")


class TestProgressAPI:
    """Test the /progress and /process endpoints through the FastAPI test client."""

    @pytest.fixture
    def client(self, engine, tmp_data_root, project):
        from autoedit.project_paths import create_project_tree
        from autoedit.api import create_app

        create_project_tree(tmp_data_root, project["id"])
        app = create_app(engine=engine, data_root=tmp_data_root, auth_enabled=False)
        from fastapi.testclient import TestClient

        return TestClient(app)

    def test_get_progress_fresh_project(self, client, project):
        """GET /projects/{id}/progress returns pipeline stages."""
        resp = client.get(f"/projects/{project['id']}/progress")
        assert resp.status_code == 200
        data = resp.json()
        assert data["project_id"] == project["id"]
        assert data["status"] == "created"
        assert data["ready"] is False
        assert len(data["stages"]) == 12
        # Verify stage structure
        for stage in data["stages"]:
            assert "key" in stage
            assert "label" in stage
            assert "status" in stage

    def test_get_progress_404(self, client):
        """Progress endpoint returns 404 for nonexistent project."""
        resp = client.get("/projects/NONEXISTENT_PROJECT_ID_XX/progress")
        assert resp.status_code == 404

    def test_process_requires_channels(self, client, project):
        """/process returns 400 when no channels are mapped."""
        resp = client.post(f"/projects/{project['id']}/process")
        assert resp.status_code == 400
        assert "audio channels" in str(resp.json()["detail"]).lower()

    def test_project_status_visible_in_list(self, client, project):
        """Project listing includes status field."""
        resp = client.get("/projects")
        assert resp.status_code == 200
        projects = resp.json()["projects"]
        our_project = next(p for p in projects if p["id"] == project["id"])
        assert "status" in our_project
        assert our_project["status"] == "created"

    def test_progress_after_status_change(self, engine, tmp_data_root, project, client):
        """Progress reflects DB status changes."""
        from autoedit.project_paths import create_project_tree

        create_project_tree(tmp_data_root, project["id"])
        set_project_status(engine, project["id"], "ready")

        resp = client.get(f"/projects/{project['id']}/progress")
        assert resp.status_code == 200
        data = resp.json()
        assert data["status"] == "ready"
        # When status is 'ready' and all stages show 'queued', ready should be False
        # (ready flag only true when all stages are actually 'done')
        assert data["ready"] is False  # No stages actually completed
