from __future__ import annotations

from datetime import UTC, datetime

import pytest
from pydantic import ValidationError

from autoedit.ai.contracts import AIResultArtifact, DiarizationTurn, SpeakerMapping
from autoedit.ai.speaker_mapping import (
    ConfirmedSpeakerMapping,
    PriorConfirmedSpeaker,
    SpeakerIdentityEvidence,
    resolve_speaker_mappings,
)


def _turn(turn_id: str, label: str, start_ms: int) -> DiarizationTurn:
    return DiarizationTurn(
        turn_id=turn_id,
        diarizer_speaker_id=label,
        start_ms=start_ms,
        end_ms=start_ms + 500,
    )


def _voice(label: str, speaker: str, turn: str, confidence: float = 0.95) -> SpeakerIdentityEvidence:
    return SpeakerIdentityEvidence(
        evidence_id=f"voice-{label}-{speaker}-{turn}",
        kind="voice",
        diarizer_speaker_id=label,
        candidate_speaker_id=speaker,
        source_turn_ids=[turn],
        confidence=confidence,
        detail="voice-embedding match",
    )


def test_high_confidence_voice_evidence_from_multiple_turns_suggests_identity():
    turns = [_turn("turn-2", "SPEAKER_00", 600), _turn("turn-1", "SPEAKER_00", 0)]

    result = resolve_speaker_mappings(
        turns,
        evidence=[
            _voice("SPEAKER_00", "speaker-alice", "turn-2", 0.92),
            _voice("SPEAKER_00", "speaker-alice", "turn-1", 0.96),
        ],
    )

    assert result.mappings == [
        SpeakerMapping(
            diarizer_speaker_id="SPEAKER_00",
            speaker_id="speaker-alice",
            status="suggested",
            confidence=0.94,
            evidence=[
                "voice-SPEAKER_00-speaker-alice-turn-1",
                "voice-SPEAKER_00-speaker-alice-turn-2",
            ],
        )
    ]
    assert [turn.source_turn_id for turn in result.resolved_turns] == ["turn-1", "turn-2"]
    assert {turn.provenance for turn in result.resolved_turns} == {"suggested_mapping"}


def test_one_turn_or_low_confidence_voice_match_does_not_suggest():
    turns = [_turn("t1", "S0", 0), _turn("t2", "S0", 600)]

    one_turn = resolve_speaker_mappings(turns, evidence=[_voice("S0", "alice", "t1")])
    low_confidence = resolve_speaker_mappings(
        turns,
        evidence=[_voice("S0", "alice", "t1", 0.81), _voice("S0", "alice", "t2", 0.84)],
    )

    assert one_turn.mappings[0].status == "unresolved"
    assert low_confidence.mappings[0].status == "unresolved"
    assert one_turn.resolved_turns == low_confidence.resolved_turns == []


def test_transcript_context_is_audited_but_never_establishes_identity_alone():
    turns = [_turn("t1", "S0", 0), _turn("t2", "S0", 600)]
    context = SpeakerIdentityEvidence(
        evidence_id="context-1",
        kind="transcript_context",
        diarizer_speaker_id="S0",
        candidate_speaker_id="alice",
        source_turn_ids=["t1", "t2"],
        confidence=1.0,
        detail="speaker says their name is Alice",
    )

    result = resolve_speaker_mappings(turns, evidence=[context])

    assert result.mappings[0].status == "unresolved"
    assert result.mappings[0].speaker_id is None
    assert result.mappings[0].evidence == ["context-1"]
    assert result.resolved_turns == []


def test_prior_confirmation_requires_current_voice_validation_and_handles_label_swap():
    turns = [
        _turn("alice-1", "SPEAKER_01", 0),
        _turn("alice-2", "SPEAKER_01", 600),
        _turn("bob-1", "SPEAKER_00", 1200),
        _turn("bob-2", "SPEAKER_00", 1800),
    ]
    priors = [
        PriorConfirmedSpeaker(
            speaker_id="alice", human_label="Alice", prior_diarizer_speaker_id="SPEAKER_00"
        ),
        PriorConfirmedSpeaker(
            speaker_id="bob", human_label="Bob", prior_diarizer_speaker_id="SPEAKER_01"
        ),
    ]
    evidence = [
        _voice("SPEAKER_01", "alice", "alice-1"),
        _voice("SPEAKER_01", "alice", "alice-2"),
        _voice("SPEAKER_00", "bob", "bob-1"),
        _voice("SPEAKER_00", "bob", "bob-2"),
    ]

    result = resolve_speaker_mappings(turns, evidence=evidence, prior_confirmed=priors)

    assert [(m.diarizer_speaker_id, m.speaker_id, m.status) for m in result.mappings] == [
        ("SPEAKER_00", "bob", "confirmed"),
        ("SPEAKER_01", "alice", "confirmed"),
    ]
    assert {turn.provenance for turn in result.resolved_turns} == {"prior_confirmed_mapping"}
    assert {turn.speaker_id: turn.human_label for turn in result.resolved_turns} == {
        "alice": "Alice",
        "bob": "Bob",
    }


