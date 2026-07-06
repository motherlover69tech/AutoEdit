from __future__ import annotations

from typing import Any


def _interval_overlap(a_start: int, a_end: int, b_start: int, b_end: int) -> int:
    """Return overlap duration in ms between two intervals."""
    start = max(a_start, b_start)
    end = min(a_end, b_end)
    return max(0, end - start)


def build_summary(
    topics_data: list[dict[str, Any]],
    speaking_intervals: list[dict[str, Any]],
    activity_timeline: list[dict[str, Any]] | None = None,
) -> dict[str, Any]:
    """Build a summary.json from topics, speaking intervals, and activity.

    Args:
        topics_data: List of {label, colour, spans: [{start_ms, end_ms, conciseness, summary}]}.
        speaking_intervals: List of {channel_id, speaker_label, start_ms, end_ms}.
        activity_timeline: Optional activity timeline for overlap/silence totals.

    Returns:
        Dict matching the summary.json contract from spec Section 5.5.
    """
    # Build topics section
    topic_results = []
    for topic in topics_data:
        speaker_time: dict[str, int] = {}
        for si in speaking_intervals:
            spk = si.get("speaker_label", "unknown")
            overlap_ms = 0
            for span in topic.get("spans", []):
                overlap_ms += _interval_overlap(
                    si["start_ms"], si["end_ms"],
                    span["start_ms"], span["end_ms"],
                )
            if overlap_ms > 0:
                speaker_time[spk] = speaker_time.get(spk, 0) + overlap_ms

        topic_results.append({
            "label": topic["label"],
            "colour": topic.get("colour", "#000000"),
            "spans": topic.get("spans", []),
            "speaker_time_ms": speaker_time,
        })

    # Build totals
    total_speaker_time: dict[str, int] = {}
    for topic in topic_results:
        for spk, ms in topic["speaker_time_ms"].items():
            total_speaker_time[spk] = total_speaker_time.get(spk, 0) + ms

    talk_overlap_ms = 0
    silence_ms = 0
    if activity_timeline:
        for seg in activity_timeline:
            active = seg.get("active", [])
            dur = seg["end_ms"] - seg["start_ms"]
            if len(active) >= 2:
                talk_overlap_ms += dur
            elif len(active) == 0:
                silence_ms += dur

    return {
        "topics": topic_results,
        "totals": {
            "speaker_time_ms": total_speaker_time,
            "talk_overlap_ms": talk_overlap_ms,
            "silence_ms": silence_ms,
        },
    }
