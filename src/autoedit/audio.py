from __future__ import annotations

from pathlib import Path

import numpy as np
from scipy import signal as scipy_signal

from autoedit.ffproc import run_ffmpeg_watchdog


class SyncQualityError(RuntimeError):
    """Raised when automatic audio alignment is too weak to trust."""

    def __init__(self, angle_id: str, *, quality: float, threshold: float) -> None:
        self.angle_id = angle_id
        self.quality = float(quality)
        self.threshold = float(threshold)
        super().__init__(
            f"sync_quality_low: angle {angle_id} matched with quality "
            f"{self.quality:.2f}, below required {self.threshold:.2f}"
        )


def bandpass_filter(
    data: np.ndarray,
    sample_rate: float,
    *,
    low: float = 300.0,
    high: float = 3000.0,
    order: int = 5,
) -> np.ndarray:
    nyquist = sample_rate / 2.0
    low_norm = low / nyquist
    high_norm = high / nyquist
    if high_norm >= 1.0:
        high_norm = 0.99
    b, a = scipy_signal.butter(order, [low_norm, high_norm], btype="band")
    # Keep long-form sync memory bounded.  The live app syncs 90+ minute
    # guide tracks; after chunked 48 kHz -> 8 kHz downsampling, the arrays are
    # small enough to filter stably in float64 and cast back to float32.
    data32 = np.asarray(data, dtype=np.float32)
    return scipy_signal.lfilter(b, a, data32).astype(np.float32, copy=False)


def downsample(data: np.ndarray, orig_rate: int, target_rate: int = 8000) -> np.ndarray:
    if orig_rate == target_rate:
        return data
    num_samples = int(len(data) * target_rate / orig_rate)
    return scipy_signal.resample(data, num_samples)


