"""Create a synchronized, deterministic mono analysis track for local AI."""

from __future__ import annotations

import os
import tempfile
import wave
from datetime import UTC, datetime
from pathlib import Path
from typing import Callable, Literal
from uuid import uuid4

from pydantic import Field, field_validator

from autoedit.ai.artifacts import atomic_write_json, sha256_file
from autoedit.ai.contracts import SafeId, Sha256, StrictContract, confined_relative_path
from autoedit.ffproc import run_ffmpeg_watchdog


class AnalysisAudioError(RuntimeError):
    """Raised when analysis audio cannot be rendered or validated."""


class AnalysisSource(StrictContract):
    source_id: SafeId
    relative_path: str
    sync_offset_ms: int
    source_kind: Literal["isolated_lav", "mapped_channel", "camera_guide"]

    @field_validator("relative_path")
    @classmethod
    def validate_relative_path(cls, value: str) -> str:
        return confined_relative_path(value)


class PreparedSource(AnalysisSource):
    sha256: Sha256
    duration_ms: int = Field(gt=0)
    sample_rate: int = Field(gt=0)
    channels: int = Field(gt=0)


class AnalysisPreparationManifest(StrictContract):
    schema_version: Literal["1.0"] = "1.0"
    created_at: datetime
    strategy: Literal["isolated_lav", "mono_mix", "camera_mix"]
    relative_path: str
    sha256: Sha256
    duration_ms: int = Field(gt=0)
    sample_rate: Literal[16_000]
    channels: Literal[1]
    sources: list[PreparedSource] = Field(min_length=1)

    @field_validator("relative_path")
    @classmethod
    def validate_relative_path(cls, value: str) -> str:
        return confined_relative_path(value)


def build_analysis_audio_command(
    project_dir: str | Path,
    sources: list[AnalysisSource],
    output_path: str | Path,
) -> tuple[list[str], list[AnalysisSource], str]:
    """Return an FFmpeg command using source-time offsets on the master timeline.

    Stored positive sync offsets mean source time is ahead of master time, so
    the beginning of that source is trimmed. Negative offsets mean the source
    begins after master zero and therefore require leading silence.
    """
    project = Path(project_dir).resolve()
    if not sources:
        raise ValueError("at least one analysis source is required")

    isolated = [source for source in sources if source.source_kind == "isolated_lav"]
    mapped = [source for source in sources if source.source_kind == "mapped_channel"]
    if isolated:
        selected = isolated
        strategy = "isolated_lav"
    elif mapped:
        selected = mapped
        strategy = "mono_mix"
    else:
        selected = list(sources)
        strategy = "camera_mix"

    paths = [_resolve_source(project, source.relative_path) for source in selected]
    command = ["ffmpeg", "-hide_banner", "-loglevel", "error", "-y"]
    for path in paths:
        command.extend(["-i", str(path)])

    filters: list[str] = []
    gain = 1.0 / len(selected)
    labels: list[str] = []
    for index, source in enumerate(selected):
        chain = f"[{index}:a]aformat=channel_layouts=mono,aresample=16000"
        if source.sync_offset_ms > 0:
            chain += f",atrim=start={source.sync_offset_ms / 1000:.3f},asetpts=PTS-STARTPTS"
        elif source.sync_offset_ms < 0:
            chain += f",adelay={abs(source.sync_offset_ms)}"
        chain += f",volume={gain:.8f}[s{index}]"
        filters.append(chain)
        labels.append(f"[s{index}]")

    if len(selected) == 1:
        filters.append(
            "[s0]anull,aresample=16000,"
            "aformat=sample_fmts=s16:channel_layouts=mono[out]"
        )
    else:
        filters.append(
            f"{''.join(labels)}amix=inputs={len(selected)}:duration=longest:"
            "dropout_transition=0:normalize=0,aresample=16000,"
            "aformat=sample_fmts=s16:channel_layouts=mono[out]"
        )

    command.extend(
        [
            "-filter_complex",
            ";".join(filters),
            "-map",
            "[out]",
            "-ar",
            "16000",
            "-ac",
            "1",
            "-c:a",
            "pcm_s16le",
            str(output_path),
        ]
    )
    return command, selected, strategy


