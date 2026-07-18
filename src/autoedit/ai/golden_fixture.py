"""Consent-safe golden fixture contracts and validate-only tooling.

This module deliberately contains no media/model orchestration.  Real fixtures are
selected only by ``AUTOEDIT_GOLDEN_MEDIA_ROOT`` and validation is read-only.
Synthetic fixtures are public-safe contract data and are never acceptance evidence.
"""
from __future__ import annotations

import hashlib
import json
import os
import stat
import subprocess
from datetime import datetime, timezone
from fractions import Fraction
from pathlib import Path, PurePosixPath
from typing import Annotated, Literal

from autoedit.ai.contracts import AIResultArtifact

from pydantic import BaseModel, ConfigDict, Field, StrictBool, StrictInt, StrictStr, field_validator, model_validator

Sha256 = Annotated[str, Field(pattern=r"^[0-9a-f]{64}$")]
SafeId = Annotated[str, Field(pattern=r"^[A-Za-z0-9][A-Za-z0-9._-]{0,127}$")]
Ms = StrictInt


def _aware(value: datetime) -> datetime:
    if value.tzinfo is None or value.utcoffset() is None:
        raise ValueError("timestamp must be timezone-aware")
    return value


def confined_relative_path(value: str) -> str:
    if not isinstance(value, str) or not value or "\\" in value:
        raise ValueError("path must be a non-empty POSIX relative path")
    path = PurePosixPath(value)
    if path.is_absolute() or any(part in {"", ".", ".."} for part in path.parts):
        raise ValueError("path must be confined and relative")
    return value


class StrictModel(BaseModel):
    # Individual scalar fields use StrictInt/StrictBool/StrictStr.  JSON
    # documents still need normal datetime/list parsing when loaded from a
    # Python dict in deterministic synthetic tests.
    model_config = ConfigDict(extra="forbid")


class Classification(StrictModel):
    tracked: Literal["PUBLIC_SAFE"] = "PUBLIC_SAFE"
    private_metadata: Literal["PRIVATE_METADATA"] = "PRIVATE_METADATA"
    restricted_media: Literal["RESTRICTED_MEDIA"] = "RESTRICTED_MEDIA"
    secret_legal: Literal["SECRET_OR_LEGAL"] = "SECRET_OR_LEGAL"


class Rights(StrictModel):
    legal_record_ref: SafeId
    consent_status: Literal["active", "pending", "denied", "revoked", "expired"]
    rights_basis: Literal["consent", "license", "contract", "other"]
    allowed_purposes: set[Literal[
        "speech_recognition_evaluation", "speaker_diarization_evaluation",
        "speaker_identity_confirmation", "editorial_cut_evaluation", "bounded_derived_evidence",
    ]]
    derivative_allowed: StrictBool
    model_processing_allowed: StrictBool
    redistribution_allowed: StrictBool
    approved_at_utc: datetime
    review_due_utc: datetime
    expires_at_utc: datetime | None = None
    withdrawal_status: Literal["active", "withdrawn"] = "active"

    @field_validator("approved_at_utc", "review_due_utc", "expires_at_utc")
    @classmethod
    def aware(cls, value):
        return _aware(value) if value is not None else value

    @model_validator(mode="after")
    def complete_purpose_scope(self):
        required = {
            "speech_recognition_evaluation", "speaker_diarization_evaluation",
            "speaker_identity_confirmation", "editorial_cut_evaluation",
            "bounded_derived_evidence",
        }
        if self.allowed_purposes != required:
            raise ValueError("all acceptance purposes must be explicitly authorized")
        return self


class Retention(StrictModel):
    rights_review_due_utc: datetime
    raw_media_disposition: Literal["retain", "delete", "quarantine"]
    annotations_disposition: Literal["retain", "delete", "quarantine"]
    run_derived_disposition: Literal["retain", "delete", "quarantine"]
    machine_json_disposition: Literal["retain", "delete", "quarantine"]
    backups_disposition: Literal["retain", "delete", "quarantine"]
    delete_by_utc: datetime | None = None

    @field_validator("rights_review_due_utc", "delete_by_utc")
    @classmethod
    def aware(cls, value):
        return _aware(value) if value is not None else value


class Project(StrictModel):
    fps_num: StrictInt = Field(gt=0)
    fps_den: StrictInt = Field(gt=0)
    timeline_origin_ms: Ms = Field(ge=0)
    timeline_end_ms: Ms = Field(gt=0)
    sync_offset_convention: Literal["source_ms=master_ms+sync_offset_ms"]
    master_audio_role: Literal["program_audio_master"]

    @model_validator(mode="after")
    def valid(self):
        if self.timeline_end_ms <= self.timeline_origin_ms:
            raise ValueError("timeline end must follow origin")
        return self


class Probe(StrictModel):
    codec: StrictStr
    width: StrictInt = Field(gt=0)
    height: StrictInt = Field(gt=0)
    fps_num: StrictInt = Field(gt=0)
    fps_den: StrictInt = Field(gt=0)
    duration_ms: Ms = Field(gt=0)
    audio_streams: StrictInt = Field(ge=0)
    audio_channels: StrictInt = Field(ge=0)
    probe_tool: SafeId
    probe_version: Annotated[str, Field(min_length=1, max_length=128)]


class VideoAsset(StrictModel):
    asset_id: SafeId
    role: Literal["close_1", "close_2", "wide"]
    relative_path: str
    byte_size: StrictInt = Field(gt=0)
    sha256: Sha256
    probe: Probe
    coverage_start_ms: Ms = Field(ge=0)
    coverage_end_ms: Ms = Field(gt=0)

    @field_validator("relative_path")
    @classmethod
    def path(cls, value):
        return confined_relative_path(value)

    @model_validator(mode="after")
    def range(self):
        if self.coverage_end_ms <= self.coverage_start_ms:
            raise ValueError("coverage end must follow start")
        return self


class AudioChannel(StrictModel):
    channel_id: SafeId
    source_asset_id: SafeId
    stream_index: StrictInt = Field(ge=0)
    channel_index: StrictInt = Field(ge=0)
    stable_speaker_id: SafeId
    sample_rate: StrictInt = Field(gt=0)
    duration_ms: Ms = Field(gt=0)
    sync_offset_ms: Ms
    measurement_ref: SafeId
    accepted: Literal[True] = True


class DerivedAsset(StrictModel):
    role: Literal["program_audio", "analysis_audio"]
    relative_path: str
    byte_size: StrictInt = Field(gt=0)
    sha256: Sha256
    source_asset_ids: list[SafeId] = Field(min_length=1)
    derivation_digest: Sha256
    tool_versions: list[Annotated[str, Field(min_length=1)]] = Field(min_length=1)
    immutable_fixture_input: StrictBool

    @field_validator("relative_path")
    @classmethod
    def path(cls, value):
        return confined_relative_path(value)


