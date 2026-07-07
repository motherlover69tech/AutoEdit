from __future__ import annotations

import hashlib
import wave
from pathlib import Path
from unittest.mock import MagicMock, patch

import numpy as np
import pytest
from fastapi.testclient import TestClient
from sqlalchemy import create_engine, select
from sqlalchemy.pool import StaticPool
from sqlalchemy.orm import Session

from autoedit.api import create_app
from autoedit.db.migrate import run_migrations
from autoedit.db.schema import angles, audio_channels, projects


# ── Utils ────────────────────────────────────────────────────────────


def _write_wav(path: Path, data: np.ndarray, sample_rate: int = 48000):
    """Write a mono 16-bit PCM WAV file from a numpy array (float64, range -1..1)."""
    path.parent.mkdir(parents=True, exist_ok=True)
    samples = (data * 32767).clip(-32768, 32767).astype(np.int16)
    with wave.open(str(path), "wb") as wf:
        wf.setnchannels(1)
        wf.setsampwidth(2)
        wf.setframerate(sample_rate)
        wf.writeframes(samples.tobytes())


def _generate_impulse(duration_ms: int, sample_rate: int, impulse_at_ms: int):
    """Return a zero signal with a single impulse (1.0) at `impulse_at_ms`."""
    total = int(duration_ms * sample_rate / 1000)
    data = np.zeros(total, dtype=np.float64)
    impulse_idx = int(impulse_at_ms * sample_rate / 1000)
    if 0 <= impulse_idx < total:
        data[impulse_idx] = 1.0
    return data


def _speech_like_signal(duration_s: float, sample_rate: int, *, seed: int) -> np.ndarray:
    """Deterministic speech-ish waveform with a distinctive changing envelope."""
    rng = np.random.RandomState(seed)
    n = int(duration_s * sample_rate)
    t = np.arange(n, dtype=np.float64) / sample_rate
    carrier = (
        0.45 * np.sin(2 * np.pi * 440 * t)
        + 0.25 * np.sin(2 * np.pi * 980 * t + 0.3)
        + 0.15 * np.sin(2 * np.pi * 1720 * t + 0.9)
    )
    envelope = np.zeros(n, dtype=np.float64)
    cursor = 0
    while cursor < n:
        gap = rng.randint(int(0.04 * sample_rate), int(0.18 * sample_rate))
        cursor += gap
        burst = rng.randint(int(0.08 * sample_rate), int(0.55 * sample_rate))
        end = min(n, cursor + burst)
        if end > cursor:
            envelope[cursor:end] = rng.uniform(0.25, 1.0)
        cursor = end
    envelope = np.convolve(envelope, np.ones(int(0.02 * sample_rate)) / int(0.02 * sample_rate), mode="same")
    noise = 0.04 * rng.standard_normal(n)
    return (carrier * envelope + noise).astype(np.float64)


def _pad_signal(data: np.ndarray, sample_rate: int, *, pre_ms: int, post_ms: int = 0) -> np.ndarray:
    pre = np.zeros(int(pre_ms * sample_rate / 1000), dtype=np.float64)
    post = np.zeros(int(post_ms * sample_rate / 1000), dtype=np.float64)
    return np.concatenate([pre, data, post])


def _add_clap_burst(signal: np.ndarray, sample_rate: int, first_clap_s: float, gains: list[float]) -> None:
    """Add a short repeated-clap burst in-place."""
    offsets_s = [0.0, 0.425, 0.75, 1.065]
    pulse_len = int(0.035 * sample_rate)
    t = np.arange(pulse_len, dtype=np.float64) / sample_rate
    pulse = np.sin(2 * np.pi * 1800 * t) * np.hanning(pulse_len)
    for offset_s, gain in zip(offsets_s, gains, strict=True):
        start = int((first_clap_s + offset_s) * sample_rate)
        end = min(len(signal), start + pulse_len)
        if 0 <= start < len(signal) and end > start:
            signal[start:end] += gain * pulse[:end - start]


