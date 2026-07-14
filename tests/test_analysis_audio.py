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