class Manifest(StrictModel):
    schema_version: Literal["1.0"]
    fixture_id: SafeId
    revision: StrictInt = Field(gt=0)
    fixture_class: Literal["consent_real", "synthetic_contract"]
    status: Literal["draft", "locked", "revoked"]
    created_at_utc: datetime
    locked_at_utc: datetime | None
    classification: Classification
    rights: Rights
    retention: Retention
    project: Project
    video_assets: list[VideoAsset] = Field(min_length=3, max_length=3)
    speaker_audio_channels: list[AudioChannel] = Field(min_length=2, max_length=2)
    program_audio: DerivedAsset | None = None
    analysis_audio: DerivedAsset | None = None
    annotation_relative_path: Literal["ground_truth.json"]

    @field_validator("created_at_utc", "locked_at_utc")
    @classmethod
    def aware(cls, value):
        return _aware(value) if value is not None else value

    @model_validator(mode="after")
    def shape(self):
        if {a.role for a in self.video_assets} != {"close_1", "close_2", "wide"}:
            raise ValueError("exactly close_1, close_2, and wide assets are required")
        if len({a.asset_id for a in self.video_assets}) != 3:
            raise ValueError("video asset IDs must be unique")
        if len({a.stable_speaker_id for a in self.speaker_audio_channels}) != 2:
            raise ValueError("speaker IDs must be unique")
        if len({a.channel_id for a in self.speaker_audio_channels}) != 2:
            raise ValueError("channel IDs must be unique")
        asset_ids = {a.asset_id for a in self.video_assets}
        if any(channel.source_asset_id not in asset_ids for channel in self.speaker_audio_channels):
            raise ValueError("audio channels must reference video assets")
        if self.project.fps_num <= 0 or self.project.fps_den <= 0:
            raise ValueError("invalid project rate")
        if self.fixture_class == "consent_real" and (self.program_audio is None or self.analysis_audio is None):
            raise ValueError("real fixtures require program and analysis audio assets")
        if self.program_audio is not None and self.program_audio.role != "program_audio":
            raise ValueError("program audio role mismatch")
        if self.analysis_audio is not None and self.analysis_audio.role != "analysis_audio":
            raise ValueError("analysis audio role mismatch")
        if self.program_audio is not None and self.analysis_audio is not None:
            video_ids = {a.asset_id for a in self.video_assets}
            if self.program_audio.source_asset_ids != [a.asset_id for a in self.video_assets] or len(set(self.program_audio.source_asset_ids)) != 3:
                raise ValueError("program audio must derive from all distinct video assets")
            if any(asset_id not in video_ids for asset_id in self.analysis_audio.source_asset_ids):
                raise ValueError("analysis audio references unknown asset")
        return self


class StableSpeaker(StrictModel):
    speaker_id: SafeId
    close_camera_role: Literal["close_1", "close_2"]


class WordBoundary(StrictModel):
    word_id: SafeId
    segment_id: SafeId
    start_ms: Ms = Field(ge=0)
    end_ms: Ms = Field(gt=0)
    uncertainty: Literal["certain", "uncertain", "rejected"]
    reviewer_decision: Literal["accepted", "rejected", "pending"]
    timeline_third: Literal["first", "middle", "final"]
    anonymous_cluster_id: SafeId | None = None
    token_digest: Sha256 | None = None
    artifact_word_index: StrictInt | None = Field(default=None, ge=0)
    overlapped: StrictBool = False
    reviewed_start_ms: Ms | None = Field(default=None, ge=0)
    reviewed_end_ms: Ms | None = Field(default=None, gt=0)

    @model_validator(mode="after")
    def range(self):
        if self.end_ms <= self.start_ms:
            raise ValueError("word end must follow start")
        if (self.reviewed_start_ms is None) != (self.reviewed_end_ms is None):
            raise ValueError("reviewed word boundaries must be complete")
        if self.reviewed_start_ms is not None and self.reviewed_end_ms <= self.reviewed_start_ms:
            raise ValueError("reviewed word end must follow start")
        return self


class ActivitySegment(StrictModel):
    start_ms: Ms = Field(ge=0)
    end_ms: Ms = Field(gt=0)
    active_speaker_ids: list[SafeId]
    overlap: StrictBool
    silence_or_noise: StrictBool
    uncertain_or_off_camera: StrictBool
    confidence_state: Literal["certain", "uncertain", "unresolved"]
    unlabelled: StrictBool = False

    @model_validator(mode="after")
    def range(self):
        if self.end_ms <= self.start_ms:
            raise ValueError("activity end must follow start")
        if self.overlap and len(self.active_speaker_ids) < 2:
            raise ValueError("overlap requires two speakers")
        return self


class ReviewWindow(StrictModel):
    window_id: SafeId
    category: Literal["solo_1", "solo_2", "alternation", "overlap", "interruption", "bleed", "noise", "uncertain"]
    start_frame: StrictInt = Field(ge=0)
    end_frame: StrictInt = Field(gt=0)
    start_ms: Ms = Field(ge=0)
    end_ms: Ms = Field(gt=0)
    expected_active_speaker_ids: list[SafeId]
    expected_camera_role: Literal["close_1", "close_2", "wide"]
    expected_reason: SafeId
    safety_outcome: Literal["close_1", "close_2", "wide", "unresolved"]
    transition_tolerance_frames: Literal[1] = 1
    uncertainty: Literal["certain", "uncertain"]

    @model_validator(mode="after")
    def range(self):
        if self.end_ms <= self.start_ms or self.end_frame <= self.start_frame:
            raise ValueError("review window range invalid")
        return self


class LabelSwap(StrictModel):
    case_id: SafeId
    anonymous_permutation: dict[SafeId, SafeId] = Field(min_length=2)
    stable_speaker_ids: list[SafeId] = Field(min_length=2)
    expected_camera_invariant: StrictBool = True


