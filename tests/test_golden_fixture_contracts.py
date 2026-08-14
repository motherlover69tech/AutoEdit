from __future__ import annotations

import json
import os
from pathlib import Path

import pytest
from pydantic import ValidationError
from autoedit.ai.contracts import AIResultArtifact
from autoedit.ai.golden_fixture import (
    GroundTruth,
    Manifest,
    Approvals,
    RunEvidence,
    WordBoundary,
    bundle_id,
    build_run_evidence,
    sha256_bytes,
    confined_relative_path,
    evaluate_current_run,
    evaluate_fixture_set,
    evaluate_gate_one,
    redacted_result,
    synthetic_cdl,
    synthetic_fixture,
    validate_fixture,
)
from autoedit.ai.golden_fixture_adapter import artifact_words


def test_synthetic_contract_is_deterministic_and_strict():
    first, truth = synthetic_fixture()
    second, _ = synthetic_fixture()
    assert first == second
    parsed = Manifest.model_validate(first)
    assert parsed.fixture_class == "synthetic_contract"
    assert GroundTruth.model_validate(truth).word_boundaries[0].timeline_third == "first"
    with pytest.raises(ValidationError):
        Manifest.model_validate({**first, "revision": "1"})
    with pytest.raises(ValidationError):
        Manifest.model_validate({**first, "unexpected": 1})


def test_confined_paths_reject_escape_and_platform_separators():
    assert confined_relative_path("media/close_1.mp4") == "media/close_1.mp4"
    for value in ("/tmp/x", "../x", "media/../x", "media\\x", ""):
        with pytest.raises(ValueError):
            confined_relative_path(value)


def test_bundle_hash_is_length_delimited():
    assert bundle_id(b"a", b"bc") != bundle_id(b"ab", b"c")
    assert len(bundle_id(b"manifest", b"truth")) == 64


def test_gate_one_selects_actual_thirds_and_checks_both_boundaries():
    words = [
        WordBoundary(word_id="w1", segment_id="s", start_ms=100, end_ms=200,
                     uncertainty="certain", reviewer_decision="accepted", timeline_third="first",
                     anonymous_cluster_id="anon_a", reviewed_start_ms=100, reviewed_end_ms=200),
        WordBoundary(word_id="w2", segment_id="s", start_ms=5000, end_ms=5100,
                     uncertainty="certain", reviewer_decision="accepted", timeline_third="middle",
                     anonymous_cluster_id="anon_b", reviewed_start_ms=5000, reviewed_end_ms=5100),
        WordBoundary(word_id="w3", segment_id="s", start_ms=9000, end_ms=9100,
                     uncertainty="certain", reviewer_decision="accepted", timeline_third="final",
                     anonymous_cluster_id="anon_a", reviewed_start_ms=9000, reviewed_end_ms=9100),
    ]
    result = evaluate_gate_one(words=words, timeline_start_ms=0, timeline_end_ms=10000,
                               fps_num=25, fps_den=1, sync_offset_ms=0)
    assert [item.word_id for item in result] == ["w1", "w2", "w3"]
    assert all(item.start_error_ms == item.end_error_ms == 0 for item in result)
    assert all(item.frame_tolerance_ms == 40 for item in result)


def test_gate_one_compares_candidate_predictions_after_offset_once():
    truth = [
        WordBoundary(word_id="w1", segment_id="s", start_ms=100, end_ms=200,
                     uncertainty="certain", reviewer_decision="accepted", timeline_third="first",
                     reviewed_start_ms=100, reviewed_end_ms=200),
        WordBoundary(word_id="w2", segment_id="s", start_ms=5000, end_ms=5100,
                     uncertainty="certain", reviewer_decision="accepted", timeline_third="middle",
                     reviewed_start_ms=5000, reviewed_end_ms=5100),
        WordBoundary(word_id="w3", segment_id="s", start_ms=9000, end_ms=9100,
                     uncertainty="certain", reviewer_decision="accepted", timeline_third="final",
                     reviewed_start_ms=9000, reviewed_end_ms=9100),
    ]
    predicted = [item.model_copy(update={"start_ms": item.start_ms + 20, "end_ms": item.end_ms + 20}) for item in truth]
    result = evaluate_gate_one(words=truth, predicted_words=predicted, timeline_start_ms=0,
                               timeline_end_ms=10000, fps_num=25, fps_den=1, sync_offset_ms=20)
    assert all(item.start_error_ms == item.end_error_ms == 0 for item in result)
    with pytest.raises(ValueError, match="missing"):
        evaluate_gate_one(words=truth, predicted_words=predicted[:2], timeline_start_ms=0,
                          timeline_end_ms=10000, fps_num=25, fps_den=1)


