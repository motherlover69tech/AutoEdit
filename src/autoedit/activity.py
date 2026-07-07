from __future__ import annotations

from typing import Any


def compute_activity_timeline(
    channel_intervals: list[dict[str, Any]],
    *,
    total_duration_ms: int | None = None,
) -> list[dict[str, Any]]:
    """Build a contiguous activity timeline from per-channel speaking intervals.

    Args:
        channel_intervals: List of dicts, each with:
            - channel_id: str
            - speaker_label: str
            - intervals: list of {start_ms, end_ms} dicts
        total_duration_ms: If provided, extend timeline to cover this duration.
            If None, timeline covers the max end_ms across all intervals.

    Returns:
        List of {start_ms, end_ms, active: [speaker_label, ...]} dicts.
        Consecutive segments with identical active sets are merged.
    """
    # Collect all time boundary points
    boundaries: set[int] = {0}
    for ch in channel_intervals:
        for ival in ch["intervals"]:
            boundaries.add(ival["start_ms"])
            boundaries.add(ival["end_ms"])

    if total_duration_ms is not None:
        boundaries.add(total_duration_ms)

    # If no intervals, emit a single silent segment
    if len(boundaries) <= 1:
        end = total_duration_ms or 0
        return [{"start_ms": 0, "end_ms": end, "active": []}]

    sorted_bounds = sorted(boundaries)

    # Build interval index per speaker for fast overlap checks
    speaker_intervals: dict[str, list[tuple[int, int, float | None]]] = {}
    speaker_labels: dict[str, str] = {}
    for ch in channel_intervals:
        lid = ch["speaker_label"]
        speaker_labels[ch["channel_id"]] = lid
        intervals_list = [
            (iv["start_ms"], iv["end_ms"], iv.get("mean_db"))
            for iv in ch["intervals"]
        ]
        if intervals_list:
            speaker_intervals[ch["channel_id"]] = intervals_list

    # Build timeline
    timeline: list[dict[str, Any]] = []
    for i in range(len(sorted_bounds) - 1):
        t_start = sorted_bounds[i]
        t_end = sorted_bounds[i + 1]
        if t_start == t_end:
            continue

        active = []
        levels: dict[str, float] = {}
        mid = (t_start + t_end) // 2
        for ch_id, intervals in speaker_intervals.items():
            for s, e, mean_db in intervals:
                if s <= mid < e:
                    label = speaker_labels[ch_id]
                    active.append(label)
                    if mean_db is not None:
                        # Per-speaker level lets the cut engine tell real
                        # simultaneous speech from cross-mic bleed (bleed
                        # sits well below the true speaker's level).
                        levels[label] = float(mean_db)
                    break

        seg: dict[str, Any] = {
            "start_ms": t_start,
            "end_ms": t_end,
            "active": sorted(active),
        }
        if levels:
            seg["levels"] = levels
        timeline.append(seg)

    # Merge consecutive segments with identical active sets
    if not timeline:
        end = total_duration_ms or 0
        return [{"start_ms": 0, "end_ms": end, "active": []}]

    merged = [timeline[0]]
    for seg in timeline[1:]:
        prev = merged[-1]
        if prev["active"] == seg["active"]:
            combined: dict[str, Any] = {
                "start_ms": prev["start_ms"],
                "end_ms": seg["end_ms"],
                "active": prev["active"],
            }
            # Keep the louder reading per speaker across the merged span.
            levels: dict[str, float] = {}
            for part in (prev, seg):
                for spk, db in part.get("levels", {}).items():
                    levels[spk] = max(db, levels[spk]) if spk in levels else db
            if levels:
                combined["levels"] = levels
            merged[-1] = combined
        else:
            merged.append(seg)

    return merged
