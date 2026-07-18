"""Validation and presentation helpers for operator speaker confirmation."""
from __future__ import annotations

from collections import defaultdict
import json
from pathlib import Path
from typing import Any

from pydantic import ValidationError

from autoedit.ai.contracts import AIResultArtifact


class ArtifactValidationError(ValueError):
    """Raised when the durable AI result is malformed or incomplete."""


def load_artifact(project_dir: Path, *, strict: bool = True) -> dict[str, Any] | None:
    path = project_dir / "audio" / "ai" / "v1" / "result.json"
    if not path.is_file():
        return None
    try:
        raw = path.read_text(encoding="utf-8")
        if not strict:
            value = json.loads(raw)
            if not isinstance(value, dict):
                raise ValueError("artifact must be a JSON object")
            return value
        artifact = AIResultArtifact.model_validate_json(raw)
    except (OSError, json.JSONDecodeError, ValidationError, ValueError) as exc:
        raise ArtifactValidationError(f"invalid AI result artifact: {exc}") from exc
    return artifact.model_dump(mode="json")


def artifact_version(artifact: dict[str, Any]) -> str:
    return str(artifact.get("run_id") or "")


def snippets(artifact: dict[str, Any], minimum: int = 2) -> dict[str, list[dict[str, int | str]]]:
    """Return bounded, distinct program-audio ranges for every observed label."""
    end = int(artifact["timeline_end_ms"])
    grouped: dict[str, list[dict[str, Any]]] = defaultdict(list)
    for turn in artifact.get("diarization_turns", []):
        start = max(0, int(turn["start_ms"]))
        stop = min(end, int(turn["end_ms"]))
        if stop > start:
            grouped[str(turn["diarizer_speaker_id"])].append(
                {"turn_id": turn["turn_id"], "start_ms": start, "end_ms": stop}
            )
    result: dict[str, list[dict[str, int | str]]] = {}
    for label, turns in grouped.items():
        chosen: list[dict[str, int | str]] = []
        for turn in sorted(turns, key=lambda item: (item["start_ms"], item["turn_id"])):
            if any(turn["start_ms"] < old["end_ms"] and old["start_ms"] < turn["end_ms"] for old in chosen):
                continue
            chosen.append(turn)
            if len(chosen) >= minimum:
                break
        result[label] = chosen
    return result


def validate_confirmation_payload(*, artifact: dict[str, Any], diarizer_speaker_id: str, speaker_id: str, camera_id: str, evidence_turn_ids: list[str]) -> None:
    labels = {str(item["diarizer_speaker_id"]) for item in artifact.get("diarization_turns", [])}
    if diarizer_speaker_id not in labels:
        raise ValueError("unknown anonymous speaker label")
    turns = {str(item["turn_id"]): item for item in artifact.get("diarization_turns", [])}
    if len(evidence_turn_ids) < 2 or len(set(evidence_turn_ids)) != len(evidence_turn_ids):
        raise ValueError("at least two distinct evidence turns are required")
    if any(turns.get(item, {}).get("diarizer_speaker_id") != diarizer_speaker_id for item in evidence_turn_ids):
        raise ValueError("evidence turns must belong to the anonymous speaker")
    if not speaker_id.strip() or not camera_id.strip():
        raise ValueError("speaker and camera association are required")