def test_frame_projection_uses_shared_contract():
    manifest, truth = synthetic_fixture()
    for window in truth["review_windows"]:
        assert window["start_ms"] == round(window["start_frame"] * 1000 / 25)
        assert window["end_ms"] == round(window["end_frame"] * 1000 / 25)


def test_synthetic_cdl_is_explicitly_ineligible():
    cdl = synthetic_cdl()
    assert cdl["synthetic_ineligible"] is True
    assert all("synthetic" in clip["reason_code"] for clip in cdl["clips"])


def test_redaction_drops_sensitive_values_and_bounds_codes():
    result = redacted_result(valid=False, errors=["GOLD_HASH_MISMATCH", "private transcript", "/secret/root"], words=3)
    encoded = json.dumps(result)
    assert "private transcript" not in encoded
    assert "/secret/root" not in encoded
    assert result["errors"] == ["GOLD_HASH_MISMATCH"]


def test_unconfigured_root_is_clean_result(tmp_path: Path, monkeypatch: pytest.MonkeyPatch):
    monkeypatch.delenv("AUTOEDIT_GOLDEN_MEDIA_ROOT", raising=False)
    result = validate_fixture(tmp_path, "fixture_1")
    assert result["errors"] == ["GOLD_ROOT_NOT_CONFIGURED"]
    assert result["valid"] is False


def test_synthetic_fixture_never_becomes_real_acceptance(tmp_path: Path, monkeypatch: pytest.MonkeyPatch):
    monkeypatch.setenv("AUTOEDIT_GOLDEN_MEDIA_ROOT", str(tmp_path))
    package = tmp_path / "fixtures" / "synthetic_contract"
    package.mkdir(parents=True)
    manifest, truth = synthetic_fixture()
    truth_bytes = json.dumps(truth, sort_keys=True).encode()
    manifest["rights"]["review_due_utc"] = "2099-01-01T00:00:00Z"
    manifest["retention"]["rights_review_due_utc"] = "2099-01-01T00:00:00Z"
    # The fixture remains intentionally invalid for acceptance; hashes are not
    # fabricated here, proving that the validator fails closed on placeholders.
    (package / "fixture.manifest.json").write_bytes(json.dumps(manifest).encode())
    (package / "ground_truth.json").write_bytes(truth_bytes)
    (package / "approvals.json").write_text("{}")
    result = validate_fixture(tmp_path, "synthetic_contract")
    assert result["valid"] is False
    assert "GOLD_SCHEMA_INVALID" in result["errors"] or "GOLD_ROOT_UNSAFE" in result["errors"]


def test_real_manifest_requires_audio_assets():
    manifest, _ = synthetic_fixture()
    with pytest.raises(ValidationError, match="program and analysis"):
        Manifest.model_validate({**manifest, "fixture_class": "consent_real"})


def test_ground_truth_must_be_locked():
    _, truth = synthetic_fixture()
    with pytest.raises(ValidationError, match="locked"):
        GroundTruth.model_validate({**truth, "status": "draft", "locked_at_utc": None})


def test_approvals_reject_duplicate_blanket_scopes():
    digest = "0" * 64
    decision = {"decision": "PASS", "decided_at_utc": "2026-01-01T00:00:00Z", "operator_id": "operator", "scope": "consent", "manifest_sha256": digest}
    payload = {"schema_version": "1.0", "fixture_id": "synthetic_contract", "fixture_revision": 1,
               "manifest_sha256": digest, "ground_truth_sha256": digest, "bundle_id": digest,
               "approval_revision": 1, "rights_and_consent_decision": decision,
               "retention_and_backup_decision": decision, "speaker_identity_decisions": [decision, decision],
               "word_truth_decisions": [decision], "editorial_truth_decisions": [decision],
               "overall_fixture_decision": "PASS"}
    with pytest.raises(ValidationError, match="distinct"):
        Approvals.model_validate(payload)


