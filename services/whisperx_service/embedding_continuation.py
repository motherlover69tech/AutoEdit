"""Conservative post-gap diarization label-continuation validation."""
from __future__ import annotations

import math
from collections.abc import Mapping, Sequence
from typing import Any


def _cosine(left: Sequence[float], right: Sequence[float]) -> float:
    if len(left) != len(right) or not left:
        raise ValueError("embedding dimensions must match and be non-empty")
    if any(isinstance(value, bool) or not isinstance(value, (int, float)) or not math.isfinite(value)
           for value in (*left, *right)):
        raise ValueError("embeddings must contain finite numbers")
    dot = sum(float(a) * float(b) for a, b in zip(left, right))
    left_norm = math.sqrt(sum(float(value) ** 2 for value in left))
    right_norm = math.sqrt(sum(float(value) ** 2 for value in right))
    if left_norm == 0 or right_norm == 0:
        raise ValueError("embeddings must have non-zero norm")
    return dot / (left_norm * right_norm)


def validate_postgap_continuations(
    turns: Sequence[Mapping[str, Any]],
    *,
    minimum_similarity: float = 0.85,
    minimum_margin: float = 0.05,
    maximum_gap_seconds: float = 5.0,
) -> list[dict[str, Any]]:
    """Correct an isolated post-gap label only with decisive voice evidence.

    Input order is irrelevant. Embeddings are accepted only through the private
    ``_embedding`` field and are removed from returned turns. The immediately
    preceding non-overlap turn is the continuation candidate. Relabeling also
    requires the candidate similarity to exceed recent evidence for the newly
    assigned cluster by ``minimum_margin``.
    """
    if not 0 <= minimum_similarity <= 1 or not 0 <= minimum_margin <= 1:
        raise ValueError("similarity thresholds must be between zero and one")
    if maximum_gap_seconds < 0:
        raise ValueError("maximum gap must be non-negative")

    ordered = sorted((dict(turn) for turn in turns), key=lambda item: (
        float(item["start"]), float(item["end"]), str(item.get("turn_id", ""))
    ))
    recent_by_speaker: dict[str, tuple[float, ...]] = {}
    previous: dict[str, Any] | None = None
    for turn in ordered:
        embedding_raw = turn.pop("_embedding", None)
        embedding = tuple(float(value) for value in embedding_raw) if embedding_raw is not None else None
        speaker = str(turn["diarizer_speaker_id"])
        if (
            previous is not None
            and embedding is not None
            and previous.get("_private_embedding") is not None
            and not turn.get("overlap")
            and not previous.get("overlap")
        ):
            gap = float(turn["start"]) - float(previous["end"])
            previous_speaker = str(previous["diarizer_speaker_id"])
            if 0 < gap <= maximum_gap_seconds and speaker != previous_speaker:
                continuation_similarity = _cosine(embedding, previous["_private_embedding"])
                assigned_embedding = recent_by_speaker.get(speaker)
                assigned_similarity = (
                    _cosine(embedding, assigned_embedding)
                    if assigned_embedding is not None
                    else -1.0
                )
                if (
                    continuation_similarity >= minimum_similarity
                    and continuation_similarity - assigned_similarity >= minimum_margin
                ):
                    turn["original_diarizer_speaker_id"] = speaker
                    turn["diarizer_speaker_id"] = previous_speaker
                    turn["label_provenance"] = "embedding_continuation"
                    turn["continuation_similarity"] = round(continuation_similarity, 6)
                    speaker = previous_speaker
        if embedding is not None:
            recent_by_speaker[speaker] = embedding
        turn["_private_embedding"] = embedding
        previous = turn

    for turn in ordered:
        turn.pop("_private_embedding", None)
    return ordered


__all__ = ["validate_postgap_continuations"]
