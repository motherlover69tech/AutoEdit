from __future__ import annotations

import re
from typing import Any

from autoedit.config import Settings
from autoedit.llm_client import get_llm_client


def parse_sub_edit_intent(
    prompt: str,
    known_topics: list[str],
) -> dict:
    """Parse a natural-language sub-edit request into structured params.

    Args:
        prompt: Natural language request (e.g. "one minute about budget").
        known_topics: List of known topic labels in the project.

    Returns:
        {"confident": True, "params": {...}} on success,
        {"confident": False, "reason": "...", "suggestions": [...]} on ambiguity.
    """
    text = prompt.strip()
    if not text:
        return {"confident": False, "reason": "Empty prompt.", "suggestions": []}

    # Try LLM-based parsing first
    settings = Settings()
    if settings.llm_model and settings.ollama_base_url:
        try:
            import asyncio
            return asyncio.run(_llm_parse_sub_edit_intent(prompt, known_topics, settings))
        except Exception as e:
            # Fall back to deterministic parser on any LLM error
            import logging
            logging.getLogger(__name__).warning(f"LLM NL parsing failed, using deterministic parser: {e}")

    # Fallback to deterministic parser
    return _deterministic_parse_sub_edit_intent(prompt, known_topics)


async def _llm_parse_sub_edit_intent(
    prompt: str,
    known_topics: list[str],
    settings: Settings,
) -> dict:
    """Use LLM to parse natural language sub-edit request."""
    client = get_llm_client(settings)

    system_prompt = """You are an expert at parsing natural language video editing requests.
Given a user's prompt and a list of available topics, extract structured parameters for creating a sub-edit.

Return ONLY valid JSON with this schema:
{
  "confident": boolean,
  "params": {
    "mode": "by_topics" | "minus_topics" | "custom_ranges",
    "topic_labels": string[] | null,
    "exclude_labels": string[] | null,
    "ranges": [{"start_ms": int, "end_ms": int}] | null,
    "target_duration_secs": int | null
  },
  "reason": string | null,
  "suggestions": string[]
}

Modes:
- "by_topics": User wants a cut ABOUT specific topics (include these)
- "minus_topics": User wants everything EXCEPT specific topics (exclude these)
- "custom_ranges": User specifies explicit time ranges

Extract target_duration_secs from phrases like "2 minutes", "90 seconds", "one minute", etc.
Extract time ranges from formats like "12:00", "12:00-14:00", "from 12:00 to 14:00"."""

    topics_list = ", ".join(f'"{t}"' for t in known_topics)
    user_prompt = f"""Available topics: [{topics_list}]

User request: "{prompt}"

Parse this request and return the JSON structure."""

    result = await client.chat(
        system=system_prompt,
        user=user_prompt,
        temperature=0.1,
        format_json=True,
    )

    # Validate result
    if not isinstance(result, dict):
        raise ValueError("LLM did not return a dict")

    confident = result.get("confident", False)
    params = result.get("params", {})
    reason = result.get("reason")
    suggestions = result.get("suggestions", [])

    if not confident:
        return {"confident": False, "reason": reason or "LLM not confident", "suggestions": suggestions}

    # Validate params structure
    mode = params.get("mode")
    if mode not in ("by_topics", "minus_topics", "custom_ranges"):
        raise ValueError(f"Invalid mode from LLM: {mode}")

    # Validate topic labels against known topics
    if params.get("topic_labels"):
        params["topic_labels"] = [t for t in params["topic_labels"] if t in known_topics]
    if params.get("exclude_labels"):
        params["exclude_labels"] = [t for t in params["exclude_labels"] if t in known_topics]

    return {"confident": True, "params": params}