def test_artifact_adapter_uses_exact_segment_indices_and_master_timeline():
    _, truth = synthetic_fixture()
    selected = [WordBoundary.model_validate({**word, "artifact_word_index": index,
        "reviewed_start_ms": word["start_ms"], "reviewed_end_ms": word["end_ms"]})
        for word, index in zip(truth["word_boundaries"], (0, 1, 0))]
    artifact = AIResultArtifact.model_validate({
        "schema_version": "1.0", "run_id": "run_1", "created_at": "2026-01-01T00:00:00Z",
        "status": "completed", "timeline_origin_ms": 0, "timeline_end_ms": 30000,
        "sources": [
            {"source_id": "channel_1", "relative_path": "audio/a.wav", "sha256": "0" * 64, "duration_ms": 30000, "sample_rate": 48000, "channels": 1, "sync_offset_ms": 120},
            {"source_id": "channel_2", "relative_path": "audio/b.wav", "sha256": "1" * 64, "duration_ms": 30000, "sample_rate": 48000, "channels": 1, "sync_offset_ms": -80},
        ],
        "analysis_audio": {"relative_path": "audio/analysis.wav", "sha256": "2" * 64, "strategy": "mono_mix", "duration_ms": 30000, "sample_rate": 16000, "channels": 1},
        "models": [{"task": "asr", "provider": "synthetic", "model_id": "fixture", "version": "1"}],
        "segments": [
            {"segment_id": "segment_1", "start_ms": 1000, "end_ms": 14700, "text": "words", "words": [
                {"text": "word_first", "start_ms": 1000, "end_ms": 1200},
                {"text": "word_middle", "start_ms": 14500, "end_ms": 14700},
            ]},
            {"segment_id": "segment_2", "start_ms": 28000, "end_ms": 28200, "text": "word_final", "words": [
                {"text": "word_final", "start_ms": 28000, "end_ms": 28200},
            ]},
        ],
        "diarization_turns": [
            {"turn_id": "turn_a", "diarizer_speaker_id": "anon_a", "start_ms": 0, "end_ms": 10000},
            {"turn_id": "turn_b", "diarizer_speaker_id": "anon_b", "start_ms": 10000, "end_ms": 20000},
            {"turn_id": "turn_c", "diarizer_speaker_id": "anon_a", "start_ms": 20000, "end_ms": 30000},
        ],
    })
    actual = artifact_words(artifact, selected, source_offsets_ms={"channel_1": 120, "channel_2": -80})
    assert [word.start_ms for word in actual] == [1000, 14500, 28000]
    assert {word.anonymous_cluster_id for word in actual} == {"anon_a", "anon_b"}
    assert all(item.offset_applied_ms == 0 for item in evaluate_gate_one(
        words=selected, predicted_words=actual, timeline_start_ms=0, timeline_end_ms=30000,
        fps_num=25, fps_den=1,
    ))