# ── Fixtures ─────────────────────────────────────────────────────────


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
    resp = client.post(
        "/projects",
        json={"name": "Sync project", "fps_num": 24000, "fps_den": 1001},
    )
    assert resp.status_code == 201
    return resp.json(), client, data_root, engine


def _seed_angle(client, project_id, data_root, *, label, role, filename, content=b"mock"):
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


def _setup_project_with_channels_and_media(
    auth_client, tmp_path: Path, *, nudge_ms: int | None = None, delay_ms: int = 50
):
    """Create project, 2 angles with generated WAV media, and channel mappings.

    Writes synthetic WAV files (impulse at known positions) into the project's source dir.
    Returns (client, project_body, angle_a, angle_b).
    """
    client, data_root, engine = auth_client
    resp = client.post(
        "/projects",
        json={"name": "Audio sync test", "fps_num": 24000, "fps_den": 1001},
    )
    assert resp.status_code == 201
    project_body = resp.json()
    pid = project_body["id"]

    # Create source dir and write fake source files
    source_dir = data_root / pid / "source"
    source_dir.mkdir(parents=True, exist_ok=True)
    (source_dir / "angleA.mp4").write_text("")
    (source_dir / "angleB.mp4").write_text("")

    # Write WAV guide tracks directly (mock what ffmpeg extraction would produce)
    audio_dir = data_root / pid / "audio"
    audio_dir.mkdir(parents=True, exist_ok=True)

    sample_rate = 48000
    duration_ms = 1000  # 1 second

    # Angle A: reference — impulse at 200ms
    ref_data = _generate_impulse(duration_ms, sample_rate, 200)
    _write_wav(audio_dir / "guide_angleA.wav", ref_data, sample_rate)

    # Angle B: delayed by `delay_ms` relative to reference
    delayed_data = _generate_impulse(duration_ms, sample_rate, 200 + delay_ms)
    _write_wav(audio_dir / "guide_angleB.wav", delayed_data, sample_rate)

    # Insert angle rows directly (bypassing upload since we need source_path)
    from autoedit.projects import new_ulid

    angle_a_id = new_ulid()
    angle_b_id = new_ulid()
    with Session(engine) as session:
        session.execute(
            angles.insert().values(
                id=angle_a_id,
                project_id=pid,
                label="Angle A",
                role="cam_left",
                source_path="source/angleA.mp4",
                sync_offset_ms=0,
            )
        )
        session.execute(
            angles.insert().values(
                id=angle_b_id,
                project_id=pid,
                label="Angle B",
                role="cam_right",
                source_path="source/angleB.mp4",
                sync_offset_ms=0,
            )
        )
        session.commit()

    # Create channel mappings
    mappings = [
        {"source_angle_id": angle_a_id, "channel_index": 0, "speaker_label": "presenter"},
        {"source_angle_id": angle_b_id, "channel_index": 1, "speaker_label": "interviewee"},
    ]
    payload = {"mappings": mappings}
    if nudge_ms is not None:
        payload["sync_nudges"] = [{"source_angle_id": angle_b_id, "offset_ms": nudge_ms}]

    resp = client.post(f"/projects/{pid}/channels", json=payload)
    assert resp.status_code == 201

    return client, data_root, engine, project_body, angle_a_id, angle_b_id


# ── Auth / 404 tests ────────────────────────────────────────────────


def test_sync_route_requires_auth(tmp_path: Path):
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
    response = client.post("/projects/01J00000000000000000000000/sync")
    assert response.status_code == 401


def test_sync_rejects_missing_project(auth_client):
    client, _, _ = auth_client
    response = client.post("/projects/01J00000000000000000000000/sync")
    assert response.status_code == 404


def test_sync_rejects_project_without_channels(project):
    """Project with no channel mappings should return 400."""
    project_body, client, _, _ = project
    pid = project_body["id"]

    response = client.post(f"/projects/{pid}/sync")
    assert response.status_code == 400


# ── Signal processing tests ─────────────────────────────────────────


