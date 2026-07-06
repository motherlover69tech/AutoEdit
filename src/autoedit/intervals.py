from __future__ import annotations

import numpy as np


def compute_speaking_intervals(
    rms_db: list[float],
    *,
    hop_ms: int = 20,
    threshold_db: float = -40.0,
    hangover_ms: int = 300,
    min_duration_ms: int = 150,
    start_ms: int = 0,
) -> list[dict[str, float]]:
    """Turn a loudness envelope into clean speaking intervals.

    Args:
        rms_db: RMS energy values in dBFS, one per hop window.
        hop_ms: Window hop in milliseconds.
        threshold_db: dBFS threshold — values above this count as speech.
        hangover_ms: Merge gaps shorter than this between two speech runs.
        min_duration_ms: Drop bursts shorter than this (lip smacks, coughs).
        start_ms: Timeline offset to add to all returned times.

    Returns:
        List of {start_ms, end_ms, mean_db, peak_db} dicts sorted by start_ms.
    """
    if not rms_db:
        return []

    hangover_hops = max(1, int(hangover_ms / hop_ms))
    min_hops = max(1, int(min_duration_ms / hop_ms))

    # Mark each hop as speech or not
    is_speech = np.array(rms_db, dtype=np.float64) > threshold_db

    # Build raw runs first, then merge adjacent runs separated by short gaps.
    # Find all speech runs
    runs: list[tuple[int, int]] = []  # (start_idx, end_idx) exclusive end
    in_run = False
    run_start = 0
    for i in range(len(is_speech)):
        if is_speech[i]:
            if not in_run:
                in_run = True
                run_start = i
        else:
            if in_run:
                runs.append((run_start, i))
                in_run = False
    if in_run:
        runs.append((run_start, len(is_speech)))

    # Drop runs shorter than min_hops
    runs = [(s, e) for s, e in runs if (e - s) >= min_hops]

    if not runs:
        return []

    # Merge runs separated by short gaps (≤ hangover_hops)
    merged_runs: list[tuple[int, int]] = [runs[0]]
    for run in runs[1:]:
        prev_start, prev_end = merged_runs[-1]
        gap = run[0] - prev_end
        if gap <= hangover_hops:
            # Merge: extend the previous run
            merged_runs[-1] = (prev_start, run[1])
        else:
            merged_runs.append(run)

    # Convert to output format
    intervals = []
    for s, e in merged_runs:
        segment = rms_db[s:e]
        intervals.append({
            "start_ms": s * hop_ms + start_ms,
            "end_ms": e * hop_ms + start_ms,
            "mean_db": round(float(np.mean(segment)), 2),
            "peak_db": round(float(np.max(segment)), 2),
        })

    return intervals
