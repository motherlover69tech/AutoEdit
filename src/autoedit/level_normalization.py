from __future__ import annotations

from collections.abc import Iterable, Mapping
from statistics import median
from typing import Any


def _row_get(row: Any, key: str) -> Any:
    """Read key from SQLAlchemy row, mapping, or lightweight test object."""
    if isinstance(row, Mapping):
        return row.get(key)
    return getattr(row, key, None)


def compute_level_normalization(
    channel_rows: Iterable[Any],
    *,
    max_gain_db: float = 24.0,
) -> dict[str, Any]:
    """Compute analysis-only gain offsets that align per-channel VAD thresholds.

    The processing pipeline uses per-channel noise floors/VAD thresholds so a
    quiet lav can still detect speech.  Cut dominance, however, compares levels
    between channels.  Comparing raw dBFS makes a hotter mic look dominant even
    when it is only recording bleed.  This stage aligns each channel's VAD
    threshold to the median project threshold, so later activity levels compare
    "dB above this channel's speech gate" rather than absolute recording level.

    Returns a JSON-serializable artifact written as audio/level_normalization.json.
    The gain is for analysis metadata only; it does not alter source WAVs or the
    browser/NLE program audio.
    """
    channels: list[dict[str, Any]] = []
    for row in channel_rows:
        channel_id = _row_get(row, "id")
        threshold = _row_get(row, "vad_threshold_db")
        if not channel_id or threshold is None:
            continue
        channels.append({
            "id": str(channel_id),
            "speaker_label": _row_get(row, "speaker_label"),
            "vad_threshold_db": float(threshold),
        })

    if not channels:
        raise ValueError("no channels with vad_threshold_db available")

    target = float(median(ch["vad_threshold_db"] for ch in channels))
    result_channels: dict[str, dict[str, Any]] = {}
    for ch in channels:
        raw_gain = target - ch["vad_threshold_db"]
        gain = max(-max_gain_db, min(max_gain_db, raw_gain))
        result_channels[ch["id"]] = {
            "speaker_label": ch["speaker_label"],
            "vad_threshold_db": round(ch["vad_threshold_db"], 3),
            "gain_db": round(float(gain), 3),
        }

    return {
        "version": 1,
        "strategy": "vad_threshold_alignment_v1",
        "description": (
            "Analysis-only gain offsets align channel VAD thresholds before "
            "activity levels are compared for cut dominance. Source WAVs and "
            "program audio are not modified."
        ),
        "target_threshold_db": round(target, 3),
        "max_gain_db": round(float(max_gain_db), 3),
        "channels": result_channels,
    }


def gain_for_channel(normalization: Mapping[str, Any] | None, channel_id: str) -> float:
    """Return analysis gain for channel_id from a normalization artifact."""
    if not normalization:
        return 0.0
    channel = (normalization.get("channels") or {}).get(channel_id) or {}
    try:
        return float(channel.get("gain_db") or 0.0)
    except (TypeError, ValueError):
        return 0.0
