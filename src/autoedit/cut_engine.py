from __future__ import annotations

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
    # ── Temporal angle-resolution rules ───────────────────────────────
    # These stop the cut being driven by every raw VAD edge. Set all four
    # to 0 to recover the old fully-instantaneous behaviour.
    #
    # Cross-mic bleed rejection: when both channels read "active" but one
    # speaker is at least this many dB louder, treat it as that speaker
    # solo, not an overlap. Bleed typically sits 10-20 dB below the true
    # speaker, so 8 dB separates bleed from genuine simultaneous speech.
    "dominance_db": 8.0,
    # Genuine overlaps shorter than this do not cut to wide; the current
    # speaker holds the frame. Covers interruption onsets and backchannel
    # ("mm-hm", "yeah") that briefly overlap the main speaker.
    "overlap_min_ms": 900,
    # A solo remark by speaker B sandwiched inside speaker A's turn, no
    # longer than this, does not steal the shot ("right", "exactly").
    "interject_max_ms": 1200,
    # Rapid exchange → wide: when speakers trade turns quickly (each
    # change within exchange_gap_ms of the previous, at least
    # exchange_min_turns changes in the chain), hold the wide shot for
    # the middle of the exchange instead of ping-ponging singles.
    "exchange_gap_ms": 2500,
    "exchange_min_turns": 3,
}


def _resolve_activity_segments(
    activity_timeline: list[dict[str, Any]],
    effective: dict[str, Any],
) -> list[dict[str, Any]]:
    """Resolve raw activity segments into editorial intents.

    Turns per-VAD-edge activity into a list of
    ``{start_ms, end_ms, kind, speaker, reason}`` intents where kind is
    "solo" | "overlap" | "silence". Four passes, each individually
    disableable by zeroing its parameter:

    1. Dominance (dominance_db): an "overlap" where one speaker is much
       louder than the others is cross-mic bleed, not simultaneous speech
       — resolve it to the dominant speaker solo.
    2. Short-overlap absorption (overlap_min_ms): genuine overlaps shorter
       than the threshold hold the current speaker instead of flashing wide.
    3. Interjection suppression (interject_max_ms): a brief solo remark by
       B inside A's turn does not steal the shot.
    4. Rapid-exchange detection (exchange_gap_ms / exchange_min_turns):
       quick back-and-forth goes wide for the middle of the exchange.
    """
    dominance_db = float(effective.get("dominance_db") or 0)
    overlap_min_ms = int(effective.get("overlap_min_ms") or 0)
    interject_max_ms = int(effective.get("interject_max_ms") or 0)
    exchange_gap_ms = int(effective.get("exchange_gap_ms") or 0)
    exchange_min_turns = int(effective.get("exchange_min_turns") or 0)

    # ── Pass 1: classify, applying dominance to demote bleed ─────────
    intents: list[dict[str, Any]] = []
    for seg in activity_timeline:
        active = seg.get("active", [])
        levels = seg.get("levels", {}) or {}
        if len(active) == 0:
            kind, speaker = "silence", None
        elif len(active) == 1:
            kind, speaker = "solo", active[0]
        else:
            kind, speaker = "overlap", None
            if dominance_db > 0 and levels:
                known = [(levels[a], a) for a in active if a in levels]
                if len(known) == len(active) and len(known) >= 2:
                    known.sort(reverse=True)
                    if known[0][0] - known[1][0] >= dominance_db:
                        kind, speaker = "solo", known[0][1]
        intent: dict[str, Any] = {
            "start_ms": seg["start_ms"],
            "end_ms": seg["end_ms"],
            "kind": kind,
            "speaker": speaker,
        }
        if kind == "overlap":
            intent["active"] = list(active)
        intents.append(intent)
    intents = _merge_intents(intents)

    # ── Pass 2: absorb short overlaps into the current speaker ───────
    if overlap_min_ms > 0:
        for i, it in enumerate(intents):
            if it["kind"] != "overlap":
                continue
            if it["end_ms"] - it["start_ms"] >= overlap_min_ms:
                continue
            # Hold the previous solo speaker; at the head of the timeline
            # fall forward to the next solo speaker instead.
            holder = None
            for j in range(i - 1, -1, -1):
                if intents[j]["kind"] == "solo":
                    holder = intents[j]["speaker"]
                    break
            if holder is None:
                for j in range(i + 1, len(intents)):
                    if intents[j]["kind"] == "solo":
                        holder = intents[j]["speaker"]
                        break
            if holder is not None:
                it["kind"], it["speaker"] = "solo", holder
        intents = _merge_intents(intents)

    # ── Pass 3: suppress sandwiched interjections ─────────────────────
    if interject_max_ms > 0:
        changed = True
        while changed:
            changed = False
            for i in range(1, len(intents) - 1):
                cur = intents[i]
                if cur["kind"] != "solo":
                    continue
                if cur["end_ms"] - cur["start_ms"] > interject_max_ms:
                    continue
                prev, nxt = intents[i - 1], intents[i + 1]
                if (
                    prev["kind"] == "solo" and nxt["kind"] == "solo"
                    and prev["speaker"] == nxt["speaker"]
                    and prev["speaker"] != cur["speaker"]
                ):
                    cur["speaker"] = prev["speaker"]
                    changed = True
            if changed:
                intents = _merge_intents(intents)

    # ── Pass 4: rapid exchange → wide ─────────────────────────────────
    if exchange_min_turns > 0 and exchange_gap_ms > 0:
        # Speaker-change points between consecutive solo runs (silence or
        # overlap between them still counts as one change if the gap
        # between the runs is small enough to chain).
        solos = [
            (idx, it) for idx, it in enumerate(intents) if it["kind"] == "solo"
        ]
        changes: list[tuple[int, int, int]] = []  # (time, left_idx, right_idx)
        for (ia, a), (ib, b) in zip(solos, solos[1:]):
            if a["speaker"] != b["speaker"]:
                changes.append((b["start_ms"], ia, ib))

        # Chain changes whose spacing is within exchange_gap_ms.
        chain: list[tuple[int, int, int]] = []
        chains: list[list[tuple[int, int, int]]] = []
        for ch in changes:
            if chain and ch[0] - chain[-1][0] > exchange_gap_ms:
                chains.append(chain)
                chain = []
            chain.append(ch)
        if chain:
            chains.append(chain)

        for chain in chains:
            if len(chain) < exchange_min_turns:
                continue
            # Wide from the first change to the last change: the opening
            # speaker keeps their lead-in shot, the closing speaker keeps
            # the tail; everything traded in between goes wide.
            first_t, last_t = chain[0][0], chain[-1][0]
            for it in intents:
                if it["kind"] == "solo" and it["start_ms"] >= first_t and it["end_ms"] <= last_t:
                    it["kind"], it["speaker"] = "overlap", None
                    it["reason"] = "exchange:wide"
        intents = _merge_intents(intents)

    return intents


