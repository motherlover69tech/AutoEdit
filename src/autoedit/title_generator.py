from __future__ import annotations

import random


def generate_titles(
    summary: dict,
    *,
    count: int = 3,
) -> dict:
    """Generate YouTube title suggestions from a project summary.

    Args:
        summary: The summary.json dict with "topics" and "totals".
        count: Number of titles per category.

    Returns:
        {"titles": [{"type": "descriptive"|"clickbait"|"question"|"short", "text": "..."}]}
    """
    topics = summary.get("topics", [])
    totals = summary.get("totals", {})

    if not topics:
        return {"titles": []}

    topic_labels = [t["label"] for t in topics if t.get("label")]
    speakers = list(totals.get("speaker_time_ms", {}).keys())

    if not topic_labels:
        return {"titles": []}

    primary_topic = topic_labels[0]
    secondary_topic = topic_labels[1] if len(topic_labels) > 1 else None
    primary_speaker = speakers[0] if speakers else "Speaker"
    secondary_speaker = speakers[1] if len(speakers) > 1 else None

    total_minutes = _total_duration_minutes(totals)

    titles = []

    # ── Descriptive ────────────────────────────────────────────
    descriptive = [
        f"{primary_topic}: A Conversation with {primary_speaker}",
        f"Interview: {primary_speaker} on {primary_topic}",
    ]
    if secondary_topic and secondary_speaker:
        descriptive.append(f"{primary_topic} & {secondary_topic} — {primary_speaker} and {secondary_speaker}")
        descriptive.append(f"Inside {primary_topic}: {primary_speaker} and {secondary_speaker} Discuss")
    else:
        descriptive.append(f"Deep Dive: {primary_topic} with {primary_speaker}")
        descriptive.append(f"{primary_speaker} Explains {primary_topic}")

    if total_minutes:
        descriptive.append(f"{primary_topic} — {primary_speaker} ({total_minutes} min)")

    titles.extend(_pick(descriptive, "descriptive", count))

    # ── Clickbait ──────────────────────────────────────────────
    clickbait = [
        f"You Won't Believe What {primary_speaker} Said About {primary_topic}",
        f"The Truth About {primary_topic} Finally Revealed",
        f"{primary_speaker} Just Changed Everything We Know About {primary_topic}",
    ]
    if secondary_speaker:
        clickbait.append(f"{primary_speaker} vs {secondary_speaker}: Who's Right About {primary_topic}?")
        clickbait.append(f"Watch {secondary_speaker} React to {primary_topic}")
    clickbait.append(f"This {primary_topic} Discussion Will Change Your Mind")
    clickbait.append(f"Why Everyone's Talking About {primary_topic} Right Now")

    titles.extend(_pick(clickbait, "clickbait", count))

    # ── Question ───────────────────────────────────────────────
    questions = [
        f"Can We Really Trust What We Know About {primary_topic}?",
        f"Is {primary_speaker} Right About {primary_topic}?",
        f"What Does {primary_topic} Mean for the Future?",
    ]
    if secondary_speaker:
        questions.append(f"{primary_speaker} or {secondary_speaker}: Who Makes the Better Case on {primary_topic}?")
        questions.append(f"What Happened When {primary_speaker} Challenged {secondary_speaker} on {primary_topic}?")

    titles.extend(_pick(questions, "question", count))

    # ── Short / social ─────────────────────────────────────────
    shorts = [
        f"{primary_speaker} on {primary_topic} — 60 Seconds",
        f"The Key Moment on {primary_topic}",
    ]
    if secondary_topic:
        shorts.append(f"{primary_topic} + {secondary_topic} in 2 Minutes")
    shorts.append(f"{primary_speaker}'s Best Point on {primary_topic}")
    if secondary_speaker:
        shorts.append(f"{primary_speaker} & {secondary_speaker} on {primary_topic}")

    titles.extend(_pick(shorts, "short", count))

    return {"titles": titles}


def _pick(pool: list[str], kind: str, count: int) -> list[dict]:
    """Pick 'count' items from pool, shuffling for variety."""
    rng = random.Random(hash(pool[0] + kind))
    selected = rng.sample(pool, min(count, len(pool)))
    return [{"type": kind, "text": t} for t in selected]


def _total_duration_minutes(totals: dict) -> int | None:
    """Estimate total duration in minutes from speaker times."""
    speaker_ms = totals.get("speaker_time_ms", {})
    total_ms = sum(speaker_ms.values()) + totals.get("talk_overlap_ms", 0) + totals.get("silence_ms", 0)
    if total_ms <= 0:
        # Fallback: just speaker time
        total_ms = sum(speaker_ms.values())
    if total_ms <= 0:
        return None
    minutes = round(total_ms / 60000)
    return max(1, minutes)
