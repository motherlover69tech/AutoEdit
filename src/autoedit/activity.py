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
    speaker_intervals: dict[str, list[tuple[int, int]]] = {}
    speaker_labels: dict[str, str] = {}
    for ch in channel_intervals:
        lid = ch["speaker_label"]
        speaker_labels[ch["channel_id"]] = lid
        intervals_list = [(iv["start_ms"], iv["end_ms"]) for iv in ch["intervals"]]
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
        mid = (t_start + t_end) // 2
        for ch_id, intervals in speaker_intervals.items():
            for s, e in intervals:
                if s <= mid < e:
                    active.append(speaker_labels[ch_id])
                    break

        timeline.append({
            "start_ms": t_start,
            "end_ms": t_end,
            "active": sorted(active),
        })

    # Merge consecutive segments with identical active sets
    if not timeline:
        end = total_duration_ms or 0
        return [{"start_ms": 0, "end_ms": end, "active": []}]

    merged = [timeline[0]]
    for seg in timeline[1:]:
        prev = merged[-1]
        if prev["active"] == seg["active"]:
            merged[-1] = {
                "start_ms": prev["start_ms"],
                "end_ms": seg["end_ms"],
                "active": prev["active"],
            }
        else:
            merged.append(seg)

    return merged
