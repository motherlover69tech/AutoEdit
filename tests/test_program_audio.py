from __future__ import annotations

from pathlib import Path
from unittest.mock import patch

import pytest
from fastapi.testclient import TestClient
from sqlalchemy import create_engine
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


@pytest.fixture
def project_with_wavs(auth_client):
    """Project with audio channels that have WAV files."""
    client, data_root, engine = auth_client

    r = client.post(
        "/projects", json={"name": "Program audio", "fps_num": 24000, "fps_den": 1001},
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
            source_path="source/b.mp4", sync_offset_ms=50,
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

    import wave as _wave
    import numpy as _np

    def _write_wav(path, duration_samples=48000):
        samples = (_np.sin(_np.linspace(0, 440 * 2 * _np.pi, duration_samples)) * 32767).astype(_np.int16)
        with _wave.open(str(path), "wb") as wf:
            wf.setnchannels(1)
            wf.setsampwidth(2)
            wf.setframerate(48000)
            wf.writeframes(samples.tobytes())

    _write_wav(audio_dir / "ch_presenter.wav")
    _write_wav(audio_dir / "ch_interviewee.wav")

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


# ── Pure function tests ─────────────────────────────────────────────


def test_generate_program_audio_calls_ffmpeg():
    """generate_program_audio invokes ffmpeg with correct args for stereo mix."""
    from autoedit.program_audio import generate_program_audio

    with patch("autoedit.program_audio.run_ffmpeg_watchdog") as mock_run:
        mock_run.return_value.returncode = 0

        generate_program_audio(
            [("/tmp/a.wav", 0), ("/tmp/b.wav", 50)],
            "/tmp/program.m4a",
        )

    mock_run.assert_called_once()
    cmd = mock_run.call_args[0][0]

    # Check key arguments
    assert "-y" in cmd
    assert "/tmp/a.wav" in str(cmd)
    assert "/tmp/b.wav" in str(cmd)
    assert "/tmp/program.m4a" in str(cmd)

    # Check filter complex for adelay with offset
    filter_arg_idx = cmd.index("-filter_complex") + 1
    filter_spec = cmd[filter_arg_idx]
    assert "adelay=0|0" in filter_spec
    assert "adelay=50|50" in filter_spec
    assert "amerge=inputs=2" in filter_spec
    assert "-c:a" in cmd
    assert "aac" in cmd
    assert "-movflags" in cmd
    assert "+faststart" in cmd


def test_generate_program_audio_single_channel():
    """Single channel → mono output without amerge."""
    from autoedit.program_audio import generate_program_audio

    with patch("autoedit.program_audio.run_ffmpeg_watchdog") as mock_run:
        mock_run.return_value.returncode = 0
        generate_program_audio([("/tmp/a.wav", 0)], "/tmp/program.m4a")

    cmd = mock_run.call_args[0][0]
    filter_arg_idx = cmd.index("-filter_complex") + 1
    filter_spec = cmd[filter_arg_idx]
    assert "adelay=0|0" in filter_spec
    assert "amerge" not in filter_spec


def test_generate_program_audio_ffmpeg_failure():
    """RuntimeError is raised on ffmpeg non-zero exit."""
    from autoedit.program_audio import generate_program_audio

    with patch("autoedit.program_audio.run_ffmpeg_watchdog") as mock_run:
        mock_run.return_value.returncode = 1
        mock_run.return_value.stderr = "ffmpeg error"

        with pytest.raises(RuntimeError, match="ffmpeg program audio generation failed"):
            generate_program_audio([("/tmp/a.wav", 0)], "/tmp/program.m4a")


def test_generate_program_audio_empty_channels():
    """Empty channel list raises ValueError."""
    from autoedit.program_audio import generate_program_audio

    with pytest.raises(ValueError, match="at least one channel"):
        generate_program_audio([], "/tmp/program.m4a")


def test_generate_program_audio_too_many_channels():
    """More than 2 channels raises ValueError."""
    from autoedit.program_audio import generate_program_audio

    with pytest.raises(ValueError, match="at most 2 channels"):
        generate_program_audio(
            [("/tmp/a.wav", 0), ("/tmp/b.wav", 0), ("/tmp/c.wav", 0)],
            "/tmp/program.m4a",
        )


# ── API route tests ─────────────────────────────────────────────────


def test_program_audio_route_requires_auth(tmp_path: Path):
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
    response = client.post("/projects/01J00000000000000000000000/program-audio")
    assert response.status_code == 401


def test_program_audio_rejects_missing_project(auth_client):
    client, _, _ = auth_client
    response = client.post("/projects/01J00000000000000000000000/program-audio")
    assert response.status_code == 404


def test_program_audio_rejects_without_wavs(auth_client):
    """Project with channels but no WAV files should return 400."""
    client, data_root, engine = auth_client
    r = client.post(
        "/projects", json={"name": "No WAVs", "fps_num": 24000, "fps_den": 1001},
    )
    pid = r.json()["id"]

    a1 = new_ulid()
    with Session(engine) as session:
        session.execute(angles.insert().values(
            id=a1, project_id=pid, label="A", role="cam_left",
            source_path="source/a.mp4", sync_offset_ms=0,
        ))
        session.commit()

    client.post(f"/projects/{pid}/channels", json={
        "mappings": [
            {"source_angle_id": a1, "channel_index": 0, "speaker_label": "presenter"},
            {"source_angle_id": a1, "channel_index": 1, "speaker_label": "interviewee"},
        ],
    })

    response = client.post(f"/projects/{pid}/program-audio")
    assert response.status_code == 400


def test_program_audio_generates_m4a(project_with_wavs):
    """Program audio route creates program.m4a file."""
    client, data_root, engine, pid = project_with_wavs

    with patch("autoedit.program_audio.run_ffmpeg_watchdog") as mock_run:
        mock_run.return_value.returncode = 0

        response = client.post(f"/projects/{pid}/program-audio")

    assert response.status_code == 200
    result = response.json()
    assert result["path"] == "audio/program.m4a"
    assert result["channels"] == 2


def test_program_audio_ffmpeg_args(project_with_wavs):
    """Verify ffmpeg receives correct args from the API route."""
    client, data_root, engine, pid = project_with_wavs

    with patch("autoedit.program_audio.run_ffmpeg_watchdog") as mock_run:
        mock_run.return_value.returncode = 0
        client.post(f"/projects/{pid}/program-audio")

    cmd = mock_run.call_args[0][0]

    # Should contain WAV paths
    assert any("ch_presenter.wav" in str(a) for a in cmd)
    assert any("ch_interviewee.wav" in str(a) for a in cmd)

    # Should contain output path
    assert any(str(data_root / pid / "audio" / "program.m4a") in str(a) for a in cmd)

    # Should use AAC codec and faststart
    assert "aac" in cmd
    assert "+faststart" in cmd

    # Should cap apad to the longest delayed input rather than muxing silence forever
    assert "-t" in cmd
    assert cmd[cmd.index("-t") + 1] == "1.050"

    # Should apply adelay for the offset
    filter_arg_idx = cmd.index("-filter_complex") + 1
    filter_spec = cmd[filter_arg_idx]
    assert "adelay=0" in filter_spec
    assert "adelay=50" in filter_spec


def test_program_audio_uses_sync_offsets(project_with_wavs):
    """The API route reads sync offsets from angles table."""
    client, data_root, engine, pid = project_with_wavs

    with patch("autoedit.program_audio.run_ffmpeg_watchdog") as mock_run:
        mock_run.return_value.returncode = 0
        client.post(f"/projects/{pid}/program-audio")

    cmd = mock_run.call_args[0][0]
    filter_arg_idx = cmd.index("-filter_complex") + 1
    filter_spec = cmd[filter_arg_idx]

    # Angle B has sync_offset_ms=50 → that channel should get adelay=50
    assert "adelay=50|50" in filter_spec
