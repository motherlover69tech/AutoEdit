"""Audit-only LLM extraction of participant-name context.

This module deliberately does not map names to diarizer labels. It produces
weak, timestamped contextual candidates that can be retained for review while
voice evidence and operator confirmation remain authoritative for identity.
"""

from __future__ import annotations

import math
import re
from typing import Annotated, Any, Literal, Protocol, Sequence

from pydantic import Field, StrictFloat, StringConstraints, model_validator

from autoedit.ai.contracts import StrictContract
from autoedit.llm_client import LLMClient

CandidateText = Annotated[str, StringConstraints(min_length=1, max_length=255)]
CandidateName = Annotated[str, StringConstraints(min_length=1, max_length=128)]


class SpeakerNameCandidate(StrictContract):
    name: CandidateName
    evidence_quote: CandidateText
    start_seconds: Annotated[StrictFloat, Field(ge=0.0)]
    confidence: Annotated[StrictFloat, Field(ge=0.0, le=1.0)]
    basis: Literal[
        "explicit_self_introduction",
        "explicit_address_or_reference",
        "uncertain_context",
    ]

    @model_validator(mode="after")
    def enforce_audit_confidence_ceiling(self) -> "SpeakerNameCandidate":
        ceiling = {
            "explicit_self_introduction": 1.0,
            "explicit_address_or_reference": 0.40,
            "uncertain_context": 0.25,
        }[self.basis]
        if not math.isfinite(self.start_seconds) or not math.isfinite(self.confidence):
            raise ValueError("candidate timestamp and confidence must be finite")
        if self.confidence > ceiling:
            raise ValueError(f"confidence exceeds {self.basis} audit ceiling")
        return self


class SpeakerContextResult(StrictContract):
    candidates: list[SpeakerNameCandidate]
    notes: Annotated[str, StringConstraints(max_length=1000)]


class _ChatClient(Protocol):
    async def chat(self, system: str, user: str, **kwargs: Any) -> dict[str, Any]: ...


async def extract_speaker_name_candidates(
    transcript_segments: Sequence[dict[str, Any]],
    *,
    client: _ChatClient | None = None,
) -> SpeakerContextResult:
    """Extract auditable names without asserting voice/cluster identity."""

    lines: list[str] = []
    validated_segments: list[tuple[float, float, str]] = []
    for index, segment in enumerate(transcript_segments):
        try:
            start_value = segment["start"]
            end_value = segment["end"]
            text_value = segment["text"]
        except (KeyError, TypeError) as exc:
            raise ValueError(f"invalid transcript segment at index {index}") from exc
        if (
            isinstance(start_value, bool)
            or isinstance(end_value, bool)
            or not isinstance(start_value, (int, float))
            or not isinstance(end_value, (int, float))
            or not isinstance(text_value, str)
        ):
            raise ValueError(f"invalid transcript segment at index {index}")
        start = float(start_value)
        end = float(end_value)
        text = text_value.strip()
        if not math.isfinite(start) or not math.isfinite(end) or start < 0 or end <= start or not text:
            raise ValueError(f"invalid transcript segment at index {index}")
        lines.append(f"[{start:.3f}-{end:.3f}] {text}")
        validated_segments.append((start, end, text))

    if not lines:
        return SpeakerContextResult(candidates=[], notes="")

    system = (
        "You are an audit-only participant-name evidence extractor for video editing. "
        "The transcript has no reliable speaker labels. Extract only participant names "
        "explicitly supported by an exact transcript quote. Never assign a name to a "
        "diarizer or voice cluster, infer identity from turn order, or claim voice "
        "recognition. Confidence must be at most 0.40 for explicit address/reference "
        "and at most 0.25 for uncertain context. Return an empty candidates array when "
        "evidence is insufficient."
    )
    llm = client or LLMClient()
    payload = await llm.chat(
        system,
        "\n".join(lines),
        temperature=0.0,
        format_json=True,
        max_tokens=600,
        json_schema=SpeakerContextResult.model_json_schema(),
        think=False,
        keep_alive=0,
    )
    if _contains_thinking_trace(payload):
        raise ValueError("LLM returned a thinking trace in non-thinking mode")
    result = SpeakerContextResult.model_validate(payload)
    for candidate in result.candidates:
        matching_segments = [
            text
            for start, end, text in validated_segments
            if start <= candidate.start_seconds < end
        ]
        if not matching_segments or not any(
            candidate.evidence_quote in text for text in matching_segments
        ):
            raise ValueError("speaker candidate evidence is not grounded in its transcript segment")
        if not _quote_explicitly_names_candidate(candidate.name, candidate.evidence_quote):
            raise ValueError("speaker candidate name is not grounded in its evidence quote")
    return result


def _quote_explicitly_names_candidate(name: str, quote: str) -> bool:
    normalized_name = " ".join(name.split()).casefold()
    normalized_quote = " ".join(quote.split()).casefold()
    if not normalized_name:
        return False
    return re.search(
        rf"(?<!\w){re.escape(normalized_name)}(?!\w)",
        normalized_quote,
    ) is not None


def _contains_thinking_trace(value: Any) -> bool:
    if isinstance(value, str):
        lowered = value.lower()
        return "<think" in lowered or "</think>" in lowered
    if isinstance(value, dict):
        return any(
            key.lower() == "thinking" or _contains_thinking_trace(item)
            for key, item in value.items()
        )
    if isinstance(value, (list, tuple)):
        return any(_contains_thinking_trace(item) for item in value)
    return False


__all__ = [
    "SpeakerContextResult",
    "SpeakerNameCandidate",
    "extract_speaker_name_candidates",
]