def _read_wav_float(path: Path, target_sample_rate: int | None = None) -> tuple[np.ndarray, int]:
    """Read PCM WAV audio as mono float32, optionally downsampling while reading.

    Large AUTOEDIT guide tracks can be ~90 minutes long.  Reading the whole
    48 kHz WAV into float64 and then resampling creates many multi-GB arrays;
    for sync we only need an 8 kHz speech-band signal, so downsample in chunks
    before concatenating.
    """
    import wave as _wave

    chunks: list[np.ndarray] = []
    with _wave.open(str(path), "rb") as wf:
        nchannels = wf.getnchannels()
        sampwidth = wf.getsampwidth()
        framerate = wf.getframerate()
        out_rate = target_sample_rate or framerate
        # 30 seconds per chunk keeps peak temporary arrays small while avoiding
        # thousands of tiny concatenations.
        frames_per_chunk = max(1, int(framerate * 30))
        remainder = np.empty(0, dtype=np.float32)
        integer_ratio = framerate // out_rate if target_sample_rate and framerate % out_rate == 0 else None

        while True:
            raw = wf.readframes(frames_per_chunk)
            if not raw:
                break
            if sampwidth == 2:
                samples = np.frombuffer(raw, dtype=np.int16).astype(np.float32) / np.float32(32768.0)
            elif sampwidth == 4:
                samples = np.frombuffer(raw, dtype=np.int32).astype(np.float32) / np.float32(2147483648.0)
            else:
                raise ValueError(f"unsupported sample width: {sampwidth}")
            if nchannels > 1:
                samples = samples.reshape(-1, nchannels).mean(axis=1, dtype=np.float32)

            if target_sample_rate is not None and target_sample_rate != framerate:
                if integer_ratio is not None:
                    if remainder.size:
                        samples = np.concatenate([remainder, samples])
                    keep = (samples.size // integer_ratio) * integer_ratio
                    if keep:
                        chunks.append(
                            samples[:keep]
                            .reshape(-1, integer_ratio)
                            .mean(axis=1, dtype=np.float32)
                            .astype(np.float32, copy=False)
                        )
                    remainder = samples[keep:].astype(np.float32, copy=False)
                else:
                    # Rare non-integer-rate fallback.  This can still allocate
                    # more, but normal AUTOEDIT guides are 48k -> 8k.
                    chunks.append(samples.astype(np.float32, copy=False))
            else:
                chunks.append(samples.astype(np.float32, copy=False))

        if target_sample_rate is not None and target_sample_rate != framerate:
            if integer_ratio is not None:
                if remainder.size:
                    chunks.append(np.array([float(remainder.mean())], dtype=np.float32))
            elif chunks:
                data = np.concatenate(chunks).astype(np.float32, copy=False)
                data = downsample(data, framerate, target_sample_rate).astype(np.float32, copy=False)
                return data, target_sample_rate

    if not chunks:
        return np.empty(0, dtype=np.float32), target_sample_rate or framerate
    return np.concatenate(chunks).astype(np.float32, copy=False), target_sample_rate or framerate


def _energy_envelope(data: np.ndarray, sample_rate: int, window_ms: int = 50) -> np.ndarray:
    """Compute RMS energy envelope with given window size."""
    window_samples = max(1, int(window_ms * sample_rate / 1000))
    num_windows = len(data) // window_samples
    if num_windows == 0:
        if len(data) == 0:
            return np.array([0.0])
        return np.array([np.sqrt(np.mean(data**2))])
    trimmed = data[:num_windows * window_samples]
    squared = trimmed.reshape(num_windows, window_samples) ** 2
    return np.sqrt(squared.mean(axis=1))


def _normalize_envelope(envelope: np.ndarray) -> np.ndarray:
    """Robustly normalize an RMS envelope so camera mic quality matters less."""
    envelope = np.asarray(envelope, dtype=np.float64)
    envelope = np.nan_to_num(envelope, nan=0.0, posinf=0.0, neginf=0.0)
    # Compress very loud peaks so a camera limiter or clipped clap does not dominate.
    envelope = np.log1p(np.maximum(envelope, 0.0))
    median = float(np.median(envelope))
    mad = float(np.median(np.abs(envelope - median)))
    if mad > 1e-9:
        return (envelope - median) / (1.4826 * mad)
    std = float(envelope.std())
    if std > 1e-9:
        return (envelope - float(envelope.mean())) / std
    return np.zeros_like(envelope)


def _correlation_quality(corr: np.ndarray) -> float:
    abs_corr = np.abs(np.asarray(corr, dtype=np.float64))
    if abs_corr.size == 0:
        return 0.0
    peak_val = float(abs_corr.max())
    median_val = float(np.median(abs_corr))
    return peak_val / (median_val + 1e-10)


def _full_envelope_offset(
    env_ref: np.ndarray,
    env_other: np.ndarray,
    *,
    window_ms: int,
) -> tuple[int, float]:
    """Legacy full-track envelope correlation, preserving sign convention."""
    ref_norm = _normalize_envelope(env_ref)
    other_norm = _normalize_envelope(env_other)
    corr = scipy_signal.correlate(ref_norm, other_norm, mode="full", method="fft")
    peak_idx = int(np.argmax(np.abs(corr)))
    center = len(ref_norm) - 1
    env_lag = peak_idx - center
    return round(env_lag * window_ms), _correlation_quality(corr)


def _window_sync_candidates(
    env_ref: np.ndarray,
    env_other: np.ndarray,
    *,
    window_ms: int,
    window_seconds: float = 60.0,
    max_windows: int = 16,
) -> list[tuple[int, float]]:
    """Correlate high-information reference windows against the other track.

    Full-track correlation is easily pulled around by different pre-roll/post-roll,
    long silence, or one camera's noisy mic.  Windowed matching produces multiple
    offset votes from energetic sections; the caller clusters them and rejects
    outliers.
    """
    min_len = min(len(env_ref), len(env_other))
    if min_len < 20:
        return []

    requested_frames = max(20, round(window_seconds * 1000 / window_ms))
    # For short clips/tests, use a smaller but still meaningful window.
    window_frames = min(requested_frames, max(20, min_len // 2))
    if window_frames >= len(env_ref) or window_frames > len(env_other):
        return []

    ref_norm = _normalize_envelope(env_ref)
    other_norm = _normalize_envelope(env_other)
    step = max(1, window_frames // 2)
    starts = list(range(0, len(ref_norm) - window_frames + 1, step))
    if not starts:
        return []

    scored_starts: list[tuple[float, int]] = []
    for start in starts:
        segment = ref_norm[start:start + window_frames]
        # Prefer sections with changing speech/activity, not flat silence.
        score = float(segment.std()) * float(np.mean(np.abs(segment)))
        if score > 1e-6:
            scored_starts.append((score, start))
    scored_starts.sort(reverse=True)

    selected: list[int] = []
    min_separation = max(1, window_frames // 2)
    for _score, start in scored_starts:
        if all(abs(start - existing) >= min_separation for existing in selected):
            selected.append(start)
        if len(selected) >= max_windows:
            break

    candidates: list[tuple[int, float]] = []
    for start in selected:
        segment = ref_norm[start:start + window_frames]
        corr = scipy_signal.correlate(other_norm, segment, mode="valid", method="fft")
        if corr.size == 0:
            continue
        other_start = int(np.argmax(np.abs(corr)))
        # Sign convention matches _full_envelope_offset/find_sync_offset:
        # positive means the reference is delayed relative to the other;
        # negative means the other is delayed relative to the reference.
        offset_frames = start - other_start
        candidates.append((round(offset_frames * window_ms), _correlation_quality(corr)))
    return candidates


def _cluster_offset_candidates(
    candidates: list[tuple[int, float]],
    *,
    min_quality: float,
    tolerance_ms: int = 250,
) -> tuple[int, float] | None:
    good = [(offset, quality) for offset, quality in candidates if quality >= min_quality]
    if len(good) < 2:
        return None

    good.sort(key=lambda item: item[0])
    clusters: list[list[tuple[int, float]]] = []
    for candidate in good:
        offset, _quality = candidate
        placed = False
        for cluster in clusters:
            cluster_center = float(np.median([entry[0] for entry in cluster]))
            if abs(offset - cluster_center) <= tolerance_ms:
                cluster.append(candidate)
                placed = True
                break
        if not placed:
            clusters.append([candidate])

    # Prefer repeated agreement over a single loud/false peak.
    best = max(clusters, key=lambda cluster: (len(cluster), sum(q for _o, q in cluster)))
    if len(best) < 2:
        return None
    offsets = [offset for offset, _quality in best]
    qualities = [quality for _offset, quality in best]
    return int(round(float(np.median(offsets)) / 50.0) * 50), float(np.median(qualities))


def _transient_envelope(data: np.ndarray, sample_rate: int, frame_ms: int = 5) -> np.ndarray:
    """High-frequency transient envelope for claps/slates.

    The speech-band RMS envelope is good for long-form matching, but repeated
    claps can pull it to a later spike.  This envelope normalises gain/noise and
    emphasises sharp waveform onsets so the sync anchor can be the first clap
    onset instead of the loudest repeated clap.
    """
    if len(data) == 0:
        return np.array([], dtype=np.float64)
    nyquist = sample_rate / 2.0
    low = min(800.0 / nyquist, 0.95)
    high = min(3500.0 / nyquist, 0.98)
    if high <= low:
        high = min(0.98, low + 0.02)
    b, a = scipy_signal.butter(4, [low, high], btype="band")
    filtered = scipy_signal.lfilter(b, a, data)
    rectified = np.abs(filtered)
    frame_samples = max(1, int(sample_rate * frame_ms / 1000))
    frames = len(rectified) // frame_samples
    if frames == 0:
        return np.array([0.0], dtype=np.float64)
    envelope = rectified[:frames * frame_samples].reshape(frames, frame_samples).mean(axis=1)
    scale = float(np.percentile(envelope, 90)) + 1e-9
    envelope = np.log1p(envelope / scale)
    median = float(np.median(envelope))
    mad = float(np.median(np.abs(envelope - median)))
    if mad > 1e-9:
        return (envelope - median) / (1.4826 * mad)
    std = float(envelope.std())
    if std > 1e-9:
        return (envelope - float(envelope.mean())) / std
    return np.zeros_like(envelope)


def _transient_bursts(envelope: np.ndarray, frame_ms: int = 5) -> list[list[dict[str, float]]]:
    if envelope.size < 3:
        return []
    peaks, props = scipy_signal.find_peaks(
        envelope,
        distance=max(1, round(30 / frame_ms)),
        prominence=5.0,
        height=5.0,
    )
    items = [
        {
            "idx": float(int(idx)),
            "t": float(idx * frame_ms / 1000.0),
            "h": float(height),
            "p": float(prominence),
        }
        for idx, height, prominence in zip(peaks, props["peak_heights"], props["prominences"], strict=True)
    ]
    bursts: list[list[dict[str, float]]] = []
    current: list[dict[str, float]] = []
    for item in items:
        if not current or item["t"] - current[-1]["t"] <= 0.75:
            current.append(item)
        else:
            if len(current) >= 3 and current[-1]["t"] - current[0]["t"] <= 2.5:
                bursts.append(current)
            current = [item]
    if len(current) >= 3 and current[-1]["t"] - current[0]["t"] <= 2.5:
        bursts.append(current)
    return bursts


def _burst_score(burst: list[dict[str, float]]) -> float:
    heights = np.array([peak["h"] for peak in burst], dtype=np.float64)
    prominences = np.array([peak["p"] for peak in burst], dtype=np.float64)
    duration = max(float(burst[-1]["t"] - burst[0]["t"]), 0.1)
    return float((len(burst) ** 0.8) * np.percentile(heights, 70) * np.percentile(prominences, 70) / (1.0 + duration * 0.25))


def _first_reference_clap_peak(burst: list[dict[str, float]]) -> dict[str, float]:
    """First main spike in the reference burst.

    Camera scratch tracks often include tiny handling/pre-clap ticks immediately
    before the slate/clap.  For the reference we skip those and start from the
    first clearly visible spike.
    """
    threshold = max(9.5, 0.25 * max(peak["h"] for peak in burst))
    for peak in burst:
        if peak["h"] >= threshold and peak["p"] >= 5.0:
            return peak
    return max(burst, key=lambda peak: peak["h"])


def _first_other_clap_peak(burst: list[dict[str, float]]) -> dict[str, float]:
    """First sync spike in a non-reference burst.

    If the first peak is a weak pickup of the same first clap, keep it.  If the
    burst starts with low precursors before the main clap pattern, skip them.
    This handles the cab sync project: the presenter camera hears the first clap
    weakly, while the audio-source camera has a couple of low pre-transients
    before the first real clap spike.
    """
    max_height = max(peak["h"] for peak in burst)
    first = burst[0]
    if first["h"] >= 8.0 and first["h"] < 0.25 * max_height:
        return first
    threshold = max(8.0, 0.40 * max_height)
    for peak in burst:
        if peak["h"] >= threshold and peak["p"] >= 5.0:
            return peak
    for peak in burst:
        if peak["h"] >= 8.0 and peak["p"] >= 5.0:
            return peak
    return max(burst, key=lambda peak: peak["h"])


def _transient_onset(envelope: np.ndarray, peak_idx: int, frame_ms: int = 5) -> float:
    peak_value = float(envelope[peak_idx])
    lookback = max(1, round(1000 / frame_ms))
    baseline = float(np.percentile(envelope[max(0, peak_idx - lookback):peak_idx], 20)) if peak_idx > 0 else 0.0
    threshold = baseline + (peak_value - baseline) * 0.35
    pos = peak_idx
    max_walk = max(1, round(500 / frame_ms))
    while pos > 0 and pos > peak_idx - max_walk and envelope[pos] > threshold:
        pos -= 1
    return float((pos + 1) * frame_ms)


def _matching_transient_burst_offset(
    reference: np.ndarray,
    other: np.ndarray,
    sample_rate: int,
    *,
    base_offset_ms: int | None = None,
    frame_ms: int = 5,
) -> tuple[int, float] | None:
    """Return a clap/slate onset offset when a shared transient burst is found."""
    ref_env = _transient_envelope(reference, sample_rate, frame_ms)
    other_env = _transient_envelope(other, sample_rate, frame_ms)
    ref_bursts = _transient_bursts(ref_env, frame_ms)
    other_bursts = _transient_bursts(other_env, frame_ms)
    if not ref_bursts or not other_bursts:
        return None

    # Prefer the earliest strong reference burst after camera handling noise, not
    # necessarily the loudest later clap/speech burst.
    scored_ref = [(burst, _burst_score(burst)) for burst in ref_bursts if burst[0]["t"] >= 20.0]
    if not scored_ref:
        scored_ref = [(burst, _burst_score(burst)) for burst in ref_bursts]
    best_ref_score = max(score for _burst, score in scored_ref)
    viable_ref = [item for item in scored_ref if item[1] >= max(250.0, best_ref_score * 0.70)]
    viable_ref.sort(key=lambda item: item[0][0]["t"])

    best_candidate: tuple[int, float] | None = None
    for ref_burst, ref_score in viable_ref:
        ref_anchor = _first_reference_clap_peak(ref_burst)
        ref_onset_ms = _transient_onset(ref_env, int(ref_anchor["idx"]), frame_ms)
        burst_candidates: list[tuple[float, float, list[dict[str, float]]]] = []
        for other_burst in other_bursts:
            other_anchor = _first_other_clap_peak(other_burst)
            other_onset_ms = _transient_onset(other_env, int(other_anchor["idx"]), frame_ms)
            offset_s = (ref_onset_ms - other_onset_ms) / 1000.0
            if abs(offset_s) > 120.0:
                continue
            matches = 0
            errors: list[float] = []
            for ref_peak in ref_burst:
                nearest = min(abs(ref_peak["t"] - (other_peak["t"] + offset_s)) for other_peak in other_burst)
                if nearest <= 0.16:
                    matches += 1
                    errors.append(nearest)
            if matches < 4:
                continue
            mean_error = float(np.mean(errors)) if errors else 1.0
            other_score = _burst_score(other_burst)
            score = (matches * 100.0) + min(ref_score, other_score) - (mean_error * 1000.0)
            if base_offset_ms is not None:
                # Keep the clap correction close to the robust long-form match;
                # this prevents unrelated repeated transient bursts from taking over.
                score -= min(abs((offset_s * 1000.0) - base_offset_ms), 2000.0) * 0.15
            burst_candidates.append((score, offset_s, other_burst))
        if not burst_candidates:
            continue
        burst_candidates.sort(reverse=True, key=lambda item: item[0])
        score, offset_s, _other_burst = burst_candidates[0]
        # First viable reference burst wins: it is the clap/slate onset. Later
        # bursts may score higher but are repeated claps/speech and can be late.
        best_candidate = (int(round(offset_s * 1000.0)), max(5.0, score / 100.0))
        break

    return best_candidate


def _fine_envelope_refinement(
    reference: np.ndarray,
    other: np.ndarray,
    sample_rate: int,
    *,
    coarse_offset_ms: int,
    fine_ms: int = 5,
    search_ms: int = 150,
    window_seconds: float = 60.0,
) -> int | None:
    """Refine a coarse envelope offset on a fine 5 ms grid.

    The coarse path works on a 50 ms RMS envelope and rounds its answer to a
    multiple of 50 ms — up to ±1-2 frames of lip-sync error at 25 fps when no
    clap/slate is available for the transient path. This pass re-correlates a
    high-energy region on a 5 ms envelope within ±search_ms of the coarse
    offset, keeping the robustness of envelope matching (immune to mic
    phase/position differences, unlike raw-waveform correlation) while
    reducing quantisation to 1/8th of a frame.

    Returns a refined offset in ms (same sign convention as
    find_sync_offset), or None when the signals are too short or the fine
    correlation is not clearly peaked.
    """
    env_ref = _normalize_envelope(_energy_envelope(reference, sample_rate, fine_ms))
    env_other = _normalize_envelope(_energy_envelope(other, sample_rate, fine_ms))

    lag_frames = max(1, round(search_ms / fine_ms))
    coarse_frames = round(coarse_offset_ms / fine_ms)
    window_frames = max(40, round(window_seconds * 1000 / fine_ms))
    window_frames = min(window_frames, len(env_ref), max(40, len(env_other) // 2))
    if len(env_ref) < 40 or len(env_other) < 40:
        return None

    # Pick the highest-energy reference window whose counterpart (under the
    # coarse offset) lies fully inside the other track, including lag margin.
    step = max(1, window_frames // 2)
    best_start, best_score = None, 0.0
    for start in range(0, len(env_ref) - window_frames + 1, step):
        other_start = start - coarse_frames - lag_frames
        other_end = start - coarse_frames + window_frames + lag_frames
        if other_start < 0 or other_end > len(env_other):
            continue
        segment = env_ref[start:start + window_frames]
        score = float(segment.std()) * float(np.mean(np.abs(segment)))
        if score > best_score:
            best_score, best_start = score, start
    if best_start is None or best_score <= 1e-6:
        return None

    ref_seg = env_ref[best_start:best_start + window_frames]
    o_lo = best_start - coarse_frames - lag_frames
    o_hi = best_start - coarse_frames + window_frames + lag_frames
    other_seg = env_other[o_lo:o_hi]

    corr = scipy_signal.correlate(other_seg, ref_seg, mode="valid", method="fft")
    if corr.size == 0 or _correlation_quality(corr) < 2.5:
        return None
    k = int(np.argmax(np.abs(corr)))
    matched_other_start = o_lo + k
    refined_frames = best_start - matched_other_start
    refined_ms = refined_frames * fine_ms
    if abs(refined_ms - coarse_offset_ms) > search_ms:
        return None
    return int(refined_ms)


def find_sync_offset(
    reference: np.ndarray,
    other: np.ndarray,
    sample_rate: int,
    *,
    min_quality: float = 5.0,
) -> tuple[int, float]:
    """Find the temporal offset between two audio signals.

    Returns (offset_ms, quality). Sign convention is intentionally preserved
    from the original implementation: negative means ``other`` is delayed
    relative to ``reference``; positive means ``other`` starts earlier.

    The detector first builds a speech-band RMS envelope and uses multiple
    high-energy windows to vote for an offset.  Then, when a shared clap/slate
    burst is present, it refines to the first transient onset in that burst so a
    repeated later clap cannot pull sync out by several frames.  If transient
    matching is unavailable, it falls back to the envelope result.
    """
    window_ms = 50
    env_ref = _energy_envelope(reference, sample_rate, window_ms)
    env_other = _energy_envelope(other, sample_rate, window_ms)

    candidates = _window_sync_candidates(
        env_ref,
        env_other,
        window_ms=window_ms,
    )
    clustered = _cluster_offset_candidates(candidates, min_quality=min_quality)
    envelope_result = clustered if clustered is not None else _full_envelope_offset(env_ref, env_other, window_ms=window_ms)

    refined_ms = _fine_envelope_refinement(
        reference, other, sample_rate, coarse_offset_ms=envelope_result[0]
    )
    if refined_ms is not None:
        envelope_result = (refined_ms, envelope_result[1])

    transient = _matching_transient_burst_offset(reference, other, sample_rate, base_offset_ms=envelope_result[0])
    if transient is not None and transient[1] >= min_quality:
        return transient

    return envelope_result


def compute_sync_offsets(
    guide_tracks: dict[str, str],
    reference_angle_id: str,
    *,
    operator_nudge_ms: int = 0,
) -> dict[str, int]:
    """Compute sync offsets by correlating guide tracks against a reference."""
    ref_path = guide_tracks.get(reference_angle_id)
    if ref_path is None:
        raise ValueError(f"reference angle {reference_angle_id} not in guide tracks")

    ref_data, ref_rate = _read_wav_float(Path(ref_path), target_sample_rate=8000)
    ref_filtered = bandpass_filter(ref_data, ref_rate)
    ref_ds = ref_filtered

    offsets: dict[str, int] = {reference_angle_id: 0}

    for angle_id, path in guide_tracks.items():
        if angle_id == reference_angle_id:
            continue

        other_data, other_rate = _read_wav_float(Path(path), target_sample_rate=8000)
        other_filtered = bandpass_filter(other_data, other_rate)
        other_ds = other_filtered

        offset_ms, quality = find_sync_offset(ref_ds, other_ds, 8000)
        min_quality = 5.0
        if quality < min_quality:
            raise SyncQualityError(angle_id, quality=quality, threshold=min_quality)
        # find_sync_offset sign: positive = reference delayed relative to other.
        # We want positive = other delayed relative to reference → negate.
        offsets[angle_id] = -offset_ms + operator_nudge_ms

    return offsets


def extract_channel(
    source_path: str,
    channel_index: int,
    output_path: str,
    *,
    plog=None,
) -> None:
    """Extract a single audio channel to a mono 48 kHz PCM WAV using ffmpeg."""
    cmd = [
        "ffmpeg", "-y",
        "-i", source_path,
        "-map", "0:a:0",
        "-af", f"pan=mono|c0=c{channel_index}",
        "-ac", "1",
        "-ar", "48000",
        "-c:a", "pcm_s16le",
        output_path,
    ]
    if plog is not None:
        plog.cmd("extract_channel", cmd)
    try:
        # Stall watchdog instead of a fixed timeout: extracting audio from
        # 60-90+ minute sources on slow/busy storage legitimately exceeded
        # the old timeout=600, aborting the whole pipeline.
        result = run_ffmpeg_watchdog(cmd)
    except FileNotFoundError as exc:
        raise RuntimeError("ffmpeg executable not found") from exc
    if plog is not None:
        plog.cmd_result(result.returncode, result.stderr)
    if result.returncode != 0:
        raise RuntimeError(f"ffmpeg channel extraction failed: {result.stderr}")


def extract_guide_track(
    source_path: str,
    output_path: str,
    *,
    plog=None,
) -> None:
    """Extract a mono downmix guide track for sync correlation."""
    cmd = [
        "ffmpeg", "-y",
        "-i", source_path,
        "-ac", "1",
        "-ar", "48000",
        "-c:a", "pcm_s16le",
        output_path,
    ]
    if plog is not None:
        plog.cmd("guide_track", cmd)
    try:
        result = run_ffmpeg_watchdog(cmd)
    except FileNotFoundError as exc:
        raise RuntimeError("ffmpeg executable not found") from exc
    if plog is not None:
        plog.cmd_result(result.returncode, result.stderr)
    if result.returncode != 0:
        raise RuntimeError(f"ffmpeg guide track extraction failed: {result.stderr}")


def compute_cross_correlation(
    reference: np.ndarray,
    other: np.ndarray,
    *,
    max_lag_seconds: float = 10.0,
    sample_rate: int = 8000,
) -> tuple[int, int]:
    """Backward-compatible wrapper around find_sync_offset."""
    offset_ms, _quality = find_sync_offset(reference, other, sample_rate)
    # Clamp to max_lag for compatibility
    max_lag_ms = int(max_lag_seconds * 1000)
    offset_ms = -offset_ms  # flip sign convention
    if abs(offset_ms) > max_lag_ms:
        offset_ms = 0
    offset_samples = round(offset_ms * sample_rate / 1000)
    return offset_samples, offset_ms
