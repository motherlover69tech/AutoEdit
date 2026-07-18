import pytest

from autoedit.ai.activity_from_turns import (
    ArtifactImportError,
    activity_from_turns,
    import_artifact,
)
from autoedit.ai.gpu_measurement import GPUSample, summarize_gpu_acceptance, validate_sampling
from autoedit.cut_engine import generate_cdl


def test_unresolved_turn_is_explicit_safe_wide_and_contiguous():
    activity = activity_from_turns(
        [
            {"start_ms": 0, "end_ms": 1000, "speaker_id": "alice", "confidence": 0.9,
             "mapping_status": "confirmed", "provenance": "confirmed_mapping"},
            {"start_ms": 1000, "end_ms": 2000, "speaker_id": None, "confidence": None},
        ],
        timeline_end_ms=2000,
    )
    assert [(item["start_ms"], item["end_ms"]) for item in activity] == [(0, 1000), (1000, 2000)]
    assert activity[1]["safe_wide"] is True
    cdl = generate_cdl(activity, {"alice": "cam-a"}, {"wide": 0}, wide_angle_id="wide")
    assert cdl["clips"][-1]["angle_id"] == "wide"
    assert cdl["clips"][-1]["reason_code"] == "unresolved_speaker"


def test_overlap_is_safe_wide_even_when_below_minimum_shot():
    activity = activity_from_turns(
        [
            {"start_ms": 0, "end_ms": 1000, "speaker_id": "alice", "confidence": 1.0,
             "mapping_status": "confirmed", "provenance": "confirmed_mapping"},
            {"start_ms": 350, "end_ms": 650, "speaker_id": "bob", "confidence": 1.0,
             "mapping_status": "confirmed", "provenance": "confirmed_mapping"},
        ],
        timeline_end_ms=1000,
    )
    assert any(item["mapping_status"] == "unresolved" for item in activity)
    cdl = generate_cdl(activity, {"alice": "cam-a", "bob": "cam-b"}, {}, wide_angle_id="wide")
    assert [clip["angle_id"] for clip in cdl["clips"]] == ["cam-a", "wide", "cam-a"]


def test_low_confidence_is_not_collapsed_into_a_closeup():
    activity = activity_from_turns(
        [
            {"start_ms": 0, "end_ms": 1000, "speaker_id": "alice", "confidence": 0.95,
             "mapping_status": "confirmed", "provenance": "confirmed_mapping"},
            {"start_ms": 1000, "end_ms": 1100, "speaker_id": "bob", "confidence": 0.1,
             "mapping_status": "confirmed", "provenance": "confirmed_mapping"},
            {"start_ms": 1100, "end_ms": 2000, "speaker_id": "alice", "confidence": 0.95,
             "mapping_status": "confirmed", "provenance": "confirmed_mapping"},
        ],
        timeline_end_ms=2000,
        confidence_threshold=0.5,
    )
    cdl = generate_cdl(activity, {"alice": "cam-a", "bob": "cam-b"}, {}, wide_angle_id="wide")
    assert [clip["angle_id"] for clip in cdl["clips"]] == ["cam-a", "wide", "cam-a"]
    assert cdl["clips"][1]["reason_code"] == "low_confidence"


def test_confirmed_activity_preserves_worker_confidence():
    activity = activity_from_turns(
        [{"start_ms": 0, "end_ms": 1000, "speaker_id": "alice", "confidence": 0.6,
          "mapping_status": "confirmed", "provenance": "confirmed_mapping"}],
        timeline_end_ms=1000,
        confidence_threshold=0.5,
    )
    assert activity[0]["confidence"] == 0.6


def test_suggested_mapping_can_never_be_closeup_authority():
    activity = activity_from_turns(
        [{
            "start_ms": 0,
            "end_ms": 1000,
            "speaker_id": "alice",
            "mapping_status": "suggested",
            "provenance": "suggested_mapping",
        }],
        timeline_end_ms=1000,
    )
    assert activity[0]["active"] == []
    assert activity[0]["reason"] == "unresolved:wide"


def test_import_artifact_rejects_malformed_payload_before_projection():
    with pytest.raises(ArtifactImportError, match="invalid AI artifact"):
        import_artifact({"schema_version": "1.0"})


def test_out_of_bounds_turn_is_rejected_instead_of_clipped():
    try:
        activity_from_turns(
            [{"start_ms": -1, "end_ms": 100, "speaker_id": "alice"}],
            timeline_end_ms=1000,
        )
    except ValueError as exc:
        assert "within the master timeline" in str(exc)
    else:
        raise AssertionError("expected strict bounds rejection")


def test_whisperx_activity_requires_a_real_wide_angle():
    activity = activity_from_turns(
        [{"start_ms": 0, "end_ms": 1000, "speaker_id": "alice"}],
        timeline_end_ms=1000,
    )
    try:
        generate_cdl(activity, {"alice": "cam-a"}, {})
    except ValueError as exc:
        assert "wide angle is required" in str(exc)
    else:
        raise AssertionError("expected fail-closed missing-wide rejection")


def test_gpu_summary_uses_ten_percent_or_two_gib_headroom():
    samples = [
        GPUSample(0, 32768, 1000, "baseline"),
        GPUSample(250, 32768, 30000, "overlap", ("whisperx", "dots")),
    ]
    result = summarize_gpu_acceptance(samples)
    assert result["peak_used_mib"] == 30000
    assert result["required_headroom_mib"] == 3277
    assert result["verdict"] == "FAIL"


def test_gpu_sampler_rejects_large_gaps():
    try:
        validate_sampling([GPUSample(0, 100, 1, "a"), GPUSample(501, 100, 1, "b")])
    except ValueError as exc:
        assert "gap" in str(exc)
    else:
        raise AssertionError("expected sampler gap failure")


def test_safe_wide_cannot_be_overridden_by_hold_policy():
    activity = [{
        "start_ms": 0, "end_ms": 120, "active": [], "safe_wide": True,
        "source": "whisperx", "mapping_status": "unresolved", "reason": "unresolved:wide",
    }]
    cdl = generate_cdl(
        activity, {}, {}, wide_angle_id="wide",
        params={"overlap_to_wide": False, "min_shot_ms": 0},
    )
    assert cdl["clips"][0]["angle_id"] == "wide"


def test_missing_confirmation_metadata_is_not_closeup_authority():
    activity = activity_from_turns(
        [{"start_ms": 0, "end_ms": 1000, "speaker_id": "alice", "confidence": 0.9}],
        timeline_end_ms=1000,
    )
    assert activity[0]["active"] == []
    assert activity[0]["mapping_status"] == "unresolved"


def test_confidence_boundary_is_preserved_when_projecting():
    activity = activity_from_turns(
        [
            {"start_ms": 0, "end_ms": 500, "speaker_id": "alice", "confidence": 0.9,
             "mapping_status": "confirmed", "provenance": "confirmed_mapping"},
            {"start_ms": 500, "end_ms": 1000, "speaker_id": "alice", "confidence": 0.6,
             "mapping_status": "confirmed", "provenance": "confirmed_mapping"},
        ], timeline_end_ms=1000, confidence_threshold=0.5,
    )
    assert [(item["start_ms"], item["end_ms"], item["confidence"]) for item in activity] == [
        (0, 500, 0.9), (500, 1000, 0.6)
    ]


def test_empty_or_unverified_artifact_import_fails_closed():
    with pytest.raises(ArtifactImportError, match="invalid AI artifact|non-empty"):
        import_artifact({"schema_version": "1.0", "run_id": "run-empty"})