def test_prior_confirmation_without_current_voice_evidence_stays_unresolved():
    result = resolve_speaker_mappings(
        [_turn("t1", "S0", 0)],
        prior_confirmed=[PriorConfirmedSpeaker(speaker_id="alice", prior_diarizer_speaker_id="S0")],
    )

    assert result.mappings[0].status == "unresolved"
    assert result.resolved_turns == []


def test_conflicting_qualifying_voice_candidates_remain_unresolved():
    turns = [_turn("t1", "S0", 0), _turn("t2", "S0", 600)]
    evidence = [
        _voice("S0", "alice", "t1"),
        _voice("S0", "alice", "t2"),
        _voice("S0", "bob", "t1", 0.94),
        _voice("S0", "bob", "t2", 0.94),
    ]

    result = resolve_speaker_mappings(turns, evidence=evidence)

    assert result.mappings[0].status == "unresolved"
    assert result.mappings[0].speaker_id is None
    assert result.mappings[0].evidence == sorted(item.evidence_id for item in evidence)
    assert result.resolved_turns == []


def test_current_operator_confirmation_resolves_with_confirmed_provenance():
    turns = [_turn("t1", "S0", 0)]
    confirmed = ConfirmedSpeakerMapping(
        diarizer_speaker_id="S0", speaker_id="alice", human_label="Alice"
    )

    result = resolve_speaker_mappings(turns, confirmed=[confirmed])

    assert result.mappings[0].status == "confirmed"
    assert result.mappings[0].confidence == 1.0
    assert result.resolved_turns[0].provenance == "confirmed_mapping"
    assert result.resolved_turns[0].human_label == "Alice"


def test_conflicting_operator_confirmations_do_not_resolve():
    result = resolve_speaker_mappings(
        [_turn("t1", "S0", 0)],
        confirmed=[
            ConfirmedSpeakerMapping(diarizer_speaker_id="S0", speaker_id="alice"),
            ConfirmedSpeakerMapping(diarizer_speaker_id="S0", speaker_id="bob"),
        ],
    )

    assert result.mappings[0].status == "unresolved"
    assert result.resolved_turns == []


def test_one_stable_identity_cannot_resolve_to_multiple_diarizer_labels():
    turns = [
        _turn("s0-1", "S0", 0),
        _turn("s0-2", "S0", 600),
        _turn("s1-1", "S1", 1200),
        _turn("s1-2", "S1", 1800),
    ]

    operator_conflict = resolve_speaker_mappings(
        turns,
        confirmed=[
            ConfirmedSpeakerMapping(diarizer_speaker_id="S0", speaker_id="alice"),
            ConfirmedSpeakerMapping(diarizer_speaker_id="S1", speaker_id="alice"),
        ],
    )
    voice_conflict = resolve_speaker_mappings(
        turns,
        evidence=[
            _voice("S0", "alice", "s0-1"),
            _voice("S0", "alice", "s0-2"),
            _voice("S1", "alice", "s1-1"),
            _voice("S1", "alice", "s1-2"),
        ],
    )

    for result in (operator_conflict, voice_conflict):
        assert all(mapping.status == "unresolved" for mapping in result.mappings)
        assert all(mapping.speaker_id is None for mapping in result.mappings)
        assert result.resolved_turns == []


def test_output_is_deterministic_and_includes_every_observed_label():
    turns = [_turn("z", "S1", 900), _turn("b", "S0", 500), _turn("a", "S0", 0)]

    result = resolve_speaker_mappings(turns)

    assert [mapping.diarizer_speaker_id for mapping in result.mappings] == ["S0", "S1"]
    assert all(mapping.status == "unresolved" for mapping in result.mappings)


def test_evidence_must_reference_matching_observed_turns():
    turns = [_turn("t1", "S0", 0)]

    with pytest.raises(ValueError, match="matching observed turn"):
        resolve_speaker_mappings(turns, evidence=[_voice("S0", "alice", "missing")])

    with pytest.raises(ValueError, match="matching observed turn"):
        resolve_speaker_mappings(turns, evidence=[_voice("S1", "alice", "t1")])


