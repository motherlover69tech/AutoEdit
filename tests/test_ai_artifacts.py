from __future__ import annotations

import hashlib
import json
from datetime import UTC, datetime
from pathlib import Path

import pytest
from pydantic import ValidationError

from autoedit.ai.artifacts import AIArtifactStore, ArtifactIntegrityError
from autoedit.ai.contracts import AIResultArtifact


def _sha(path: Path) -> str:
    return hashlib.sha256(path.read_bytes()).hexdigest()


def _artifact(project: Path, *, run_id: str = "run-0001") -> AIResultArtifact:
    source = project / "audio" / "speaker-a.wav"
    analysis = project / "audio" / "ai" / "analysis.wav"
    return AIResultArtifact.model_validate(
        {
            "schema_version": "1.0",
            "run_id": run_id,
            "created_at": datetime.now(UTC).isoformat(),
            "status": "completed",
            "timeline_origin_ms": 0,
            "timeline_end_ms": 2_000,
            "sources": [
                {
                    "source_id": "speaker-a",
                    "relative_path": "audio/speaker-a.wav",
                    "sha256": _sha(source),
                    "duration_ms": 2_000,
                    "sample_rate": 48_000,
                    "channels": 1,
                    "sync_offset_ms": 0,
                }
            ],
            "analysis_audio": {
                "relative_path": "audio/ai/analysis.wav",
                "sha256": _sha(analysis),
                "strategy": "isolated_lav",
                "duration_ms": 2_000,
                "sample_rate": 16_000,
                "channels": 1,
            },
            "models": [
                {
                    "task": "asr",
                    "provider": "whisperx",
                    "model_id": "large-v3",
                    "version": "3.8.6",
                    "compute_type": "float16",
                }
            ],
            "segments": [
                {
                    "segment_id": "seg-1",
                    "start_ms": 100,
                    "end_ms": 900,
                    "text": "Hello world",
                    "words": [
                        {
                            "text": "Hello",
                            "start_ms": 100,
                            "end_ms": 400,
                            "confidence": 0.98,
                        },
                        {
                            "text": "world",
                            "start_ms": 450,
                            "end_ms": 900,
                            "confidence": 0.95,
                        },
                    ],
                }
            ],
            "diarization_turns": [
                {
                    "turn_id": "turn-1",
                    "diarizer_speaker_id": "SPEAKER_00",
                    "start_ms": 80,
                    "end_ms": 920,
                    "confidence": 0.9,
                    "overlap": False,
                }
            ],
            "speaker_mappings": [
                {
                    "diarizer_speaker_id": "SPEAKER_00",
                    "speaker_id": "speaker-a",
                    "status": "suggested",
                    "confidence": 0.84,
                    "evidence": ["isolated-channel-overlap"],
                }
            ],
            "warnings": [],
        }
    )


def _project(tmp_path: Path) -> Path:
    project = tmp_path / "project"
    (project / "audio" / "ai").mkdir(parents=True)
    (project / "audio" / "speaker-a.wav").write_bytes(b"source-audio")
    (project / "audio" / "ai" / "analysis.wav").write_bytes(b"analysis-audio")
    return project


def test_artifact_round_trips_through_last_known_good_store(tmp_path: Path):
    project = _project(tmp_path)
    store = AIArtifactStore(project)
    artifact = _artifact(project)

    published = store.publish(artifact)

    assert published == project / "audio" / "ai" / "v1" / "result.json"
    assert store.load_last_good() == artifact
    assert (project / "audio" / "ai" / "v1" / "runs" / "run-0001.json").is_file()


def test_failed_run_does_not_replace_last_known_good(tmp_path: Path):
    project = _project(tmp_path)
    store = AIArtifactStore(project)
    original = _artifact(project)
    store.publish(original)

    store.record_failure(
        run_id="run-0002",
        stage="diarization",
        error_code="worker_unavailable",
        message="GPU worker did not become ready",
    )

    assert store.load_last_good() == original
    failure = json.loads(
        (project / "audio" / "ai" / "v1" / "failures" / "run-0002.json").read_text()
    )
    assert failure["stage"] == "diarization"
    assert failure["error_code"] == "worker_unavailable"