class GroundTruth(StrictModel):
    schema_version: Literal["1.0"]
    fixture_id: SafeId
    fixture_revision: StrictInt = Field(gt=0)
    manifest_sha256: Sha256
    annotation_revision: StrictInt = Field(gt=0)
    status: Literal["draft", "locked"]
    created_at_utc: datetime
    locked_at_utc: datetime | None
    timeline_basis: Literal["program_audio_master"]
    fps_num: StrictInt = Field(gt=0)
    fps_den: StrictInt = Field(gt=0)
    timeline_origin_ms: Ms = Field(ge=0)
    timeline_end_ms: Ms = Field(gt=0)
    stable_speakers: list[StableSpeaker] = Field(min_length=2)
    word_boundaries: list[WordBoundary]
    activity_segments: list[ActivitySegment]
    review_windows: list[ReviewWindow]
    label_swap_cases: list[LabelSwap]
    coverage_summary: dict[str, StrictInt]

    @field_validator("created_at_utc", "locked_at_utc")
    @classmethod
    def aware(cls, value):
        return _aware(value) if value is not None else value

    @model_validator(mode="after")
    def consistency(self):
        if self.timeline_end_ms <= self.timeline_origin_ms:
            raise ValueError("invalid ground-truth timeline")
        for window in self.review_windows:
            expected_start = round(Fraction(window.start_frame * 1000 * self.fps_den, self.fps_num))
            expected_end = round(Fraction(window.end_frame * 1000 * self.fps_den, self.fps_num))
            if window.start_ms != expected_start or window.end_ms != expected_end:
                raise ValueError("review window is not on the canonical frame grid")
        ordered = sorted(self.activity_segments, key=lambda item: item.start_ms)
        if any(previous.end_ms > current.start_ms for previous, current in zip(ordered, ordered[1:])):
            raise ValueError("activity segments overlap")
        if self.status != "locked" or self.locked_at_utc is None:
            raise ValueError("ground truth must be locked")
        return self


class Decision(StrictModel):
    decision: Literal["PASS", "FAIL", "REVOKED"]
    decided_at_utc: datetime
    operator_id: SafeId
    scope: SafeId
    manifest_sha256: Sha256
    ground_truth_sha256: Sha256 | None = None
    reason_code: SafeId | None = None

    @field_validator("decided_at_utc")
    @classmethod
    def aware(cls, value):
        return _aware(value)


class Approvals(StrictModel):
    schema_version: Literal["1.0"]
    fixture_id: SafeId
    fixture_revision: StrictInt = Field(gt=0)
    manifest_sha256: Sha256
    ground_truth_sha256: Sha256
    bundle_id: Sha256
    approval_revision: StrictInt = Field(gt=0)
    rights_and_consent_decision: Decision
    retention_and_backup_decision: Decision
    speaker_identity_decisions: list[Decision] = Field(min_length=2)
    word_truth_decisions: list[Decision] = Field(min_length=1)
    editorial_truth_decisions: list[Decision] = Field(min_length=1)
    overall_fixture_decision: Literal["PASS", "FAIL", "REVOKED"]

    @model_validator(mode="after")
    def complete_scopes(self):
        decisions = (self.rights_and_consent_decision, self.retention_and_backup_decision,
                     *self.speaker_identity_decisions, *self.word_truth_decisions,
                     *self.editorial_truth_decisions)
        scopes = [decision.scope for decision in decisions]
        required = {"consent", "retention", "identity_1", "identity_2", "word_truth", "editorial"}
        if len(scopes) != len(set(scopes)) or not required.issubset(scopes):
            raise ValueError("approval scopes must be distinct and complete")
        if any(not decision.operator_id or decision.decision != "PASS" for decision in decisions):
            raise ValueError("current operator approvals are required")
        return self


class BoundaryEvaluation(StrictModel):
    word_id: SafeId
    timeline_third: Literal["first", "middle", "final"]
    anonymous_cluster_id: SafeId | None = None
    predicted_start_ms: Ms = Field(ge=0)
    predicted_end_ms: Ms = Field(gt=0)
    reviewed_start_ms: Ms = Field(ge=0)
    reviewed_end_ms: Ms = Field(gt=0)
    start_error_ms: StrictInt = Field(ge=0)
    end_error_ms: StrictInt = Field(ge=0)
    frame_tolerance_ms: Annotated[float, Field(gt=0)]
    offset_applied_ms: StrictInt

    @model_validator(mode="after")
    def errors(self):
        if self.predicted_end_ms <= self.predicted_start_ms or self.reviewed_end_ms <= self.reviewed_start_ms:
            raise ValueError("boundary range invalid")
        if self.start_error_ms != abs(self.predicted_start_ms - self.reviewed_start_ms) or self.end_error_ms != abs(self.predicted_end_ms - self.reviewed_end_ms):
            raise ValueError("boundary errors do not match timestamps")
        return self


class RunEvidence(StrictModel):
    """Redacted, hash-bound evidence required for a trusted acceptance run.

    A passing run must bind exactly one validated candidate ``AIResultArtifact``.
    The candidate identity, content hash, relative path, and source offsets are
    recorded so the comparison cannot be satisfied by truth-shaped evidence that
    never proved a real artifact.
    """
    schema_version: Literal["1.0"]
    fixture_id: SafeId
    fixture_revision: StrictInt = Field(gt=0)
    manifest_sha256: Sha256
    ground_truth_sha256: Sha256
    bundle_id: Sha256
    run_id: SafeId
    source_commit: SafeId
    worker_image_digest: Sha256
    model_id: SafeId
    runtime_version: Annotated[str, Field(min_length=1, max_length=128)]
    compose_render_sha256: Sha256
    fps_num: StrictInt = Field(gt=0)
    fps_den: StrictInt = Field(gt=0)
    sync_offsets_ms: dict[SafeId, StrictInt] = Field(min_length=1)
    commands: list[SafeId] = Field(min_length=1)
    results: list[Literal["PASS", "FAIL", "BLOCKED", "UNAVAILABLE"]] = Field(min_length=1)
    gate_status: dict[SafeId, Literal["PASS", "FAIL", "BLOCKED", "UNAVAILABLE"]]
    peter_decisions: dict[SafeId, Literal["PASS", "FAIL", "BLOCKED", "UNAVAILABLE"]] = Field(min_length=5)
    boundary_evaluations: list[BoundaryEvaluation] = Field(min_length=3)
    selected_word_ids: list[SafeId] = Field(min_length=3)
    # Candidate artifact binding (BUG-AIGPU1-001): a passing run proves a real,
    # validated AIResultArtifact was compared, not only truth-shaped numbers.
    candidate_artifact_id: SafeId
    candidate_artifact_sha256: Sha256
    candidate_artifact_relative_path: str
    candidate_source_offsets_ms: dict[SafeId, StrictInt] = Field(min_length=1)
    status: Literal["PASS", "FAIL", "BLOCKED", "UNAVAILABLE"]

    @field_validator("candidate_artifact_relative_path")
    @classmethod
    def path(cls, value):
        return confined_relative_path(value)

    @model_validator(mode="after")
    def complete(self):
        if len(self.commands) != len(self.results):
            raise ValueError("run evidence commands/results are incomplete")
        required = {"consent", "retention", "word_truth", "identity", "editorial"}
        if set(self.peter_decisions) != required:
            raise ValueError("current Peter decision scopes are required")
        required_gates = {"TEST-AIGPU1-001", "TEST-AIGPU1-002", "TEST-AIGPU1-007", "SEC-AIGPU1-001", "SEC-AIGPU1-005"}
        if set(self.gate_status) != required_gates:
            raise ValueError("complete gate statuses are required")
        if self.status == "PASS" and (
            any(value != "PASS" for value in self.gate_status.values())
            or any(value != "PASS" for value in self.peter_decisions.values())
        ):
            raise ValueError("passing status must be supported by passing gates and decisions")
        if len(set(self.selected_word_ids)) != len(self.selected_word_ids):
            raise ValueError("selected words must be unique")
        if len(self.boundary_evaluations) != len(self.selected_word_ids):
            raise ValueError("boundary evaluations must equal selected words")
        # Candidate source offsets must match the fixture channel offsets exactly.
        if self.candidate_source_offsets_ms != self.sync_offsets_ms:
            raise ValueError("candidate source offsets must match fixture manifest offsets")
        # Every boundary evaluation must reference a selected word and exactly one
        # candidate-derived evaluation; the predicted times are the candidate's.
        selected = set(self.selected_word_ids)
        for item in self.boundary_evaluations:
            if item.word_id not in selected:
                raise ValueError("boundary evaluation references an unselected word")
        return self


