from __future__ import annotations

import hashlib
import json
from pathlib import Path
from unittest.mock import patch

import pytest
from fastapi.testclient import TestClient
from sqlalchemy import create_engine, func, select
from sqlalchemy.pool import StaticPool
from sqlalchemy.orm import Session

from autoedit.api import create_app
from autoedit.db.migrate import run_migrations
from autoedit.db.schema import angles, audio_channels
from autoedit.projects import new_ulid


def _read_fixture(name: str) -> dict:
    return json.loads((Path(__file__).parent / "fixtures" / "ffprobe" / name).read_text())


def _probe_fixture(name: str):
    """Return a mock probe function that parses the fixture and returns probe dict format."""
    fixture = _read_fixture(name)

    # Parse the fixture the same way probe_source_file does
    streams = fixture.get("streams", [])
    fmt_data = fixture.get("format", {})

    video_stream = None
    for s in streams:
        if s.get("codec_type") == "video":
            video_stream = s
            break

    r_frame_rate = video_stream.get("r_frame_rate", "0/1")
    if "/" in r_frame_rate:
        num_str, den_str = r_frame_rate.split("/", 1)
        fps_num, fps_den = int(num_str), int(den_str)
    else:
        fps_num, fps_den = int(float(r_frame_rate) * 1000 + 0.5), 1000

    duration_ms = int(float(fmt_data.get("duration", "0")) * 1000 + 0.5)
    width = video_stream.get("width", 0)
    height = video_stream.get("height", 0)
    vcodec = video_stream.get("codec_name", "unknown")

    warnings = []
    if width != 1920 or height != 1080:
        warnings.append(f"expected 1080p input, got {width}x{height}")
    if vcodec != "h264":
        warnings.append(f"expected H.264 codec, got {vcodec}")

    result = {
        "width": width,
        "height": height,
        "vcodec": vcodec,
        "src_fps_num": fps_num,
        "src_fps_den": fps_den,
        "duration_ms": duration_ms,
        "warnings": warnings,
    }

    def _probe(source_path: str) -> dict:
        return result

    return _probe


# ── Fixtures ──────────────────────────────────────────────────────────


@pytest.fixture
def auth_client(tmp_path: Path):
    """Client with auth enabled, logged in as Peter."""
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
    """Create a project and return (project_body, client, data_root, engine)."""
    client, data_root, engine = auth_client
    response = client.post(
        "/projects",
        json={"name": "Probe project", "fps_num": 24000, "fps_den": 1001},
    )
    assert response.status_code == 201
    return response.json(), client, data_root, engine


def _seed_angle(client, project_id, data_root, *, label, role, filename, content=b"mock"):
    """Upload + complete an angle, return the angle dict from the API response."""
    created = client.post(
        f"/projects/{project_id}/uploads",
        json={
            "filename": filename,
            "label": label,
            "role": role,
            "total_bytes": len(content),
            "total_chunks": 1,
        },
    )
    assert created.status_code == 201
    upload_id = created.json()["upload_id"]
    client.post(f"/upload/{upload_id}/chunk/0", content=content)
    complete = client.post(
        f"/upload/{upload_id}/complete",
        json={
            "sha256": hashlib.sha256(content).hexdigest(),
            "total_bytes": len(content),
        },
    )
    assert complete.status_code == 201
    return complete.json()


@pytest.fixture
def project_with_angles(auth_client):
    """Project with three angles uploaded (A=cam_left, B=cam_right, C=wide)."""
    client, data_root, engine = auth_client
    resp = client.post(
        "/projects",
        json={"name": "Three angles", "fps_num": 24000, "fps_den": 1001},
    )
    assert resp.status_code == 201
    project_body = resp.json()
    pid = project_body["id"]

    angle_a = _seed_angle(
        client, pid, data_root,
        label="Angle A", role="cam_left", filename="angleA.mp4", content=b"angle-a-content",
    )
    angle_b = _seed_angle(
        client, pid, data_root,
        label="Angle B", role="cam_right", filename="angleB.mp4", content=b"angle-b-content",
    )
    angle_c = _seed_angle(
        client, pid, data_root,
        label="Angle C", role="wide", filename="angleC.mp4", content=b"angle-c-content",
    )
    return project_body, client, data_root, engine, [angle_a, angle_b, angle_c]


# ── Probe tests ───────────────────────────────────────────────────────