def test_source_hash_mismatch_cannot_replace_last_known_good(tmp_path: Path):
    project = _project(tmp_path)
    store = AIArtifactStore(project)
    original = _artifact(project)
    store.publish(original)
    (project / "audio" / "speaker-a.wav").write_bytes(b"tampered")

    with pytest.raises(ArtifactIntegrityError, match="hash mismatch"):
        store.publish(original.model_copy(update={"run_id": "run-0002"}))

    assert store.load_last_good() == original


def test_artifact_rejects_path_traversal(tmp_path: Path):
    project = _project(tmp_path)
    artifact = _artifact(project)
    payload = artifact.model_dump(mode="json")
    payload["sources"][0]["relative_path"] = "../outside.wav"

    with pytest.raises(ValidationError, match="confined relative path"):
        AIResultArtifact.model_validate(payload)


def test_artifact_rejects_word_outside_segment(tmp_path: Path):
    project = _project(tmp_path)
    payload = _artifact(project).model_dump(mode="json")
    payload["segments"][0]["words"][0]["start_ms"] = 50

    with pytest.raises(ValidationError, match="word timestamps must be within segment"):
        AIResultArtifact.model_validate(payload)


def test_artifact_rejects_turn_beyond_master_timeline(tmp_path: Path):
    project = _project(tmp_path)
    payload = _artifact(project).model_dump(mode="json")
    payload["diarization_turns"][0]["end_ms"] = 2_001

    with pytest.raises(ValidationError, match="master timeline"):
        AIResultArtifact.model_validate(payload)


def test_artifact_rejects_unknown_fields(tmp_path: Path):
    project = _project(tmp_path)
    payload = _artifact(project).model_dump(mode="json")
    payload["unversioned_guess"] = True

    with pytest.raises(ValidationError, match="Extra inputs are not permitted"):
        AIResultArtifact.model_validate(payload)


def test_artifact_rejects_naive_created_at(tmp_path: Path):
    project = _project(tmp_path)
    payload = _artifact(project).model_dump(mode="json")
    payload["created_at"] = "2026-07-14T01:00:00"

    with pytest.raises(ValidationError, match="timezone-aware"):
        AIResultArtifact.model_validate(payload)


@pytest.mark.parametrize(
    ("section", "message"),
    [
        ("sources", "source IDs must be unique"),
        ("segments", "segment IDs must be unique"),
        ("diarization_turns", "diarization turn IDs must be unique"),
        ("overlaps", "overlap IDs must be unique"),
        ("speaker_turns", "speaker turn IDs must be unique"),
    ],
)
def test_artifact_rejects_duplicate_record_ids(tmp_path: Path, section: str, message: str):
    project = _project(tmp_path)
    payload = _artifact_with_resolved_turn(project)
    payload[section].append(dict(payload[section][0]))

    with pytest.raises(ValidationError, match=message):
        AIResultArtifact.model_validate(payload)


def test_artifact_rejects_overlap_without_temporal_support_from_each_speaker(tmp_path: Path):
    project = _project(tmp_path)
    payload = _artifact_with_resolved_turn(project)
    payload["diarization_turns"][1].update(start_ms=700, end_ms=800)

    with pytest.raises(ValidationError, match="covered by each listed speaker"):
        AIResultArtifact.model_validate(payload)


def test_resolved_speaker_turn_requires_matching_turn_and_mapping(tmp_path: Path):
    project = _project(tmp_path)
    payload = _artifact(project).model_dump(mode="json")
    payload["speaker_mappings"] = [
        {
            "diarizer_speaker_id": "SPEAKER_00",
            "speaker_id": "speaker-a",
            "status": "confirmed",
        }
    ]
    payload["speaker_turns"] = [
        {
            "turn_id": "resolved-1",
            "source_turn_id": "turn-1",
            "diarizer_speaker_id": "SPEAKER_00",
            "speaker_id": "speaker-a",
            "start_ms": 100,
            "end_ms": 900,
            "provenance": "confirmed_mapping",
        }
    ]

    artifact = AIResultArtifact.model_validate(payload)
    assert artifact.speaker_turns[0].speaker_id == "speaker-a"

    payload["speaker_turns"][0]["speaker_id"] = "invented-speaker"
    with pytest.raises(ValidationError, match="resolved speaker mapping"):
        AIResultArtifact.model_validate(payload)


