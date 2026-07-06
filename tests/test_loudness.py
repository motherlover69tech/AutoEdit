from __future__ import annotations

import json
from pathlib import Path

import numpy as np
import pytest
from fastapi.testclient import TestClient
from sqlalchemy import create_engine, select
from sqlalchemy.pool import StaticPool
from sqlalchemy.orm import Session

from autoedit.api import create_app
from autoedit.db.migrate import run_migrations
from autoedit.db.schema import angles, audio_channels
from autoedit.projects import new_ulid


def _write_test_wav(path: Path, data: np.ndarray, sample_rate: int = 48000):
    """Write a mono 16-bit PCM WAV from float64 data (-1..1 range)."""
    import wave
    path.parent.mkdir(parents=True, exist_ok=True)
    samples = (data * 32767).clip(-32768, 32767).astype(np.int16)
    with wave.open(str(path), "wb") as wf:
        wf.setnchannels(1)
        wf.setsampwidth(2)
        wf.setframerate(sample_rate)
        wf.writeframes(samples.tobytes())


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


@pytest.fixture
def project_with_channels(auth_client):
    """Project with 2 angles, channel mappings, and test WAV files on disk."""
    client, data_root, engine = auth_client

    r = client.post(
        "/projects", json={"name": "Loudness test", "fps_num": 24000, "fps_den": 1001},
    )
    assert r.status_code == 201
    pid = r.json()["id"]

    # Create angles directly
    a1 = new_ulid()
    a2 = new_ulid()
    with Session(engine) as session:
        session.execute(
            angles.insert().values(
                id=a1, project_id=pid, label="A", role="cam_left",
                source_path="source/a.mp4", sync_offset_ms=0,
            )
        )
        session.execute(
            angles.insert().values(
                id=a2, project_id=pid, label="B", role="cam_right",
                source_path="source/b.mp4", sync_offset_ms=0,
            )
        )
        session.commit()

    # Channel mappings
    r = client.post(f"/projects/{pid}/channels", json={
        "mappings": [
            {"source_angle_id": a1, "channel_index": 0, "speaker_label": "presenter"},
            {"source_angle_id": a2, "channel_index": 0, "speaker_label": "interviewee"},
        ],
    })
    assert r.status_code == 201

    # Write test WAV files to simulate channel extraction output
    audio_dir = data_root / pid / "audio"
    sample_rate = 48000
    duration = 1.0  # 1 second
    t = np.linspace(0, duration, int(sample_rate * duration), endpoint=False)

    # Channel 1: 440 Hz sine at -6 dB
    ch1 = 0.5 * np.sin(2 * np.pi * 440 * t)
    _write_test_wav(audio_dir / "ch_presenter.wav", ch1)

    # Channel 2: 1 kHz sine at -12 dB
    ch2 = 0.25 * np.sin(2 * np.pi * 1000 * t)
    _write_test_wav(audio_dir / "ch_interviewee.wav", ch2)

    # Update audio_channels wav_path
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


# ── Pure function tests ─────────────────────────────────────────────


def test_compute_loudness_correct_length():
    """With hop_ms=20 and 1s of audio, expect 50 values."""
    from autoedit.loudness import compute_loudness_envelope

    # 48000 samples = 1 second
    data = np.random.RandomState(42).randn(48000) * 0.1
    result = compute_loudness_envelope(data, sample_rate=48000, hop_ms=20)

    assert len(result) == 50
    assert all(isinstance(v, float) for v in result)


def test_compute_loudness_values_are_dbfs():
    """Values should be negative dB (dBFS, relative to full scale)."""
    from autoedit.loudness import compute_loudness_envelope

    # Full-scale sine
    data = np.sin(np.linspace(0, 1000 * 2 * np.pi, 48000))
    result = compute_loudness_envelope(data, sample_rate=48000, hop_ms=20)

    # Full-scale sine RMS is about -3 dB
    for v in result:
        assert -10 < v < 0, f"Expected near 0 dBFS, got {v}"


def test_compute_loudness_silence_is_low():
    """Silence should produce very negative dB values."""
    from autoedit.loudness import compute_loudness_envelope

    data = np.zeros(48000)
    result = compute_loudness_envelope(data, sample_rate=48000, hop_ms=20)

    # Silence should be well below -60 dB
    for v in result:
        assert v < -60, f"Expected silence < -60 dB, got {v}"


def test_compute_loudness_respects_hop():
    """Different hop values produce different array lengths."""
    from autoedit.loudness import compute_loudness_envelope

    data = np.zeros(48000)
    r20 = compute_loudness_envelope(data, sample_rate=48000, hop_ms=20)
    r40 = compute_loudness_envelope(data, sample_rate=48000, hop_ms=40)

    assert len(r20) == 50
    assert len(r40) == 25


# ── API route tests ─────────────────────────────────────────────────


def test_loudness_route_requires_auth(tmp_path: Path):
    engine = create_engine(
        "sqlite:///:memory:",
        connect_args={"check_same_thread": False},
        poolclass=StaticPool,
    )
    run_migrations(engine)
    app = create_app(
        engine=engine, data_root=tmp_path, auth_enabled=True,
        operator_password="pw", session_secret="secret",
        session_cookie_secure=False,
    )
    client = TestClient(app)

    response = client.post("/projects/01J00000000000000000000000/loudness")
    assert response.status_code == 401


def test_loudness_rejects_missing_project(auth_client):
    client, _, _ = auth_client
    response = client.post("/projects/01J00000000000000000000000/loudness")
    assert response.status_code == 404


def test_loudness_writes_json(project_with_channels):
    """Loudness endpoint computes envelopes and writes loudness.json."""
    client, data_root, engine, pid = project_with_channels

    response = client.post(f"/projects/{pid}/loudness")

    assert response.status_code == 200
    result = response.json()
    assert result["hop_ms"] == 20
    assert "channels" in result
    assert len(result["channels"]) == 2

    # Check the JSON file on disk
    json_path = data_root / pid / "audio" / "loudness.json"
    assert json_path.is_file()

    on_disk = json.loads(json_path.read_text())
    assert on_disk["hop_ms"] == 20
    assert "channels" in on_disk

    # Each channel should have rms_db array and start_ms
    for ch_id, ch_data in on_disk["channels"].items():
        assert "rms_db" in ch_data
        assert "start_ms" in ch_data
        assert len(ch_data["rms_db"]) == 50  # 1s / 20ms hop


def test_loudness_rejects_project_without_channels(auth_client):
    """Project with no channel mappings should return 400."""
    client, _, _ = auth_client
    r = client.post(
        "/projects", json={"name": "No channels", "fps_num": 24000, "fps_den": 1001},
    )
    pid = r.json()["id"]

    response = client.post(f"/projects/{pid}/loudness")
    assert response.status_code == 400