def _consent_real_bundle():
    """Build a deterministic, valid consent_real manifest/truth/approvals triple."""
    stamp = "2026-01-01T00:00:00Z"
    digest = "0" * 64
    probe = {"codec": "h264", "width": 1920, "height": 1080, "fps_num": 25, "fps_den": 1,
             "duration_ms": 300000, "audio_streams": 1, "audio_channels": 2, "probe_tool": "ffprobe", "probe_version": "6"}
    videos = [{"asset_id": f"asset_{i}", "role": role, "relative_path": f"media/{role}.mp4", "byte_size": 1,
               "sha256": digest, "probe": probe, "coverage_start_ms": 0, "coverage_end_ms": 300000}
              for i, role in enumerate(("close_1", "close_2", "wide"), 1)]
    manifest = {
        "schema_version": "1.0", "fixture_id": "real_fixture", "revision": 1, "fixture_class": "consent_real",
        "status": "locked", "created_at_utc": stamp, "locked_at_utc": stamp, "classification": {},
        "rights": {"legal_record_ref": "legal_1", "consent_status": "active", "rights_basis": "consent",
                   "allowed_purposes": ["speech_recognition_evaluation", "speaker_diarization_evaluation",
                                        "speaker_identity_confirmation", "editorial_cut_evaluation", "bounded_derived_evidence"],
                   "derivative_allowed": True, "model_processing_allowed": True, "redistribution_allowed": False,
                   "approved_at_utc": stamp, "review_due_utc": "2099-01-01T00:00:00Z", "withdrawal_status": "active"},
        "retention": {"rights_review_due_utc": "2099-01-01T00:00:00Z", "raw_media_disposition": "retain",
                      "annotations_disposition": "retain", "run_derived_disposition": "retain",
                      "machine_json_disposition": "retain", "backups_disposition": "retain"},
        "project": {"fps_num": 25, "fps_den": 1, "timeline_origin_ms": 0, "timeline_end_ms": 300000,
                    "sync_offset_convention": "source_ms=master_ms+sync_offset_ms", "master_audio_role": "program_audio_master"},
        "video_assets": videos,
        "speaker_audio_channels": [
            {"channel_id": "channel_1", "source_asset_id": "asset_1", "stream_index": 0, "channel_index": 0,
             "stable_speaker_id": "speaker_1", "sample_rate": 48000, "duration_ms": 300000, "sync_offset_ms": 120, "measurement_ref": "sync_1"},
            {"channel_id": "channel_2", "source_asset_id": "asset_2", "stream_index": 0, "channel_index": 1,
             "stable_speaker_id": "speaker_2", "sample_rate": 48000, "duration_ms": 300000, "sync_offset_ms": -80, "measurement_ref": "sync_2"},
        ],
        "program_audio": {"role": "program_audio", "relative_path": "audio/program.wav", "byte_size": 1,
                          "sha256": digest, "source_asset_ids": ["asset_1", "asset_2", "asset_3"],
                          "derivation_digest": digest, "tool_versions": ["tool-1"], "immutable_fixture_input": True},
        "analysis_audio": {"role": "analysis_audio", "relative_path": "audio/analysis.wav", "byte_size": 1,
                           "sha256": digest, "source_asset_ids": ["asset_1"],
                           "derivation_digest": digest, "tool_versions": ["tool-1"], "immutable_fixture_input": True},
        "annotation_relative_path": "ground_truth.json",
    }
    truth = {
        "schema_version": "1.0", "fixture_id": "real_fixture", "fixture_revision": 1, "manifest_sha256": digest,
        "annotation_revision": 1, "status": "locked", "created_at_utc": stamp, "locked_at_utc": stamp,
        "timeline_basis": "program_audio_master", "fps_num": 25, "fps_den": 1, "timeline_origin_ms": 0,
        "timeline_end_ms": 300000,
        "stable_speakers": [{"speaker_id": "speaker_1", "close_camera_role": "close_1"},
                            {"speaker_id": "speaker_2", "close_camera_role": "close_2"}],
        "word_boundaries": [
            {"word_id": "w_first", "segment_id": "seg_1", "start_ms": 1000, "end_ms": 1200, "uncertainty": "certain",
             "reviewer_decision": "accepted", "timeline_third": "first", "anonymous_cluster_id": "anon_a",
             "artifact_word_index": 0, "reviewed_start_ms": 1000, "reviewed_end_ms": 1200},
            {"word_id": "w_middle", "segment_id": "seg_1", "start_ms": 150000, "end_ms": 150200, "uncertainty": "certain",
             "reviewer_decision": "accepted", "timeline_third": "middle", "anonymous_cluster_id": "anon_b",
             "artifact_word_index": 1, "reviewed_start_ms": 150000, "reviewed_end_ms": 150200},
            {"word_id": "w_final", "segment_id": "seg_2", "start_ms": 298000, "end_ms": 298200, "uncertainty": "certain",
             "reviewer_decision": "accepted", "timeline_third": "final", "anonymous_cluster_id": "anon_a",
             "artifact_word_index": 0, "reviewed_start_ms": 298000, "reviewed_end_ms": 298200},
        ],
        "activity_segments": [{"start_ms": 0, "end_ms": 300000, "active_speaker_ids": ["speaker_1"], "overlap": False,
                               "silence_or_noise": False, "uncertain_or_off_camera": False, "confidence_state": "certain"}],
        "review_windows": [
            {"window_id": "win_1", "category": "solo_1", "start_frame": 0, "end_frame": 125, "start_ms": 0, "end_ms": 5000,
             "expected_active_speaker_ids": ["speaker_1"], "expected_camera_role": "close_1", "expected_reason": "speaking",
             "safety_outcome": "close_1", "uncertainty": "certain"},
        ],
        "label_swap_cases": [],
        "coverage_summary": {"words": 3},
    }
    decision = {"decision": "PASS", "decided_at_utc": stamp, "operator_id": "operator", "scope": "consent",
                "manifest_sha256": digest, "ground_truth_sha256": digest}
    approvals = {
        "schema_version": "1.0", "fixture_id": "real_fixture", "fixture_revision": 1, "manifest_sha256": digest,
        "ground_truth_sha256": digest, "bundle_id": digest, "approval_revision": 1,
        "rights_and_consent_decision": decision, "retention_and_backup_decision": {**decision, "scope": "retention"},
        "speaker_identity_decisions": [{**decision, "scope": "identity_1"}, {**decision, "scope": "identity_2"}],
        "word_truth_decisions": [{**decision, "scope": "word_truth"}],
        "editorial_truth_decisions": [{**decision, "scope": "editorial"}],
        "overall_fixture_decision": "PASS",
    }
    return manifest, truth, approvals


