from __future__ import annotations

from pathlib import Path


def ms_to_frames(t_ms: int, fps_num: int, fps_den: int) -> int:
    """Convert milliseconds to nearest frame number.

    1 frame = fps_den / fps_num seconds = fps_den * 1000 / fps_num ms
    """
    return round(t_ms * fps_num / (fps_den * 1000))


def frame_boundary_ms(frames: int, fps_num: int, fps_den: int) -> int:
    """Canonical integer-ms representation of a frame boundary.

    At NTSC-family rates (23.976, 29.97, 24 fps) frame boundaries are not
    integer milliseconds, so a convention is needed for storing them in the
    integer-ms CDL. This rounds the exact boundary to the nearest ms
    (half-up) and is the single source of truth shared by the cut engine
    (which snaps to it) and the validator (which checks against it).
    """
    return (frames * fps_den * 1000 + fps_num // 2) // fps_num


def is_frame_exact(t_ms: int, fps_num: int, fps_den: int) -> bool:
    """Check if an integer ms value is the canonical form of a frame boundary.

    True exactness is impossible in integer ms at NTSC rates; instead a
    value is "frame exact" when it equals frame_boundary_ms() of its
    nearest frame — i.e. it round-trips through the canonical grid.
    """
    return t_ms == frame_boundary_ms(ms_to_frames(t_ms, fps_num, fps_den), fps_num, fps_den)


def validate_cdl(
    cdl: dict,
    fps_num: int,
    fps_den: int,
    source_files: dict[str, Path] | None = None,
    source_durations_ms: dict[str, int] | None = None,
) -> dict:
    """Validate a CDL against the CDL contract (spec Section 2.4).

    Args:
        cdl: The CDL dict with a "clips" key.
        fps_num: Project FPS numerator.
        fps_den: Project FPS denominator.
        source_files: Optional mapping of angle_id -> source file path for existence check.
        source_durations_ms: Optional mapping of angle_id -> source duration in ms for bounds check.

    Returns:
        {"valid": True} or {"valid": False, "error": "...", "clip_index": N}
    """
    clips = cdl.get("clips", [])

    if not clips:
        return {"valid": False, "error": "CDL has no clips", "clip_index": -1}

    required_keys = {"angle_id", "timeline_in_ms", "src_in_ms", "dur_ms"}

    for i, clip in enumerate(clips):
        # Required fields
        missing = required_keys - set(clip.keys())
        if missing:
            return {
                "valid": False,
                "error": f"clip {i} missing required fields: {sorted(missing)}",
                "clip_index": i,
            }

        # Type check
        for key in ("timeline_in_ms", "src_in_ms", "dur_ms"):
            if not isinstance(clip[key], int):
                return {
                    "valid": False,
                    "error": f"clip {i}: {key} must be an integer, got {type(clip[key]).__name__}",
                    "clip_index": i,
                }

        # Positive values
        if clip["dur_ms"] <= 0:
            return {
                "valid": False,
                "error": f"clip {i}: dur_ms must be positive, got {clip['dur_ms']}",
                "clip_index": i,
            }
        if clip["src_in_ms"] < 0:
            return {
                "valid": False,
                "error": f"clip {i}: src_in_ms must be >= 0, got {clip['src_in_ms']}",
                "clip_index": i,
            }
        if clip["timeline_in_ms"] < 0:
            return {
                "valid": False,
                "error": f"clip {i}: timeline_in_ms must be >= 0, got {clip['timeline_in_ms']}",
                "clip_index": i,
            }

        # Frame-exact check: both boundaries of the clip must sit on the
        # canonical frame grid. Checking dur_ms in isolation is wrong at
        # NTSC rates — a span between two canonical boundaries has a
        # duration that is NOT itself a canonical boundary value.
        if not is_frame_exact(clip["timeline_in_ms"], fps_num, fps_den):
            return {
                "valid": False,
                "error": f"clip {i}: timeline_in_ms={clip['timeline_in_ms']} is not on the frame grid for {fps_num}/{fps_den} fps",
                "clip_index": i,
            }
        if not is_frame_exact(clip["timeline_in_ms"] + clip["dur_ms"], fps_num, fps_den):
            return {
                "valid": False,
                "error": f"clip {i}: clip end {clip['timeline_in_ms'] + clip['dur_ms']} (timeline_in_ms + dur_ms) is not on the frame grid for {fps_num}/{fps_den} fps",
                "clip_index": i,
            }
        if not is_frame_exact(clip["src_in_ms"], fps_num, fps_den):
            return {
                "valid": False,
                "error": f"clip {i}: src_in_ms={clip['src_in_ms']} is not an exact frame multiple for {fps_num}/{fps_den} fps",
                "clip_index": i,
            }

    # Sort check
    for i in range(len(clips) - 1):
        if clips[i]["timeline_in_ms"] >= clips[i + 1]["timeline_in_ms"]:
            return {
                "valid": False,
                "error": f"clips out of order: clip {i} timeline_in_ms={clips[i]['timeline_in_ms']} >= clip {i+1} timeline_in_ms={clips[i+1]['timeline_in_ms']}",
                "clip_index": i,
            }

    # Contiguity check
    for i in range(len(clips) - 1):
        expected = clips[i]["timeline_in_ms"] + clips[i]["dur_ms"]
        actual = clips[i + 1]["timeline_in_ms"]
        if expected != actual:
            direction = "gap" if actual > expected else "overlap"
            return {
                "valid": False,
                "error": f"{direction} between clip {i} and {i+1}: expected timeline_in_ms={expected}, got {actual} (diff={actual - expected}ms)",
                "clip_index": i,
            }

    # Source file checks (optional)
    if source_files:
        angle_ids = {clip["angle_id"] for clip in clips}
        for aid in angle_ids:
            if aid not in source_files:
                return {
                    "valid": False,
                    "error": f"angle_id '{aid}' has no source file in project",
                    "clip_index": -1,
                }
            if not source_files[aid].is_file():
                return {
                    "valid": False,
                    "error": f"source file for angle '{aid}' not found: {source_files[aid]}",
                    "clip_index": -1,
                }

    if source_durations_ms:
        for i, clip in enumerate(clips):
            aid = clip["angle_id"]
            if aid in source_durations_ms:
                max_dur = source_durations_ms[aid]
                if clip["src_in_ms"] + clip["dur_ms"] > max_dur:
                    return {
                        "valid": False,
                        "error": f"clip {i}: src_in_ms + dur_ms ({clip['src_in_ms'] + clip['dur_ms']}ms) exceeds source duration ({max_dur}ms) for angle '{aid}'",
                        "clip_index": i,
                    }

    return {"valid": True}
