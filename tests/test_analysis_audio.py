from __future__ import annotations

import subprocess
import wave
from pathlib import Path

import pytest

from autoedit.ai.analysis_audio import (
    AnalysisAudioError,
    AnalysisSource,
    build_analysis_audio_command,
    prepare_analysis_audio,
)


def _wav(path: Path, *, frames: int = 16_000, rate: int = 16_000, value: int = 200) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    sample = int(value).to_bytes(2, "little", signed=True)
    with wave.open(str(path), "wb") as handle:
        handle.setnchannels(1)
        handle.setsampwidth(2)
        handle.setframerate(rate)
        handle.writeframes(sample * frames)


def test_command_prefers_isolated_lavs_and_applies_source_time_offsets(tmp_path: Path):
    project = tmp_path / "project"
    for name in ("lav-a.wav", "lav-b.wav", "camera.wav"):
        _wav(project / "audio" / name)
    sources = [
        AnalysisSource(
            source_id="lav-a",
            relative_path="audio/lav-a.wav",
            sync_offset_ms=0,
            source_kind="isolated_lav",
        ),
        AnalysisSource(
            source_id="lav-b",
            relative_path="audio/lav-b.wav",
            sync_offset_ms=7_759,
            source_kind="isolated_lav",
        ),
        AnalysisSource(
            source_id="camera",
            relative_path="audio/camera.wav",
            sync_offset_ms=-500,
            source_kind="camera_guide",
        ),
    ]

    command, selected, strategy = build_analysis_audio_command(
        project,
        sources,
        project / "audio" / "ai" / "analysis.tmp.wav",
    )

    assert strategy == "isolated_lav"
    assert [source.source_id for source in selected] == ["lav-a", "lav-b"]
    rendered = " ".join(command)
    assert "camera.wav" not in rendered
    assert "atrim=start=7.759" in rendered
    assert "adelay=" not in rendered
    assert "aresample=16000" in rendered
    assert command[-3:-1] == ["-c:a", "pcm_s16le"]


def test_command_uses_silence_delay_for_negative_source_time_offset(tmp_path: Path):
    project = tmp_path / "project"
    _wav(project / "audio" / "mapped.wav")
    sources = [
        AnalysisSource(
            source_id="mapped",
            relative_path="audio/mapped.wav",
            sync_offset_ms=-500,
            source_kind="mapped_channel",
        )
    ]

    command, _selected, strategy = build_analysis_audio_command(
        project,
        sources,
        project / "audio" / "ai" / "analysis.tmp.wav",
    )

    assert strategy == "mono_mix"
    assert "adelay=500" in " ".join(command)


def test_prepare_writes_hashed_manifest_and_validated_audio(tmp_path: Path):
    project = tmp_path / "project"
    _wav(project / "audio" / "lav.wav", rate=48_000, frames=48_000)

    def runner(command):
        _wav(Path(command[-1]))
        return subprocess.CompletedProcess(command, 0, "", "")

    manifest = prepare_analysis_audio(
        project,
        [
            AnalysisSource(
                source_id="lav",
                relative_path="audio/lav.wav",
                sync_offset_ms=0,
                source_kind="isolated_lav",
            )
        ],
        runner=runner,
    )

    assert manifest.schema_version == "1.0"
    assert manifest.strategy == "isolated_lav"
    assert manifest.sample_rate == 16_000
    assert manifest.channels == 1
    assert manifest.duration_ms == 1_000
    assert len(manifest.sha256) == 64
    assert (project / "audio" / "ai" / "analysis.wav").is_file()
    assert (project / "audio" / "ai" / "analysis.manifest.json").is_file()


def test_failed_render_preserves_previous_analysis_audio_and_manifest(tmp_path: Path):
    project = tmp_path / "project"
    source_path = project / "audio" / "lav.wav"
    output_path = project / "audio" / "ai" / "analysis.wav"
    manifest_path = project / "audio" / "ai" / "analysis.manifest.json"
    _wav(source_path, rate=48_000, frames=48_000)
    _wav(output_path, value=123)
    manifest_path.write_text('{"old": true}\n')
    old_audio = output_path.read_bytes()

    def runner(command):
        Path(command[-1]).write_bytes(b"partial")
        return subprocess.CompletedProcess(command, 1, "", "decoder failed")

    with pytest.raises(AnalysisAudioError, match="decoder failed"):
        prepare_analysis_audio(
            project,
            [
                AnalysisSource(
                    source_id="lav",
                    relative_path="audio/lav.wav",
                    sync_offset_ms=0,
                    source_kind="isolated_lav",
                )
            ],
            runner=runner,
        )

    assert output_path.read_bytes() == old_audio
    assert manifest_path.read_text() == '{"old": true}\n'
    assert not list(output_path.parent.glob("*.tmp.wav"))


