from __future__ import annotations

import numpy as np


def compute_noise_floor(
    rms_db: list[float],
    *,
    margin_db: float = 8.0,
) -> tuple[float, float]:
    """Compute noise floor (10th percentile) and VAD threshold from RMS-dB values.

    Args:
        rms_db: List of RMS energy values in dBFS.
        margin_db: Margin above noise floor for the VAD trigger (default 8 dB).

    Returns:
        (noise_floor_db, vad_threshold_db) tuple.
    """
    if not rms_db:
        return -100.0, -92.0

    arr = np.array(rms_db, dtype=np.float64)
    floor = float(np.percentile(arr, 10))
    threshold = floor + margin_db
    return floor, threshold
