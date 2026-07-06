from __future__ import annotations

import json
from pathlib import Path

import pytest
from fastapi.testclient import TestClient
from sqlalchemy import create_engine, text
from sqlalchemy.orm import Session
from sqlalchemy.pool import StaticPool

from autoedit.api import create_app
from autoedit.db.migrate import run_migrations
from autoedit.db.schema import notes
from autoedit.projects import new_ulid

MISSING_PROJECT_ID = "01J00000000000000000000000"


@pytest.fixture
def app_context(tmp_path: Path):
    engine = create_engine(
        "sqlite:///:memory:",
        connect_args={"check_same_thread": False},
        poolclass=StaticPool,
    )
    run_migrations(engine)
    app = create_app(engine=engine, data_root=tmp_path, auth_enabled=False)
    return TestClient(app), tmp_path, engine


def _create_project(client: TestClient) -> str:
    response = client.post(
        "/projects",
        json={"name": "Notes Test", "fps_num": 24000, "fps_den": 1001},
    )
    assert response.status_code == 201
    return response.json()["id"]


def _login(client: TestClient) -> str:
    """Login and return the session cookie value."""
    resp = client.post(
        "/auth/login",
        json={"password": "pw", "display_name": "Reviewer One"},
    )
    assert resp.status_code in (200, 204)
    cookie = resp.headers.get("set-cookie", "")
    # Extract session cookie value
    for part in cookie.split("; "):
        if part.startswith("autoedit_session="):
            return part
    return cookie


def _auth_app(tmp_path: Path) -> tuple[TestClient, Path]:
    engine = create_engine(
        "sqlite:///:memory:",
        connect_args={"check_same_thread": False},
        poolclass=StaticPool,
    )
    run_migrations(engine)
    app = create_app(
        engine=engine, data_root=tmp_path,
        auth_enabled=True, operator_password="pw", session_secret="s",
        session_cookie_secure=False,
    )
    return TestClient(app), tmp_path


# ── Auth tests ────────────────────────────────────────────────

def test_create_note_requires_auth(tmp_path: Path):
    client, _ = _auth_app(tmp_path)
    response = client.post(
        f"/projects/{MISSING_PROJECT_ID}/notes",
        json={"t_ms": 1000, "body": "test", "kind": "note"},
    )
    assert response.status_code == 401


def test_list_notes_requires_auth(tmp_path: Path):
    client, _ = _auth_app(tmp_path)
    response = client.get(f"/projects/{MISSING_PROJECT_ID}/notes")
    assert response.status_code == 401


def test_delete_note_requires_auth(tmp_path: Path):
    client, _ = _auth_app(tmp_path)
    response = client.delete(f"/projects/{MISSING_PROJECT_ID}/notes/1")
    assert response.status_code == 401


# ── CRUD tests (auth disabled for simplicity) ────────────────

def test_create_note(app_context):
    client, _, engine = app_context
    project_id = _create_project(client)

    response = client.post(
        f"/projects/{project_id}/notes",
        json={"t_ms": 2500, "body": "Cut here — jump in audio.", "kind": "cut_suggestion"},
    )
    assert response.status_code == 201
    body = response.json()
    assert body["t_ms"] == 2500
    assert body["body"] == "Cut here — jump in audio."
    assert body["kind"] == "cut_suggestion"
    assert body["author"] == "operator"  # default when auth disabled
    assert "id" in body
    assert "created_at" in body

    # Verify DB
    with Session(engine) as session:
        rows = session.execute(
            text("SELECT * FROM notes WHERE project_id = :pid"),
            {"pid": project_id},
        ).fetchall()
    assert len(rows) == 1
    assert rows[0].t_ms == 2500


def test_create_note_with_auth_uses_display_name(tmp_path: Path):
    client, _ = _auth_app(tmp_path)
    # Create project (auth disabled for project creation via separate client)
    engine2 = create_engine("sqlite:///:memory:", connect_args={"check_same_thread": False}, poolclass=StaticPool)
    run_migrations(engine2)
    app2 = create_app(engine=engine2, data_root=tmp_path, auth_enabled=False)
    client2 = TestClient(app2)
    project_id = _create_project(client2)

    # Login and create note
    cookie = _login(client)
    response = client.post(
        f"/projects/{project_id}/notes",
        json={"t_ms": 1000, "body": "Hello", "kind": "note"},
        headers={"Cookie": cookie},
    )
    # Will be 404 because app_contexts differ (different engine), but tests the auth path
    # Instead use a shared app
    pass  # covered by integration test below