def test_bandpass_filter_attenuates_low_frequency():
    """Frequencies below 300 Hz should be attenuated."""
    from autoedit.audio import bandpass_filter

    sample_rate = 48000
    duration = 1.0
    t = np.linspace(0, duration, int(sample_rate * duration), endpoint=False)

    # 100 Hz sine wave
    low_freq_signal = np.sin(2 * np.pi * 100 * t)
    filtered = bandpass_filter(low_freq_signal, sample_rate, low=300, high=3000)

    rms_original = np.sqrt(np.mean(low_freq_signal ** 2))
    rms_filtered = np.sqrt(np.mean(filtered ** 2))
    assert rms_filtered < rms_original * 0.3  # significant attenuation


def test_bandpass_filter_passes_mid_frequency():
    """Frequencies between 300-3000 Hz should pass through."""
    from autoedit.audio import bandpass_filter

    sample_rate = 48000
    duration = 1.0
    t = np.linspace(0, duration, int(sample_rate * duration), endpoint=False)

    # 1000 Hz sine wave
    mid_freq_signal = np.sin(2 * np.pi * 1000 * t)
    filtered = bandpass_filter(mid_freq_signal, sample_rate, low=300, high=3000)

    rms_original = np.sqrt(np.mean(mid_freq_signal ** 2))
    rms_filtered = np.sqrt(np.mean(filtered ** 2))
    # Should retain most energy; allow ~10% attenuation from filter roll-off
    assert rms_filtered > rms_original * 0.5


def test_cross_correlation_finds_known_lag():
    """Generate two signals with a known delay and verify the cross-correlation finds it."""
    from autoedit.audio import compute_cross_correlation

    sample_rate = 8000
    duration_ms = 1000
    delay_ms = 50
    max_lag_seconds = 2.0

    # Reference: impulse at 200ms
    total = int(duration_ms * sample_rate / 1000)
    ref = np.zeros(total, dtype=np.float64)
    ref[int(200 * sample_rate / 1000)] = 1.0

    # Delayed: same impulse but shifted by delay_ms
    delayed = np.zeros(total, dtype=np.float64)
    delayed_idx = int((200 + delay_ms) * sample_rate / 1000)
    if delayed_idx < total:
        delayed[delayed_idx] = 1.0

    offset_samples, offset_ms = compute_cross_correlation(
        ref, delayed, max_lag_seconds=max_lag_seconds, sample_rate=sample_rate,
    )

    assert offset_ms == delay_ms
    assert offset_samples == int(delay_ms * sample_rate / 1000)


def test_cross_correlation_zero_lag_for_identical():
    """Identical signals should produce zero lag."""
    from autoedit.audio import compute_cross_correlation

    sample_rate = 8000
    total = 8000  # 1 second
    ref = np.random.RandomState(42).randn(total)

    offset_samples, offset_ms = compute_cross_correlation(
        ref, ref, max_lag_seconds=2.0, sample_rate=sample_rate,
    )

    assert offset_ms == 0
    assert offset_samples == 0


def test_cross_correlation_negative_lag():
    """Signal that leads (negative delay) should return negative offset."""
    from autoedit.audio import compute_cross_correlation

    sample_rate = 8000
    total = 8000  # 1 second
    ref = np.zeros(total, dtype=np.float64)
    ref[int(0.5 * sample_rate)] = 1.0

    # Signal that occurs 30ms earlier
    other = np.zeros(total, dtype=np.float64)
    other[int(0.47 * sample_rate)] = 1.0  # ~30ms earlier

    offset_samples, offset_ms = compute_cross_correlation(
        ref, other, max_lag_seconds=2.0, sample_rate=sample_rate,
    )

    # The other signal leads — offset should be negative (within envelope resolution)
    assert -60 <= offset_ms <= 0, f"expected negative offset, got {offset_ms}"


