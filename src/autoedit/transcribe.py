from __future__ import annotations

import math
import random
from collections.abc import Mapping
from pathlib import Path
from typing import Any

import httpx

from autoedit.config import Settings


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
        master_start = pos + start_ms
        master_end = end + start_ms
        if master_end <= 0:
            pos = end + random.randint(200, 2000)
            continue
        words = _generate_mock_words(text, max(0, master_start))
        words = [
            {**word, "end_ms": min(word["end_ms"], master_end)}
            for word in words
            if word["start_ms"] < master_end
        ]

        segments.append({
            "speaker": speaker_label,
            "start_ms": max(0, master_start),
            "end_ms": master_end,
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


def _seconds_to_ms(value: Any, *, field: str) -> int:
    """Validate finite non-negative seconds and convert to integer milliseconds."""
    if isinstance(value, bool) or not isinstance(value, (int, float)):
        raise ValueError(f"{field} must be a finite non-negative number")
    try:
        seconds = float(value)
    except (TypeError, ValueError) as exc:
        raise ValueError(f"{field} must be a finite non-negative number") from exc
    if not math.isfinite(seconds) or seconds < 0:
        raise ValueError(f"{field} must be a finite non-negative number")
    return int(round(seconds * 1000))


def resolve_shared_audio_path(audio_path: str | Path, data_root: str | Path) -> Path:
    """Resolve an audio path and confine it to a shared media root."""
    root = Path(data_root).resolve()
    candidate = Path(audio_path)
    if not candidate.is_absolute():
        candidate = root / candidate
    resolved = candidate.resolve()
    try:
        resolved.relative_to(root)
    except ValueError as exc:
        raise ValueError("audio_path must stay inside DATA_ROOT") from exc
    if not resolved.is_file():
        raise FileNotFoundError(f"audio file not found: {resolved}")
    return resolved


def normalize_whisperx_result(
    payload: dict[str, Any],
    *,
    start_ms: int,
    speaker_label: str,
) -> dict[str, Any]:
    """Normalize WhisperX output to AUTOEDIT's master-timeline contract.

    WhisperX emits seconds relative to the submitted WAV. ``start_ms`` is the
    already-converted source-to-master shift and is added exactly once. Source
    pre-roll before master zero is discarded/clipped rather than publishing
    negative timestamps. Some tokens cannot be force-aligned; those words are
    retained without invented timestamps.
    """
    raw_segments = payload.get("segments")
    if not isinstance(raw_segments, list):
        raise ValueError("WhisperX response must contain a segments list")

    timeline_offset = int(start_ms)
    normalized: list[dict[str, Any]] = []
    for segment_index, raw_segment in enumerate(raw_segments):
        if not isinstance(raw_segment, Mapping):
            raise ValueError(f"segments[{segment_index}] must be an object")
        if raw_segment.get("start") is None or raw_segment.get("end") is None:
            raise ValueError(f"segments[{segment_index}] must include start and end")

        source_start = _seconds_to_ms(
            raw_segment["start"], field=f"segments[{segment_index}].start"
        )
        source_end = _seconds_to_ms(
            raw_segment["end"], field=f"segments[{segment_index}].end"
        )
        if source_end <= source_start:
            raise ValueError(f"segments[{segment_index}] end must be after start")

        segment_start = source_start + timeline_offset
        segment_end = source_end + timeline_offset
        if segment_end <= 0:
            continue
        segment_start = max(0, segment_start)

        raw_words = raw_segment.get("words") or []
        if not isinstance(raw_words, list):
            raise ValueError(f"segments[{segment_index}].words must be a list")
        words: list[dict[str, Any]] = []
        for word_index, raw_word in enumerate(raw_words):
            if not isinstance(raw_word, Mapping):
                raise ValueError(
                    f"segments[{segment_index}].words[{word_index}] must be an object"
                )
            raw_text = raw_word.get("word", raw_word.get("w", ""))
            if not isinstance(raw_text, str):
                raise ValueError(
                    f"segments[{segment_index}].words[{word_index}].word must be a string"
                )
            text = raw_text.strip()
            if not text:
                continue
            word: dict[str, Any] = {"w": text}
            raw_word_start = raw_word.get("start")
            raw_word_end = raw_word.get("end")
            if (raw_word_start is None) != (raw_word_end is None):
                raise ValueError(
                    f"segments[{segment_index}].words[{word_index}] must include both start and end"
                )
            if raw_word_start is not None:
                word_start_source = _seconds_to_ms(
                    raw_word_start,
                    field=f"segments[{segment_index}].words[{word_index}].start",
                )
                word_end_source = _seconds_to_ms(
                    raw_word_end,
                    field=f"segments[{segment_index}].words[{word_index}].end",
                )
                if (
                    word_end_source <= word_start_source
                    or word_start_source < source_start
                    or word_end_source > source_end
                ):
                    raise ValueError(
                        f"segments[{segment_index}].words[{word_index}] timestamps "
                        "must be ordered and inside the segment"
                    )
                word_start = word_start_source + timeline_offset
                word_end = word_end_source + timeline_offset
                if word_end <= 0:
                    continue
                word["start_ms"] = max(segment_start, word_start, 0)
                word["end_ms"] = min(segment_end, word_end)
            confidence = raw_word.get("score", raw_word.get("confidence"))
            if confidence is not None:
                if isinstance(confidence, bool) or not isinstance(confidence, (int, float)):
                    raise ValueError(
                        f"segments[{segment_index}].words[{word_index}] confidence "
                        "must be between 0 and 1"
                    )
                try:
                    confidence_value = float(confidence)
                except (TypeError, ValueError) as exc:
                    raise ValueError(
                        f"segments[{segment_index}].words[{word_index}] confidence "
                        "must be between 0 and 1"
                    ) from exc
                if not math.isfinite(confidence_value) or not 0 <= confidence_value <= 1:
                    raise ValueError(
                        f"segments[{segment_index}].words[{word_index}] confidence "
                        "must be between 0 and 1"
                    )
                word["conf"] = confidence_value
            words.append(word)

        text = raw_segment.get("text", "")
        if not isinstance(text, str):
            raise ValueError(f"segments[{segment_index}].text must be a string")
        normalized.append({
            "speaker": speaker_label,
            "start_ms": segment_start,
            "end_ms": segment_end,
            "text": text.strip(),
            "words": words,
        })

    result: dict[str, Any] = {"segments": normalized}
    if payload.get("language"):
        result["language"] = payload["language"]
    return result


class WhisperXClient:
    """HTTP client for AUTOEDIT's internal WhisperX GPU service."""

    def __init__(
        self,
        settings: Settings | None = None,
        *,
        transport: httpx.BaseTransport | None = None,
    ) -> None:
        self.settings = settings or Settings()
        self.base_url = str(self.settings.whisperx_base_url).rstrip("/")
        self.transport = transport

    def transcribe(self, audio_path: str | Path) -> dict[str, Any]:
        path = Path(audio_path).resolve()
        payload = {
            "audio_path": str(path),
            "model": self.settings.whisper_model,
            "language": self.settings.whisper_language,
            "batch_size": self.settings.whisper_batch_size,
            "compute_type": self.settings.whisper_compute_type,
            "align": self.settings.whisper_align,
        }
        timeout = httpx.Timeout(
            self.settings.whisperx_timeout_seconds,
            connect=10.0,
        )
        try:
            with httpx.Client(timeout=timeout, transport=self.transport) as client:
                response = client.post(f"{self.base_url}/v1/transcribe", json=payload)
            response.raise_for_status()
            result = response.json()
        except httpx.HTTPStatusError as exc:
            try:
                detail = exc.response.json().get("detail", exc.response.text)
            except (ValueError, AttributeError):
                detail = exc.response.text
            raise RuntimeError(
                f"WhisperX service error {exc.response.status_code}: {detail}"
            ) from exc
        except (httpx.HTTPError, ValueError) as exc:
            raise RuntimeError(f"WhisperX request failed: {exc}") from exc
        if not isinstance(result, dict) or not isinstance(result.get("segments"), list):
            raise RuntimeError("WhisperX returned an invalid response: segments list missing")
        return result


def transcribe_with_backend(
    audio_path: str | Path,
    *,
    settings: Settings | None = None,
    start_ms: int = 0,
    speaker_label: str = "speaker",
    mock_sample_rate: int | None = None,
    mock_duration_samples: int | None = None,
    whisperx_client: WhisperXClient | None = None,
) -> dict[str, Any]:
    """Transcribe a WAV with the explicitly configured backend."""
    active_settings = settings or Settings()
    backend = active_settings.whisper_backend.strip().lower()
    if backend == "mock":
        if mock_sample_rate is None or mock_duration_samples is None:
            raise ValueError("mock backend requires WAV sample rate and duration")
        return mock_transcribe(
            mock_sample_rate,
            duration_samples=mock_duration_samples,
            start_ms=start_ms,
            speaker_label=speaker_label,
        )
    if backend == "whisperx":
        raw = (whisperx_client or WhisperXClient(active_settings)).transcribe(audio_path)
        return normalize_whisperx_result(
            raw,
            start_ms=start_ms,
            speaker_label=speaker_label,
        )
    raise ValueError(
        f"unsupported WHISPER_BACKEND={active_settings.whisper_backend!r}; "
        "expected 'mock' or 'whisperx'"
    )