def _candidate_artifact(offsets: dict[str, int] | None = None):
    offsets = offsets or {"channel_1": 120, "channel_2": -80}
    return AIResultArtifact.model_validate({
        "schema_version": "1.0", "run_id": "candidate_run_7", "created_at": "2026-01-01T00:00:00Z",
        "status": "completed", "timeline_origin_ms": 0, "timeline_end_ms": 300000,
        "sources": [
            {"source_id": "channel_1", "relative_path": "audio/a.wav", "sha256": "1" * 64, "duration_ms": 300000,
             "sample_rate": 48000, "channels": 1, "sync_offset_ms": offsets["channel_1"]},
            {"source_id": "channel_2", "relative_path": "audio/b.wav", "sha256": "2" * 64, "duration_ms": 300000,
             "sample_rate": 48000, "channels": 1, "sync_offset_ms": offsets["channel_2"]},
        ],
        "analysis_audio": {"relative_path": "audio/analysis.wav", "sha256": "3" * 64, "strategy": "mono_mix",
                           "duration_ms": 300000, "sample_rate": 16000, "channels": 1},
        "models": [{"task": "asr", "provider": "whisperx", "model_id": "large-v3", "version": "fp16"}],
        "segments": [
            {"segment_id": "seg_1", "start_ms": 0, "end_ms": 200000, "text": "t", "words": [
                {"text": "x", "start_ms": 1000, "end_ms": 1200},
                {"text": "y", "start_ms": 150000, "end_ms": 150200},
            ]},
            {"segment_id": "seg_2", "start_ms": 290000, "end_ms": 300000, "text": "t", "words": [
                {"text": "z", "start_ms": 298000, "end_ms": 298200},
            ]},
        ],
        "diarization_turns": [
            {"turn_id": "turn_a", "diarizer_speaker_id": "anon_a", "start_ms": 0, "end_ms": 100000},
            {"turn_id": "turn_b", "diarizer_speaker_id": "anon_b", "start_ms": 100000, "end_ms": 200000},
            {"turn_id": "turn_c", "diarizer_speaker_id": "anon_a", "start_ms": 200000, "end_ms": 300000},
        ],
    })


