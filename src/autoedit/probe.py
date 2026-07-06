from __future__ import annotations

import json
import re
import subprocess
from typing import Any


def _parse_r_frame_rate(rate_str: str) -> tuple[int, int]:
    """Parse a frame rate string like '24000/1001' into (num, den) integers."""
    if "/" in rate_str:
        num_str, den_str = rate_str.split("/", 1)
        return int(num_str), int(den_str)
    return int(float(rate_str) * 1000 + 0.5), 1000


def _parse_timecode_ms(tc: str, fps_num: int, fps_den: int) -> int | None:
    """Parse HH:MM:SS:FF or HH:MM:SS;FF timecode to milliseconds."""
    tc = tc.strip().replace(";", ":")
    parts = tc.split(":")
    if len(parts) != 4:
        return None
    try:
        h, m, s, f = int(parts[0]), int(parts[1]), int(parts[2]), int(parts[3])
    except ValueError:
        return None
    total_seconds = h * 3600 + m * 60 + s
    total_ms = total_seconds * 1000 + round(f * fps_den * 1000 / fps_num)
    return total_ms


def probe_source_file(source_path: str) -> dict[str, Any]:
    """Run ffprobe on a media file and return parsed metadata."""
    try:
        result = subprocess.run(
            ["ffprobe", "-v", "quiet", "-show_streams", "-show_format",
             "-of", "json", source_path],
            capture_output=True, text=True, check=True,
        )
    except FileNotFoundError as exc:
        raise RuntimeError("ffprobe executable not found") from exc
    probe_data = json.loads(result.stdout)

    streams = probe_data.get("streams", [])
    fmt = probe_data.get("format", {})

    video_stream = None
    for stream in streams:
        if stream.get("codec_type") == "video":
            video_stream = stream
            break
    if video_stream is None:
        raise ValueError(f"no video stream found in {source_path}")

    r_frame_rate = video_stream.get("r_frame_rate", "0/1")
    fps_num, fps_den = _parse_r_frame_rate(r_frame_rate)
    duration_ms = int(float(fmt.get("duration", "0")) * 1000 + 0.5)
    width = video_stream.get("width", 0)
    height = video_stream.get("height", 0)
    vcodec = video_stream.get("codec_name", "unknown")

    # Embedded timecode (HH:MM:SS:FF) from video stream tags
    tc_str = (video_stream.get("tags") or {}).get("timecode") or ""
    tc_ms = _parse_timecode_ms(tc_str, fps_num, fps_den) if tc_str else None

    warnings: list[str] = []
    if width != 1920 or height != 1080:
        warnings.append(f"expected 1080p input, got {width}x{height}")
    if vcodec != "h264":
        warnings.append(f"expected H.264 codec, got {vcodec}")

    audio_streams: list[dict[str, Any]] = []
    for stream in streams:
        if stream.get("codec_type") != "audio":
            continue
        idx = int(stream.get("index", len(audio_streams)))
        ch = int(stream.get("channels") or 0)
        audio_streams.append({
            "stream_index": idx,
            "codec": stream.get("codec_name", "unknown"),
            "channels": ch,
            "channel_layout": stream.get("channel_layout") or "",
            "sample_rate": int(stream.get("sample_rate") or 0),
            "channel_indices": list(range(max(ch, 0))),
        })

    return {
        "width": width,
        "height": height,
        "vcodec": vcodec,
        "src_fps_num": fps_num,
        "src_fps_den": fps_den,
        "duration_ms": duration_ms,
        "timecode_ms": tc_ms,
        "timecode": tc_str or None,
        "audio_streams": audio_streams,
        "warnings": warnings,
    }
