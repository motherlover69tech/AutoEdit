"""Versioned contracts for durable local-AI results.

All timestamps use integer milliseconds on the synchronized project master
 timeline. These models are intentionally strict: unknown fields and malformed
 partial results must fail before they can become the last-known-good artifact.
"""

from __future__ import annotations

from datetime import datetime
from pathlib import PurePosixPath
from typing import Annotated, Literal

from pydantic import (
    BaseModel,
    ConfigDict,
    Field,
    StrictInt,
    StringConstraints,
    field_validator,
    model_validator,
)

Sha256 = Annotated[str, StringConstraints(pattern=r"^[0-9a-f]{64}$")]
SafeId = Annotated[str, StringConstraints(pattern=r"^[A-Za-z0-9][A-Za-z0-9._-]{0,127}$")]
IntegerMs = StrictInt
PositiveMs = Annotated[StrictInt, Field(gt=0)]
NonNegativeMs = Annotated[StrictInt, Field(ge=0)]
Confidence = Annotated[float, Field(ge=0.0, le=1.0)]


def _require_aware_datetime(value: datetime) -> datetime:
    if value.tzinfo is None or value.utcoffset() is None:
        raise ValueError("created_at must be timezone-aware")
    return value


def _require_unique_ids(items: list, attribute: str, description: str) -> None:
    values = [getattr(item, attribute) for item in items]
    if len(values) != len(set(values)):
        raise ValueError(f"{description} must be unique")


class StrictContract(BaseModel):
    model_config = ConfigDict(extra="forbid")


class SourceManifest(StrictContract):
    source_id: SafeId
    relative_path: str
    sha256: Sha256
    duration_ms: PositiveMs
    sample_rate: Annotated[int, Field(gt=0, le=384_000)]
    channels: Annotated[int, Field(gt=0, le=64)]
    sync_offset_ms: IntegerMs

    @field_validator("relative_path")
    @classmethod
    def validate_relative_path(cls, value: str) -> str:
        return confined_relative_path(value)


class AnalysisAudioManifest(StrictContract):
    relative_path: str
    sha256: Sha256
    strategy: Literal["isolated_lav", "mono_mix", "camera_mix"]
    duration_ms: PositiveMs
    sample_rate: Literal[16_000]
    channels: Literal[1]

    @field_validator("relative_path")
    @classmethod
    def validate_relative_path(cls, value: str) -> str:
        return confined_relative_path(value)


class ModelIdentity(StrictContract):
    task: Literal["asr", "alignment", "diarization", "speaker_mapping"]
    provider: SafeId
    model_id: Annotated[str, StringConstraints(min_length=1, max_length=255)]
    version: Annotated[str, StringConstraints(min_length=1, max_length=128)]
    compute_type: Annotated[str, StringConstraints(min_length=1, max_length=64)] | None = None


class WordTiming(StrictContract):
    text: Annotated[str, StringConstraints(min_length=1)]
    start_ms: NonNegativeMs
    end_ms: PositiveMs
    confidence: Confidence | None = None

    @model_validator(mode="after")
    def validate_range(self) -> "WordTiming":
        if self.end_ms <= self.start_ms:
            raise ValueError("word end_ms must be greater than start_ms")
        return self


class TranscriptSegment(StrictContract):
    segment_id: SafeId
    start_ms: NonNegativeMs
    end_ms: PositiveMs
    text: str
    words: list[WordTiming] = Field(default_factory=list)

    @model_validator(mode="after")
    def validate_range_and_words(self) -> "TranscriptSegment":
        if self.end_ms <= self.start_ms:
            raise ValueError("segment end_ms must be greater than start_ms")
        previous_start = self.start_ms
        for word in self.words:
            if word.start_ms < self.start_ms or word.end_ms > self.end_ms:
                raise ValueError("word timestamps must be within segment timestamps")
            if word.start_ms < previous_start:
                raise ValueError("word timestamps must be ordered")
            previous_start = word.start_ms
        return self