def _on_disk_bundle(tmp_path: Path, *, artifact: AIResultArtifact | None = None):
    manifest_data, truth_data, approvals_data = _consent_real_bundle()
    manifest = Manifest.model_validate(manifest_data)
    truth = GroundTruth.model_validate(truth_data)
    approvals = Approvals.model_validate(approvals_data)
    manifest_bytes = manifest.model_dump_json().encode()
    truth_bytes = truth.model_dump_json().encode()
    truth.manifest_sha256 = sha256_bytes(manifest_bytes)
    approvals.manifest_sha256 = sha256_bytes(manifest_bytes)
    approvals.ground_truth_sha256 = sha256_bytes(truth_bytes)
    approvals.bundle_id = bundle_id(manifest_bytes, truth_bytes)
    artifact = artifact or _candidate_artifact()
    run_id = artifact.run_id
    artifact_path = tmp_path / "runs" / run_id / "artifacts" / "candidate.json"
    artifact_path.parent.mkdir(parents=True)
    artifact_path.write_text(artifact.model_dump_json())
    kwargs = {
        "root": tmp_path,
        "manifest": manifest,
        "truth": truth,
        "approvals": approvals,
        "manifest_bytes": manifest_bytes,
        "truth_bytes": truth_bytes,
        "run_id": run_id,
        "source_commit": "commit_abc",
        "worker_image_digest": "4" * 64,
        "runtime_version": "py3.13",
        "compose_render_sha256": "5" * 64,
        "candidate_artifact_relative_path": "artifacts/candidate.json",
    }
    return kwargs, artifact_path


def test_run_evidence_is_built_from_on_disk_candidate_without_authority_fields(tmp_path: Path):
    kwargs, artifact_path = _on_disk_bundle(tmp_path)
    evidence = build_run_evidence(**kwargs)
    payload = evidence.model_dump()

    assert evidence.schema_version == "2.0"
    assert evidence.candidate_artifact_sha256 == sha256_bytes(artifact_path.read_bytes())
    assert evidence.candidate_artifact_mtime_ns == artifact_path.stat().st_mtime_ns
    assert not {"status", "results", "gate_status", "artifact_valid", "evidence_digest", "construction_proof"}.intersection(payload)


def test_run_evidence_rejects_nonexistent_or_malformed_on_disk_artifact(tmp_path: Path):
    kwargs, artifact_path = _on_disk_bundle(tmp_path)
    artifact_path.unlink()
    with pytest.raises(ValueError, match="missing|unreadable"):
        build_run_evidence(**kwargs)
    artifact_path.parent.mkdir(parents=True, exist_ok=True)
    artifact_path.write_text("{}")
    with pytest.raises(ValueError, match="valid artifact"):
        build_run_evidence(**kwargs)


@pytest.mark.parametrize("run_id", ["../outside", "../../outside", "/tmp/outside"])
def test_run_evidence_rejects_unconfined_run_id_before_filesystem_access(
    tmp_path: Path, run_id: str
):
    kwargs, _artifact_path = _on_disk_bundle(tmp_path)
    with pytest.raises(ValueError, match="run id"):
        build_run_evidence(**{**kwargs, "run_id": run_id})


def test_run_evidence_rejects_symlinked_runs_root(tmp_path: Path):
    kwargs, _artifact_path = _on_disk_bundle(tmp_path)
    runs_root = tmp_path / "runs"
    outside = tmp_path.parent / f"{tmp_path.name}-outside-runs"
    runs_root.rename(outside)
    runs_root.symlink_to(outside, target_is_directory=True)
    with pytest.raises(ValueError, match="linked|confined"):
        build_run_evidence(**kwargs)


def test_run_evidence_rejects_wrong_on_disk_source_offsets(tmp_path: Path):
    artifact = _candidate_artifact(offsets={"channel_1": 999, "channel_2": -80})
    kwargs, _artifact_path = _on_disk_bundle(tmp_path, artifact=artifact)
    with pytest.raises(ValueError, match="candidate source offsets"):
        build_run_evidence(**kwargs)


