from __future__ import annotations

import math
from typing import Any

from autoedit.config import Settings
from autoedit.llm_client import get_llm_client


FILLER_WORDS = frozenset({
    "um", "uh", "er", "ah", "like", "you know", "i mean",
    "sort of", "kind of", "basically", "actually", "literally",
    "right", "okay", "so", "well", "anyway",
})


def _tokenize(text: str) -> list[str]:
    """Simple word tokenizer: lowercase, split on whitespace, strip punctuation."""
    return [w.strip(",.!?;:\"'()[]{}").lower() for w in text.split() if w.strip(",.!?;:\"'()[]{}")]


def _count_filler_ngrams(tokens: list[str]) -> int:
    """Count filler words (single + bigram)."""
    count = 0
    i = 0
    while i < len(tokens):
        # Check bigram first
        if i + 1 < len(tokens):
            bigram = f"{tokens[i]} {tokens[i+1]}"
            if bigram in FILLER_WORDS:
                count += 1
                i += 2
                continue
        # Check unigram
        if tokens[i] in FILLER_WORDS:
            count += 1
        i += 1
    return count


def compute_filler_density(text: str) -> float:
    """Ratio of filler words to total words. Returns 0..1."""
    tokens = _tokenize(text)
    if not tokens:
        return 0.0
    fillers = _count_filler_ngrams(tokens)
    return fillers / len(tokens)


def compute_word_rate(total_words: int, duration_ms: int) -> float:
    """Words per minute (WPM)."""
    if duration_ms <= 0:
        return 0.0
    return total_words * 60000.0 / duration_ms


def _clamp_score(score: float) -> int:
    return max(1, min(5, round(score)))


async def _llm_grade_conciseness(
    transcript_text: str,
    span_dur_ms: int,
    settings: Settings,
) -> dict[str, Any] | None:
    """Use LLM to grade conciseness of a topic span.

    Returns None if LLM is not available or fails.
    """
    if not transcript_text.strip():
        return None

    client = get_llm_client(settings)

    duration_sec = span_dur_ms / 1000

    system_prompt = """You are an expert at evaluating how concise and focused a spoken segment is.
Given a transcript segment and its duration, rate its conciseness on a scale of 1-5.

5 = Extremely concise: Every word adds value, no filler, tight delivery
4 = Very concise: Minor filler, but overall focused and efficient
3 = Moderate: Some rambling or filler, but generally on track
2 = Rambling: Significant filler, tangents, repetition
1 = Very rambling: Excessive filler, lost thread, hard to follow

Consider: filler words (um, uh, like, you know), repetition, tangents, circular explanations, information density.

Return ONLY valid JSON:
{
  "score": int (1-5),
  "rationale": "Brief explanation of the rating",
  "filler_density_estimate": float (0-1),
  "key_observations": string[]
}"""

    user_prompt = f"""Segment duration: {duration_sec:.1f} seconds

Transcript:
{transcript_text[:4000]}  # Truncate if too long

Rate conciseness 1-5."""

    try:
        result = await client.chat(
            system=system_prompt,
            user=user_prompt,
            temperature=0.2,
            format_json=True,
        )

        if isinstance(result, dict) and "score" in result:
            score = max(1, min(5, int(result["score"])))
            return {
                "llm_score": score,
                "llm_rationale": result.get("rationale", ""),
                "llm_filler_density": result.get("filler_density_estimate", 0.0),
                "llm_observations": result.get("key_observations", []),
            }
    except Exception as e:
        import logging
        logging.getLogger(__name__).warning(f"LLM conciseness grading failed: {e}")

    return None


def grade_conciseness(
    *,
    current_score: int,
    transcript_text: str,
    span_dur_ms: int,
    median_span_dur_ms: int,
) -> dict[str, Any]:
    """Compute a defensible conciseness grade for a topic span.

    Combines the LLM/mock score with deterministic signals:
      - filler word density (downgrade if high)
      - duration ratio vs median (downgrade if much longer, upgrade if shorter)
      - word rate (WPM)

    Args:
        current_score: Existing conciseness score (1-5) from the mock/LLM.
        transcript_text: Combined text of all transcript segments in this span.
        span_dur_ms: Duration of the span in milliseconds.
        median_span_dur_ms: Median duration across all spans.

    Returns:
        Dict with {
            conciseness: int (1-5),
            filler_density: float,
            word_rate_wpm: float,
            dur_ratio: float,
            rationale: str,
        }
    """
    tokens = _tokenize(transcript_text)
    word_count = len(tokens)

    filler_density = compute_filler_density(transcript_text) if transcript_text else 0.0
    word_rate = compute_word_rate(word_count, span_dur_ms) if word_count > 0 else 0.0
    dur_ratio = span_dur_ms / median_span_dur_ms if median_span_dur_ms > 0 else 1.0

    # Start from mock/LLM score
    score = float(current_score)

    # Try to get LLM score as well (async, but we'll run it synchronously here)
    # Note: In production, this should be called from an async context
    try:
        settings = Settings()
        if settings.llm_model and settings.ollama_base_url:
            import asyncio
            llm_result = asyncio.run(_llm_grade_conciseness(transcript_text, span_dur_ms, settings))
            if llm_result:
                # Blend LLM score with deterministic score (weighted average)
                llm_score = llm_result["llm_score"]
                score = (score * 0.4) + (llm_score * 0.6)
    except Exception:
        pass  # Use deterministic only

    # Downgrade for high filler density (>15% fillers = -2, >8% = -1)
    if filler_density > 0.15:
        score -= 2
    elif filler_density > 0.08:
        score -= 1

    # Adjust for duration vs median
    if dur_ratio > 2.0:
        score -= 1  # Much longer than median → rambling
    elif dur_ratio < 0.5:
        score += 1  # Much shorter → concise

    final = _clamp_score(score)

    # Build rationale
    parts = [f"score={final}"]
    parts.append(f"filler_density={filler_density:.0%}")
    parts.append(f"wpm={word_rate:.0f}")
    parts.append(f"dur_ratio={dur_ratio:.1f}x")
    if filler_density > 0.08:
        parts.append("high_filler_penalty")
    if dur_ratio > 2.0:
        parts.append("long_vs_median")
    elif dur_ratio < 0.5:
        parts.append("short_vs_median")

    return {
        "conciseness": final,
        "filler_density": round(filler_density, 4),
        "word_rate_wpm": round(word_rate, 1),
        "dur_ratio": round(dur_ratio, 2),
        "rationale": " | ".join(parts),
    }