def test_analysis_source_rejects_project_escape():
    with pytest.raises(ValueError, match="confined relative path"):
        AnalysisSource(
            source_id="bad",
            relative_path="../outside.wav",
            sync_offset_ms=0,
            source_kind="camera_guide",
        )


def _read_samples(path: Path) -> tuple[float, float]:
    """Return (mean_db, peak_db) of a 16-bit mono WAV."""
    import array
    import math

    with wave.open(str(path), "rb") as handle:
        frames = handle.readframes(handle.getnframes())
    samples = array.array("h")
    samples.frombytes(frames)
    rms = math.sqrt(sum(sample * sample for sample in samples) / len(samples))
    peak = max(abs(sample) for sample in samples)
    return (
        20.0 * math.log10(rms / 32768.0),
        20.0 * math.log10(peak / 32768.0),
    )


def test_normalize_quiet_audio_lifts_toward_target(tmp_path: Path):
    from autoedit.ai.analysis_audio import _normalize_analysis_gain

    path = tmp_path / "quiet.wav"
    _wav(path, frames=16_000, value=100)  # mean ≈ −50.3 dB
    gain = _normalize_analysis_gain(path)
    assert gain > 20
    mean_db, peak_db = _read_samples(path)
    assert -21.5 <= mean_db <= -18.5
    assert peak_db <= -3.0


def test_normalize_loud_audio_reaches_target(tmp_path: Path):
    from autoedit.ai.analysis_audio import _normalize_analysis_gain

    path = tmp_path / "loud.wav"
    _wav(path, frames=16_000, value=30_000)  # mean ≈ −0.77 dB, peak == rms
    gain = _normalize_analysis_gain(path)
    assert gain < -10  # attenuated toward the −20 dB target
    mean_db, peak_db = _read_samples(path)
    assert -21.5 <= mean_db <= -18.5
    assert peak_db <= -3.0


def test_normalize_high_crest_audio_clamps_boost_to_peak_ceiling(tmp_path: Path):
    from autoedit.ai.analysis_audio import _normalize_analysis_gain

    path = tmp_path / "crest.wav"
    values = [100] * 15_980 + [30_000] * 20  # quiet body, hot peaks
    raw = b"".join(int(v).to_bytes(2, "little", signed=True) for v in values)
    with wave.open(str(path), "wb") as handle:
        handle.setnchannels(1)
        handle.setsampwidth(2)
        handle.setframerate(16_000)
        handle.writeframes(raw)
    gain = _normalize_analysis_gain(path)
    assert -3.0 < gain < 0.0  # boost clamped by the −3 dB peak ceiling
    _mean_db, peak_db = _read_samples(path)
    assert peak_db <= -3.0


def test_normalize_silence_is_unchanged(tmp_path: Path):
    from autoedit.ai.analysis_audio import _normalize_analysis_gain

    path = tmp_path / "silence.wav"
    _wav(path, frames=16_000, value=0)
    before = path.read_bytes()
    assert _normalize_analysis_gain(path) == 0.0
    assert path.read_bytes() == before


def test_prepare_applies_normalization_and_records_gain(tmp_path: Path):
    project = tmp_path / "project"
    _wav(project / "audio" / "lav.wav", rate=48_000, frames=48_000)

    def runner(command):
        _wav(Path(command[-1]), value=100)  # quiet rendered mix
        return subprocess.CompletedProcess(command, 0, "", "")

    manifest = prepare_analysis_audio(
        project,
        [
            AnalysisSource(
                source_id="lav",
                relative_path="audio/lav.wav",
                sync_offset_ms=0,
                source_kind="isolated_lav",
            )
        ],
        runner=runner,
    )

    assert manifest.normalized_gain_db > 20
    mean_db, _peak_db = _read_samples(project / "audio" / "ai" / "analysis.wav")
    assert -21.5 <= mean_db <= -18.5
    # manifest hash matches the published (normalized) file
    from autoedit.ai.analysis_audio import sha256_file  # noqa: PLC0415

    assert manifest.sha256 == sha256_file(project / "audio" / "ai" / "analysis.wav")