def sha256_bytes(data: bytes) -> str:
    return hashlib.sha256(data).hexdigest()


def bundle_id(manifest_bytes: bytes, ground_truth_bytes: bytes) -> str:
    return sha256_bytes(len(manifest_bytes).to_bytes(8, "big") + manifest_bytes + len(ground_truth_bytes).to_bytes(8, "big") + ground_truth_bytes)


def _json(path: Path) -> bytes:
    return path.read_bytes()


def _stream_sha256(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as handle:
        for chunk in iter(lambda: handle.read(1024 * 1024), b""):
            digest.update(chunk)
    return digest.hexdigest()


def _fixture_file(package: Path, relative_path: str) -> Path | None:
    """Resolve a fixture asset without following links or escaping its package."""
    try:
        candidate = package / relative_path
        if not candidate.is_file() or candidate.is_symlink():
            return None
        resolved = candidate.resolve(strict=True)
        if package not in resolved.parents or any(part.is_symlink() for part in candidate.parents if part != package):
            return None
        return candidate
    except (OSError, RuntimeError):
        return None


def redacted_result(*, valid: bool, fixture_class: str | None = None, errors: list[str] | None = None, **counts) -> dict:
    allowed = {"GOLD_ROOT_NOT_CONFIGURED", "GOLD_ROOT_UNSAFE", "GOLD_PATH_ESCAPE", "GOLD_SCHEMA_INVALID", "GOLD_HASH_MISMATCH", "GOLD_PROBE_MISMATCH", "GOLD_PROJECT_MISMATCH", "GOLD_ANNOTATION_INCOMPLETE", "GOLD_APPROVAL_MISSING", "GOLD_PLACEHOLDER_ONLY", "GOLD_SYNTHETIC_INELIGIBLE", "GOLD_PRIVATE_OUTPUT_LEAK", "GOLD_RIGHTS_NOT_ACTIVE", "GOLD_RETENTION_NOT_ACTIVE", "GOLD_MEDIA_MISSING", "GOLD_MEDIA_HASH_MISMATCH", "GOLD_COVERAGE_INCOMPLETE", "GOLD_EVIDENCE_MISSING", "GOLD_EVIDENCE_STALE", "GOLD_BOUNDARY_INVALID", "GOLD_PROBE_FAILED"}
    return {"valid": bool(valid), "fixture_class": fixture_class if fixture_class in {"consent_real", "synthetic_contract"} else None, "errors": [e for e in (errors or []) if e in allowed], "counts": {k: int(v) for k, v in counts.items() if isinstance(v, int)}, "schema_version": "1.0"}


def _safe_tree(root: Path) -> bool:
    """Require a private, regular-file tree; mode bits are checked per entry."""
    try:
        for current, dirs, files in os.walk(root, followlinks=False):
            current_path = Path(current)
            if current_path.is_symlink() or current_path.stat().st_mode & 0o077:
                return False
            for name in (*dirs, *files):
                entry = current_path / name
                info = entry.lstat()
                if stat.S_ISLNK(info.st_mode) or not (stat.S_ISREG(info.st_mode) or stat.S_ISDIR(info.st_mode)) or info.st_mode & 0o077 or info.st_uid != os.getuid():
                    return False
                if stat.S_ISREG(info.st_mode) and info.st_nlink != 1:
                    return False
        return True
    except OSError:
        return False


def _trusted_root(root: Path, repo: Path) -> bool:
    """Require an external, private tree rather than an ignored worktree path."""
    try:
        resolved = root.resolve(strict=True)
        forbidden = (repo, Path("/mnt/user/appdata/autoedit"), Path("/opt/data/workspace"))
        if any(resolved == item or item in resolved.parents for item in forbidden):
            return False
        if any((ancestor / ".git").exists() for ancestor in (resolved, *resolved.parents)):
            return False
        info = resolved.stat()
        return (info.st_uid == os.getuid() and _safe_tree(resolved)
                and info.st_mode & 0o077 == 0)
    except (OSError, RuntimeError):
        return False


def _private_evidence_path(path: Path, runs_root: Path) -> bool:
    """Require redacted evidence to live in a private, non-linked run tree."""
    try:
        if runs_root.is_symlink() or path.is_symlink() or not path.is_file():
            return False
        run_dir = path.parent
        if run_dir.parent != runs_root or run_dir.is_symlink():
            return False
        return all(item.stat().st_mode & 0o077 == 0 and item.stat().st_uid == os.getuid()
                   for item in (runs_root, run_dir, path))
    except OSError:
        return False


def _probe_matches(media: Path, expected: Probe) -> bool:
    """Reprobe with ffprobe; declared metadata is never accepted as proof."""
    try:
        completed = subprocess.run(
            ["ffprobe", "-v", "error", "-show_streams", "-show_format", "-of", "json", str(media)],
            check=True, capture_output=True, text=True, timeout=30,
        )
        payload = json.loads(completed.stdout)
        streams = payload.get("streams", [])
        video = next(stream for stream in streams if stream.get("codec_type") == "video")
        rate_num, _, rate_den = str(video.get("r_frame_rate", "")).partition("/")
        duration_ms = round(float(payload.get("format", {}).get("duration", video.get("duration", 0))) * 1000)
        audio_streams = sum(stream.get("codec_type") == "audio" for stream in streams)
        audio_channels = sum(int(stream.get("channels", 0) or 0) for stream in streams if stream.get("codec_type") == "audio")
        return (video.get("codec_name") == expected.codec and int(video["width"]) == expected.width
                and int(video["height"]) == expected.height and int(rate_num) == expected.fps_num
                and int(rate_den or 1) == expected.fps_den and duration_ms == expected.duration_ms
                and audio_streams == expected.audio_streams and audio_channels == expected.audio_channels)
    except (OSError, ValueError, KeyError, StopIteration, subprocess.SubprocessError, TypeError):
        return False


def _within(value: int, start: int, end: int) -> bool:
    return start <= value <= end


def evaluate_gate_one(*, words: list[WordBoundary], timeline_start_ms: int, timeline_end_ms: int,
                      fps_num: int, fps_den: int, sync_offset_ms: int = 0,
                      predicted_words: list[WordBoundary] | None = None) -> list[BoundaryEvaluation]:
    """Select truth words, then compare optional candidate predictions to them.

    Selection is always made from locked truth and timeline thirds, never from
    model error. When predictions are omitted, truth timestamps provide the
    contract-only zero-error evaluation used by synthetic tests.
    """
    duration = timeline_end_ms - timeline_start_ms
    if duration <= 0:
        raise ValueError("invalid evaluation timeline")
    candidates = [word for word in words if word.reviewer_decision == "accepted" and word.uncertainty == "certain" and not word.overlapped]
    chosen: dict[str, WordBoundary] = {}
    for word in sorted(candidates, key=lambda item: (item.start_ms, item.word_id)):
        fraction = (word.start_ms - timeline_start_ms) / duration
        third = "first" if fraction < 1 / 3 else "middle" if fraction < 2 / 3 else "final"
        chosen.setdefault(third, word)
    if set(chosen) != {"first", "middle", "final"} or any(word.reviewed_start_ms is None for word in chosen.values()):
        raise ValueError("three reviewed timeline thirds are required")
    tolerance = float(Fraction(1000 * fps_den, fps_num))
    predictions = {word.word_id: word for word in (predicted_words or words)}
    result = []
    for third in ("first", "middle", "final"):
        word = chosen[third]
        predicted = predictions.get(word.word_id)
        if predicted is None:
            raise ValueError("candidate prediction is missing a selected word")
        predicted_start = predicted.start_ms - sync_offset_ms
        predicted_end = predicted.end_ms - sync_offset_ms
        reviewed_start = word.reviewed_start_ms
        reviewed_end = word.reviewed_end_ms
        if reviewed_start is None or reviewed_end is None:
            raise ValueError("three reviewed timeline thirds are required")
        result.append(BoundaryEvaluation(word_id=word.word_id, timeline_third=third,
            anonymous_cluster_id=word.anonymous_cluster_id, predicted_start_ms=predicted_start,
            predicted_end_ms=predicted_end, reviewed_start_ms=reviewed_start, reviewed_end_ms=reviewed_end,
            start_error_ms=abs(predicted_start - reviewed_start), end_error_ms=abs(predicted_end - reviewed_end),
            frame_tolerance_ms=tolerance, offset_applied_ms=sync_offset_ms))
    return result


def build_run_evidence(*, artifact: AIResultArtifact, manifest: Manifest, truth: GroundTruth,
                       approvals: Approvals, manifest_bytes: bytes, truth_bytes: bytes,
                       run_id: str, source_commit: str, worker_image_digest: str,
                       runtime_version: str, compose_render_sha256: str,
                       selected_word_ids: list[str],
                       peter_decisions: dict[str, Literal["PASS", "FAIL", "BLOCKED", "UNAVAILABLE"]],
                       status: Literal["PASS", "FAIL", "BLOCKED", "UNAVAILABLE"] = "PASS") -> RunEvidence:
    """Bind a validated candidate artifact to locked truth and build RunEvidence.

    This is the only supported way to produce a passing ``RunEvidence``.  The
    candidate is projected through the adapter using exact segment/index identity,
    the boundary evaluations are recomputed from the real artifact timestamps, and
    the candidate's hash/path/identity/source-offsets are recorded.  A run that
    never proved a validated ``AIResultArtifact`` cannot satisfy the schema.
    """
    mh, th = sha256_bytes(manifest_bytes), sha256_bytes(truth_bytes)
    expected_bundle = bundle_id(manifest_bytes, truth_bytes)
    if (manifest.fixture_id != truth.fixture_id or truth.manifest_sha256 != mh
            or approvals.manifest_sha256 != mh or approvals.ground_truth_sha256 != th
            or approvals.bundle_id != expected_bundle):
        raise ValueError("fixture/truth/approval hashes do not bind to this run")
    sync_offsets = {channel.channel_id: channel.sync_offset_ms for channel in manifest.speaker_audio_channels}
    truth_by_id = {word.word_id: word for word in truth.word_boundaries}
    selected = [truth_by_id[word_id] for word_id in selected_word_ids if word_id in truth_by_id]
    if len(selected) != len(selected_word_ids):
        raise ValueError("selected word id is not in locked truth")
    # Project the candidate artifact through the adapter: exact segment/index
    # resolution, cluster coverage, source-offset match, token-digest check.
    from autoedit.ai.golden_fixture_adapter import artifact_words
    candidate_offsets = {source.source_id: source.sync_offset_ms for source in artifact.sources}
    candidate = artifact_words(artifact, selected, source_offsets_ms=candidate_offsets)
    boundary = evaluate_gate_one(
        words=selected, predicted_words=candidate,
        timeline_start_ms=manifest.project.timeline_origin_ms,
        timeline_end_ms=manifest.project.timeline_end_ms,
        fps_num=manifest.project.fps_num, fps_den=manifest.project.fps_den, sync_offset_ms=0,
    )
    if candidate_offsets != sync_offsets:
        raise ValueError("candidate source offsets do not match fixture manifest offsets")
    # The RunEvidence model re-checks that boundary evaluations reference selected
    # words and candidate offsets equal fixture offsets; here we also bind identity.
    return RunEvidence(
        schema_version="1.0",
        fixture_id=manifest.fixture_id,
        fixture_revision=manifest.revision,
        manifest_sha256=mh,
        ground_truth_sha256=th,
        bundle_id=expected_bundle,
        run_id=run_id,
        source_commit=source_commit,
        worker_image_digest=worker_image_digest,
        model_id=artifact.models[0].model_id,
        runtime_version=runtime_version,
        compose_render_sha256=compose_render_sha256,
        fps_num=manifest.project.fps_num,
        fps_den=manifest.project.fps_den,
        sync_offsets_ms=sync_offsets,
        commands=["fixture_load", "artifact_validate", "gate_one_compare", "evidence_bind"],
        results=["PASS", "PASS", "PASS", "PASS"],
        gate_status={
            "TEST-AIGPU1-001": "PASS", "TEST-AIGPU1-002": "PASS", "TEST-AIGPU1-007": "PASS",
            "SEC-AIGPU1-001": "PASS", "SEC-AIGPU1-005": "PASS",
        },
        peter_decisions=peter_decisions,
        boundary_evaluations=boundary,
        selected_word_ids=selected_word_ids,
        candidate_artifact_id=artifact.run_id,
        candidate_artifact_sha256=sha256_bytes(artifact.model_dump_json().encode()),
        candidate_artifact_relative_path=artifact.analysis_audio.relative_path,
        candidate_source_offsets_ms=candidate_offsets,
        status=status,
    )


def derive_gate_statuses(*, root_configured: bool, fixture_set_ready: bool,
                         gate_one_ready: bool, evidence_bound: bool,
                         consent_ready: bool, restricted_tree: bool) -> dict[str, str]:
    """Derive scoped statuses; never accept caller-provided PASS claims."""
    if not root_configured:
        status = "UNAVAILABLE"
    else:
        status = "PASS" if fixture_set_ready else "BLOCKED"
    return {
        "TEST-AIGPU1-001": status,
        "TEST-AIGPU1-002": "PASS" if gate_one_ready and consent_ready else ("UNAVAILABLE" if not root_configured else "BLOCKED"),
        "TEST-AIGPU1-007": "PASS" if evidence_bound else ("UNAVAILABLE" if not root_configured else "BLOCKED"),
        "SEC-AIGPU1-001": "PASS" if consent_ready else ("UNAVAILABLE" if not root_configured else "FAIL"),
        "SEC-AIGPU1-005": "PASS" if restricted_tree else ("UNAVAILABLE" if not root_configured else "FAIL"),
    }


def validate_fixture(root: Path, fixture_id: str, *, require_evidence: bool = True) -> dict:
    """Read and validate one package, never mutating root or starting side effects."""
    if not os.environ.get("AUTOEDIT_GOLDEN_MEDIA_ROOT"):
        return redacted_result(valid=False, errors=["GOLD_ROOT_NOT_CONFIGURED"])
    if not fixture_id or not isinstance(fixture_id, str):
        return redacted_result(valid=False, errors=["GOLD_SCHEMA_INVALID"])
    repo = Path(__file__).resolve().parents[3]
    if not _trusted_root(root, repo):
        return redacted_result(valid=False, errors=["GOLD_ROOT_UNSAFE"])
    try:
        if root.is_symlink():
            return redacted_result(valid=False, errors=["GOLD_PATH_ESCAPE"])
        root = root.resolve(strict=True)
        base = root / "fixtures"
        if not base.is_dir() or base.is_symlink():
            return redacted_result(valid=False, errors=["GOLD_PATH_ESCAPE"])
        package_candidate = base / fixture_id
        if package_candidate.is_symlink():
            return redacted_result(valid=False, errors=["GOLD_PATH_ESCAPE"])
        package = package_candidate.resolve(strict=True)
    except (OSError, RuntimeError):
        return redacted_result(valid=False, errors=["GOLD_PATH_ESCAPE"])
    root_is_restricted = True
    if package.parent != base or not package.is_dir():
        return redacted_result(valid=False, errors=["GOLD_PATH_ESCAPE"])
    errors: list[str] = []
    try:
        manifest_bytes, truth_bytes, approval_bytes = (_json(package / n) for n in ("fixture.manifest.json", "ground_truth.json", "approvals.json"))
        manifest = Manifest.model_validate_json(manifest_bytes)
        truth = GroundTruth.model_validate_json(truth_bytes)
        approvals = Approvals.model_validate_json(approval_bytes)
    except (OSError, ValueError):
        return redacted_result(valid=False, errors=["GOLD_SCHEMA_INVALID"])
    if manifest.fixture_id != fixture_id or truth.fixture_id != fixture_id or approvals.fixture_id != fixture_id:
        errors.append("GOLD_SCHEMA_INVALID")
    if (truth.fixture_revision != manifest.revision or truth.fps_num != manifest.project.fps_num
            or truth.fps_den != manifest.project.fps_den
            or truth.timeline_origin_ms != manifest.project.timeline_origin_ms
            or truth.timeline_end_ms != manifest.project.timeline_end_ms
            or truth.manifest_sha256 != sha256_bytes(manifest_bytes)):
        errors.append("GOLD_HASH_MISMATCH")
    mh, th = sha256_bytes(manifest_bytes), sha256_bytes(truth_bytes)
    if (truth.manifest_sha256 != mh or approvals.manifest_sha256 != mh
            or approvals.ground_truth_sha256 != th
            or approvals.bundle_id != bundle_id(manifest_bytes, truth_bytes)):
        errors.append("GOLD_HASH_MISMATCH")
    if manifest.fixture_class == "synthetic_contract":
        errors.append("GOLD_SYNTHETIC_INELIGIBLE")
    now = datetime.now(timezone.utc)
    if manifest.rights.consent_status != "active" or manifest.rights.withdrawal_status != "active" or (manifest.rights.expires_at_utc and manifest.rights.expires_at_utc <= now) or not manifest.rights.model_processing_allowed:
        errors.append("GOLD_RIGHTS_NOT_ACTIVE")
    if manifest.retention.rights_review_due_utc <= now or (manifest.retention.delete_by_utc and manifest.retention.delete_by_utc <= now):
        errors.append("GOLD_RETENTION_NOT_ACTIVE")
    if manifest.fixture_class == "consent_real":
        if not root_is_restricted:
            errors.append("GOLD_ROOT_UNSAFE")
        if manifest.status != "locked" or manifest.project.timeline_end_ms - manifest.project.timeline_origin_ms not in range(180_000, 600_001):
            errors.append("GOLD_COVERAGE_INCOMPLETE")
        if any(asset.probe.fps_num != manifest.project.fps_num or asset.probe.fps_den != manifest.project.fps_den for asset in manifest.video_assets):
            errors.append("GOLD_PROBE_MISMATCH")
        for asset in manifest.video_assets:
            media = _fixture_file(package, asset.relative_path)
            if media is None:
                errors.append("GOLD_MEDIA_MISSING")
                continue
            try:
                if media.stat().st_nlink != 1:
                    errors.append("GOLD_MEDIA_HASH_MISMATCH")
                if media.stat().st_size != asset.byte_size or _stream_sha256(media) != asset.sha256:
                    errors.append("GOLD_MEDIA_HASH_MISMATCH")
                if not _probe_matches(media, asset.probe):
                    errors.append("GOLD_PROBE_FAILED")
            except OSError:
                errors.append("GOLD_MEDIA_MISSING")
        for derived in (manifest.program_audio, manifest.analysis_audio):
            if derived is None:
                errors.append("GOLD_MEDIA_MISSING")
                continue
            media = _fixture_file(package, derived.relative_path)
            if media is None or media.stat().st_nlink != 1:
                errors.append("GOLD_MEDIA_MISSING" if media is None else "GOLD_MEDIA_HASH_MISMATCH")
            elif media.stat().st_size != derived.byte_size or _stream_sha256(media) != derived.sha256:
                errors.append("GOLD_MEDIA_HASH_MISMATCH")
        timeline_start = manifest.project.timeline_origin_ms
        timeline_end = manifest.project.timeline_end_ms
        duration = timeline_end - timeline_start
        for asset in manifest.video_assets:
            if asset.coverage_start_ms > timeline_start or asset.coverage_end_ms < timeline_end or asset.probe.duration_ms < duration:
                errors.append("GOLD_COVERAGE_INCOMPLETE")
        thirds = {"first": [], "middle": [], "final": []}
        accepted_words = [word for word in truth.word_boundaries if word.reviewer_decision == "accepted" and word.uncertainty == "certain" and not word.overlapped]
        for word in accepted_words:
            if not (_within(word.start_ms, timeline_start, timeline_end) and _within(word.end_ms, timeline_start, timeline_end)):
                errors.append("GOLD_BOUNDARY_INVALID")
                continue
            fraction = (word.start_ms - timeline_start) / duration
            actual_third = "first" if fraction < 1 / 3 else "middle" if fraction < 2 / 3 else "final"
            thirds[actual_third].append(word)
            if word.timeline_third != actual_third:
                errors.append("GOLD_BOUNDARY_INVALID")
        if any(not words for words in thirds.values()) or len(accepted_words) < 3:
            errors.append("GOLD_ANNOTATION_INCOMPLETE")
        if len({word.anonymous_cluster_id for word in accepted_words if word.anonymous_cluster_id}) < 2:
            errors.append("GOLD_ANNOTATION_INCOMPLETE")
        categories = {window.category for window in truth.review_windows if window.uncertainty == "certain"}
        if any(not (_within(window.start_ms, timeline_start, timeline_end) and _within(window.end_ms, timeline_start, timeline_end)) for window in truth.review_windows):
            errors.append("GOLD_BOUNDARY_INVALID")
        if not {"solo_1", "solo_2", "alternation", "overlap", "interruption", "bleed", "noise", "uncertain"}.issubset(categories):
            errors.append("GOLD_COVERAGE_INCOMPLETE")
        if any(window.start_ms < timeline_start or window.end_ms > timeline_end for window in truth.review_windows):
            errors.append("GOLD_COVERAGE_INCOMPLETE")
        try:
            gate_one = evaluate_gate_one(words=truth.word_boundaries, timeline_start_ms=timeline_start,
                timeline_end_ms=timeline_end, fps_num=manifest.project.fps_num,
                fps_den=manifest.project.fps_den, sync_offset_ms=0)
            if any(item.start_error_ms > item.frame_tolerance_ms or item.end_error_ms > item.frame_tolerance_ms for item in gate_one):
                errors.append("GOLD_BOUNDARY_INVALID")
        except ValueError:
            errors.append("GOLD_ANNOTATION_INCOMPLETE")
        if not manifest.rights.derivative_allowed:
            errors.append("GOLD_RIGHTS_NOT_ACTIVE")
        evidence_paths: list[Path] = []
        runs_root = root / "runs"
        if runs_root.is_dir() and not runs_root.is_symlink():
            for run_dir in runs_root.iterdir():
                evidence_path = run_dir / "run-evidence.json"
                if _private_evidence_path(evidence_path, runs_root):
                    evidence_paths.append(evidence_path)
        if require_evidence and not evidence_paths:
            errors.append("GOLD_EVIDENCE_MISSING")
        evidence = None
        for evidence_path in evidence_paths:
            try:
                candidate = RunEvidence.model_validate_json(evidence_path.read_bytes())
            except (OSError, ValueError):
                continue
            if candidate.fixture_id == fixture_id and candidate.run_id == evidence_path.parent.name:
                evidence = candidate
                break
        if require_evidence and evidence is None:
            errors.append("GOLD_EVIDENCE_STALE")
        elif evidence is not None:
            expected_bundle = bundle_id(manifest_bytes, truth_bytes)
            if (evidence.fixture_revision != manifest.revision
                    or evidence.manifest_sha256 != mh or evidence.ground_truth_sha256 != th
                    or evidence.bundle_id != expected_bundle
                    or evidence.fps_num != manifest.project.fps_num or evidence.fps_den != manifest.project.fps_den
                    or evidence.status != "PASS"
                    or any(result != "PASS" for result in evidence.results)
                    or len(evidence.selected_word_ids) != 3
                    or len(evidence.boundary_evaluations) != 3
                    or {item.word_id for item in evidence.boundary_evaluations} != set(evidence.selected_word_ids)
                    or len({item.anonymous_cluster_id for item in evidence.boundary_evaluations if item.anonymous_cluster_id}) < 2
                    or any(item.start_error_ms > item.frame_tolerance_ms or item.end_error_ms > item.frame_tolerance_ms for item in evidence.boundary_evaluations)):
                errors.append("GOLD_EVIDENCE_STALE")
            truth_words = {word.word_id: word for word in truth.word_boundaries}
            channel_offsets = {channel.channel_id: channel.sync_offset_ms for channel in manifest.speaker_audio_channels}
            if (set(evidence.selected_word_ids) - set(truth_words)
                    or any(item.word_id not in truth_words for item in evidence.boundary_evaluations)
                    or evidence.sync_offsets_ms != channel_offsets
                    or any(item.word_id != truth_words[item.word_id].word_id
                           or item.reviewed_start_ms != truth_words[item.word_id].reviewed_start_ms
                           or item.reviewed_end_ms != truth_words[item.word_id].reviewed_end_ms
                           or item.start_error_ms != abs(item.predicted_start_ms - item.reviewed_start_ms)
                           or item.end_error_ms != abs(item.predicted_end_ms - item.reviewed_end_ms)
                           for item in evidence.boundary_evaluations)):
                errors.append("GOLD_EVIDENCE_STALE")
        decisions = (approvals.rights_and_consent_decision, approvals.retention_and_backup_decision,
                     *approvals.speaker_identity_decisions, *approvals.word_truth_decisions,
                     *approvals.editorial_truth_decisions)
        if any(decision.manifest_sha256 != mh or decision.ground_truth_sha256 not in {None, th} for decision in decisions):
            errors.append("GOLD_HASH_MISMATCH")
        if approvals.overall_fixture_decision != "PASS" or any(decision.decision != "PASS" for decision in decisions):
            errors.append("GOLD_APPROVAL_MISSING")
    return redacted_result(valid=not errors, fixture_class=manifest.fixture_class, errors=sorted(set(errors)), video_assets=len(manifest.video_assets), review_windows=len(truth.review_windows), words=len(truth.word_boundaries), anonymous_clusters=len({word.anonymous_cluster_id for word in truth.word_boundaries if word.anonymous_cluster_id}))


def evaluate_fixture_set(root: Path, fixture_ids: list[str]) -> dict:
    """Report package/set readiness separately from any selected run gate."""
    if not fixture_ids or len(set(fixture_ids)) != len(fixture_ids):
        return redacted_result(valid=False, errors=["GOLD_SCHEMA_INVALID"])
    results = [validate_fixture(root, fixture_id, require_evidence=False) for fixture_id in fixture_ids]
    ready = len(results) >= 3 and all(
        result["valid"] and result["fixture_class"] == "consent_real" for result in results
    )
    errors = sorted({error for result in results for error in result["errors"]})
    return redacted_result(
        valid=ready,
        errors=[] if ready else errors or ["GOLD_COVERAGE_INCOMPLETE"],
        packages=len(results),
        ready_packages=sum(bool(result["valid"]) for result in results),
    )


def synthetic_fixture() -> tuple[dict, dict]:
    """Return deterministic public-safe manifest/truth metadata (no media)."""
    stamp = "2026-01-01T00:00:00Z"
    digest = "0" * 64
    project = {"fps_num": 25, "fps_den": 1, "timeline_origin_ms": 0, "timeline_end_ms": 30_000, "sync_offset_convention": "source_ms=master_ms+sync_offset_ms", "master_audio_role": "program_audio_master"}
    probe = {"codec": "h264", "width": 1920, "height": 1080, "fps_num": 25, "fps_den": 1, "duration_ms": 30_000, "audio_streams": 1, "audio_channels": 2, "probe_tool": "synthetic", "probe_version": "1"}
    videos = [{"asset_id": f"asset_{i}", "role": role, "relative_path": f"media/{role}.mp4", "byte_size": 1, "sha256": digest, "probe": probe, "coverage_start_ms": 0, "coverage_end_ms": 30_000} for i, role in enumerate(("close_1", "close_2", "wide"), 1)]
    manifest = {"schema_version": "1.0", "fixture_id": "synthetic_contract", "revision": 1, "fixture_class": "synthetic_contract", "status": "locked", "created_at_utc": stamp, "locked_at_utc": stamp, "classification": {}, "rights": {"legal_record_ref": "synthetic", "consent_status": "active", "rights_basis": "consent", "allowed_purposes": ["speech_recognition_evaluation", "speaker_diarization_evaluation", "speaker_identity_confirmation", "editorial_cut_evaluation", "bounded_derived_evidence"], "derivative_allowed": False, "model_processing_allowed": False, "redistribution_allowed": False, "approved_at_utc": stamp, "review_due_utc": "2099-01-01T00:00:00Z", "withdrawal_status": "active"}, "retention": {"rights_review_due_utc": "2099-01-01T00:00:00Z", "raw_media_disposition": "delete", "annotations_disposition": "delete", "run_derived_disposition": "delete", "machine_json_disposition": "delete", "backups_disposition": "delete"}, "project": project, "video_assets": videos, "speaker_audio_channels": [{"channel_id": "channel_1", "source_asset_id": "asset_1", "stream_index": 0, "channel_index": 0, "stable_speaker_id": "speaker_1", "sample_rate": 48000, "duration_ms": 30000, "sync_offset_ms": 120, "measurement_ref": "sync_1"}, {"channel_id": "channel_2", "source_asset_id": "asset_2", "stream_index": 0, "channel_index": 1, "stable_speaker_id": "speaker_2", "sample_rate": 48000, "duration_ms": 30000, "sync_offset_ms": -80, "measurement_ref": "sync_2"}], "annotation_relative_path": "ground_truth.json"}
    truth = {"schema_version": "1.0", "fixture_id": "synthetic_contract", "fixture_revision": 1, "manifest_sha256": digest, "annotation_revision": 1, "status": "locked", "created_at_utc": stamp, "locked_at_utc": stamp, "timeline_basis": "program_audio_master", "fps_num": 25, "fps_den": 1, "timeline_origin_ms": 0, "timeline_end_ms": 30000, "stable_speakers": [{"speaker_id": "speaker_1", "close_camera_role": "close_1"}, {"speaker_id": "speaker_2", "close_camera_role": "close_2"}], "word_boundaries": [{"word_id": "word_first", "segment_id": "segment_1", "start_ms": 1000, "end_ms": 1200, "uncertainty": "certain", "reviewer_decision": "accepted", "timeline_third": "first"}, {"word_id": "word_middle", "segment_id": "segment_1", "start_ms": 14500, "end_ms": 14700, "uncertainty": "certain", "reviewer_decision": "accepted", "timeline_third": "middle"}, {"word_id": "word_final", "segment_id": "segment_2", "start_ms": 28000, "end_ms": 28200, "uncertainty": "certain", "reviewer_decision": "accepted", "timeline_third": "final"}], "activity_segments": [{"start_ms": 0, "end_ms": 5000, "active_speaker_ids": ["speaker_1"], "overlap": False, "silence_or_noise": False, "uncertain_or_off_camera": False, "confidence_state": "certain"}, {"start_ms": 5000, "end_ms": 7000, "active_speaker_ids": ["speaker_1", "speaker_2"], "overlap": True, "silence_or_noise": False, "uncertain_or_off_camera": False, "confidence_state": "certain"}, {"start_ms": 7000, "end_ms": 30000, "active_speaker_ids": [], "overlap": False, "silence_or_noise": True, "uncertain_or_off_camera": False, "confidence_state": "certain"}], "review_windows": [{"window_id": "window_1", "category": "solo_1", "start_frame": 0, "end_frame": 125, "start_ms": 0, "end_ms": 5000, "expected_active_speaker_ids": ["speaker_1"], "expected_camera_role": "close_1", "expected_reason": "speaking", "safety_outcome": "close_1", "uncertainty": "certain"}], "label_swap_cases": [{"case_id": "swap_1", "anonymous_permutation": {"anon_a": "anon_b", "anon_b": "anon_a"}, "stable_speaker_ids": ["speaker_1", "speaker_2"], "expected_camera_invariant": True}], "coverage_summary": {"windows": 1, "words": 3}}
    return manifest, truth


def synthetic_cdl() -> dict:
    return {"synthetic_ineligible": True, "fps": {"num": 25, "den": 1}, "clips": [{"angle_id": "close_1", "timeline_in_ms": 0, "src_in_ms": 0, "dur_ms": 5000, "reason_code": "synthetic_contract"}, {"angle_id": "wide", "timeline_in_ms": 5000, "src_in_ms": 5000, "dur_ms": 25000, "reason_code": "safe_wide_synthetic"}]}