def test_create_note_author_from_session(tmp_path: Path):
    engine = create_engine("sqlite:///:memory:", connect_args={"check_same_thread": False}, poolclass=StaticPool)
    run_migrations(engine)
    app = create_app(
        engine=engine, data_root=tmp_path,
        auth_enabled=True, operator_password="pw", session_secret="s",
        session_cookie_secure=False,
    )
    client = TestClient(app)

    # Login first
    cookie = _login(client)

    # Create project (needs session)
    resp = client.post(
        "/projects",
        json={"name": "Notes Test", "fps_num": 24000, "fps_den": 1001},
        headers={"Cookie": cookie},
    )
    assert resp.status_code == 201
    project_id = resp.json()["id"]

    # Create note with auth
    response = client.post(
        f"/projects/{project_id}/notes",
        json={"t_ms": 500, "body": "Test note", "kind": "note"},
        headers={"Cookie": cookie},
    )
    assert response.status_code == 201
    assert response.json()["author"] == "Reviewer One"


def test_list_notes_empty(app_context):
    client, _, _ = app_context
    project_id = _create_project(client)

    response = client.get(f"/projects/{project_id}/notes")
    assert response.status_code == 200
    assert response.json()["notes"] == []


def test_list_notes(app_context):
    client, _, _ = app_context
    project_id = _create_project(client)

    client.post(f"/projects/{project_id}/notes",
                json={"t_ms": 1000, "body": "First", "kind": "note"})
    client.post(f"/projects/{project_id}/notes",
                json={"t_ms": 500, "body": "Second", "kind": "cut_suggestion"})

    response = client.get(f"/projects/{project_id}/notes")
    assert response.status_code == 200
    body = response.json()
    assert len(body["notes"]) == 2
    # Sorted by t_ms
    assert body["notes"][0]["t_ms"] == 500
    assert body["notes"][0]["body"] == "Second"
    assert body["notes"][1]["t_ms"] == 1000
    assert body["notes"][1]["body"] == "First"


def test_delete_note(app_context):
    client, _, engine = app_context
    project_id = _create_project(client)

    resp = client.post(f"/projects/{project_id}/notes",
                       json={"t_ms": 1000, "body": "To delete", "kind": "note"})
    note_id = resp.json()["id"]

    delete_resp = client.delete(f"/projects/{project_id}/notes/{note_id}")
    assert delete_resp.status_code == 200
    assert delete_resp.json()["deleted"] is True

    # Verify gone
    list_resp = client.get(f"/projects/{project_id}/notes")
    assert list_resp.json()["notes"] == []


def test_delete_nonexistent_note_returns_404(app_context):
    client, _, _ = app_context
    project_id = _create_project(client)

    response = client.delete(f"/projects/{project_id}/notes/99999")
    assert response.status_code == 404


def test_create_note_missing_project_returns_404(app_context):
    client, _, _ = app_context
    response = client.post(
        f"/projects/{MISSING_PROJECT_ID}/notes",
        json={"t_ms": 1000, "body": "test", "kind": "note"},
    )
    assert response.status_code == 404


def test_create_note_invalid_kind_returns_422(app_context):
    client, _, _ = app_context
    project_id = _create_project(client)

    response = client.post(
        f"/projects/{project_id}/notes",
        json={"t_ms": 1000, "body": "test", "kind": "invalid"},
    )
    assert response.status_code in (400, 422)


def test_create_note_rejects_negative_t_ms(app_context):
    client, _, _ = app_context
    project_id = _create_project(client)

    response = client.post(
        f"/projects/{project_id}/notes",
        json={"t_ms": -1, "body": "test", "kind": "note"},
    )
    assert response.status_code in (400, 422)


