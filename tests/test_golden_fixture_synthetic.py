from __future__ import annotations

from autoedit.ai.golden_fixture import synthetic_cdl, synthetic_fixture
from autoedit.cdl_validator import validate_cdl


def test_generated_metadata_covers_speaker_overlap_silence_and_offsets():
    manifest, truth = synthetic_fixture()
    assert [c["sync_offset_ms"] for c in manifest["speaker_audio_channels"]] == [120, -80]
    assert any(segment["overlap"] for segment in truth["activity_segments"])
    assert any(segment["silence_or_noise"] for segment in truth["activity_segments"])
    assert {word["timeline_third"] for word in truth["word_boundaries"]} == {"first", "middle", "final"}


def test_generated_cdl_is_frame_valid_but_not_real_acceptance():
    result = validate_cdl(synthetic_cdl(), 25, 1)
    assert result["valid"] is True
    assert synthetic_cdl()["synthetic_ineligible"] is True


def test_label_swap_is_anonymous_only():
    _, truth = synthetic_fixture()
    swap = truth["label_swap_cases"][0]
    assert swap["expected_camera_invariant"] is True
    assert set(swap["anonymous_permutation"]) == {"anon_a", "anon_b"}
    assert set(swap["stable_speaker_ids"]) == {"speaker_1", "speaker_2"}
