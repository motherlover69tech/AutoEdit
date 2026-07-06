from __future__ import annotations

import random
from typing import Any


def mock_diarize(
    sample_rate: int,
    *,
    duration_samples: int,
    num_speakers: int = 2,
) -> list[dict[str, Any]]:
    """Generate mock speaker diarization segments for testing.

    In production, replace this with pyannote.audio or WhisperX diarization.

    Args:
        sample_rate: Audio sample rate.
        duration_samples: Total number of audio samples.
        num_speakers: Number of speakers to generate segments for (default 2).

    Returns:
        List of {speaker, start_ms, end_ms} dicts sorted by start_ms.
    """
    total_ms = int(duration_samples * 1000 / sample_rate)
    if total_ms <= 0:
        return []

    segments = []
    pos = 0
    speaker_idx = 0
    while pos < total_ms:
        dur = random.randint(800, 4000)  # 0.8–4 second utterances
        end = min(pos + dur, total_ms)
        segments.append({
            "speaker": f"speaker_{speaker_idx % num_speakers}",
            "start_ms": pos,
            "end_ms": end,
        })
        pos = end
        speaker_idx += 1

    return segments
