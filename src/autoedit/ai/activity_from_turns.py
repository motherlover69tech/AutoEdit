"""Project-master activity projection for resolved WhisperX turns.

The projection deliberately keeps anonymous/unresolved speech visible as an
explicit safe-wide state instead of dropping it.  The existing CDL contract
can therefore retain its ``active`` list while callers can audit why a span
was routed wide.
"""
from __future__ import annotations

from collections.abc import Iterable, Mapping, Sequence
from dataclasses import dataclass
import math
from typing import Any


class ActivityProjectionError(ValueError):
    """Raised when an AI turn set cannot be safely projected."""


class ArtifactImportError(ValueError):
    """Raised when a worker artifact is malformed or not source-bound."""


@dataclass(frozen=True)
class ArtifactImportResult:
    """Stable API-layer result for a validated, source-bound artifact."""

    artifact: Any
    source_hashes_verified: bool


def activity_from_turns(
    turns: Sequence[dict[str, Any] | Any],
    *,
    timeline_end_ms: int,
    confidence_threshold: float = 0.0,
) -> list[dict[str, Any]]:
    """Build a contiguous, deterministic activity timeline from speaker turns.

    ``turns`` may be mappings or contract objects.  A turn is authoritative
    only when it has a stable ``speaker_id`` and confidence at least the
    threshold.  Unresolved/low-confidence turns remain represented in
    ``unresolved`` and are intentionally not put in ``active``; the cut layer
    uses that marker to select the wide camera.
    """
    if not isinstance(timeline_end_ms, int) or isinstance(timeline_end_ms, bool) or timeline_end_ms <= 0:
        raise ActivityProjectionError("timeline_end_ms must be positive")
    if confidence_threshold < 0 or confidence_threshold > 1:
        raise ActivityProjectionError("confidence_threshold must be between 0 and 1")

    boundaries = {0, timeline_end_ms}
    normalized: list[tuple[int, int, str | None, bool, bool, float | None, str | None]] = []
    for turn in turns:
        if isinstance(turn, Mapping):
            value = turn
        elif hasattr(turn, "model_dump"):
            value = turn.model_dump()
        else:
            raise ActivityProjectionError("turn must be a mapping or contract object")
        start, end = value["start_ms"], value["end_ms"]
        if not isinstance(start, int) or isinstance(start, bool) or not isinstance(end, int) or isinstance(end, bool):
            raise ActivityProjectionError("turn timestamps must be integers")
        if start < 0 or end > timeline_end_ms or end <= start:
            raise ActivityProjectionError("turn timestamps must be within the master timeline")
        speaker = value.get("speaker_id")
        confidence = value.get("confidence")
        if confidence is not None and (
            not isinstance(confidence, (int, float))
            or isinstance(confidence, bool)
            or not math.isfinite(confidence)
            or confidence < 0
            or confidence > 1
        ):
            raise ActivityProjectionError("turn confidence must be finite and between 0 and 1")
        # Suggested mappings are evidence, never camera authority.  A raw
        # diarizer label is likewise unresolved unless the caller explicitly
        # marks it as confirmed (the API passes only confirmed rows here).
        provenance = value.get("provenance")
        mapping_status = value.get("mapping_status")
        authoritative = (
            provenance in {"confirmed_mapping", "prior_confirmed_mapping"}
            and mapping_status == "confirmed"
        )
        off_camera = bool(value.get("off_camera") or value.get("uncertain_camera"))
        known = authoritative and not off_camera and bool(speaker) and (confidence is None or confidence >= confidence_threshold)
        reason_override = "off_camera:wide" if off_camera else None
        normalized.append((start, end, str(speaker) if known else None, not known, confidence is not None and confidence < confidence_threshold, confidence, reason_override))
        boundaries.update((start, end))

    ordered = sorted(boundaries)
    result: list[dict[str, Any]] = []
    for start, end in zip(ordered, ordered[1:]):
        if end <= start:
            continue
        active: set[str] = set()
        unresolved = False
        confidences: list[float] = []
        for turn_start, turn_end, speaker, is_unresolved, _is_low_confidence, confidence, _reason_override in normalized:
            if turn_start < end and turn_end > start:
                unresolved |= is_unresolved
                if speaker is not None:
                    active.add(speaker)
                    if confidence is not None:
                        confidences.append(confidence)
        if len(active) > 1:
            unresolved = True
        segment = {
            "start_ms": start,
            "end_ms": end,
            "active": sorted(active) if not unresolved else [],
            "source": "whisperx",
            "confidence": None if unresolved else (min(confidences) if confidences else None),
            "mapping_status": "unresolved" if unresolved else ("confirmed" if active else "none"),
        }
        if unresolved:
            segment["safe_wide"] = True
            if len(active) > 1:
                segment["reason"] = "overlap:wide"
            elif any(
                turn_start < end and turn_end > start and is_low_confidence
                for turn_start, turn_end, _speaker, _unresolved, is_low_confidence, _confidence, _reason_override in normalized
            ):
                segment["reason"] = "low_confidence:wide"
            elif any(
                turn_start < end and turn_end > start and reason_override == "off_camera:wide"
                for turn_start, turn_end, _speaker, _unresolved, _is_low_confidence, _confidence, reason_override in normalized
            ):
                segment["reason"] = "off_camera:wide"
            else:
                segment["reason"] = "unresolved:wide"
        result.append(segment)

    return _merge(result)


def import_artifact(artifact: Any, *, store: Any | None = None) -> ArtifactImportResult:
    """Strictly validate and optionally source-hash-check a worker artifact.

    Validation is deliberately performed before callers derive activity/CDL.
    No timestamp is clipped here: malformed or out-of-range data fails closed.
    ``store`` is an :class:`AIArtifactStore`-compatible object when source hash
    verification is required; publication remains the caller's explicit step.
    """
    try:
        from autoedit.ai.contracts import AIResultArtifact

        validated = AIResultArtifact.model_validate(artifact)
    except Exception as exc:
        raise ArtifactImportError(f"invalid AI artifact: {exc}") from exc
    if not validated.segments or not any(segment.words for segment in validated.segments):
        raise ArtifactImportError("artifact must contain non-empty aligned words")
    if not validated.diarization_turns:
        raise ArtifactImportError("artifact must contain non-empty diarization turns")
    if store is None:
        raise ArtifactImportError("source-bound artifact verification is required")
    try:
        store._verify_inputs(validated)
    except Exception as exc:
        raise ArtifactImportError(f"source-bound artifact verification failed: {exc}") from exc
    return ArtifactImportResult(validated, True)


def _merge(segments: Iterable[dict[str, Any]]) -> list[dict[str, Any]]:
    merged: list[dict[str, Any]] = []
    for segment in segments:
        if (
            merged
            and merged[-1]["end_ms"] == segment["start_ms"]
            and merged[-1]["active"] == segment["active"]
            and merged[-1]["mapping_status"] == segment["mapping_status"]
            and merged[-1].get("reason") == segment.get("reason")
            and merged[-1].get("confidence") == segment.get("confidence")
        ):
            merged[-1]["end_ms"] = segment["end_ms"]
        else:
            merged.append(dict(segment))
    return merged


# Descriptive alias for callers using the roadmap terminology.
project_resolved_turns = activity_from_turns

__all__ = [
    "ActivityProjectionError",
    "ArtifactImportError",
    "ArtifactImportResult",
    "activity_from_turns",
    "import_artifact",
    "project_resolved_turns",
]
