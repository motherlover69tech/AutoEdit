"""Deterministic speaker-identity evidence resolution.

Diarizer speaker labels are run-local anonymous cluster identifiers.  This
module therefore resolves them only from evidence tied to turns in the current
run.  Transcript-context evidence is retained for audit but is never strong
enough to establish an identity.
"""

from __future__ import annotations

from collections import defaultdict
from typing import Annotated, Literal, Sequence

from pydantic import Field, StrictFloat, StringConstraints, model_validator

from autoedit.ai.contracts import (
    Confidence,
    DiarizationTurn,
    ResolvedSpeakerTurn,
    SafeId,
    SpeakerMapping,
    StrictContract,
)

EvidenceDetail = Annotated[str, StringConstraints(min_length=1, max_length=255)]
StrictConfidence = Annotated[StrictFloat, Field(ge=0.0, le=1.0)]


class SpeakerIdentityEvidence(StrictContract):
    """Auditable identity evidence associated with current diarization turns."""

    evidence_id: SafeId
    kind: Literal["voice", "transcript_context"]
    diarizer_speaker_id: SafeId
    candidate_speaker_id: SafeId
    source_turn_ids: Annotated[list[SafeId], Field(min_length=1)]
    confidence: StrictConfidence
    detail: EvidenceDetail

    @model_validator(mode="after")
    def validate_unique_turns(self) -> "SpeakerIdentityEvidence":
        if len(set(self.source_turn_ids)) != len(self.source_turn_ids):
            raise ValueError("source_turn_ids must be unique")
        return self


class ConfirmedSpeakerMapping(StrictContract):
    """An operator confirmation made against a label in the current run."""

    diarizer_speaker_id: SafeId
    speaker_id: SafeId
    human_label: Annotated[str, StringConstraints(min_length=1, max_length=128)] | None = None


class PriorConfirmedSpeaker(StrictContract):
    """A stable project identity confirmed in an earlier run.

    ``prior_diarizer_speaker_id`` is audit metadata only and is deliberately
    not used by the resolver. Anonymous labels can swap between runs.
    """

    speaker_id: SafeId
    human_label: Annotated[str, StringConstraints(min_length=1, max_length=128)] | None = None
    prior_diarizer_speaker_id: SafeId | None = None


class SpeakerMappingResolution(StrictContract):
    mappings: list[SpeakerMapping] = Field(default_factory=list)
    resolved_turns: list[ResolvedSpeakerTurn] = Field(default_factory=list)


class SpeakerResolutionPolicy(StrictContract):
    """Conservative thresholds for deterministic automatic resolution."""

    minimum_voice_confidence: StrictConfidence = 0.85
    minimum_voice_turns: Annotated[int, Field(strict=True, ge=2)] = 2
    minimum_voice_evidence: Annotated[int, Field(strict=True, ge=2)] = 2


