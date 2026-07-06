from __future__ import annotations

import math
import random
from typing import Any


DEFAULT_CUT_PARAMS: dict[str, Any] = {
    # Direct baseline: cut on the activity edge, not after an editorial delay.
    # Keep only a tiny floor to suppress detector chatter / single-frame glitches.
    "min_shot_ms": 250,
    "overlap_to_wide": True,
    "wide_interval_ms": 0,
    "wide_interval_jitter": 0.3,
    "lead_in_ms": 0,
    "tail_ms": 0,
    "silence_behaviour": "wide",
}


def _frame_round(ms: int, frame_dur_num: int, frame_dur_den: int) -> int:
    """Snap a millisecond value to the nearest whole-frame boundary."""
    numerator = ms * frame_dur_num
    denominator = frame_dur_den * 1000
    nearest_frame = (numerator + denominator // 2) // denominator
    snapped = (nearest_frame * denominator) // frame_dur_num
    return snapped


def _snap_dur(ms: int, frame_dur_num: int, frame_dur_den: int) -> int:
    """Snap a duration in ms to the nearest whole-frame multiple (≥ 1 frame)."""
    numerator = ms * frame_dur_num
    denominator = frame_dur_den * 1000
    frames = (numerator + denominator // 2) // denominator
    if frames < 1:
        frames = 1
    return (frames * denominator) // frame_dur_num


def _merge_same_angle(clips: list[dict[str, Any]]) -> list[dict[str, Any]]:
    """Merge adjacent clips with the same angle_id."""
    merged: list[dict[str, Any]] = []
    for clip in clips:
        if merged and merged[-1]["angle_id"] == clip["angle_id"]:
            prev = merged[-1]
            clip_end = clip["timeline_in_ms"] + clip["dur_ms"]
            prev["dur_ms"] = clip_end - prev["timeline_in_ms"]
        else:
            merged.append(dict(clip))
    return merged


def _enforce_min_shot_ms(clips: list[dict[str, Any]], min_shot_ms: int) -> list[dict[str, Any]]:
    """Enforce minimum shot duration, preferring to extend into the incoming speaker.

    Strategy (applied in a single forward pass over merged clips):
      - If clip ≥ min_shot_ms → keep it.
      - If clip < min_shot_ms:
        - If it shares angle with preceding clip → merge into preceding.
        - If it shares angle with following clip → merge into following.
        - Otherwise → merge into following (incoming speaker preference).
        - First clip that is too short and has a following clip → merge into following.
        - Last clip that is too short → merge into preceding.
        - A single lone clip too short → keep it (nowhere to merge).

    Returns a new list of clips.
    """
    if not clips or min_shot_ms <= 0:
        return list(clips)

    if len(clips) == 1:
        return list(clips)

    def _merge_into_next(clips_list: list, idx: int) -> None:
        """Merge clips[idx] into clips[idx+1] (extend following backward)."""
        orig_following = clips_list[idx + 1]
        orig_end = orig_following["timeline_in_ms"] + orig_following["dur_ms"]
        new_start = clips_list[idx]["timeline_in_ms"]
        clips_list[idx + 1] = {
            "angle_id": orig_following["angle_id"],
            "timeline_in_ms": new_start,
            "dur_ms": orig_end - new_start,
            "reason": orig_following["reason"],
        }

    result: list[dict[str, Any]] = []
    i = 0
    while i < len(clips):
        clip = dict(clips[i])
        if clip["dur_ms"] >= min_shot_ms:
            result.append(clip)
            i += 1
            continue

        same_prev = result and result[-1]["angle_id"] == clip["angle_id"]
        same_next = (i + 1 < len(clips) and clips[i + 1]["angle_id"] == clip["angle_id"])

        if same_prev:
            # Merge into preceding (same angle)
            prev = result[-1]
            prev["dur_ms"] = clip["timeline_in_ms"] + clip["dur_ms"] - prev["timeline_in_ms"]
            i += 1
        elif same_next:
            # Merge into following (same angle)
            _merge_into_next(clips, i)
            i += 1
        elif i == 0:
            # First clip too short → merge into following (incoming speaker)
            _merge_into_next(clips, i)
            i += 1
        elif i == len(clips) - 1:
            # Last clip too short → merge into preceding
            if result:
                prev = result[-1]
                prev["dur_ms"] = clip["timeline_in_ms"] + clip["dur_ms"] - prev["timeline_in_ms"]
            i += 1
        else:
            # Middle clip, no shared angle → merge into following (incoming speaker)
            _merge_into_next(clips, i)
            i += 1

    return result


def _inject_periodic_wides(
    clips: list[dict[str, Any]],
    wide_angle_id: str,
    wide_interval_ms: int,
    wide_interval_jitter: float,
    min_shot_ms: int,
    total_duration_ms: int,
) -> list[dict[str, Any]]:
    """Inject periodic wide-angle shots at roughly wide_interval_ms cadence.

    Args:
        clips: Current clip list.
        wide_angle_id: Angle ID for wide shots.
        wide_interval_ms: Target interval between wide shots.
        wide_interval_jitter: Jitter factor (0..1) applied to interval.
        min_shot_ms: Minimum shot duration to respect.
        total_duration_ms: Total timeline duration.

    Returns:
        New clip list with wide shots inserted (frame-snapping done later).
    """
    if wide_interval_ms <= 0 or wide_angle_id is None or not clips:
        return list(clips)

    # Build a mutable copy
    work = [dict(c) for c in clips]
    wide_dur = 2000  # Default wide shot duration

    # Calculate injection points
    pos = wide_interval_ms
    while pos < total_duration_ms - wide_dur:
        # Apply jitter
        jitter_range = int(wide_interval_ms * wide_interval_jitter)
        if jitter_range > 0:
            pos += random.randint(-jitter_range, jitter_range)
        pos = max(wide_dur, min(pos, total_duration_ms - wide_dur))

        # Find which clip contains this position
        split_idx = None
        for j, clip in enumerate(work):
            start = clip["timeline_in_ms"]
            end = start + clip["dur_ms"]
            if pos > start and pos < end - min_shot_ms:
                split_idx = j
                break

        if split_idx is None:
            pos += wide_interval_ms
            continue

        # Don't inject if the clip is already wide
        if work[split_idx]["angle_id"] == wide_angle_id:
            pos += wide_interval_ms
            continue

        # Split: clip → [pre, wide, post]
        original = work[split_idx]
        pre_dur = pos - original["timeline_in_ms"]
        post_start = pos + wide_dur
        post_dur = (original["timeline_in_ms"] + original["dur_ms"]) - post_start

        # Only inject if neither flank is too short
        if pre_dur < min_shot_ms or post_dur < min_shot_ms:
            pos += wide_interval_ms
            continue

        # Perform the split
        new_clips = []
        new_clips.append({
            "angle_id": original["angle_id"],
            "timeline_in_ms": original["timeline_in_ms"],
            "dur_ms": pre_dur,
            "reason": original["reason"],
        })
        new_clips.append({
            "angle_id": wide_angle_id,
            "timeline_in_ms": pos,
            "dur_ms": wide_dur,
            "reason": "periodic:wide",
        })
        if post_dur > 0:
            new_clips.append({
                "angle_id": original["angle_id"],
                "timeline_in_ms": post_start,
                "dur_ms": post_dur,
                "reason": original["reason"],
            })

        work = work[:split_idx] + new_clips + work[split_idx + 1:]

        pos += wide_interval_ms

    return work


def generate_cdl(
    activity_timeline: list[dict[str, Any]],
    speaker_to_angle: dict[str, str],
    sync_offsets: dict[str, int],
    *,
    wide_angle_id: str | None = None,
    fps_num: int = 24000,
    fps_den: int = 1001,
    params: dict[str, Any] | None = None,
) -> dict[str, Any]:
    """Generate a Cut Decision List from an activity timeline.

    Args:
        activity_timeline: List of {start_ms, end_ms, active: [speaker_label, ...]}.
        speaker_to_angle: Maps speaker_label → angle_id.
        sync_offsets: Maps angle_id → sync_offset_ms.
        wide_angle_id: Angle ID for the wide shot (falls back to first available).
        fps_num, fps_den: Project frame rate for frame snapping.
        params: Rule parameter overrides (see DEFAULT_CUT_PARAMS).

    Returns:
        CDL dict matching spec Section 2.4.
    """
    if not activity_timeline:
        return {
            "version": 1,
            "project_id": "",
            "fps": {"num": fps_num, "den": fps_den},
            "audio": {"channels": []},
            "clips": [],
            "luts": {"active": None},
        }

    # Merge params
    effective = dict(DEFAULT_CUT_PARAMS)
    if params:
        effective.update(params)

    min_shot_ms = effective["min_shot_ms"]
    overlap_to_wide = effective["overlap_to_wide"]
    lead_in_ms = effective["lead_in_ms"]
    tail_ms = effective["tail_ms"]
    silence_behaviour = effective["silence_behaviour"]
    wide_interval_ms = effective["wide_interval_ms"]
    wide_interval_jitter = effective["wide_interval_jitter"]

    # Resolve wide angle
    if wide_angle_id is None:
        all_angles = set(speaker_to_angle.values())
        wide_angle_id = next(iter(all_angles)) if all_angles else None

    # ── Step 1: Determine target angle per activity segment ──────────
    raw_clips: list[dict[str, Any]] = []
    last_angle_id: str | None = None

    for seg in activity_timeline:
        t_start = seg["start_ms"]
        t_end = seg["end_ms"]
        active = seg.get("active", [])

        if len(active) == 1:
            angle_id = speaker_to_angle.get(active[0])
            reason = f"speaker:{active[0]}"
        elif len(active) >= 2 and overlap_to_wide:
            angle_id = wide_angle_id
            reason = "overlap:wide"
        elif len(active) >= 2:
            angle_id = speaker_to_angle.get(active[0])
            reason = f"overlap:{active[0]}"
        else:
            if silence_behaviour == "wide":
                angle_id = wide_angle_id
                reason = "silence:wide"
            else:
                angle_id = last_angle_id
                reason = "silence:hold"

        if angle_id is None:
            continue

        raw_clips.append({
            "angle_id": angle_id,
            "timeline_in_ms": t_start,
            "dur_ms": t_end - t_start,
            "reason": reason,
        })
        last_angle_id = angle_id

    # ── Step 2: Apply lead_in / tail_ms ──────────────────────────────
    if lead_in_ms > 0 or tail_ms > 0:
        adjusted: list[dict[str, Any]] = []
        for i, clip in enumerate(raw_clips):
            t_in = clip["timeline_in_ms"]
            dur = clip["dur_ms"]
            new_in = max(0, t_in - lead_in_ms)
            new_out = t_in + dur + tail_ms

            if adjusted and adjusted[-1]["angle_id"] == clip["angle_id"]:
                adjusted[-1]["dur_ms"] = new_out - adjusted[-1]["timeline_in_ms"]
            else:
                if adjusted and new_in < adjusted[-1]["timeline_in_ms"] + adjusted[-1]["dur_ms"]:
                    prev = adjusted[-1]
                    prev_dur = new_in - prev["timeline_in_ms"]
                    if prev_dur > 0:
                        prev["dur_ms"] = prev_dur
                    else:
                        adjusted.pop()

                dur_ms = new_out - new_in
                if dur_ms > 0:
                    adjusted.append({
                        "angle_id": clip["angle_id"],
                        "timeline_in_ms": new_in,
                        "dur_ms": dur_ms,
                        "reason": clip["reason"],
                    })
        raw_clips = adjusted

    # ── Step 3: Merge adjacent clips with same angle_id ──────────────
    raw_clips = _merge_same_angle(raw_clips)

    # ── Step 4: Anti-jitter — enforce min_shot_ms (incoming-speaker pref) ─
    raw_clips = _enforce_min_shot_ms(raw_clips, min_shot_ms)

    # ── Step 4.5: Re-merge after anti-jitter adjustments ─────────────
    raw_clips = _merge_same_angle(raw_clips)

    # Get total timeline duration for periodic wide
    total_duration = max(
        (c["timeline_in_ms"] + c["dur_ms"] for c in raw_clips),
        default=0,
    )

    # ── Step 4.6: Inject periodic wide shots ─────────────────────────
    if wide_interval_ms > 0 and wide_angle_id:
        raw_clips = _inject_periodic_wides(
            raw_clips, wide_angle_id, wide_interval_ms,
            wide_interval_jitter, min_shot_ms, total_duration,
        )
        raw_clips = _merge_same_angle(raw_clips)
        raw_clips = _enforce_min_shot_ms(raw_clips, min_shot_ms)
        raw_clips = _merge_same_angle(raw_clips)

    # ── Step 5: Frame-snap boundaries ────────────────────────────────
    snapped: list[dict[str, Any]] = []
    for clip in raw_clips:
        t_in = _frame_round(clip["timeline_in_ms"], fps_num, fps_den)
        dur = _snap_dur(clip["dur_ms"], fps_num, fps_den)
        offset = sync_offsets.get(clip["angle_id"], 0)
        src_in = _frame_round(t_in - offset, fps_num, fps_den)

        snapped.append({
            "angle_id": clip["angle_id"],
            "src_in_ms": src_in,
            "timeline_in_ms": t_in,
            "dur_ms": dur,
            "reason": clip["reason"],
        })

    # ── Step 6: Build CDL ────────────────────────────────────────────
    return {
        "version": 1,
        "project_id": "",
        "fps": {"num": fps_num, "den": fps_den},
        "audio": {"channels": list(speaker_to_angle.keys())},
        "clips": snapped,
        "luts": {"active": None},
    }