@pytest.mark.parametrize("invalid_value", [1.5, "100", True])
@pytest.mark.parametrize(
    ("section", "field"),
    [
        (None, "timeline_origin_ms"),
        (None, "timeline_end_ms"),
        ("sources", "duration_ms"),
        ("sources", "sync_offset_ms"),
        ("analysis_audio", "duration_ms"),
        ("segments", "start_ms"),
        ("segments", "end_ms"),
        ("words", "start_ms"),
        ("words", "end_ms"),
        ("diarization_turns", "start_ms"),
        ("diarization_turns", "end_ms"),
        ("overlaps", "start_ms"),
        ("overlaps", "end_ms"),
        ("speaker_turns", "start_ms"),
        ("speaker_turns", "end_ms"),
    ],
)
def test_artifact_rejects_non_integer_timeline_values(
    tmp_path: Path,
    section: str | None,
    field: str,
    invalid_value: object,
):
    project = _project(tmp_path)
    payload = _artifact_with_resolved_turn(project)
    if section is None:
        payload[field] = invalid_value
    elif section == "analysis_audio":
        payload[section][field] = invalid_value
    elif section == "words":
        payload["segments"][0]["words"][0][field] = invalid_value
    else:
        payload[section][0][field] = invalid_value

    with pytest.raises(ValidationError):
        AIResultArtifact.model_validate(payload)


def test_artifact_store_rejects_symlinked_output_root(tmp_path: Path):
    project = _project(tmp_path)
    external = tmp_path / "external"
    external.mkdir()
    artifact_root = project / "audio" / "ai" / "v1"
    artifact_root.symlink_to(external, target_is_directory=True)

    with pytest.raises(ArtifactIntegrityError, match="output path escapes project root"):
        AIArtifactStore(project).publish(_artifact(project))

    assert list(external.iterdir()) == []


def test_failure_records_are_immutable(tmp_path: Path):
    project = _project(tmp_path)
    store = AIArtifactStore(project)
    first_path = store.record_failure(
        run_id="run-failed",
        stage="asr",
        error_code="worker_error",
        message="first failure",
    )
    first_bytes = first_path.read_bytes()

    with pytest.raises(ArtifactIntegrityError, match="failure run_id.*already exists"):
        store.record_failure(
            run_id="run-failed",
            stage="diarization",
            error_code="decode_error",
            message="second failure",
        )

    assert first_path.read_bytes() == first_bytes


def test_speaker_mapping_must_reference_observed_diarizer_speaker(tmp_path: Path):
    project = _project(tmp_path)
    payload = _artifact(project).model_dump(mode="json")
    payload["speaker_mappings"].append(
        {
            "diarizer_speaker_id": "SPEAKER_99",
            "speaker_id": None,
            "status": "unresolved",
        }
    )

    with pytest.raises(ValidationError, match="observed diarizer speaker"):
        AIResultArtifact.model_validate(payload)


def test_resolved_turn_provenance_must_match_mapping_status(tmp_path: Path):
    project = _project(tmp_path)
    payload = _artifact_with_resolved_turn(project)
    payload["speaker_mappings"][0]["status"] = "suggested"
    payload["speaker_turns"][0]["provenance"] = "confirmed_mapping"

    with pytest.raises(ValidationError, match="provenance must match"):
        AIResultArtifact.model_validate(payload)


def test_duplicate_speaker_mapping_is_rejected(tmp_path: Path):
    project = _project(tmp_path)
    payload = _artifact(project).model_dump(mode="json")
    payload["speaker_mappings"].append(
        {
            "diarizer_speaker_id": "SPEAKER_00",
            "speaker_id": "speaker-b",
            "status": "confirmed",
            "confidence": 0.7,
            "evidence": ["conflicting-operator-label"],
        }
    )

    with pytest.raises(ValidationError, match="mapping diarizer IDs must be unique"):
        AIResultArtifact.model_validate(payload)


@pytest.mark.parametrize(
    ("source_turn_id", "diarizer_speaker_id"),
    [("missing-turn", "SPEAKER_00"), ("turn-2", "SPEAKER_00")],
)
def test_resolved_turn_requires_matching_source_turn(
    tmp_path: Path,
    source_turn_id: str,
    diarizer_speaker_id: str,
):
    project = _project(tmp_path)
    payload = _artifact_with_resolved_turn(project)
    payload["speaker_turns"][0]["source_turn_id"] = source_turn_id
    payload["speaker_turns"][0]["diarizer_speaker_id"] = diarizer_speaker_id

    with pytest.raises(ValidationError, match="reference its diarization turn"):
        AIResultArtifact.model_validate(payload)