def resolve_speaker_mappings(
    turns: Sequence[DiarizationTurn],
    *,
    evidence: Sequence[SpeakerIdentityEvidence] = (),
    confirmed: Sequence[ConfirmedSpeakerMapping] = (),
    prior_confirmed: Sequence[PriorConfirmedSpeaker] = (),
    policy: SpeakerResolutionPolicy | None = None,
) -> SpeakerMappingResolution:
    """Resolve current anonymous labels into stable project speaker IDs.

    Resolution order is conservative rather than probabilistic:

    * contradictory current operator confirmations remain unresolved;
    * a single current confirmation establishes a confirmed mapping unless
      qualifying current voice evidence contradicts it;
    * prior identities are reused only after qualifying current voice evidence;
    * otherwise one qualifying voice candidate becomes a suggestion;
    * transcript context is audit-only and unresolved labels produce no turns.
    """

    policy = policy or SpeakerResolutionPolicy()
    ordered_turns = sorted(turns, key=lambda item: (item.start_ms, item.end_ms, item.turn_id))
    turn_by_id = {turn.turn_id: turn for turn in ordered_turns}
    if len(turn_by_id) != len(ordered_turns):
        raise ValueError("diarization turn IDs must be unique")

    observed_labels = sorted({turn.diarizer_speaker_id for turn in ordered_turns})
    evidence_by_label: dict[str, list[SpeakerIdentityEvidence]] = defaultdict(list)
    evidence_ids: set[str] = set()
    for item in evidence:
        if item.evidence_id in evidence_ids:
            raise ValueError("speaker evidence IDs must be unique")
        evidence_ids.add(item.evidence_id)
        if any(
            turn_by_id.get(turn_id) is None
            or turn_by_id[turn_id].diarizer_speaker_id != item.diarizer_speaker_id
            for turn_id in item.source_turn_ids
        ):
            raise ValueError("speaker evidence must reference a matching observed turn")
        evidence_by_label[item.diarizer_speaker_id].append(item)

    confirmed_by_label: dict[str, list[ConfirmedSpeakerMapping]] = defaultdict(list)
    for item in confirmed:
        if item.diarizer_speaker_id not in observed_labels:
            raise ValueError("confirmed mapping must reference an observed diarizer speaker")
        confirmed_by_label[item.diarizer_speaker_id].append(item)

    prior_by_speaker: dict[str, PriorConfirmedSpeaker] = {}
    for item in prior_confirmed:
        existing = prior_by_speaker.get(item.speaker_id)
        if existing is not None and existing != item:
            raise ValueError("prior confirmed speaker IDs must be unique")
        prior_by_speaker[item.speaker_id] = item

    mappings: list[SpeakerMapping] = []
    provenance_by_label: dict[str, Literal[
        "confirmed_mapping", "suggested_mapping", "prior_confirmed_mapping"
    ]] = {}
    labels_by_speaker: dict[str, str | None] = {}

    for label in observed_labels:
        label_evidence = sorted(evidence_by_label[label], key=lambda item: item.evidence_id)
        qualifying = _qualifying_voice_candidates(label_evidence, policy)
        operator_items = confirmed_by_label[label]
        operator_speakers = {item.speaker_id for item in operator_items}
        audit_ids = [item.evidence_id for item in label_evidence]

        speaker_id: str | None = None
        status: Literal["unresolved", "suggested", "confirmed"] = "unresolved"
        confidence: Confidence | None = None
        provenance = None
        human_label = None

        if len(operator_speakers) == 1:
            operator_speaker = next(iter(operator_speakers))
            # Strong current voice evidence for another identity is a conflict,
            # not something silently overridden by an operator record.
            if not (set(qualifying) - {operator_speaker}):
                speaker_id = operator_speaker
                status = "confirmed"
                confidence = 1.0
                provenance = "confirmed_mapping"
                human_label = next(
                    (item.human_label for item in operator_items if item.human_label is not None),
                    None,
                )
                audit_ids.append(f"operator-confirmed:{operator_speaker}")
        elif not operator_speakers and len(qualifying) == 1:
            candidate = next(iter(qualifying))
            speaker_id = candidate
            confidence = qualifying[candidate]
            if candidate in prior_by_speaker:
                status = "confirmed"
                provenance = "prior_confirmed_mapping"
                human_label = prior_by_speaker[candidate].human_label
                audit_ids.append(f"prior-confirmed:{candidate}")
            else:
                status = "suggested"
                provenance = "suggested_mapping"

        mappings.append(
            SpeakerMapping(
                diarizer_speaker_id=label,
                speaker_id=speaker_id,
                status=status,
                confidence=confidence,
                evidence=sorted(audit_ids),
            )
        )
        if speaker_id is not None and provenance is not None:
            provenance_by_label[label] = provenance
            labels_by_speaker[speaker_id] = human_label

    # Anonymous diarizer labels are distinct voices. A stable project identity
    # therefore cannot be assigned to more than one observed label in the same
    # run. Fail every side of that collision closed rather than selecting one by
    # label/order and accidentally attributing two voices to one person.
    labels_by_identity: dict[str, list[str]] = defaultdict(list)
    for mapping in mappings:
        if mapping.speaker_id is not None:
            labels_by_identity[mapping.speaker_id].append(mapping.diarizer_speaker_id)
    conflicted_identities = {
        speaker_id
        for speaker_id, diarizer_labels in labels_by_identity.items()
        if len(diarizer_labels) > 1
    }
    if conflicted_identities:
        mappings = [
            SpeakerMapping(
                diarizer_speaker_id=mapping.diarizer_speaker_id,
                status="unresolved",
                evidence=mapping.evidence,
            )
            if mapping.speaker_id in conflicted_identities
            else mapping
            for mapping in mappings
        ]
        conflicted_labels = {
            label
            for speaker_id in conflicted_identities
            for label in labels_by_identity[speaker_id]
        }
        provenance_by_label = {
            label: provenance
            for label, provenance in provenance_by_label.items()
            if label not in conflicted_labels
        }

    mapping_by_label = {mapping.diarizer_speaker_id: mapping for mapping in mappings}
    resolved_turns = []
    for turn in ordered_turns:
        mapping = mapping_by_label[turn.diarizer_speaker_id]
        if mapping.speaker_id is None:
            continue
        resolved_turns.append(
            ResolvedSpeakerTurn(
                turn_id=f"resolved-{turn.turn_id}",
                source_turn_id=turn.turn_id,
                diarizer_speaker_id=turn.diarizer_speaker_id,
                speaker_id=mapping.speaker_id,
                human_label=labels_by_speaker[mapping.speaker_id],
                start_ms=turn.start_ms,
                end_ms=turn.end_ms,
                confidence=mapping.confidence,
                provenance=provenance_by_label[turn.diarizer_speaker_id],
            )
        )

    return SpeakerMappingResolution(mappings=mappings, resolved_turns=resolved_turns)


def _qualifying_voice_candidates(
    evidence: Sequence[SpeakerIdentityEvidence], policy: SpeakerResolutionPolicy
) -> dict[str, float]:
    by_candidate: dict[str, list[SpeakerIdentityEvidence]] = defaultdict(list)
    for item in evidence:
        if item.kind == "voice" and item.confidence >= policy.minimum_voice_confidence:
            by_candidate[item.candidate_speaker_id].append(item)

    qualifying: dict[str, float] = {}
    for candidate, items in by_candidate.items():
        turn_ids = {turn_id for item in items for turn_id in item.source_turn_ids}
        if (
            len(items) >= policy.minimum_voice_evidence
            and len(turn_ids) >= policy.minimum_voice_turns
        ):
            qualifying[candidate] = round(
                sum(item.confidence for item in items) / len(items), 6
            )
    return qualifying


__all__ = [
    "ConfirmedSpeakerMapping",
    "PriorConfirmedSpeaker",
    "SpeakerIdentityEvidence",
    "SpeakerMappingResolution",
    "SpeakerResolutionPolicy",
    "resolve_speaker_mappings",
]
