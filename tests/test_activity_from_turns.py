from __future__ import annotations

from autoedit.ai.activity_from_turns import activity_from_turns


def _confirmed(start_ms: int, end_ms: int, speaker_id: str, **extra):
    return {
        "start_ms": start_ms,
        "end_ms": end_ms,
        "speaker_id": speaker_id,
        "mapping_status": "confirmed",
        "provenance": "confirmed_mapping",
        "confidence": 0.99,
        **extra,
    }


def test_postgap_r1_general_onset_snap_includes_crossing_word_probe():
    """Every turn onset snaps to an aligned word already in progress."""
    turns = [
        _confirmed(0, 1000, "speaker-a"),
        _confirmed(
            1000,
            2000,
            "speaker-b",
            aligned_words=[{"start_ms": 900, "end_ms": 1100}],
        ),
    ]

    timeline = activity_from_turns(turns, timeline_end_ms=2000)

    assert any(item["start_ms"] == 900 for item in timeline)
    crossing = next(item for item in timeline if item["start_ms"] == 900)
    assert crossing["end_ms"] == 1000
    assert crossing["reason"] == "overlap:wide"
    assert next(item for item in timeline if item["start_ms"] == 1000)["active"] == ["speaker-b"]


def test_postgap_r2_gap_classification_is_order_independent():
    """Caller order cannot manufacture or suppress the post-gap safe-wide state."""
    turns = [
        _confirmed(45998, 46387, "presenter"),
        _confirmed(
            49762,
            60241,
            "interviewee",
            aligned_words=[{"start_ms": 46052, "end_ms": 50053}],
        ),
    ]

    ordered = activity_from_turns(turns, timeline_end_ms=70000)
    reordered = activity_from_turns(list(reversed(turns)), timeline_end_ms=70000)

    assert reordered == ordered
    post_gap = next(item for item in ordered if item["start_ms"] == 46052)
    assert post_gap["safe_wide"] is True
    assert post_gap["reason"] == "low_confidence:wide"