class DiarizationTurn(StrictContract):
    turn_id: SafeId
    diarizer_speaker_id: SafeId
    start_ms: NonNegativeMs
    end_ms: PositiveMs
    confidence: Confidence | None = None
    overlap: bool = False

    @model_validator(mode="after")
    def validate_range(self) -> "DiarizationTurn":
        if self.end_ms <= self.start_ms:
            raise ValueError("diarization turn end_ms must be greater than start_ms")
        return self


class SpeakerMapping(StrictContract):
    diarizer_speaker_id: SafeId
    speaker_id: SafeId | None = None
    status: Literal["unresolved", "suggested", "confirmed"]
    confidence: Confidence | None = None
    evidence: list[Annotated[str, StringConstraints(min_length=1, max_length=255)]] = Field(
        default_factory=list
    )

    @model_validator(mode="after")
    def validate_resolution(self) -> "SpeakerMapping":
        if self.status == "unresolved" and self.speaker_id is not None:
            raise ValueError("unresolved speaker mapping cannot have speaker_id")
        if self.status != "unresolved" and self.speaker_id is None:
            raise ValueError("resolved speaker mapping requires speaker_id")
        return self


class OverlapInterval(StrictContract):
    overlap_id: SafeId
    diarizer_speaker_ids: Annotated[list[SafeId], Field(min_length=2)]
    start_ms: NonNegativeMs
    end_ms: PositiveMs
    confidence: Confidence | None = None

    @model_validator(mode="after")
    def validate_overlap(self) -> "OverlapInterval":
        if self.end_ms <= self.start_ms:
            raise ValueError("overlap end_ms must be greater than start_ms")
        if len(set(self.diarizer_speaker_ids)) != len(self.diarizer_speaker_ids):
            raise ValueError("overlap speaker IDs must be distinct")
        return self


class ResolvedSpeakerTurn(StrictContract):
    turn_id: SafeId
    source_turn_id: SafeId
    diarizer_speaker_id: SafeId
    speaker_id: SafeId
    human_label: Annotated[str, StringConstraints(min_length=1, max_length=128)] | None = None
    start_ms: NonNegativeMs
    end_ms: PositiveMs
    confidence: Confidence | None = None
    provenance: Literal[
        "confirmed_mapping", "suggested_mapping", "prior_confirmed_mapping"
    ]

    @model_validator(mode="after")
    def validate_range(self) -> "ResolvedSpeakerTurn":
        if self.end_ms <= self.start_ms:
            raise ValueError("resolved turn end_ms must be greater than start_ms")
        return self