def test_validator_rejects_wrong_stored_byte_digest_and_timestamp(tmp_path: Path):
    from autoedit.ai.golden_fixture import _recompute_run_acceptance

    kwargs, artifact_path = _on_disk_bundle(tmp_path)
    evidence = build_run_evidence(**kwargs)
    evidence_path = artifact_path.parent.parent / "run-evidence.json"
    evidence_path.write_text(evidence.model_dump_json())
    assert _recompute_run_acceptance(
        evidence_path, evidence, kwargs["manifest"], kwargs["truth"],
        kwargs["manifest_bytes"], kwargs["truth_bytes"],
    ) is True

    wrong_digest = evidence.model_copy(update={"candidate_artifact_sha256": "f" * 64})
    assert _recompute_run_acceptance(
        evidence_path, wrong_digest, kwargs["manifest"], kwargs["truth"],
        kwargs["manifest_bytes"], kwargs["truth_bytes"],
    ) is False

    stat_before = artifact_path.stat()
    os.utime(
        artifact_path,
        ns=(stat_before.st_atime_ns, stat_before.st_mtime_ns + 1_000_000_000),
    )
    assert artifact_path.stat().st_mtime_ns != stat_before.st_mtime_ns
    assert _recompute_run_acceptance(
        evidence_path, evidence, kwargs["manifest"], kwargs["truth"],
        kwargs["manifest_bytes"], kwargs["truth_bytes"],
    ) is False


def test_forged_all_pass_fields_are_not_part_of_evidence_contract(tmp_path: Path):
    kwargs, _artifact_path = _on_disk_bundle(tmp_path)
    forged = build_run_evidence(**kwargs).model_dump()
    forged.update({
        "status": "PASS",
        "results": ["PASS"],
        "gate_status": {"TEST-AIGPU1-007": "PASS"},
        "construction_proof": "public-secret-that-self-authenticates",
        "artifact_valid": True,
    })
    with pytest.raises(ValidationError):
        RunEvidence.model_validate(forged)


def test_fixture_set_requires_explicit_distinct_selection(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
):
    monkeypatch.setattr(
        "autoedit.ai.golden_fixture.validate_fixture",
        lambda *_args, **_kwargs: {
            "valid": True,
            "fixture_class": "consent_real",
            "errors": [],
            "counts": {},
        },
    )
    assert evaluate_fixture_set(tmp_path, ["a", "b", "c"])["valid"] is True
    assert evaluate_fixture_set(tmp_path, ["a", "a", "c"])["valid"] is False


def test_current_run_requires_one_validator_recomputed_selected_run(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
):
    kwargs, artifact_path = _on_disk_bundle(tmp_path)
    package = tmp_path / "fixtures" / "real_fixture"
    package.mkdir(parents=True)
    (package / "fixture.manifest.json").write_bytes(kwargs["manifest_bytes"])
    (package / "ground_truth.json").write_bytes(kwargs["truth_bytes"])
    evidence = build_run_evidence(**kwargs)
    evidence_path = artifact_path.parent.parent / "run-evidence.json"
    evidence_path.write_text(evidence.model_dump_json())
    for path in (tmp_path / "runs", evidence_path.parent, evidence_path):
        path.chmod(0o700 if path.is_dir() else 0o600)
    monkeypatch.setattr(
        "autoedit.ai.golden_fixture.validate_fixture",
        lambda *_args, **_kwargs: {"valid": True},
    )
    assert evaluate_current_run(tmp_path, "real_fixture", evidence.run_id) is True
    assert evaluate_current_run(tmp_path, "real_fixture", "other-run") is False

    duplicate_dir = tmp_path / "runs" / "duplicate-run"
    duplicate_dir.mkdir()
    duplicate_dir.chmod(0o700)
    duplicate_artifact = duplicate_dir / "artifacts" / "candidate.json"
    duplicate_artifact.parent.mkdir()
    duplicate_artifact.parent.chmod(0o700)
    duplicate_payload = _candidate_artifact().model_copy(update={"run_id": "duplicate-run"})
    duplicate_artifact.write_text(duplicate_payload.model_dump_json())
    duplicate_artifact.chmod(0o600)
    duplicate_evidence = build_run_evidence(**{**kwargs, "run_id": "duplicate-run"})
    duplicate_evidence_path = duplicate_dir / "run-evidence.json"
    duplicate_evidence_path.write_text(duplicate_evidence.model_dump_json())
    duplicate_evidence_path.chmod(0o600)
    assert evaluate_current_run(tmp_path, "real_fixture", evidence.run_id) is False
