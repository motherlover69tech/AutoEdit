from __future__ import annotations

import subprocess
from pathlib import Path


def generate_proxy(
    source_path: str,
    output_path: str,
    *,
    encoder: str = "h264_vaapi",
    gop: int = 12,
    height: int = 720,
    crf: int = 20,
    plog = None,
) -> None:
    """Generate a silent short-GOP playback proxy using ffmpeg.

    Supports software (libx264), Intel VAAPI (h264_vaapi), and the older
    experimental QSV branch (h264_qsv). The VAAPI path requests hardware
    decode/uploaded frames and hardware encode through /dev/dri/renderD128.
    """
    is_qsv = encoder == "h264_qsv"
    is_vaapi = encoder == "h264_vaapi"

    cmd = ["ffmpeg", "-y"]

    if is_vaapi:
        cmd += [
            "-vaapi_device", "/dev/dri/renderD128",
            "-hwaccel", "vaapi",
            "-hwaccel_output_format", "vaapi",
        ]

    cmd += ["-i", source_path]

    if is_vaapi:
        cmd += [
            "-vf", f"scale_vaapi=w=-2:h={height}",
            "-c:v", encoder,
            "-g", str(gop),
            "-keyint_min", str(gop),
            "-qp", str(crf),
            "-movflags", "+faststart",
            "-an",
        ]
    else:
        cmd += [
            "-vf", f"scale=-2:{height}",
            "-c:v", encoder,
            "-g", str(gop),
            "-keyint_min", str(gop),
            "-sc_threshold", "0",
            "-movflags", "+faststart",
            "-an",
        ]

        if is_qsv:
            cmd += [
                "-pix_fmt", "nv12",
                "-global_quality", str(crf),
                "-look_ahead", "1",
                "-look_ahead_depth", "40",
                "-preset", "medium",
            ]
        else:
            cmd += [
                "-profile:v", "high",
                "-pix_fmt", "yuv420p",
                "-preset", "veryfast",
                "-crf", str(crf),
            ]

    cmd.append(output_path)

    if plog is not None:
        plog.cmd("proxy", cmd)

    try:
        result = subprocess.run(cmd, capture_output=True, text=True)
    except FileNotFoundError as exc:
        raise RuntimeError("ffmpeg executable not found") from exc

    if plog is not None:
        plog.cmd_result(result.returncode, result.stderr)

    if result.returncode != 0:
        raise RuntimeError(f"ffmpeg proxy generation failed: {result.stderr}")
