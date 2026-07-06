from __future__ import annotations

import hashlib
import json
from pathlib import Path
from unittest.mock import patch

import pytest
from fastapi.testclient import TestClient
from sqlalchemy import create_engine, select
from sqlalchemy.pool import StaticPool
from sqlalchemy.orm import Session

from autoedit.api import create_app
from autoedit.db.migrate import run_migrations
from autoedit.db.schema import angles, audio_channels
from autoedit.projects import new_ulid


@pytest.fixture
def auth_client(tmp_path: Path):
    engine = create_engine(
        "sqlite:///:memory:",
        connect_args={"check_same_thread": False},
        poolclass=StaticPool,
    )
    run_migrations(engine)
    app = create_app(
        engine=engine, data_root=tmp_path, auth_enabled=True,
        operator_password="pw", session_secret="secret",
        public_domain="autoedit.example.com", session_cookie_secure=False,
    )
    client = TestClient(app)
    login = client.post("/auth/login", json={"password": "pw", "display_name": "P"})
    assert login.status_code == 204
    return client, tmp_path, engine


def _seed_angle(client, project_id, data_root, *, label, role, filename, content=b"mock"):
    created = client.post(
        f"/projects/{project_id}/uploads",
        json={
            "filename": filename, "label": label, "role": role,
            "total_bytes": len(content), "total_chunks": 1,
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
def project_with_stereo_channels(auth_client):
    """Project with 2 channel mappings (stereo case)."""
    client, data_root, engine = auth_client
    r = client.post(
        "/projects", json={"name": "Diarize stereo", "fps_num": 24000, "fps_den": 1001},
    )
    pid = r.json()["id"]

    a1 = new_ulid()
    a2 = new_ulid()
    with Session(engine) as session:
        session.execute(angles.insert().values(
            id=a1, project_id=pid, label="A", role="cam_left",
            source_path="source/a.mp4", sync_offset_ms=0,
        ))
        session.execute(angles.insert().values(
            id=a2, project_id=pid, label="B", role="cam_right",
            source_path="source/b.mp4", sync_offset_ms=0,
        ))
        session.commit()

    client.post(f"/projects/{pid}/channels", json={
        "mappings": [
            {"source_angle_id": a1, "channel_index": 0, "speaker_label": "presenter"},
            {"source_angle_id": a2, "channel_index": 0, "speaker_label": "interviewee"},
        ],
    })

    # Write dummy WAV files
    audio_dir = data_root / pid / "audio"
    audio_dir.mkdir(parents=True, exist_ok=True)
    (audio_dir / "ch_presenter.wav").write_bytes(b"wav" * 100)
    (audio_dir / "ch_interviewee.wav").write_bytes(b"wav" * 100)

    # Update wav_path on audio_channels
    with Session(engine) as session:
        session.execute(
            audio_channels.update()
            .where(audio_channels.c.speaker_label == "presenter")
            .values(wav_path="audio/ch_presenter.wav")
        )
        session.execute(
            audio_channels.update()
            .where(audio_channels.c.speaker_label == "interviewee")
            .values(wav_path="audio/ch_interviewee.wav")
        )
        session.commit()

    return client, data_root, engine, pid


@pytest.fixture
def project_with_mono(auth_client):
    """Project with a single mono source angle and no channel mappings."""
    client, data_root, engine = auth_client
    r = client.post(
        "/projects", json={"name": "Diarize mono", "fps_num": 24000, "fps_den": 1001},
    )
    pid = r.json()["id"]

    # Seed an angle via upload so source file exists
    angle = _seed_angle(
        client, pid, data_root,
        label="Main", role="cam_left", filename="mono.mp4",
    )

    # Write a test WAV in audio dir (proper RIFF WAV, not just bytes)
    audio_dir = data_root / pid / "audio"
    audio_dir.mkdir(parents=True, exist_ok=True)
    import wave as _wave
    import numpy as _np
    samples = (_np.sin(_np.linspace(0, 1000 * 2 * _np.pi, 48000)) * 32767).astype(_np.int16)
    with _wave.open(str(audio_dir / "ch_mixed.wav"), "wb") as wf:
        wf.setnchannels(1)
        wf.setsampwidth(2)
        wf.setframerate(48000)
        wf.writeframes(samples.tobytes())

    # Create a single audio_channels row manually
    ch_id = new_ulid()
    with Session(engine) as session:
        session.execute(
            audio_channels.insert().values(
                id=ch_id,
                project_id=pid,
                speaker_label="mixed",
                source_angle_id=angle["id"],
                channel_index=0,
                wav_path="audio/ch_mixed.wav",
            )
        )
        session.commit()

    return client, data_root, engine, pid


# ── Pure function tests ─────────────────────────────────────────────


def test_mock_diarization_returns_segments():
    """Mock diarization produces speaker-labeled time segments."""
    from autoedit.diarize import mock_diarize

    segments = mock_diarize(48000, duration_samples=48000 * 10)  # 10 seconds

    assert len(segments) >= 2
    for seg in segments:
        assert "speaker" in seg
        assert "start_ms" in seg
        assert "end_ms" in seg
        assert seg["start_ms"] < seg["end_ms"]
        assert isinstance(seg["start_ms"], int)
        assert seg["speaker"] in ("speaker_0", "speaker_1")


# ── API route tests ─────────────────────────────────────────────────


def test_diarize_route_requires_auth(tmp_path: Path):
    engine = create_engine(
        "sqlite:///:memory:",
        connect_args={"check_same_thread": False}, poolclass=StaticPool,
    )
    run_migrations(engine)
    app = create_app(
        engine=engine, data_root=tmp_path, auth_enabled=True,
        operator_password="pw", session_secret="secret", session_cookie_secure=False,
    )
    client = TestClient(app)
    r = client.post("/projects/01J00000000000000000000000/diarize")
    assert r.status_code == 401


def test_diarize_rejects_missing_project(auth_client):
    client, _, _ = auth_client
    r = client.post("/projects/01J00000000000000000000000/diarize")
    assert r.status_code == 404


def test_diarize_stereo_uses_channel_mapping(project_with_stereo_channels):
    """Stereo project: diarization should use existing channel→speaker mapping."""
    client, data_root, engine, pid = project_with_stereo_channels

    with patch("autoedit.api.mock_diarize") as mock_d:
        mock_d.return_value = [
            {"speaker": "presenter", "start_ms": 0, "end_ms": 5000},
            {"speaker": "interviewee", "start_ms": 5000, "end_ms": 10000},
        ]
        response = client.post(f"/projects/{pid}/diarize")

    assert response.status_code == 200
    result = response.json()

    assert "speakers" in result
    assert len(result["speakers"]) == 2
    speaker_labels = {s["label"] for s in result["speakers"]}
    assert speaker_labels == {"presenter", "interviewee"}

    assert "segments" in result
    assert len(result["segments"]) >= 1

    # Verify diarization.json was written
    diarize_path = data_root / pid / "audio" / "diarization.json"
    assert diarize_path.is_file()
    on_disk = json.loads(diarize_path.read_text())
    assert "speakers" in on_disk
    assert "segments" in on_disk


def test_diarize_mono_runs_diarization(project_with_mono):
    """Mono project: should run actual diarization on the mixed track."""
    client, data_root, engine, pid = project_with_mono

    with patch("autoedit.api.mock_diarize") as mock_d:
        mock_d.return_value = [
            {"speaker": "speaker_0", "start_ms": 0, "end_ms": 3000},
            {"speaker": "speaker_1", "start_ms": 3000, "end_ms": 6000},
            {"speaker": "speaker_0", "start_ms": 6000, "end_ms": 10000},
        ]
        response = client.post(f"/projects/{pid}/diarize")

    assert response.status_code == 200
    result = response.json()

    assert len(result["speakers"]) >= 2
    assert len(result["segments"]) >= 2

    # The new speakers should be stored as audio_channels
    with Session(engine) as session:
        rows = session.execute(
            select(audio_channels).where(audio_channels.c.project_id == pid)
        ).all()
    speaker_labels = {row.speaker_label for row in rows}
    assert "speaker_0" in speaker_labels
    assert "speaker_1" in speaker_labels

    # Check diarization.json on disk
    diarize_path = data_root / pid / "audio" / "diarization.json"
    assert diarize_path.is_file()


def test_diarize_rejects_project_without_audio(auth_client):
    """Project with no audio_channels or WAV files should return 400."""
    client, _, _ = auth_client
    r = client.post(
        "/projects", json={"name": "No audio", "fps_num": 24000, "fps_den": 1001},
    )
    pid = r.json()["id"]

    response = client.post(f"/projects/{pid}/diarize")
    assert response.status_code == 400