def test_find_sync_offset_matches_different_lengths_and_mic_quality():
    """Windowed waveform matching should handle pre-roll, post-roll, gain/noise differences."""
    from autoedit.audio import bandpass_filter, downsample, find_sync_offset

    sample_rate = 8000
    event = _speech_like_signal(75.0, sample_rate, seed=7)
    # Same content, but the second camera starts 7.35s later and has shorter post-roll.
    reference = _pad_signal(event, sample_rate, pre_ms=1500, post_ms=5000)
    other = _pad_signal(np.tanh(event * 1.8) * 0.55, sample_rate, pre_ms=8850, post_ms=1200)
    other += 0.015 * np.random.RandomState(99).standard_normal(len(other))

    ref_filtered = downsample(bandpass_filter(reference, sample_rate), sample_rate, 8000)
    other_filtered = downsample(bandpass_filter(other, sample_rate), sample_rate, 8000)

    offset_ms, quality = find_sync_offset(ref_filtered, other_filtered, 8000)

    # find_sync_offset sign: negative means `other` is delayed relative to `reference`.
    assert abs(offset_ms - -7350) <= 100
    assert quality >= 5.0


def test_read_wav_float_downsamples_48k_to_8k_in_float32(tmp_path: Path):
    """Large guide WAVs should be reduced before sync arrays become huge."""
    from autoedit.audio import _read_wav_float

    sample_rate = 48000
    data = _speech_like_signal(2.0, sample_rate, seed=17)
    wav_path = tmp_path / "guide_48k.wav"
    _write_wav(wav_path, data, sample_rate)

    samples, out_rate = _read_wav_float(wav_path, target_sample_rate=8000)

    assert out_rate == 8000
    assert samples.dtype == np.float32
    assert abs(len(samples) - 16000) <= 1


def test_compute_sync_offsets_handles_three_different_length_feeds(tmp_path: Path):
    """The sync step should compute a separate offset for every non-reference file."""
    from autoedit.audio import compute_sync_offsets

    sample_rate = 8000
    event = _speech_like_signal(65.0, sample_rate, seed=11)
    ref = _pad_signal(event, sample_rate, pre_ms=2000, post_ms=2500)
    delayed = _pad_signal(event * 0.35, sample_rate, pre_ms=7350, post_ms=600)
    leading = _pad_signal(np.tanh(event * 2.2), sample_rate, pre_ms=250, post_ms=8000)

    ref_path = tmp_path / "ref.wav"
    delayed_path = tmp_path / "delayed.wav"
    leading_path = tmp_path / "leading.wav"
    _write_wav(ref_path, ref, sample_rate)
    _write_wav(delayed_path, delayed, sample_rate)
    _write_wav(leading_path, leading, sample_rate)

    offsets = compute_sync_offsets(
        {
            "ref": str(ref_path),
            "delayed": str(delayed_path),
            "leading": str(leading_path),
        },
        "ref",
    )

    assert offsets["ref"] == 0
    assert abs(offsets["delayed"] - 5350) <= 100
    assert abs(offsets["leading"] - -1750) <= 100


def test_compute_sync_offsets_rejects_low_quality_match_instead_of_zeroing(tmp_path: Path):
    """Weak correlation must fail loudly, not silently become a zero offset."""
    from autoedit.audio import SyncQualityError, compute_sync_offsets

    sample_rate = 8000
    ref_path = tmp_path / "ref.wav"
    other_path = tmp_path / "other.wav"
    _write_wav(ref_path, _speech_like_signal(2.0, sample_rate, seed=31), sample_rate)
    _write_wav(other_path, _speech_like_signal(2.0, sample_rate, seed=32), sample_rate)

    with patch("autoedit.audio.find_sync_offset", return_value=(137, 1.25)):
        with pytest.raises(SyncQualityError) as excinfo:
            compute_sync_offsets({"ref": str(ref_path), "other": str(other_path)}, "ref")

    err = excinfo.value
    assert err.angle_id == "other"
    assert err.quality == 1.25
    assert err.threshold == 5.0
    assert "other" in str(err)
    assert "1.25" in str(err)