def test_resolved_turn_cannot_reference_unresolved_mapping(tmp_path: Path):
    project = _project(tmp_path)
    payload = _artifact_with_resolved_turn(project)
    payload["speaker_mappings"][0] = {
        "diarizer_speaker_id": "SPEAKER_00",
        "speaker_id": None,
        "status": "unresolved",
        "confidence": 0.31,
        "evidence": ["identity-ambiguous"],
    }

    with pytest.raises(ValidationError, match="resolved speaker mapping"):
        AIResultArtifact.model_validate(payload)


def test_speaker_identity_metadata_and_uncertainty_round_trip(tmp_path: Path):
    project = _project(tmp_path)
    artifact = AIResultArtifact.model_validate(_artifact_with_resolved_turn(project))
    round_tripped = AIResultArtifact.model_validate_json(artifact.model_dump_json())

    confirmed = round_tripped.speaker_mappings[0]
    unresolved = round_tripped.speaker_mappings[1]
    resolved = round_tripped.speaker_turns[0]
    overlap = round_tripped.overlaps[0]

    assert confirmed.confidence == 0.91
    assert confirmed.evidence == ["operator-confirmed"]
    assert unresolved.status == "unresolved"
    assert unresolved.speaker_id is None
    assert resolved.human_label == "Presenter"
    assert resolved.confidence == 0.88
    assert resolved.provenance == "confirmed_mapping"
    assert overlap.diarizer_speaker_ids == ["SPEAKER_00", "SPEAKER_01"]
    assert overlap.start_ms == 500
    assert overlap.end_ms == 600
    assert round_tripped.diarization_turns[1].overlap is True


@pytest.mark.parametrize("symlink_parent", ["v1", "failures"])
def test_failure_output_rejects_symlinked_parent(
    tmp_path: Path,
    symlink_parent: str,
):
    project = _project(tmp_path)
    external = tmp_path / f"external-{symlink_parent}"
    external.mkdir()
    v1_root = project / "audio" / "ai" / "v1"
    if symlink_parent == "v1":
        v1_root.symlink_to(external, target_is_directory=True)
    else:
        v1_root.mkdir()
        (v1_root / "failures").symlink_to(external, target_is_directory=True)

    with pytest.raises(ArtifactIntegrityError, match="output path escapes project root"):
        AIArtifactStore(project).record_failure(
            run_id="escaped-failure",
            stage="diarization",
            error_code="decode_error",
            message="must remain confined",
        )

    assert list(external.iterdir()) == []


def test_publish_rejects_symlinked_runs_parent(tmp_path: Path):
    project = _project(tmp_path)
    external = tmp_path / "external-runs"
    external.mkdir()
    v1_root = project / "audio" / "ai" / "v1"
    v1_root.mkdir()
    (v1_root / "runs").symlink_to(external, target_is_directory=True)

    with pytest.raises(ArtifactIntegrityError, match="output path escapes project root"):
        AIArtifactStore(project).publish(_artifact(project))

    assert list(external.iterdir()) == []
    assert not (v1_root / "result.json").exists()


def _artifact_with_resolved_turn(project: Path) -> dict:
    payload = _artifact(project).model_dump(mode="json")
    payload["overlaps"] = [
        {
            "overlap_id": "overlap-1",
            "diarizer_speaker_ids": ["SPEAKER_00", "SPEAKER_01"],
            "start_ms": 500,
            "end_ms": 600,
        }
    ]
    payload["diarization_turns"].append(
        {
            "turn_id": "turn-2",
            "diarizer_speaker_id": "SPEAKER_01",
            "start_ms": 500,
            "end_ms": 600,
            "overlap": True,
        }
    )
    payload["speaker_mappings"] = [
        {
            "diarizer_speaker_id": "SPEAKER_00",
            "speaker_id": "speaker-a",
            "status": "confirmed",
            "confidence": 0.91,
            "evidence": ["operator-confirmed"],
        },
        {
            "diarizer_speaker_id": "SPEAKER_01",
            "speaker_id": None,
            "status": "unresolved",
        },
    ]
    payload["speaker_turns"] = [
        {
            "turn_id": "resolved-1",
            "source_turn_id": "turn-1",
            "diarizer_speaker_id": "SPEAKER_00",
            "speaker_id": "speaker-a",
            "human_label": "Presenter",
            "start_ms": 100,
            "end_ms": 900,
            "confidence": 0.88,
            "provenance": "confirmed_mapping",
        }
    ]
    return payload