def test_probe_route_requires_auth(tmp_path: Path):
    """Probe endpoint returns 401 when auth is enabled and no session cookie."""
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
        "/projects/01J00000000000000000000000/angles/01J00000000000000000000000/probe",
    )

    assert response.status_code == 401


def test_probe_rejects_missing_project(auth_client):
    """Probe on non-existent project returns 404."""
    client, _, _ = auth_client
    response = client.post(
        "/projects/01J00000000000000000000000/angles/01J00000000000000000000000/probe",
    )
    assert response.status_code == 404


def test_probe_rejects_missing_angle(auth_client):
    """Probe on non-existent angle returns 404."""
    client, _, _ = auth_client
    resp = client.post(
        "/projects",
        json={"name": "Test", "fps_num": 24000, "fps_den": 1001},
    )
    pid = resp.json()["id"]

    response = client.post(f"/projects/{pid}/angles/01J00000000000000000000000/probe")
    assert response.status_code == 404


def test_probe_rejects_invalid_angle_id(project):
    """Probe with a non-ULID angle id returns 400."""
    project_body, client, _, _ = project
    pid = project_body["id"]

    response = client.post(f"/projects/{pid}/angles/not-a-valid-ulid/probe")
    assert response.status_code in {400, 404}


def test_probe_updates_angle_with_metadata(project_with_angles):
    """Probe populates angles row from mocked ffprobe output."""
    project_body, client, data_root, engine, angle_list = project_with_angles
    pid = project_body["id"]
    angle_a = angle_list[0]

    with (
        patch("autoedit.api.probe_source_file", _probe_fixture("h264_1080p.json")),
    ):
        response = client.post(f"/projects/{pid}/angles/{angle_a['id']}/probe")

    assert response.status_code == 200
    result = response.json()
    assert result["angle_id"] == angle_a["id"]
    assert result["width"] == 1920
    assert result["height"] == 1080
    assert result["vcodec"] == "h264"
    assert result["src_fps_num"] == 24000
    assert result["src_fps_den"] == 1001
    assert result["duration_ms"] == 30030  # 30.03s * 1000
    assert "warnings" in result
    assert len(result["warnings"]) == 0

    # Verify DB row updated
    with Session(engine) as session:
        row = session.execute(select(angles).where(angles.c.id == angle_a["id"])).one()._mapping
    assert row.width == 1920
    assert row.height == 1080
    assert row.vcodec == "h264"
    assert row.src_fps_num == 24000
    assert row.src_fps_den == 1001
    assert row.duration_ms == 30030


def test_probe_warns_on_non_1080p(project_with_angles):
    """720p source returns a warning but still records metadata."""
    project_body, client, _, _, angle_list = project_with_angles
    pid = project_body["id"]
    angle_a = angle_list[0]

    with (
        patch("autoedit.api.probe_source_file", _probe_fixture("h264_720p.json")),
    ):
        response = client.post(f"/projects/{pid}/angles/{angle_a['id']}/probe")

    assert response.status_code == 200
    result = response.json()
    assert result["width"] == 1280
    assert result["height"] == 720
    assert len(result["warnings"]) >= 1
    assert any("1080" in w for w in result["warnings"])


def test_probe_warns_on_non_h264(project_with_angles):
    """HEVC source returns a warning but still records metadata."""
    project_body, client, _, _, angle_list = project_with_angles
    pid = project_body["id"]
    angle_a = angle_list[0]

    with (
        patch("autoedit.api.probe_source_file", _probe_fixture("hevc_1080p.json")),
    ):
        response = client.post(f"/projects/{pid}/angles/{angle_a['id']}/probe")

    assert response.status_code == 200
    result = response.json()
    assert result["vcodec"] == "hevc"
    assert len(result["warnings"]) >= 1
    assert any("H.264" in w or "h264" in w for w in result["warnings"])


# ── Channel mapping tests ─────────────────────────────────────────────


def test_channel_mapping_route_requires_auth(tmp_path: Path):
    """Channel mapping endpoint returns 401 when auth is enabled."""
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
        "/projects/01J00000000000000000000000/channels",
        json={"mappings": []},
    )

    assert response.status_code == 401


def test_channel_mapping_rejects_missing_project(auth_client):
    """Channel mapping to missing project returns 404."""
    client, _, _ = auth_client
    response = client.post(
        "/projects/01J00000000000000000000000/channels",
        json={
            "mappings": [
                {"source_angle_id": "01J00000000000000000000000", "channel_index": 0, "speaker_label": "a"},
                {"source_angle_id": "01J00000000000000000000000", "channel_index": 1, "speaker_label": "b"},
            ],
        },
    )
    assert response.status_code == 404


