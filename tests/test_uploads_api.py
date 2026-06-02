from __future__ import annotations

import hashlib
from pathlib import Path

import pytest
from fastapi.testclient import TestClient
from sqlalchemy import create_engine, func, select
from sqlalchemy.pool import StaticPool
from sqlalchemy.orm import Session

from autoedit.api import create_app
from autoedit.db.migrate import run_migrations
from autoedit.db.schema import angles


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
        session_cookie_secure=False,
    )
    client = TestClient(app)
    login = client.post(
        "/auth/login",
        json={"password": "correct-password", "display_name": "Peter"},
    )
    assert login.status_code == 204
    return client, tmp_path, engine


@pytest.fixture
def project(auth_client):
    client, data_root, engine = auth_client
    response = client.post(
        "/projects",
        json={"name": "Upload project", "fps_num": 24000, "fps_den": 1001},
    )
    assert response.status_code == 201
    return response.json(), client, data_root, engine


def start_upload(
    client: TestClient,
    project_id: str,
    *,
    filename: str = "angleA.mp4",
    label: str = "presenter",
    role: str = "cam_left",
    total_bytes: int = 12,
    total_chunks: int = 3,
):
    return client.post(
        f"/projects/{project_id}/uploads",
        json={
            "filename": filename,
            "label": label,
            "role": role,
            "total_bytes": total_bytes,
            "total_chunks": total_chunks,
        },
    )


def test_upload_routes_require_auth(tmp_path: Path):
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

    response = client.post(
        "/projects/01J00000000000000000000000/uploads",
        json={
            "filename": "angleA.mp4",
            "label": "presenter",
            "role": "cam_left",
            "total_bytes": 1,
            "total_chunks": 1,
        },
    )

    assert response.status_code == 401


def test_start_upload_rejects_missing_project(auth_client):
    client, _, _ = auth_client

    response = start_upload(client, "01J00000000000000000000000")

    assert response.status_code == 404
    assert response.json() == {"detail": "project not found"}


@pytest.mark.parametrize("filename", ["../evil.mp4", "nested/evil.mp4", "", ".", ".."]) 
def test_start_upload_rejects_path_traversal_filename(project, filename):
    project_body, client, _, _ = project

    response = start_upload(client, project_body["id"], filename=filename)

    assert response.status_code == 400


def test_chunk_upload_rejects_invalid_upload_id_and_index(project):
    project_body, client, _, _ = project
    created = start_upload(client, project_body["id"])
    assert created.status_code == 201
    upload_id = created.json()["upload_id"]

    traversal = client.post("/upload/../evil/chunk/0", content=b"abcd")
    assert traversal.status_code in {400, 404}

    wildcard_status = client.get("/upload/*")
    assert wildcard_status.status_code == 400

    negative = client.post(f"/upload/{upload_id}/chunk/-1", content=b"abcd")
    assert negative.status_code in {400, 404}

    out_of_range = client.post(f"/upload/{upload_id}/chunk/3", content=b"abcd")
    assert out_of_range.status_code == 400


def test_interrupted_upload_resumes_and_complete_writes_source_and_angle(project):
    project_body, client, data_root, engine = project
    content = b"aaaabbbbcccc"
    expected_sha = hashlib.sha256(content).hexdigest()

    created = start_upload(
        client,
        project_body["id"],
        total_bytes=len(content),
        total_chunks=3,
    )
    assert created.status_code == 201
    upload_id = created.json()["upload_id"]

    assert client.post(f"/upload/{upload_id}/chunk/0", content=b"aaaa").status_code == 200
    assert client.post(f"/upload/{upload_id}/chunk/2", content=b"cccc").status_code == 200
    status = client.get(f"/upload/{upload_id}")
    assert status.status_code == 200
    assert status.json()["highest_contiguous_chunk"] == 0

    assert client.post(f"/upload/{upload_id}/chunk/1", content=b"bbbb").status_code == 200
    status = client.get(f"/upload/{upload_id}")
    assert status.json()["highest_contiguous_chunk"] == 2

    complete = client.post(
        f"/upload/{upload_id}/complete",
        json={"sha256": expected_sha, "total_bytes": len(content)},
    )
    assert complete.status_code == 201
    angle = complete.json()
    assert len(angle["id"]) == 26
    assert angle["project_id"] == project_body["id"]
    assert angle["source_path"] == "source/angleA.mp4"

    source_path = data_root / project_body["id"] / "source" / "angleA.mp4"
    assert source_path.read_bytes() == content

    with Session(engine) as session:
        count = session.execute(select(func.count()).select_from(angles)).scalar_one()
    assert count == 1


def test_wrong_sha_rejects_and_cleans_temp_upload(project):
    project_body, client, data_root, _ = project
    content = b"aaaabbbb"
    created = start_upload(
        client,
        project_body["id"],
        filename="angleB.mp4",
        label="interviewee",
        role="cam_right",
        total_bytes=len(content),
        total_chunks=2,
    )
    upload_id = created.json()["upload_id"]
    assert client.post(f"/upload/{upload_id}/chunk/0", content=b"aaaa").status_code == 200
    assert client.post(f"/upload/{upload_id}/chunk/1", content=b"bbbb").status_code == 200

    response = client.post(
        f"/upload/{upload_id}/complete",
        json={"sha256": "0" * 64, "total_bytes": len(content)},
    )

    assert response.status_code == 400
    assert response.json() == {"detail": "sha256 mismatch"}
    assert not (data_root / project_body["id"] / ".uploads" / upload_id).exists()
    assert not (data_root / project_body["id"] / "source" / "angleB.mp4").exists()


def test_three_uploads_to_one_project_create_three_angles(project):
    project_body, client, data_root, engine = project
    uploads = [
        ("angleA.mp4", "presenter", "cam_left", b"angle-a"),
        ("angleB.mp4", "interviewee", "cam_right", b"angle-b"),
        ("angleC.mp4", "wide", "wide", b"angle-c"),
    ]

    for filename, label, role, content in uploads:
        created = start_upload(
            client,
            project_body["id"],
            filename=filename,
            label=label,
            role=role,
            total_bytes=len(content),
            total_chunks=1,
        )
        assert created.status_code == 201
        upload_id = created.json()["upload_id"]
        assert client.post(f"/upload/{upload_id}/chunk/0", content=content).status_code == 200
        complete = client.post(
            f"/upload/{upload_id}/complete",
            json={"sha256": hashlib.sha256(content).hexdigest(), "total_bytes": len(content)},
        )
        assert complete.status_code == 201
        assert (data_root / project_body["id"] / "source" / filename).read_bytes() == content

    with Session(engine) as session:
        count = session.execute(select(func.count()).select_from(angles)).scalar_one()
    assert count == 3