def test_models_are_strict_and_evidence_turn_ids_are_unique():
    with pytest.raises(ValidationError, match="Extra inputs are not permitted"):
        PriorConfirmedSpeaker.model_validate({"speaker_id": "alice", "unknown": True})

    with pytest.raises(ValidationError, match="source_turn_ids must be unique"):
        SpeakerIdentityEvidence(
            evidence_id="e1",
            kind="voice",
            diarizer_speaker_id="S0",
            candidate_speaker_id="alice",
            source_turn_ids=["t1", "t1"],
            confidence=0.9,
            detail="duplicate",
        )


def test_operator_confirmation_conflicting_with_qualifying_voice_stays_unresolved():
    turns = [_turn("t1", "S0", 0), _turn("t2", "S0", 600)]

    result = resolve_speaker_mappings(
        turns,
        confirmed=[ConfirmedSpeakerMapping(diarizer_speaker_id="S0", speaker_id="alice")],
        evidence=[_voice("S0", "bob", "t1"), _voice("S0", "bob", "t2")],
    )

    assert result.mappings[0].status == "unresolved"
    assert result.mappings[0].speaker_id is None
    assert result.resolved_turns == []


def test_duplicate_evidence_ids_are_rejected():
    turns = [_turn("t1", "S0", 0), _turn("t2", "S0", 600)]
    first = _voice("S0", "alice", "t1")
    duplicate = _voice("S0", "alice", "t2").model_copy(
        update={"evidence_id": first.evidence_id}
    )

    with pytest.raises(ValueError, match="evidence IDs must be unique"):
        resolve_speaker_mappings(turns, evidence=[first, duplicate])


def test_conflicting_prior_records_for_stable_identity_are_rejected():
    priors = [
        PriorConfirmedSpeaker(
            speaker_id="alice",
            human_label="Alice",
            prior_diarizer_speaker_id="S0",
        ),
        PriorConfirmedSpeaker(
            speaker_id="alice",
            human_label="Alicia",
            prior_diarizer_speaker_id="S1",
        ),
    ]

    with pytest.raises(ValueError, match="prior confirmed speaker IDs must be unique"):
        resolve_speaker_mappings([_turn("t1", "S0", 0)], prior_confirmed=priors)


def test_resolver_output_validates_in_artifact_for_all_mapping_provenance_states():
    turns = [
        _turn("confirmed-1", "S0", 0),
        _turn("prior-1", "S1", 600),
        _turn("prior-2", "S1", 1200),
        _turn("suggested-1", "S2", 1800),
        _turn("suggested-2", "S2", 2400),
        _turn("unresolved-1", "S3", 3000),
    ]
    resolution = resolve_speaker_mappings(
        turns,
        confirmed=[
            ConfirmedSpeakerMapping(
                diarizer_speaker_id="S0", speaker_id="alice", human_label="Alice"
            )
        ],
        prior_confirmed=[PriorConfirmedSpeaker(speaker_id="bob", human_label="Bob")],
        evidence=[
            _voice("S1", "bob", "prior-1"),
            _voice("S1", "bob", "prior-2"),
            _voice("S2", "carol", "suggested-1"),
            _voice("S2", "carol", "suggested-2"),
        ],
    )

    artifact = AIResultArtifact.model_validate(
        {
            "schema_version": "1.0",
            "run_id": "resolver-integration",
            "created_at": datetime.now(UTC),
            "status": "completed",
            "timeline_origin_ms": 0,
            "timeline_end_ms": 4000,
            "sources": [
                {
                    "source_id": "program",
                    "relative_path": "audio/program.wav",
                    "sha256": "0" * 64,
                    "duration_ms": 4000,
                    "sample_rate": 48000,
                    "channels": 1,
                    "sync_offset_ms": 0,
                }
            ],
            "analysis_audio": {
                "relative_path": "audio/ai/analysis.wav",
                "sha256": "1" * 64,
                "strategy": "mono_mix",
                "duration_ms": 4000,
                "sample_rate": 16000,
                "channels": 1,
            },
            "models": [
                {
                    "task": "speaker_mapping",
                    "provider": "autoedit",
                    "model_id": "deterministic-resolver",
                    "version": "1",
                }
            ],
            "diarization_turns": [turn.model_dump() for turn in turns],
            "speaker_mappings": [mapping.model_dump() for mapping in resolution.mappings],
            "speaker_turns": [turn.model_dump() for turn in resolution.resolved_turns],
        }
    )

    assert {turn.provenance for turn in artifact.speaker_turns} == {
        "confirmed_mapping",
        "prior_confirmed_mapping",
        "suggested_mapping",
    }
    assert {turn.diarizer_speaker_id for turn in artifact.speaker_turns} == {"S0", "S1", "S2"}
    unresolved = next(
        mapping for mapping in artifact.speaker_mappings if mapping.diarizer_speaker_id == "S3"
    )
    assert unresolved.status == "unresolved"