def _merge_intents(intents: list[dict[str, Any]]) -> list[dict[str, Any]]:
    """Merge adjacent intents with identical kind+speaker."""
    merged: list[dict[str, Any]] = []
    for it in intents:
        if (
            merged
            and merged[-1]["kind"] == it["kind"]
            and merged[-1]["speaker"] == it["speaker"]
        ):
            merged[-1]["end_ms"] = it["end_ms"]
            if it.get("reason") and not merged[-1].get("reason"):
                merged[-1]["reason"] = it["reason"]
        else:
            merged.append(dict(it))
    return merged


def _frame_round(ms: int, frame_dur_num: int, frame_dur_den: int) -> int:
    """Snap a millisecond value to the canonical nearest-frame boundary.

    Delegates to the validator's frame_boundary_ms so the cut engine and
    the CDL validator agree on the single integer-ms representation of
    every frame boundary (round-half-up). The previous floor-division here
    disagreed with the validator at NTSC rates and made 23.976/29.97/24fps
    CDLs unvalidatable.
    """
    from autoedit.cdl_validator import frame_boundary_ms, ms_to_frames

    return frame_boundary_ms(
        ms_to_frames(ms, frame_dur_num, frame_dur_den), frame_dur_num, frame_dur_den
    )


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

    # ── Step 1: Resolve activity into editorial intents, then angles ──
    # The resolver applies bleed dominance, short-overlap absorption,
    # interjection suppression, and rapid-exchange detection before any
    # angle is chosen, so the cut is driven by editorial turns rather
    # than raw VAD edges.
    intents = _resolve_activity_segments(activity_timeline, effective)

    raw_clips: list[dict[str, Any]] = []
    last_angle_id: str | None = None

    for it in intents:
        t_start = it["start_ms"]
        t_end = it["end_ms"]

        if it["kind"] == "solo":
            angle_id = speaker_to_angle.get(it["speaker"])
            reason = f"speaker:{it['speaker']}"
        elif it["kind"] == "overlap" and overlap_to_wide:
            angle_id = wide_angle_id
            reason = it.get("reason") or "overlap:wide"
        elif it["kind"] == "overlap":
            # overlap_to_wide disabled: hold the previous angle if we have
            # one, otherwise fall back to the first mapped speaker.
            if last_angle_id is not None:
                angle_id = last_angle_id
                reason = "overlap:hold"
            else:
                first_speaker = (it.get("active") or [None])[0]
                angle_id = speaker_to_angle.get(first_speaker) if first_speaker else None
                reason = f"overlap:{first_speaker}"
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
    # Snap boundary POSITIONS (each clip's start, plus the final end) and
    # derive durations from consecutive snapped boundaries. Snapping
    # timeline_in_ms and dur_ms independently rounds them in different
    # directions (round(a) + round(b) != round(a + b)), which produced
    # ±1-frame gaps/overlaps between adjacent clips, failed CDL
    # validation, and blocked FCPXML/EDL export.
    snapped: list[dict[str, Any]] = []
    if raw_clips:
        boundaries = [
            _frame_round(clip["timeline_in_ms"], fps_num, fps_den)
            for clip in raw_clips
        ]
        last = raw_clips[-1]
        final_end = _frame_round(
            last["timeline_in_ms"] + last["dur_ms"], fps_num, fps_den
        )
        for i, clip in enumerate(raw_clips):
            t_in = boundaries[i]
            t_out = boundaries[i + 1] if i + 1 < len(raw_clips) else final_end
            dur = t_out - t_in
            if dur <= 0:
                # Clip collapsed to zero frames after snapping; the next
                # clip starts at the same boundary, so contiguity holds.
                continue
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