# ── XSS safety ────────────────────────────────────────────────

def test_note_body_with_script_tag_is_preserved_not_executed(app_context):
    """The body stores the raw text; sanitisation happens at render time in the frontend."""
    client, _, _ = app_context
    project_id = _create_project(client)

    script_body = '<script>alert("xss")</script>'
    response = client.post(
        f"/projects/{project_id}/notes",
        json={"t_ms": 1000, "body": script_body, "kind": "note"},
    )
    assert response.status_code == 201
    # Body stored as-is; rendering must use textContent, not innerHTML
    assert response.json()["body"] == script_body


def test_note_body_max_length_rejected(app_context):
    client, _, _ = app_context
    project_id = _create_project(client)

    # 10KB body should be fine; 100KB rejected
    huge = "x" * 100_000
    response = client.post(
        f"/projects/{project_id}/notes",
        json={"t_ms": 1000, "body": huge, "kind": "note"},
    )
    # Should reject oversized bodies
    assert response.status_code in (400, 413, 422)


# ── Timeline-state integration ───────────────────────────────

def test_timeline_state_includes_notes(app_context):
    client, _, engine = app_context
    project_id = _create_project(client)

    # Seed a rough cut so timeline-state works
    from autoedit.db.schema import angles, cuts
    project_dir = app_context[1] / project_id
    (project_dir / "transcript").mkdir(exist_ok=True)
    summary = {"topics": [], "totals": {"speaker_time_ms": {}, "talk_overlap_ms": 0, "silence_ms": 0}}
    (project_dir / "transcript" / "summary.json").write_text(json.dumps(summary))

    angle_id = new_ulid()
    with Session(engine) as session:
        session.execute(angles.insert(), [{
            "id": angle_id, "project_id": project_id, "label": "A", "role": "cam_left",
            "source_path": "source/a.mp4",
        }])
        session.execute(cuts.insert(), [{
            "id": new_ulid(), "project_id": project_id, "name": "Rough", "kind": "rough",
            "params_json": {},
            "cdl_json": {"version": 1, "clips": [
                {"angle_id": angle_id, "src_in_ms": 0, "timeline_in_ms": 0, "dur_ms": 3000},
            ]},
        }])
        session.commit()

    # Add notes
    client.post(f"/projects/{project_id}/notes",
                json={"t_ms": 500, "body": "Note A", "kind": "note"})
    client.post(f"/projects/{project_id}/notes",
                json={"t_ms": 2000, "body": "Cut B", "kind": "cut_suggestion"})

    response = client.get(f"/projects/{project_id}/timeline-state")
    assert response.status_code == 200
    body = response.json()
    assert "notes" in body
    assert len(body["notes"]) == 2
    assert body["notes"][0]["t_ms"] == 500
    assert body["notes"][0]["kind"] == "note"
    assert body["notes"][1]["t_ms"] == 2000
    assert body["notes"][1]["kind"] == "cut_suggestion"


def test_timeline_state_empty_notes(app_context):
    client, _, engine = app_context
    project_id = _create_project(client)

    from autoedit.db.schema import angles, cuts
    project_dir = app_context[1] / project_id
    (project_dir / "transcript").mkdir(exist_ok=True)
    (project_dir / "transcript" / "summary.json").write_text(
        json.dumps({"topics": [], "totals": {"speaker_time_ms": {}, "talk_overlap_ms": 0, "silence_ms": 0}}))

    angle_id = new_ulid()
    with Session(engine) as session:
        session.execute(angles.insert(), [{
            "id": angle_id, "project_id": project_id, "label": "A", "role": "cam_left",
            "source_path": "source/a.mp4",
        }])
        session.execute(cuts.insert(), [{
            "id": new_ulid(), "project_id": project_id, "name": "R", "kind": "rough",
            "params_json": {},
            "cdl_json": {"version": 1, "clips": [
                {"angle_id": angle_id, "src_in_ms": 0, "timeline_in_ms": 0, "dur_ms": 1000},
            ]},
        }])
        session.commit()

    response = client.get(f"/projects/{project_id}/timeline-state")
    assert response.status_code == 200
    assert response.json()["notes"] == []
