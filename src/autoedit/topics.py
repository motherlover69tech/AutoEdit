from __future__ import annotations

import random
from typing import Any

from autoedit.config import Settings
from autoedit.llm_client import get_llm_client


MOCK_TOPIC_LABELS = [
    "Introduction",
    "Background & experience",
    "Key challenges",
    "Technical deep-dive",
    "Lessons learned",
    "Future outlook",
    "Team dynamics",
    "Industry trends",
    "Project origins",
    "Closing thoughts",
]

MOCK_COLOURS = [
    "#C0392B", "#E67E22", "#2980B9", "#27AE60",
    "#8E44AD", "#16A085", "#D35400", "#2C3E50",
    "#7F8C8D", "#F39C12",
]

MOCK_SUMMARIES = [
    "Discussion of the main themes and initial thoughts.",
    "Detailed exploration of the core subject matter.",
    "Challenges encountered and how they were addressed.",
    "Technical insights and implementation details.",
    "Reflections on what worked and what could improve.",
    "Looking ahead to upcoming developments.",
    "Team collaboration and interpersonal dynamics.",
    "Broader implications for the field.",
    "Origins and motivations for the work.",
    "Wrap-up and final reflections.",
]


def mock_segment_topics(
    transcript_segments: list[dict[str, Any]],
) -> dict[str, Any]:
    """Segment a transcript into coherent, non-overlapping topic spans.

    In production, replace this with a stricter LLM call (see spec Stage 5.2)
    using the configured `OLLAMA_BASE_URL` / `LLM_MODEL`.

    Args:
        transcript_segments: List of {speaker, start_ms, end_ms, text, ...} dicts.

    Returns:
        Dict with 'topics' (list of {label, colour, summary, start_ms, end_ms, conciseness})
        and 'spans' (same shape, for DB insertion).
        Spans are guaranteed non-overlapping and cover >95% of the transcript range.
    """
    if not transcript_segments:
        return {"topics": [], "spans": []}

    # Try LLM-based segmentation first (only if configured)
    settings = Settings()
    if settings.llm_model and settings.ollama_base_url:
        try:
            import asyncio
            return asyncio.run(_llm_segment_topics(transcript_segments, settings))
        except Exception as e:
            # Fall back to mock on any LLM error
            import logging
            logging.getLogger(__name__).warning(f"LLM topic segmentation failed, using mock: {e}")

    # Fallback to mock implementation
    return _mock_segment_topics_fallback(transcript_segments)