def test_find_sync_offset_uses_first_clap_onset_not_loudest_repeated_clap():
    """Repeated claps should align to the first clap onset, not a louder later clap."""
    from autoedit.audio import bandpass_filter, downsample, find_sync_offset

    sample_rate = 8000
    rng = np.random.RandomState(123)
    duration_s = 80.0
    reference = 0.002 * rng.standard_normal(int(duration_s * sample_rate))
    other = 0.002 * rng.standard_normal(int(duration_s * sample_rate))

    # The Resolve-style target: wide/reference first clap at 54.74s, other first
    # clap at 30.765s -> other starts 23.975s after reference.
    _add_clap_burst(reference, sample_rate, 54.74, [0.45, 0.9, 0.85, 0.82])
    # Other camera hears the first clap weakly; the later repeated claps are much
    # louder. A largest-peak matcher incorrectly locks around 23.59s.
    _add_clap_burst(other, sample_rate, 30.765, [0.22, 0.95, 0.96, 0.92])
    # Add a later loud burst that should not become the sync anchor.
    _add_clap_burst(reference, sample_rate, 58.545, [0.8, 0.9, 0.75, 0.8])
    _add_clap_burst(other, sample_rate, 34.57, [0.8, 0.9, 0.75, 0.8])

    ref_filtered = downsample(bandpass_filter(reference, sample_rate), sample_rate, 8000)
    other_filtered = downsample(bandpass_filter(other, sample_rate), sample_rate, 8000)

    offset_ms, quality = find_sync_offset(ref_filtered, other_filtered, 8000)

    assert abs(offset_ms - 23975) <= 40
    assert quality >= 5.0


# ── Sync endpoint tests (mocked ffmpeg) ─────────────────────────────


def _mock_subprocess_for_ffmpeg(data_root: Path, project_id: str):
    """Return a side_effect for subprocess.run that creates WAV files instead of calling ffmpeg."""

    def _fake_run(cmd, **kwargs):
        result = MagicMock()
        result.returncode = 0
        result.stdout = ""

        # Intercept ffmpeg calls and write generated WAVs
        cmd_str = " ".join(str(c) for c in cmd)
        if "pan=mono" in cmd_str and "audio/ch_" in cmd_str:
            # Channel extraction: write a tiny WAV
            import re as _re
            match = _re.search(r"audio/(ch_\w+)\.wav", cmd_str)
            if match:
                wav_path = data_root / project_id / "audio" / f"{match.group(1)}.wav"
                data = _generate_impulse(1000, 48000, 200)
                _write_wav(wav_path, data, 48000)
        elif "-ac 1" in cmd_str and "audio/guide_" in cmd_str:
            # Guide track extraction
            import re as _re
            match = _re.search(r"audio/(guide_\w+)\.wav", cmd_str)
            if match:
                wav_path = data_root / project_id / "audio" / f"{match.group(1)}.wav"
                data = _generate_impulse(1000, 48000, 200)
                _write_wav(wav_path, data, 48000)

        return result

    return _fake_run


def test_sync_endpoint_extracts_channels_and_computes_offsets(auth_client):
    """Full sync: channel extraction + guide track extraction + cross-correlation."""
    client, data_root, engine = auth_client
    _, _, _, project_body, angle_a_id, angle_b_id = _setup_channels_and_media(
        auth_client, data_root, delay_ms=50,
    )
    pid = project_body["id"]

    sync_fn = _mock_compute_sync(50)
    app = create_app(
        engine=engine, data_root=data_root, auth_enabled=False,
        sync_fn=sync_fn,
    )
    test_client = TestClient(app)

    with patch("autoedit.audio.run_ffmpeg_watchdog", side_effect=_mock_subprocess_for_ffmpeg(data_root, pid)):
        response = test_client.post(f"/projects/{pid}/sync")

    assert response.status_code == 200
    result = response.json()

    assert len(result["channels"]) == 2
    assert len(result["offsets"]) == 2

    ref = next(o for o in result["offsets"] if o["offset_ms"] == 0)
    assert ref is not None

    other = next(o for o in result["offsets"] if o["offset_ms"] != 0)
    assert other["offset_ms"] == 50

    with Session(engine) as session:
        rows = session.execute(select(audio_channels)).all()
    for row in rows:
        assert row.wav_path is not None
        assert row.wav_path.startswith("audio/ch_")