def test_channel_mapping_creates_audio_channels_rows(project_with_angles):
    """Creates two audio_channels rows with correct speaker labels."""
    project_body, client, data_root, engine, angle_list = project_with_angles
    pid = project_body["id"]
    angle_a, angle_b = angle_list[0], angle_list[1]

    response = client.post(
        f"/projects/{pid}/channels",
        json={
            "mappings": [
                {
                    "source_angle_id": angle_a["id"],
                    "channel_index": 0,
                    "speaker_label": "presenter",
                },
                {
                    "source_angle_id": angle_a["id"],
                    "channel_index": 1,
                    "speaker_label": "interviewee",
                },
            ],
        },
    )

    assert response.status_code == 201
    result = response.json()
    assert len(result["channels"]) == 2

    channel_0 = next(ch for ch in result["channels"] if ch["channel_index"] == 0)
    channel_1 = next(ch for ch in result["channels"] if ch["channel_index"] == 1)
    assert channel_0["speaker_label"] == "presenter"
    assert channel_0["source_angle_id"] == angle_a["id"]
    assert channel_1["speaker_label"] == "interviewee"
    assert channel_1["source_angle_id"] == angle_a["id"]
    assert channel_0["project_id"] == pid
    assert channel_1["project_id"] == pid
    assert len(channel_0["id"]) == 26
    assert len(channel_1["id"]) == 26

    # Verify DB rows
    with Session(engine) as session:
        rows = session.execute(
            select(audio_channels).order_by(audio_channels.c.channel_index)
        ).all()
    assert len(rows) == 2
    assert rows[0].speaker_label == "presenter"
    assert rows[1].speaker_label == "interviewee"


def test_channel_mapping_stores_sync_nudge(project_with_angles):
    """Manual sync nudge is stored as integer milliseconds on the angles row."""
    project_body, client, data_root, engine, angle_list = project_with_angles
    pid = project_body["id"]
    angle_a = angle_list[0]

    response = client.post(
        f"/projects/{pid}/channels",
        json={
            "mappings": [
                {
                    "source_angle_id": angle_a["id"],
                    "channel_index": 0,
                    "speaker_label": "presenter",
                },
                {
                    "source_angle_id": angle_a["id"],
                    "channel_index": 1,
                    "speaker_label": "interviewee",
                },
            ],
            "sync_nudges": [
                {"source_angle_id": angle_a["id"], "offset_ms": 50},
            ],
        },
    )

    assert response.status_code == 201

    # Verify sync_offset_ms in DB
    with Session(engine) as session:
        row = session.execute(select(angles).where(angles.c.id == angle_a["id"])).one()._mapping
    assert row.sync_offset_ms == 50


def test_channel_mapping_stores_negative_sync_nudge(project_with_angles):
    """Negative sync nudge is stored correctly."""
    project_body, client, _, engine, angle_list = project_with_angles
    pid = project_body["id"]
    angle_a = angle_list[0]

    client.post(
        f"/projects/{pid}/channels",
        json={
            "mappings": [
                {
                    "source_angle_id": angle_a["id"],
                    "channel_index": 0,
                    "speaker_label": "presenter",
                },
                {
                    "source_angle_id": angle_a["id"],
                    "channel_index": 1,
                    "speaker_label": "interviewee",
                },
            ],
            "sync_nudges": [
                {"source_angle_id": angle_a["id"], "offset_ms": -120},
            ],
        },
    )

    with Session(engine) as session:
        row = session.execute(select(angles).where(angles.c.id == angle_a["id"])).one()._mapping
    assert row.sync_offset_ms == -120


