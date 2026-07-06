from __future__ import annotations

import numpy as np


def compute_loudness_envelope(
    data: np.ndarray,
    *,
    sample_rate: int = 48000,
    hop_ms: int = 20,
) -> list[float]:
    """Compute RMS energy envelope in dBFS with a fixed hop size.

    Args:
        data: 1-D float64 audio samples (-1..1 range).
        sample_rate: Sample rate in Hz.
        hop_ms: Window hop in milliseconds (default 20 ms).

    Returns:
        List of dBFS values, one per hop window.
    """
    hop_samples = int(sample_rate * hop_ms / 1000)
    if hop_samples <= 0:
        return []

    num_windows = len(data) // hop_samples
    if num_windows == 0:
        return []

    result = []
    for i in range(num_windows):
        window = data[i * hop_samples : (i + 1) * hop_samples]
        rms = np.sqrt(np.mean(window ** 2))
        # Convert to dBFS: 20 * log10(rms), with floor at -100 dB
        if rms < 1e-10:
            db = -100.0
        else:
            db = 20.0 * np.log10(rms)
        result.append(float(db))

    return result