class AIResultArtifact(StrictContract):
    schema_version: Literal["1.0"]
    run_id: SafeId
    created_at: datetime
    status: Literal["completed"]
    timeline_unit: Literal["ms"] = "ms"
    timeline_basis: Literal["program_audio_master"] = "program_audio_master"
    sync_offset_convention: Literal[
        "source_ms=master_ms+sync_offset_ms"
    ] = "source_ms=master_ms+sync_offset_ms"
    timeline_origin_ms: NonNegativeMs
    timeline_end_ms: PositiveMs
    sources: Annotated[list[SourceManifest], Field(min_length=1)]
    analysis_audio: AnalysisAudioManifest
    models: Annotated[list[ModelIdentity], Field(min_length=1)]
    segments: list[TranscriptSegment] = Field(default_factory=list)
    diarization_turns: list[DiarizationTurn] = Field(default_factory=list)
    overlaps: list[OverlapInterval] = Field(default_factory=list)
    speaker_mappings: list[SpeakerMapping] = Field(default_factory=list)
    speaker_turns: list[ResolvedSpeakerTurn] = Field(default_factory=list)
    warnings: list[Annotated[str, StringConstraints(min_length=1, max_length=1000)]] = Field(
        default_factory=list
    )

    @field_validator("created_at")
    @classmethod
    def require_timezone_aware_created_at(cls, value: datetime) -> datetime:
        return _require_aware_datetime(value)

    @model_validator(mode="after")
    def validate_master_timeline(self) -> "AIResultArtifact":
        if self.timeline_end_ms <= self.timeline_origin_ms:
            raise ValueError("timeline_end_ms must be greater than timeline_origin_ms")
        _require_unique_ids(self.sources, "source_id", "source IDs")
        _require_unique_ids(self.segments, "segment_id", "segment IDs")
        _require_unique_ids(self.diarization_turns, "turn_id", "diarization turn IDs")
        _require_unique_ids(self.overlaps, "overlap_id", "overlap IDs")
        _require_unique_ids(self.speaker_turns, "turn_id", "speaker turn IDs")
        for item in [
            *self.segments,
            *self.diarization_turns,
            *self.overlaps,
            *self.speaker_turns,
        ]:
            if item.start_ms < self.timeline_origin_ms or item.end_ms > self.timeline_end_ms:
                raise ValueError("result timestamps must be within master timeline")
        turn_by_id = {turn.turn_id: turn for turn in self.diarization_turns}
        if len(turn_by_id) != len(self.diarization_turns):
            raise ValueError("diarization turn IDs must be unique")
        mapping_by_id = {
            mapping.diarizer_speaker_id: mapping for mapping in self.speaker_mappings
        }
        if len(mapping_by_id) != len(self.speaker_mappings):
            raise ValueError("speaker mapping diarizer IDs must be unique")
        observed_speaker_ids = {
            turn.diarizer_speaker_id for turn in self.diarization_turns
        }
        orphan_mapping_ids = set(mapping_by_id) - observed_speaker_ids
        if orphan_mapping_ids:
            raise ValueError("speaker mapping must reference an observed diarizer speaker")
        for overlap in self.overlaps:
            if not set(overlap.diarizer_speaker_ids).issubset(observed_speaker_ids):
                raise ValueError("overlap must reference observed diarizer speakers")
            for speaker_id in overlap.diarizer_speaker_ids:
                if not any(
                    turn.diarizer_speaker_id == speaker_id
                    and turn.start_ms <= overlap.start_ms
                    and turn.end_ms >= overlap.end_ms
                    for turn in self.diarization_turns
                ):
                    raise ValueError(
                        "overlap interval must be covered by each listed speaker"
                    )
        resolved_turn_ids = {turn.turn_id for turn in self.speaker_turns}
        if len(resolved_turn_ids) != len(self.speaker_turns):
            raise ValueError("resolved speaker turn IDs must be unique")
        for resolved in self.speaker_turns:
            source = turn_by_id.get(resolved.source_turn_id)
            mapping = mapping_by_id.get(resolved.diarizer_speaker_id)
            if source is None or source.diarizer_speaker_id != resolved.diarizer_speaker_id:
                raise ValueError("resolved turn must reference its diarization turn")
            if (
                mapping is None
                or mapping.status == "unresolved"
                or mapping.speaker_id != resolved.speaker_id
            ):
                raise ValueError("resolved turn must reference a resolved speaker mapping")
            if resolved.start_ms < source.start_ms or resolved.end_ms > source.end_ms:
                raise ValueError("resolved turn timestamps must be within source turn")
            expected_provenance = {
                "suggested": {"suggested_mapping"},
                "confirmed": {"confirmed_mapping", "prior_confirmed_mapping"},
            }[mapping.status]
            if resolved.provenance not in expected_provenance:
                raise ValueError("resolved turn provenance must match speaker mapping status")
        return self


class FailedRunArtifact(StrictContract):
    schema_version: Literal["1.0"] = "1.0"
    run_id: SafeId
    created_at: datetime
    status: Literal["failed"] = "failed"
    stage: SafeId
    error_code: SafeId
    message: Annotated[str, StringConstraints(min_length=1, max_length=2000)]

    @field_validator("created_at")
    @classmethod
    def require_timezone_aware_created_at(cls, value: datetime) -> datetime:
        return _require_aware_datetime(value)


def confined_relative_path(value: str) -> str:
    if not value or "\\" in value:
        raise ValueError("path must be a confined relative path")
    path = PurePosixPath(value)
    if path.is_absolute() or value == "." or ".." in path.parts:
        raise ValueError("path must be a confined relative path")
    normalized = path.as_posix()
    if normalized != value or normalized.startswith("/"):
        raise ValueError("path must be a confined relative path")
    return normalized