def prepare_analysis_audio(
    project_dir: str | Path,
    sources: list[AnalysisSource],
    *,
    output_relative_path: str = "audio/ai/analysis.wav",
    runner: Callable = run_ffmpeg_watchdog,
) -> AnalysisPreparationManifest:
    """Render and publish analysis audio plus a hash/version provenance manifest."""
    project = Path(project_dir).resolve()
    relative_output = confined_relative_path(output_relative_path)
    output_path = (project / relative_output).resolve()
    if not output_path.is_relative_to(project):
        raise ValueError("analysis output must be confined to project root")
    output_path.parent.mkdir(parents=True, exist_ok=True)

    fd, temp_name = tempfile.mkstemp(
        prefix=f".{output_path.stem}.", suffix=".tmp.wav", dir=output_path.parent
    )
    os.close(fd)
    temp_path = Path(temp_name)
    temp_path.unlink(missing_ok=True)

    command, selected, strategy = build_analysis_audio_command(project, sources, temp_path)
    # Validate and fingerprint every selected WAV before starting an expensive
    # render. A missing or malformed channel must not create a partial mix.
    prepared_sources = [_prepared_source(project, source) for source in selected]
    try:
        result = runner(command)
        if result.returncode != 0:
            detail = (getattr(result, "stderr", "") or "analysis audio render failed").strip()
            raise AnalysisAudioError(detail[-2000:])
        duration_ms, rate, channels = _probe_analysis_wav(temp_path)
        if rate != 16_000 or channels != 1:
            raise AnalysisAudioError("analysis audio must be mono 16 kHz PCM WAV")

        output_hash = sha256_file(temp_path)
        manifest = AnalysisPreparationManifest(
            created_at=datetime.now(UTC),
            strategy=strategy,
            relative_path=relative_output,
            sha256=output_hash,
            duration_ms=duration_ms,
            sample_rate=rate,
            channels=channels,
            sources=prepared_sources,
        )

        manifest_path = output_path.with_suffix(".manifest.json")
        token = uuid4().hex
        staged_manifest = manifest_path.with_name(f".{manifest_path.name}.{token}.staged")
        previous_output = output_path.with_name(f".{output_path.name}.{token}.previous")
        previous_manifest = manifest_path.with_name(f".{manifest_path.name}.{token}.previous")
        atomic_write_json(staged_manifest, manifest.model_dump(mode="json"))
        try:
            if output_path.exists():
                os.replace(output_path, previous_output)
            if manifest_path.exists():
                os.replace(manifest_path, previous_manifest)
            os.replace(temp_path, output_path)
            os.replace(staged_manifest, manifest_path)
        except BaseException:
            # Restore the complete old pair. Publication may touch two files,
            # so each half is staged and every interrupted replacement rolls
            # back rather than pairing new audio with stale provenance.
            output_path.unlink(missing_ok=True)
            manifest_path.unlink(missing_ok=True)
            if previous_output.exists():
                os.replace(previous_output, output_path)
            if previous_manifest.exists():
                os.replace(previous_manifest, manifest_path)
            raise
        finally:
            staged_manifest.unlink(missing_ok=True)
            previous_output.unlink(missing_ok=True)
            previous_manifest.unlink(missing_ok=True)
        return manifest
    finally:
        temp_path.unlink(missing_ok=True)


def _resolve_source(project: Path, relative_path: str) -> Path:
    relative = confined_relative_path(relative_path)
    path = (project / relative).resolve()
    if not path.is_relative_to(project):
        raise ValueError("analysis source must be confined to project root")
    if not path.is_file():
        raise FileNotFoundError(f"analysis source not found: {relative}")
    return path


def _prepared_source(project: Path, source: AnalysisSource) -> PreparedSource:
    path = _resolve_source(project, source.relative_path)
    with wave.open(str(path), "rb") as handle:
        rate = handle.getframerate()
        frames = handle.getnframes()
        channels = handle.getnchannels()
    if rate <= 0 or frames <= 0 or channels <= 0:
        raise AnalysisAudioError(f"invalid WAV source: {source.relative_path}")
    return PreparedSource(
        **source.model_dump(),
        sha256=sha256_file(path),
        duration_ms=max(1, round(frames * 1000 / rate)),
        sample_rate=rate,
        channels=channels,
    )


def _probe_analysis_wav(path: Path) -> tuple[int, int, int]:
    try:
        with wave.open(str(path), "rb") as handle:
            rate = handle.getframerate()
            frames = handle.getnframes()
            channels = handle.getnchannels()
            width = handle.getsampwidth()
    except (FileNotFoundError, OSError, wave.Error) as exc:
        raise AnalysisAudioError("analysis renderer did not produce a readable WAV") from exc
    if rate <= 0 or frames <= 0 or channels <= 0 or width != 2:
        raise AnalysisAudioError("analysis renderer produced an invalid PCM WAV")
    return max(1, round(frames * 1000 / rate)), rate, channels
