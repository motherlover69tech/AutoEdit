from __future__ import annotations

import subprocess
import wave
from pathlib import Path


def _wav_duration_seconds(path: str) -> float | None:
    """Return WAV duration in seconds, or None if the file cannot be probed."""
    try:
        with wave.open(path, "rb") as wf:
            rate = wf.getframerate()
            if rate <= 0:
                return None
            return wf.getnframes() / rate
    except (FileNotFoundError, wave.Error, OSError):
        return None


def generate_program_audio(
    channel_wavs: list[tuple[str, int]],
    output_path: str,
    *,
    bitrate: str = "192k",
    plog = None,
) -> None:
    """Mix speaker channel WAVs into a single stereo M4A file."""
    if len(channel_wavs) < 1:
        raise ValueError("at least one channel WAV required")
    if len(channel_wavs) > 2:
        raise ValueError("program audio supports at most 2 channels (stereo)")

    filter_parts = []
    # Normalize offsets so the minimum is 0 (ffmpeg 7+ rejects negative adelay).
    # Cap the output to the longest delayed input. Plain apad is otherwise an
    # infinite source, so ffmpeg will keep muxing silence until it exhausts RAM.
    min_offset = min(offset_ms for _, offset_ms in channel_wavs)
    durations = [
        _wav_duration_seconds(wav_path)
        for wav_path, _ in channel_wavs
    ]
    output_duration = None
    if all(duration is not None for duration in durations):
        output_duration = max(
            duration + ((offset_ms - min_offset) / 1000.0)
            for duration, (_, offset_ms) in zip(durations, channel_wavs, strict=True)
        )

    for i, (wav_path, offset_ms) in enumerate(channel_wavs):
        delay = offset_ms - min_offset
        delay_str = "0|0" if delay == 0 else f"{delay}|{delay}"
        pad = ",apad" if output_duration is not None else ""
        filter_parts.append(f"[{i}:a]adelay={delay_str}{pad}[ch{i}]")

    if len(channel_wavs) == 1:
        filter_spec = filter_parts[0]
        map_args = ["-map", "[ch0]"]
    else:
        filter_parts.append("[ch0][ch1]amerge=inputs=2[out]")
        filter_spec = ";".join(filter_parts)
        map_args = ["-map", "[out]"]

    cmd = ["ffmpeg", "-y"]
    for wav_path, _ in channel_wavs:
        cmd.extend(["-i", wav_path])
    cmd.extend([
        "-filter_complex", filter_spec,
        *map_args,
        "-c:a", "aac", "-b:a", bitrate,
        "-movflags", "+faststart",
    ])
    if output_duration is not None:
        cmd.extend(["-t", f"{output_duration:.3f}"])
    cmd.append(output_path)

    if plog is not None:
        plog.cmd("program_audio", cmd)

    try:
        result = subprocess.run(cmd, capture_output=True, text=True)
    except FileNotFoundError as exc:
        raise RuntimeError("ffmpeg executable not found") from exc

    if plog is not None:
        plog.cmd_result(result.returncode, result.stderr)

    if result.returncode != 0:
        raise RuntimeError(f"ffmpeg program audio generation failed: {result.stderr}")