def _deterministic_parse_sub_edit_intent(
    prompt: str,
    known_topics: list[str],
) -> dict:
    """Original deterministic parser (kept as fallback)."""
    text = prompt.strip()
    if not text:
        return {"confident": False, "reason": "Empty prompt.", "suggestions": []}

    text_lower = text.lower()

    # ── Extract target duration ────────────────────────────────
    target_duration_secs = None
    _word_nums = {"one": 1, "two": 2, "three": 3, "four": 4, "five": 5, "six": 6, "seven": 7, "eight": 8, "nine": 9, "ten": 10}
    dur_patterns = [
        (r"(\d+)\s*(?:minute|min)s?", 60),
        (r"(\d+)\s*(?:second|sec)s?", 1),
        (r"(\d+)\s*(?:min|m)(?:\s|$)", 60),
    ]
    # Also match word numbers: "one minute", "two minutes"
    for word, val in _word_nums.items():
        dur_patterns.append((fr"({word})\s*(?:minute|min)s?", val * 60))
        dur_patterns.append((fr"({word})\s*(?:second|sec)s?", val))
    for pat, multiplier in dur_patterns:
        m = re.search(pat, text_lower)
        if m:
            try:
                target_duration_secs = int(m.group(1)) * multiplier
            except ValueError:
                target_duration_secs = _word_nums.get(m.group(1), 0) * multiplier
            break

    # ── Extract time ranges (HH:MM or HH:MM:SS) ────────────────
    time_pattern = r"(\d{1,2}):(\d{2})(?::(\d{2}))?"
    times = re.findall(time_pattern, text)
    custom_ranges = []
    if len(times) >= 2:
        # Use first two timestamps as start/end
        h1, m1, s1 = int(times[0][0]), int(times[0][1]), int(times[0][2] or 0)
        h2, m2, s2 = int(times[1][0]), int(times[1][1]), int(times[1][2] or 0)
        start_ms = (h1 * 3600 + m1 * 60 + s1) * 1000
        end_ms = (h2 * 3600 + m2 * 60 + s2) * 1000
        if end_ms > start_ms:
            custom_ranges.append({"start_ms": start_ms, "end_ms": end_ms})

    if custom_ranges:
        return {
            "confident": True,
            "params": {
                "mode": "custom_ranges",
                "ranges": custom_ranges,
                "target_duration_secs": target_duration_secs,
            },
        }

    # ── Determine mode ──────────────────────────────────────────
    minus_patterns = [
        r"(?:everything|full\s*edit|all)\s+(?:except|minus|without|but\s+not|excluding)\s+(.+)",
        r"(?:minus|without|skip|exclude|remove|drop)\s+(.+)",
        r"cut\s+out\s+(.+)",
    ]

    mode = "by_topics"
    search_text = text

    for pat in minus_patterns:
        m = re.search(pat, text_lower)
        if m:
            mode = "minus_topics"
            search_text = m.group(1)
            break

    # ── Extract topic labels via fuzzy matching ─────────────────
    # Clean up search text: remove common filler words
    about_patterns = [
        r"(?:about|on|regarding|covering|around)\s+(.+)",
        r"(?:make|give|create|generate)\s+(?:me\s+)?(?:a\s+)?(?:\d+\s*(?:minute|second|min|sec)s?\s+)?(?:cut|clip|edit|version|sub-?edit)?\s*(?:about|on|of)?\s*(.+)",
        r"(?:i\s+want|i'd\s+like|please)\s+(?:a\s+)?(?:\d+\s*(?:minute|second|min|sec)s?\s+)?(?:cut|clip|edit|version|sub-?edit)?\s*(?:about|on|of)?\s*(.+)",
    ]

    for pat in about_patterns:
        m = re.search(pat, search_text)
        if m:
            search_text = m.group(1).strip()
            break

    # Remove duration mentions from search text
    search_text = re.sub(r"\d+\s*(?:minute|min|second|sec|m|s)s?", "", search_text, flags=re.IGNORECASE).strip()

    if not search_text:
        if mode == "minus_topics":
            search_text = text
        else:
            return {"confident": False, "reason": "Could not determine what topics you want.", "suggestions": known_topics[:5]}

    # ── Fuzzy match against known topics ────────────────────────
    matched = _fuzzy_match_topics(search_text, known_topics)

    if not matched:
        return {
            "confident": False,
            "reason": f"No topics matched '{search_text}'. Available topics: {', '.join(known_topics[:8])}",
            "suggestions": _fuzzy_match_topics(search_text, known_topics, threshold=0.2)[:5],
        }

    params: dict = {
        "mode": mode,
        "target_duration_secs": target_duration_secs,
    }

    if mode == "by_topics":
        params["topic_labels"] = matched
    else:
        params["exclude_labels"] = matched

    return {"confident": True, "params": params}


def _fuzzy_match_topics(
    query: str,
    topics: list[str],
    threshold: float = 0.4,
) -> list[str]:
    """Find topics that fuzzy-match the query string.

    Uses substring matching and word-overlap scoring.
    """
    query_lower = query.lower()
    query_words = set(query_lower.split())

    scored = []
    for topic in topics:
        topic_lower = topic.lower()

        # Exact substring match → highest score
        if query_lower in topic_lower or topic_lower in query_lower:
            scored.append((topic, 1.0))
            continue

        # Word overlap
        topic_words = set(topic_lower.split())
        overlap = query_words & topic_words
        if overlap:
            score = len(overlap) / max(len(query_words), len(topic_words))
            scored.append((topic, score))
            continue

        # Partial word match (e.g. "budget" in "budget discussion")
        for qw in query_words:
            if len(qw) >= 3:
                for tw in topic_words:
                    if len(tw) >= 3 and (qw in tw or tw in qw):
                        scored.append((topic, 0.35))
                        break
                else:
                    continue
                break

    # Sort by score descending
    scored.sort(key=lambda x: x[1], reverse=True)
    return [topic for topic, score in scored if score >= threshold]
