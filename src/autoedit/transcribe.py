from __future__ import annotations

import random
from typing import Any


MOCK_PHRASES = [
    "So tell me about your background.",
    "I started working in this field about ten years ago.",
    "That's a really interesting perspective.",
    "Could you elaborate on that point?",
    "I think the key insight here is fairly simple.",
    "Let me give you a concrete example.",
    "The results were quite surprising, to be honest.",
    "We decided to take a different approach after that.",
    "What do you think the long-term implications are?",
    "I'd love to hear more about your experience with that.",
    "Looking back, that was absolutely the right decision.",
    "The timeline was incredibly tight on that project.",
    "Nobody expected it to work the first time around.",
    "That's when everything changed for us.",
    "We learned a lot from that particular failure.",
]


def mock_transcribe(
    sample_rate: int,
    *,
    duration_samples: int,
    start_ms: int = 0,
    speaker_label: str = "speaker",
) -> dict[str, Any]:
    """Generate mock transcription segments for testing.

    In production, replace this with faster-whisper or whisper.cpp via
    the WHISPER_BACKEND / WHISPER_MODEL configuration.

    Args:
        sample_rate: Audio sample rate in Hz.
        duration_samples: Total number of audio samples.
        start_ms: Timeline offset for this channel (sync_offset_ms).
        speaker_label: Label for the speaker (e.g. 'presenter', 'interviewee').

    Returns:
        Dict with 'segments' list of {speaker, start_ms, end_ms, text, words}.
        All times are on the master timeline (start_ms already applied).
    """
    total_ms = int(duration_samples * 1000 / sample_rate)
    if total_ms <= 0:
        return {"segments": []}

    segments = []
    pos = 0
    while pos < total_ms:
        # Utterance length: 1–8 seconds
        dur = random.randint(1000, 8000)
        end = min(pos + dur, total_ms)

        text = random.choice(MOCK_PHRASES)
        words = _generate_mock_words(text, pos + start_ms)

        segments.append({
            "speaker": speaker_label,
            "start_ms": pos + start_ms,
            "end_ms": end + start_ms,
            "text": text,
            "words": words,
        })

        # Gap between utterances: 200–2000ms
        pos = end + random.randint(200, 2000)

    return {"segments": segments}


def _generate_mock_words(
    text: str,
    segment_start_ms: int,
) -> list[dict[str, Any]]:
    """Generate per-word timestamps distributed evenly across the text."""
    words = text.split()
    if not words:
        return []

    # Assume ~150ms per word average, distribute evenly
    total_word_ms = len(words) * 150
    result = []
    for i, w in enumerate(words):
        w_start = segment_start_ms + int(i * total_word_ms / len(words))
        w_end = segment_start_ms + int((i + 1) * total_word_ms / len(words))
        result.append({
            "w": w,
            "start_ms": w_start,
            "end_ms": w_end,
            "conf": round(random.uniform(0.85, 0.99), 2),
        })

    return result