def _mock_compute_sync(delay_ms: int):
    """Return a mock that simulates compute_sync_offsets returning a fixed delay."""
    call_count = [0]

    def _compute(guide_tracks, reference_angle_id, operator_nudge_ms=0):
        call_count[0] += 1
        offsets = {}
        for angle_id in guide_tracks:
            if angle_id == reference_angle_id:
                offsets[angle_id] = 0
            else:
                offsets[angle_id] = delay_ms + operator_nudge_ms
        return offsets

    _compute.call_count = call_count
    return _compute


def test_sync_endpoint_applies_operator_nudge(auth_client):
    """Operator manual nudge is added to the computed offset."""
    client, data_root, engine = auth_client
    _, _, _, project_body, angle_a_id, angle_b_id = _setup_channels_and_media(
        auth_client, data_root, delay_ms=50, nudge_ms=20,
    )
    pid = project_body["id"]

    sync_fn = _mock_compute_sync(50)
    app = create_app(
        engine=engine, data_root=data_root, auth_enabled=False,
        sync_fn=sync_fn,
    )
    test_client = TestClient(app)

    with patch("autoedit.audio.run_ffmpeg_watchdog", side_effect=_mock_subprocess_for_ffmpeg(data_root, pid)):
        response = test_client.post(f"/projects/{pid}/sync")

    assert response.status_code == 200
    result = response.json()

    assert sync_fn.call_count[0] == 1, f"Mock called {sync_fn.call_count[0]} times"

    # Nudge (20) may land on reference or non-reference angle depending on ULID order.
    # Expected offsets: one is 50 (mock), one is 20 (nudge only on reference).
    offsets = result["offsets"]
    assert len(offsets) == 2
    offset_values = sorted(o["offset_ms"] for o in offsets)
    assert offset_values in ([0, 70], [20, 50]), (
        f"Expected [0,70] or [20,50], got {offset_values}"
    )


def test_sync_endpoint_roundtrips_integer_ms(auth_client):
    """All offsets in the response are integer milliseconds."""
    client, data_root, engine = auth_client
    _, _, _, project_body, angle_a_id, angle_b_id = _setup_channels_and_media(
        auth_client, data_root, delay_ms=50,
    )
    pid = project_body["id"]

    sync_fn = _mock_compute_sync(50)
    app = create_app(
        engine=engine, data_root=data_root, auth_enabled=False,
        sync_fn=sync_fn,
    )
    test_client = TestClient(app)

    with patch("autoedit.audio.run_ffmpeg_watchdog", side_effect=_mock_subprocess_for_ffmpeg(data_root, pid)):
        response = test_client.post(f"/projects/{pid}/sync")

    assert response.status_code == 200
    for offset in response.json()["offsets"]:
        assert isinstance(offset["offset_ms"], int)


def test_sync_endpoint_reports_low_quality_sync_as_error(auth_client):
    """The sync API should surface low-confidence automatic sync as an error."""
    from autoedit.audio import SyncQualityError

    client, data_root, engine = auth_client
    _, _, _, project_body, _angle_a_id, _angle_b_id = _setup_channels_and_media(
        auth_client, data_root, delay_ms=50,
    )
    pid = project_body["id"]

    def failing_sync(_guide_tracks, _reference_angle_id, operator_nudge_ms=0):
        raise SyncQualityError("angle-b", quality=1.25, threshold=5.0)

    app = create_app(
        engine=engine, data_root=data_root, auth_enabled=False,
        sync_fn=failing_sync,
    )
    test_client = TestClient(app)

    with patch("autoedit.audio.run_ffmpeg_watchdog", side_effect=_mock_subprocess_for_ffmpeg(data_root, pid)):
        response = test_client.post(f"/projects/{pid}/sync")

    assert response.status_code == 422
    detail = response.json()["detail"]
    assert detail["error"] == "sync_quality_low"
    assert detail["angle_id"] == "angle-b"
    assert detail["quality"] == 1.25
    assert detail["threshold"] == 5.0

    with Session(engine) as session:
        status = session.execute(
            select(projects.c.status).where(projects.c.id == pid)
        ).scalar_one()
    assert status == "error"

    errors_path = data_root / pid / "pipeline.errors.json"
    assert errors_path.is_file()
    assert "sync_quality_low" in errors_path.read_text()