@pytest.mark.parametrize(
    "payload,expected_detail",
    [
        ({"mappings": []}, "at least two channel mappings"),
        (
            {
                "mappings": [
                    {"source_angle_id": "01J00000000000000000000000", "channel_index": 0, "speaker_label": "x"},
                ],
            },
            "at least two channel mappings",
        ),
        (
            {
                "mappings": [
                    {"source_angle_id": "01J00000000000000000000000", "channel_index": 0, "speaker_label": ""},
                    {"source_angle_id": "01J00000000000000000000000", "channel_index": 1, "speaker_label": ""},
                ],
            },
            "speaker_label",
        ),
        (
            {
                "mappings": [
                    {"source_angle_id": "01J00000000000000000000000", "channel_index": 0},
                    {"source_angle_id": "01J00000000000000000000000", "channel_index": 1},
                ],
            },
            "speaker_label",
        ),
        (
            {
                "mappings": [
                    {"source_angle_id": "01J00000000000000000000000", "channel_index": 0, "speaker_label": "p"},
                    {"source_angle_id": "01J00000000000000000000000", "channel_index": 0, "speaker_label": "i"},
                ],
            },
            "channel_index",
        ),
        (
            {
                "mappings": [
                    {"source_angle_id": "01J00000000000000000000000", "channel_index": -1, "speaker_label": "p"},
                    {"source_angle_id": "01J00000000000000000000000", "channel_index": 1, "speaker_label": "i"},
                ],
            },
            "channel_index",
        ),
    ],
)
def test_channel_mapping_rejects_invalid_payloads(auth_client, payload, expected_detail):
    """Invalid mapping payloads are rejected with 400."""
    client, _, _ = auth_client
    resp = client.post(
        "/projects",
        json={"name": "Test", "fps_num": 24000, "fps_den": 1001},
    )
    pid = resp.json()["id"]

    response = client.post(f"/projects/{pid}/channels", json=payload)
    assert response.status_code == 400


def test_channel_mapping_updates_existing_channels(project_with_angles):
    """Running channel mapping again replaces existing audio_channels rows."""
    project_body, client, _, engine, angle_list = project_with_angles
    pid = project_body["id"]
    angle_a = angle_list[0]

    # First mapping
    client.post(
        f"/projects/{pid}/channels",
        json={
            "mappings": [
                {"source_angle_id": angle_a["id"], "channel_index": 0, "speaker_label": "speaker_x"},
                {"source_angle_id": angle_a["id"], "channel_index": 1, "speaker_label": "speaker_y"},
            ],
        },
    )

    # Second mapping — same angle, different labels
    response = client.post(
        f"/projects/{pid}/channels",
        json={
            "mappings": [
                {"source_angle_id": angle_a["id"], "channel_index": 0, "speaker_label": "presenter"},
                {"source_angle_id": angle_a["id"], "channel_index": 1, "speaker_label": "interviewee"},
            ],
        },
    )

    assert response.status_code == 201
    result = response.json()
    assert len(result["channels"]) == 2

    # Should be updated, not duplicated
    with Session(engine) as session:
        count = session.execute(
            select(func.count()).select_from(audio_channels)
        ).scalar_one()
    assert count == 2
    with Session(engine) as session:
        rows = session.execute(
            select(audio_channels).order_by(audio_channels.c.channel_index)
        ).all()
    assert rows[0].speaker_label == "presenter"
    assert rows[1].speaker_label == "interviewee"


def test_probe_warns_on_fps_mismatch_with_project(project_with_angles):
    """Source fps differs from project fps — probe returns a warning."""
    project_body, client, _, _, angle_list = project_with_angles
    pid = project_body["id"]
    angle_a = angle_list[0]

    with patch("autoedit.api.probe_source_file", _probe_fixture("h264_1080p_25fps.json")):
        response = client.post(f"/projects/{pid}/angles/{angle_a['id']}/probe")

    assert response.status_code == 200
    result = response.json()
    assert result["src_fps_num"] == 25
    assert result["src_fps_den"] == 1
    assert any("frame rate" in w.lower() for w in result["warnings"])


def test_probe_warns_on_fps_mismatch_between_angles(project_with_angles):
    """Second angle has different fps from first probed angle."""
    project_body, client, _, _, angle_list = project_with_angles
    pid = project_body["id"]
    angle_a = angle_list[0]
    angle_b = angle_list[1]

    with patch("autoedit.api.probe_source_file", _probe_fixture("h264_1080p.json")):
        r1 = client.post(f"/projects/{pid}/angles/{angle_a['id']}/probe")
    assert r1.status_code == 200
    assert len(r1.json()["warnings"]) == 0

    with patch("autoedit.api.probe_source_file", _probe_fixture("h264_1080p_25fps.json")):
        r2 = client.post(f"/projects/{pid}/angles/{angle_b['id']}/probe")
    assert r2.status_code == 200
    assert any("differs from other angles" in w for w in r2.json()["warnings"])