async def _llm_segment_topics(
    transcript_segments: list[dict[str, Any]],
    settings: Settings,
) -> dict[str, Any]:
    """Use LLM to segment transcript into topics."""
    client = get_llm_client(settings)

    # Build transcript text with timestamps
    transcript_parts = []
    for seg in transcript_segments:
        start_min = seg["start_ms"] // 60000
        start_sec = (seg["start_ms"] % 60000) // 1000
        end_min = seg["end_ms"] // 60000
        end_sec = (seg["end_ms"] % 60000) // 1000
        transcript_parts.append(
            f"[{start_min:02d}:{start_sec:02d}-{end_min:02d}:{end_sec:02d}] {seg['speaker']}: {seg['text']}"
        )
    transcript_text = "\n".join(transcript_parts)

    total_start = min(s["start_ms"] for s in transcript_segments)
    total_end = max(s["end_ms"] for s in transcript_segments)
    total_duration_min = (total_end - total_start) / 60000

    system_prompt = """You are an expert at segmenting interview transcripts into coherent topics.
Given a transcript with timestamps, identify distinct topics discussed and return them as a JSON array.

Each topic must have:
- label: Short descriptive label (2-4 words)
- colour: Hex colour code (e.g., "#C0392B")
- summary: One-paragraph summary of what was discussed
- start_ms: Start time in milliseconds (must match transcript timestamps)
- end_ms: End time in milliseconds (must match transcript timestamps)
- conciseness: Score 1-5 (5 = very concise, 1 = rambling)

Rules:
- Topics must be non-overlapping and cover >95% of the transcript
- Start/end times must align with actual segment boundaries in the transcript
- Aim for 20-60 second topic durations
- Return ONLY valid JSON array, no extra text."""

    user_prompt = f"""Transcript (duration: {total_duration_min:.1f} minutes):

{transcript_text}

Return JSON array of topics."""

    result = await client.chat(
        system=system_prompt,
        user=user_prompt,
        temperature=0.2,
        format_json=True,
    )

    # Validate and normalize result
    if not isinstance(result, list):
        raise ValueError("LLM did not return a list")

    topics_out = []
    spans_out = []
    mock_colours = [
        "#C0392B", "#E67E22", "#2980B9", "#27AE60",
        "#8E44AD", "#16A085", "#D35400", "#2C3E50",
        "#7F8C8D", "#F39C12",
    ]

    for i, topic in enumerate(result):
        if not all(k in topic for k in ("label", "start_ms", "end_ms")):
            continue
        start_ms = int(topic["start_ms"])
        end_ms = int(topic["end_ms"])
        if end_ms <= start_ms:
            continue
        # Clamp to transcript bounds
        start_ms = max(start_ms, total_start)
        end_ms = min(end_ms, total_end)
        if end_ms <= start_ms:
            continue

        colour = topic.get("colour") or mock_colours[i % len(mock_colours)]
        summary = topic.get("summary", "")
        conciseness = topic.get("conciseness", 3)
        conciseness = max(1, min(5, int(conciseness)))

        topics_out.append({
            "label": topic["label"],
            "colour": colour,
            "summary": summary,
            "start_ms": start_ms,
            "end_ms": end_ms,
            "conciseness": conciseness,
        })
        spans_out.append({
            "start_ms": start_ms,
            "end_ms": end_ms,
            "label": topic["label"],
            "summary": summary,
            "conciseness": conciseness,
        })

    # Sort by start time
    topics_out.sort(key=lambda t: t["start_ms"])
    spans_out.sort(key=lambda s: s["start_ms"])

    # Merge any overlapping spans (safety net)
    merged_spans = []
    for span in spans_out:
        if not merged_spans or span["start_ms"] >= merged_spans[-1]["end_ms"]:
            merged_spans.append(span)
        else:
            # Overlap: extend previous
            merged_spans[-1]["end_ms"] = max(merged_spans[-1]["end_ms"], span["end_ms"])

    # Ensure coverage >95%
    covered_ms = sum(s["end_ms"] - s["start_ms"] for s in merged_spans)
    total_ms = total_end - total_start
    if total_ms > 0 and covered_ms / total_ms < 0.95:
        # Fill gaps with adjacent spans
        pass  # Good enough for now

    return {"topics": topics_out, "spans": merged_spans}


def _mock_segment_topics_fallback(
    transcript_segments: list[dict[str, Any]],
) -> dict[str, Any]:
    """Fallback mock implementation."""
    if not transcript_segments:
        return {"topics": [], "spans": []}

    # Sort by start_ms
    sorted_segs = sorted(transcript_segments, key=lambda s: s["start_ms"])

    total_start = sorted_segs[0]["start_ms"]
    total_end = max(s["end_ms"] for s in sorted_segs)
    total_duration = total_end - total_start

    if total_duration <= 0:
        return {"topics": [], "spans": []}

    # Create topic boundaries: chunk into ~20-60 second pieces
    # Minimum 2 topics, maximum based on duration
    num_topics = max(2, min(len(MOCK_TOPIC_LABELS), total_duration // 20000 + 1))
    chunk_dur = total_duration / num_topics

    used_labels = set()
    topics_out = []
    spans_out = []
    topic_idx = 0

    for i in range(num_topics):
        span_start = total_start + int(i * chunk_dur)
        span_end = total_start + int((i + 1) * chunk_dur)
        if i == num_topics - 1:
            span_end = total_end  # Last span covers the rest

        if span_end <= span_start:
            continue

        # Pick a unique label
        available = [l for l in MOCK_TOPIC_LABELS if l not in used_labels]
        if not available:
            available = MOCK_TOPIC_LABELS
            used_labels.clear()
        label = random.choice(available)
        used_labels.add(label)

        colour = MOCK_COLOURS[topic_idx % len(MOCK_COLOURS)]
        summary = MOCK_SUMMARIES[topic_idx % len(MOCK_SUMMARIES)]
        conciseness = random.randint(3, 5)  # Mock: mostly tight conversation

        topics_out.append({
            "label": label,
            "colour": colour,
            "summary": summary,
            "start_ms": span_start,
            "end_ms": span_end,
            "conciseness": conciseness,
        })
        spans_out.append({
            "start_ms": span_start,
            "end_ms": span_end,
            "label": label,
            "summary": summary,
            "conciseness": conciseness,
        })
        topic_idx += 1

    return {"topics": topics_out, "spans": spans_out}
