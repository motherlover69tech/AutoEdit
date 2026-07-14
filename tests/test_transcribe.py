from __future__ import annotations

import hashlib
import json
import threading
from pathlib import Path
from unittest.mock import patch

import pytest
from fastapi.testclient import TestClient
from sqlalchemy import create_engine, select
from sqlalchemy.pool import StaticPool
from sqlalchemy.orm import Session

from autoedit.api import create_app
from autoedit.db.migrate import run_migrations
from autoedit.db.schema import angles, audio_channels, transcript_segments
from autoedit.projects import new_ulid


# ── Fixtures ──────────────────────────────────────────────────────


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
        whisper_backend="mock",
    )
    client = TestClient(app)
    login = client.post("/auth/login", json={"password": "pw", "display_name": "P"})
    assert login.status_code == 204
    return client, tmp_path, engine


def _seed_upload(client, project_id, data_root, *, label, role, filename, content=b"mock"):
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
def project_with_wavs(auth_client):
    """Project with audio_channels and WAV files on disk."""
    client, data_root, engine = auth_client

    r = client.post(
        "/projects", json={"name": "Transcribe test", "fps_num": 24000, "fps_den": 1001},
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

    # Write proper WAV files so the endpoint can read them
    audio_dir = data_root / pid / "audio"
    audio_dir.mkdir(parents=True, exist_ok=True)
    import wave as _wave
    import numpy as _np

    def _write_wav(path, duration_s=2.0):
        samples = (_np.sin(_np.linspace(0, 440 * 2 * _np.pi, int(48000 * duration_s))) * 32767).astype(_np.int16)
        with _wave.open(str(path), "wb") as wf:
            wf.setnchannels(1)
            wf.setsampwidth(2)
            wf.setframerate(48000)
            wf.writeframes(samples.tobytes())

    _write_wav(audio_dir / "ch_presenter.wav")
    _write_wav(audio_dir / "ch_interviewee.wav")

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


# ── Pure function tests ────────────────────────────────────────────


def test_mock_transcribe_returns_segments():
    from autoedit.transcribe import mock_transcribe

    result = mock_transcribe(48000, duration_samples=48000 * 10, speaker_label="presenter")

    assert "segments" in result
    segments = result["segments"]
    assert len(segments) >= 1

    for seg in segments:
        assert seg["speaker"] == "presenter"
        assert seg["start_ms"] >= 0
        assert seg["end_ms"] > seg["start_ms"]
        assert isinstance(seg["text"], str)
        assert len(seg["text"]) > 0
        assert "words" in seg
        assert isinstance(seg["words"], list)


def test_mock_transcribe_applies_start_ms_offset():
    """All segment times are shifted by start_ms."""
    from autoedit.transcribe import mock_transcribe

    offset = 5000
    result = mock_transcribe(48000, duration_samples=48000 * 5, start_ms=offset, speaker_label="speaker")

    for seg in result["segments"]:
        assert seg["start_ms"] >= offset
        if seg.get("words"):
            for w in seg["words"]:
                assert w["start_ms"] >= offset


def test_mock_transcribe_empty_audio():
    from autoedit.transcribe import mock_transcribe

    result = mock_transcribe(48000, duration_samples=0)
    assert result["segments"] == []


def test_mock_transcribe_words_have_confidence():
    from autoedit.transcribe import mock_transcribe

    result = mock_transcribe(48000, duration_samples=48000 * 5)

    for seg in result["segments"]:
        for w in seg["words"]:
            assert "conf" in w
            assert 0 <= w["conf"] <= 1


# ── API route tests ────────────────────────────────────────────────


def test_transcribe_route_requires_auth(tmp_path: Path):
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
    response = client.post("/projects/01J00000000000000000000000/transcribe")
    assert response.status_code == 401


def test_transcribe_rejects_missing_project(auth_client):
    client, _, _ = auth_client
    response = client.post("/projects/01J00000000000000000000000/transcribe")
    assert response.status_code == 404


def test_transcribe_rejects_without_wavs(auth_client):
    client, data_root, engine = auth_client
    r = client.post(
        "/projects", json={"name": "No WAVs", "fps_num": 24000, "fps_den": 1001},
    )
    pid = r.json()["id"]

    response = client.post(f"/projects/{pid}/transcribe")
    assert response.status_code == 400


def test_transcribe_populates_database(project_with_wavs):
    """Transcribe route writes transcript_segments to DB."""
    client, data_root, engine, pid = project_with_wavs

    with patch("autoedit.api.mock_transcribe") as mock_fn:
        mock_fn.return_value = {
            "segments": [
                {
                    "speaker": "presenter",
                    "start_ms": 0,
                    "end_ms": 5000,
                    "text": "Hello and welcome.",
                    "words": [
                        {"w": "Hello", "start_ms": 0, "end_ms": 1000, "conf": 0.95},
                        {"w": "and", "start_ms": 1000, "end_ms": 1800, "conf": 0.92},
                        {"w": "welcome", "start_ms": 1800, "end_ms": 5000, "conf": 0.97},
                    ],
                },
                {
                    "speaker": "interviewee",
                    "start_ms": 50,
                    "end_ms": 5050,
                    "text": "Thank you.",
                    "words": [
                        {"w": "Thank", "start_ms": 50, "end_ms": 2000, "conf": 0.96},
                        {"w": "you", "start_ms": 2000, "end_ms": 5050, "conf": 0.93},
                    ],
                },
            ],
        }

        response = client.post(f"/projects/{pid}/transcribe")

    assert response.status_code == 200
    assert [call.kwargs["start_ms"] for call in mock_fn.call_args_list] == [0, -50]
    result = response.json()
    assert "segments" in result
    assert len(result["segments"]) >= 2

    # Verify DB rows
    with Session(engine) as session:
        t_rows = session.execute(
            select(transcript_segments).where(
                transcript_segments.c.project_id == pid
            ).order_by(transcript_segments.c.start_ms)
        ).all()

    assert len(t_rows) >= 2
    for row in t_rows:
        assert row.start_ms >= 0
        assert row.end_ms > row.start_ms
        assert len(row.text) > 0
        assert row.project_id == pid


def test_transcribe_writes_json_file(project_with_wavs):
    """Transcribe route writes transcript.json to disk."""
    client, data_root, engine, pid = project_with_wavs

    with patch("autoedit.api.mock_transcribe") as mock_fn:
        mock_fn.return_value = {
            "segments": [
                {
                    "speaker": "presenter",
                    "start_ms": 1000,
                    "end_ms": 3000,
                    "text": "Test segment.",
                    "words": [{"w": "Test", "start_ms": 1000, "end_ms": 2000, "conf": 0.90}],
                },
            ],
        }

        client.post(f"/projects/{pid}/transcribe")

    transcript_path = data_root / pid / "transcript" / "transcript.json"
    assert transcript_path.is_file()

    on_disk = json.loads(transcript_path.read_text())
    assert "segments" in on_disk
    assert len(on_disk["segments"]) >= 1


def test_transcribe_applies_sync_offset(project_with_wavs):
    """Channel with sync_offset_ms=50 should have offset applied to segment times."""
    client, _, _, pid = project_with_wavs

    with patch("autoedit.api.mock_transcribe") as mock_fn:
        mock_fn.return_value = {
            "segments": [
                {"speaker": "presenter", "start_ms": 0, "end_ms": 2000, "text": "Hi.", "words": []},
                {"speaker": "interviewee", "start_ms": 0, "end_ms": 2000, "text": "Hello.", "words": []},
            ],
        }

        response = client.post(f"/projects/{pid}/transcribe")

    assert response.status_code == 200
    # The mock returns segments with start_ms=0 for both, but the endpoint
    # should convert the stored source delay to a source-to-master shift.
    calls = mock_fn.call_args_list
    offsets_used = [call.kwargs.get("start_ms", 0) for call in calls]
    assert offsets_used == [0, -50]


def test_transcribe_idempotent(project_with_wavs):
    """Running transcribe twice replaces old rows, not duplicates."""
    client, data_root, engine, pid = project_with_wavs

    with patch("autoedit.api.mock_transcribe") as mock_fn:
        mock_fn.return_value = {
            "segments": [
                {"speaker": "presenter", "start_ms": 0, "end_ms": 1000, "text": "Test.", "words": []},
            ],
        }
        r1 = client.post(f"/projects/{pid}/transcribe")
        assert r1.status_code == 200

    with Session(engine) as session:
        count1 = len(session.execute(
            select(transcript_segments).where(transcript_segments.c.project_id == pid)
        ).all())

    with patch("autoedit.api.mock_transcribe") as mock_fn:
        mock_fn.return_value = {
            "segments": [
                {"speaker": "presenter", "start_ms": 0, "end_ms": 1000, "text": "Test.", "words": []},
            ],
        }
        r2 = client.post(f"/projects/{pid}/transcribe")
        assert r2.status_code == 200

    with Session(engine) as session:
        count2 = len(session.execute(
            select(transcript_segments).where(transcript_segments.c.project_id == pid)
        ).all())

    # Idempotent: same number of rows
    assert count2 == count1


def test_transcribe_rejects_concurrent_run_for_same_project(project_with_wavs):
    client, _, _, pid = project_with_wavs
    second_client = TestClient(client.app)
    login = second_client.post("/auth/login", json={"password": "pw", "display_name": "P2"})
    assert login.status_code == 204

    started = threading.Event()
    release = threading.Event()
    first_responses = []

    def slow_transcribe(*args, **kwargs):
        started.set()
        assert release.wait(timeout=5)
        return {
            "segments": [
                {
                    "speaker": kwargs.get("speaker_label"),
                    "start_ms": max(0, kwargs.get("start_ms", 0)),
                    "end_ms": 1000,
                    "text": "Test.",
                    "words": [],
                }
            ]
        }

    with patch("autoedit.api.mock_transcribe", side_effect=slow_transcribe):
        first = threading.Thread(
            target=lambda: first_responses.append(
                client.post(f"/projects/{pid}/transcribe")
            )
        )
        first.start()
        assert started.wait(timeout=5)
        try:
            concurrent = second_client.post(f"/projects/{pid}/transcribe")
        finally:
            release.set()
            first.join(timeout=5)

    assert not first.is_alive()
    assert first_responses[0].status_code == 200
    assert concurrent.status_code == 409
    assert concurrent.json() == {"detail": "transcription already in progress"}


def test_transcribe_correct_word_count(project_with_wavs):
    """Each segment has matching words list."""
    client, data_root, engine, pid = project_with_wavs

    text = "One two three four five"
    word_count = len(text.split())

    with patch("autoedit.api.mock_transcribe") as mock_fn:
        mock_fn.return_value = {
            "segments": [
                {
                    "speaker": "presenter",
                    "start_ms": 0, "end_ms": 3000,
                    "text": text,
                    "words": [
                        {"w": w, "start_ms": i * 500, "end_ms": (i + 1) * 500, "conf": 0.95}
                        for i, w in enumerate(text.split())
                    ],
                },
            ],
        }

        response = client.post(f"/projects/{pid}/transcribe")

    assert response.status_code == 200
    result = response.json()
    assert len(result["segments"][0]["words"]) == word_count


def test_transcribe_validates_every_mapped_wav_before_processing(project_with_wavs):
    client, data_root, _, pid = project_with_wavs
    missing = data_root / pid / "audio" / "ch_interviewee.wav"
    missing.unlink()

    with patch("autoedit.api.mock_transcribe") as mock_fn:
        response = client.post(f"/projects/{pid}/transcribe")

    assert response.status_code == 400
    assert "interviewee" in response.json()["detail"]
    mock_fn.assert_not_called()


def test_transcribe_accepts_valid_silent_result(project_with_wavs):
    client, data_root, engine, pid = project_with_wavs

    with patch("autoedit.api.mock_transcribe", return_value={"segments": []}):
        response = client.post(f"/projects/{pid}/transcribe")

    assert response.status_code == 200
    assert response.json() == {"segments": []}
    transcript_path = data_root / pid / "transcript" / "transcript.json"
    assert json.loads(transcript_path.read_text()) == {"segments": []}
    with Session(engine) as session:
        rows = session.execute(
            select(transcript_segments).where(
                transcript_segments.c.project_id == pid
            )
        ).all()
    assert rows == []


def test_transcribe_db_failure_preserves_last_known_good_state(project_with_wavs):
    client, data_root, engine, pid = project_with_wavs
    old_result = {
        "segments": [
            {
                "speaker": "presenter",
                "start_ms": 0,
                "end_ms": 1000,
                "text": "last known good",
                "words": [],
            }
        ]
    }
    with patch("autoedit.api.mock_transcribe", return_value=old_result):
        assert client.post(f"/projects/{pid}/transcribe").status_code == 200

    transcript_path = data_root / pid / "transcript" / "transcript.json"
    old_artifact = transcript_path.read_bytes()
    with Session(engine) as session:
        old_rows = session.execute(
            select(transcript_segments.c.text).where(
                transcript_segments.c.project_id == pid
            ).order_by(transcript_segments.c.id)
        ).all()

    new_result = {
        "segments": [
            {
                "speaker": "presenter",
                "start_ms": 0,
                "end_ms": 1000,
                "text": "must not publish",
                "words": [],
            }
        ]
    }
    with (
        patch("autoedit.api.mock_transcribe", return_value=new_result),
        patch.object(transcript_segments, "insert", side_effect=RuntimeError("db down")),
    ):
        response = client.post(f"/projects/{pid}/transcribe")

    assert response.status_code == 500
    assert "previous transcript was preserved" in response.json()["detail"]
    assert transcript_path.read_bytes() == old_artifact
    with Session(engine) as session:
        rows_after = session.execute(
            select(transcript_segments.c.text).where(
                transcript_segments.c.project_id == pid
            ).order_by(transcript_segments.c.id)
        ).all()
    assert rows_after == old_rows
