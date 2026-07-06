from __future__ import annotations

from typing import Any


def select_topic_ranges(
    topic_spans: list[dict[str, Any]],
    *,
    labels: list[str] | None = None,
    exclude_labels: list[str] | None = None,
) -> list[tuple[int, int]]:
    """Select time ranges from topic spans based on inclusion/exclusion.

    Args:
        topic_spans: List of {label, start_ms, end_ms, conciseness, ...} dicts.
        labels: Only include spans whose label is in this list (None = all).
        exclude_labels: Exclude spans whose label is in this list (applied after labels).

    Returns:
        List of (start_ms, end_ms) tuples in chronological order, merged if contiguous.
    """
    selected = []
    for s in topic_spans:
        lbl = s.get("label", "")
        if labels is not None and lbl not in labels:
            continue
        if exclude_labels is not None and lbl in exclude_labels:
            continue
        selected.append((s["start_ms"], s["end_ms"]))

    # Sort and merge contiguous/overlapping ranges
    if not selected:
        return []

    selected.sort()
    merged = [selected[0]]
    for s, e in selected[1:]:
        prev_s, prev_e = merged[-1]
        if s <= prev_e:  # Overlap or contiguous
            merged[-1] = (prev_s, max(prev_e, e))
        else:
            merged.append((s, e))

    return merged


def extract_activity_ranges(
    activity_timeline: list[dict[str, Any]],
    ranges: list[tuple[int, int]],
) -> list[dict[str, Any]]:
    """Extract activity timeline segments that fall within the given ranges.

    Only segments whose ENTIRE duration is inside a range are included
    (no partial overlaps — avoids edge artifacts).
    """
    if not ranges or not activity_timeline:
        return []

    result = []
    for seg in activity_timeline:
        seg_start = seg["start_ms"]
        seg_end = seg["end_ms"]
        for rng_start, rng_end in ranges:
            if seg_start >= rng_start and seg_end <= rng_end:
                result.append(dict(seg))
                break
    return result


def rebase_timeline(
    segments: list[dict[str, Any]],
) -> list[dict[str, Any]]:
    """Shift all timeline segments so the first one starts at 0."""
    if not segments:
        return []

    base = segments[0]["start_ms"]
    return [
        {
            **seg,
            "start_ms": seg["start_ms"] - base,
            "end_ms": seg["end_ms"] - base,
        }
        for seg in segments
    ]


def generate_sub_edit(
    activity_timeline: list[dict[str, Any]],
    topic_spans: list[dict[str, Any]],
    speaker_to_angle: dict[str, str],
    sync_offsets: dict[str, int],
    *,
    wide_angle_id: str | None = None,
    fps_num: int = 24000,
    fps_den: int = 1001,
    cut_params: dict[str, Any] | None = None,
    mode: str = "custom_ranges",
    labels: list[str] | None = None,
    exclude_labels: list[str] | None = None,
    custom_ranges: list[tuple[int, int]] | None = None,
) -> dict[str, Any]:
    """Generate a sub-edit CDL from selected time ranges.

    Args:
        activity_timeline: Full project activity timeline.
        topic_spans: Topic spans with {label, start_ms, end_ms, ...}.
        speaker_to_angle, sync_offsets: See generate_cdl().
        wide_angle_id, fps_num, fps_den, cut_params: See generate_cdl().
        mode: 'by_topics', 'minus_topics', or 'custom_ranges'.
        labels: For 'by_topics' mode, which labels to include.
        exclude_labels: For 'minus_topics' mode, which labels to exclude.
        custom_ranges: For 'custom_ranges' mode, explicit (start_ms, end_ms) list.

    Returns:
        CDL dict for the sub-edit, or None if no ranges selected.
    """
    # Select ranges based on mode
    if mode == "custom_ranges" and custom_ranges:
        ranges = list(custom_ranges)
    elif mode == "by_topics":
        ranges = select_topic_ranges(topic_spans, labels=labels)
    elif mode == "minus_topics":
        ranges = select_topic_ranges(topic_spans, exclude_labels=exclude_labels)
    else:
        ranges = []

    if not ranges:
        return None

    # Extract and rebase
    sub_activity = extract_activity_ranges(activity_timeline, ranges)
    sub_activity = rebase_timeline(sub_activity)

    if not sub_activity:
        return None

    # Generate CDL (lazy import to avoid circular)
    from autoedit.cut_engine import generate_cdl
    return generate_cdl(
        sub_activity,
        speaker_to_angle,
        sync_offsets,
        wide_angle_id=wide_angle_id,
        fps_num=fps_num,
        fps_den=fps_den,
        params=cut_params,
    )


def fill_to_duration(
    ranges: list[tuple[int, int]],
    topic_spans: list[dict[str, Any]],
    target_secs: int,
) -> list[tuple[int, int]]:
    """Extend selected ranges to fill approximately target_secs of content.

    Adds chronologically adjacent spans until the total duration reaches
    the target. Prefers spans already selected; extends outward from the
    first and last selected spans.

    Args:
        ranges: Currently selected (start_ms, end_ms) ranges.
        topic_spans: All available topic spans with conciseness scores.
        target_secs: Target total duration in seconds.

    Returns:
        Extended range list (sorted, merged).
    """
    if not ranges:
        return []

    target_ms = target_secs * 1000
    current_ms = sum(e - s for s, e in ranges)

    if current_ms >= target_ms:
        return ranges

    # Build a pool of unselected spans sorted by start_ms
    selected_set = set(ranges)
    remaining = []
    for s in topic_spans:
        key = (s["start_ms"], s["end_ms"])
        if key not in selected_set:
            remaining.append(s)

    remaining.sort(key=lambda s: (s.get("conciseness", 3), s["start_ms"]))
    # Prefer higher conciseness and earlier positions

    working = list(ranges)
    for s in remaining:
        if current_ms >= target_ms:
            break
        s_start, s_end = s["start_ms"], s["end_ms"]
        dur = s_end - s_start
        working.append((s_start, s_end))
        current_ms += dur

    # Sort and merge
    if not working:
        return ranges

    working.sort()
    merged = [working[0]]
    for s, e in working[1:]:
        prev_s, prev_e = merged[-1]
        if s <= prev_e:
            merged[-1] = (prev_s, max(prev_e, e))
        else:
            merged.append((s, e))

    return merged
