"""Adapter from the canonical AIResultArtifact to fixture boundary evidence.

The artifact contract remains the source of truth.  This module only projects
validated artifact words into the existing WordBoundary evaluation shape.
"""
from __future__ import annotations

from collections.abc import Iterable, Mapping
import hashlib

from autoedit.ai.contracts import AIResultArtifact
from autoedit.ai.golden_fixture import WordBoundary


def artifact_words(
    artifact: AIResultArtifact,
    truth_words: Iterable[WordBoundary],
    *,
    source_offsets_ms: Mapping[str, int] | None = None,
) -> list[WordBoundary]:
    """Return candidate words aligned by exact segment and word index.

    Truth selection is performed by the evaluator before this adapter is called.
    ``artifact_word_index`` is therefore an immutable reference, not a fuzzy text
    match.  Artifact timestamps are already on ``program_audio_master`` and are
    intentionally copied without offset conversion.
    """
    if artifact.timeline_basis != "program_audio_master":
        raise ValueError("candidate timeline basis is invalid")
    if source_offsets_ms is not None:
        actual = {source.source_id: source.sync_offset_ms for source in artifact.sources}
        if actual != dict(source_offsets_ms):
            raise ValueError("candidate source offsets do not match fixture")

    segments = {segment.segment_id: segment for segment in artifact.segments}
    output: list[WordBoundary] = []
    for truth in truth_words:
        if truth.artifact_word_index is None:
            raise ValueError("selected truth word lacks artifact index")
        segment = segments.get(truth.segment_id)
        if segment is None or truth.artifact_word_index >= len(segment.words):
            raise ValueError("selected artifact word is missing")
        word = segment.words[truth.artifact_word_index]
        if word.start_ms < artifact.timeline_origin_ms or word.end_ms > artifact.timeline_end_ms:
            raise ValueError("candidate word is outside master timeline")
        if truth.token_digest is not None and hashlib.sha256(word.text.encode()).hexdigest() != truth.token_digest:
            raise ValueError("candidate token digest does not match")
        cluster_ids = {
            turn.diarizer_speaker_id
            for turn in artifact.diarization_turns
            if turn.start_ms < word.end_ms and turn.end_ms > word.start_ms
        }
        output.append(WordBoundary(
            word_id=truth.word_id,
            segment_id=truth.segment_id,
            artifact_word_index=truth.artifact_word_index,
            start_ms=word.start_ms,
            end_ms=word.end_ms,
            uncertainty="certain",
            reviewer_decision="accepted",
            timeline_third=truth.timeline_third,
            anonymous_cluster_id=sorted(cluster_ids)[0] if len(cluster_ids) == 1 else None,
        ))
    if len({word.anonymous_cluster_id for word in output if word.anonymous_cluster_id}) < 2:
        raise ValueError("candidate cluster coverage is incomplete")
    return output