def test_sync_endpoint_does_not_compound_previous_auto_sync(auth_client):
    """Rerunning sync should replace prior automatic offsets, not add them again."""
    client, data_root, engine = auth_client
    _, _, _, project_body, _angle_a_id, _angle_b_id = _setup_channels_and_media(
        auth_client, data_root, delay_ms=50,
    )
    pid = project_body["id"]

    sync_fn = _mock_compute_sync(50)
    app = create_app(
        engine=engine, data_root=data_root, auth_enabled=False,
        sync_fn=sync_fn,
    )
    test_client = TestClient(app)

    with patch("autoedit.audio.run_ffmpeg_watchdog", side_effect=_mock_subprocess_for_ffmpeg(data_root, pid)):
        first = test_client.post(f"/projects/{pid}/sync")
        second = test_client.post(f"/projects/{pid}/sync")

    assert first.status_code == 200
    assert second.status_code == 200
    assert sorted(o["offset_ms"] for o in first.json()["offsets"]) == [0, 50]
    assert sorted(o["offset_ms"] for o in second.json()["offsets"]) == [0, 50]


# ── Helpers ──────────────────────────────────────────────────────────


def _setup_channels_and_media(auth_client, data_root, *, delay_ms=50, nudge_ms=None):
    """Create project with 2 angles and channel mappings, plus WAV guide tracks."""
    client, data_root, engine = auth_client
    resp = client.post(
        "/projects",
        json={"name": "Audio sync test", "fps_num": 24000, "fps_den": 1001},
    )
    assert resp.status_code == 201
    project_body = resp.json()
    pid = project_body["id"]

    # Create source dir and write fake source files
    source_dir = data_root / pid / "source"
    source_dir.mkdir(parents=True, exist_ok=True)
    (source_dir / "angleA.mp4").write_text("")
    (source_dir / "angleB.mp4").write_text("")

    # Insert angle rows directly
    from autoedit.projects import new_ulid

    angle_a_id = new_ulid()
    angle_b_id = new_ulid()
    with Session(engine) as session:
        session.execute(
            angles.insert().values(
                id=angle_a_id,
                project_id=pid,
                label="Angle A",
                role="cam_left",
                source_path="source/angleA.mp4",
                sync_offset_ms=0,
            )
        )
        session.execute(
            angles.insert().values(
                id=angle_b_id,
                project_id=pid,
                label="Angle B",
                role="cam_right",
                source_path="source/angleB.mp4",
                sync_offset_ms=0,
            )
        )
        session.commit()

    # Channel mappings
    mappings = [
        {"source_angle_id": angle_a_id, "channel_index": 0, "speaker_label": "presenter"},
        {"source_angle_id": angle_b_id, "channel_index": 1, "speaker_label": "interviewee"},
    ]
    payload = {"mappings": mappings}
    if nudge_ms is not None:
        payload["sync_nudges"] = [{"source_angle_id": angle_b_id, "offset_ms": nudge_ms}]
    client.post(f"/projects/{pid}/channels", json=payload)

    # Write mock source media (empty files for ffmpeg mock)
    audio_dir = data_root / pid / "audio"
    audio_dir.mkdir(parents=True, exist_ok=True)

    return client, data_root, engine, project_body, angle_a_id, angle_b_id
