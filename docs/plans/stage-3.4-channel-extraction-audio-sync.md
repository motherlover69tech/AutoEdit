# Stage 3.4 Channel Extraction + Audio Sync Implementation Plan

> **For Hermes:** Use test-driven-development. Keep all routes behind the Stage 7.0 auth middleware when auth is enabled. ffprobe/ffmpeg not installed in CI — mock subprocess calls in tests.

**Goal:** Extract speaker channels to mono WAVs and compute per-angle sync offsets using FFT cross-correlation of guide tracks.

**Depends on:** Stage 3.3 probe & channel mapping.

**Source spec:** `docs/source/multicam_autoedit_spec.md`, Stage 3.4.

**Architecture:** Create `src/autoedit/audio.py` with two subprocess-based functions (extract_channel, extract_guide_track) and a pure-Python sync computation (cross-correlation via numpy/scipy). Add a `POST /projects/{id}/sync` endpoint that triggers both extraction and sync. Tests mock ffmpeg calls and use generated numpy audio data for correlation tests.

---

## Required behavior

### 1. Channel extraction
- For each `audio_channels` row in the project, extract the mapped channel to a mono 48 kHz PCM WAV.
- `ffmpeg -i source/<file> -map_channel 0.1.{channel_index} -ac 1 -ar 48000 -c:a pcm_s16le audio/ch_{speaker_label}.wav`
- Store `wav_path` on the `audio_channels` row.

### 2. Sync (guide track + cross-correlation)
- Extract a mono guide track per angle (downmix of all audio channels):
  `ffmpeg -i source/<file> -ac 1 -ar 48000 -c:a pcm_s16le audio/guide_{angle_id}.wav`
- Band-pass filter 300–3000 Hz, downsample to 8 kHz.
- FFT cross-correlate each non-reference angle against the reference over ±10 s window.
- Peak lag = `sync_offset_ms` for that angle.
- Reference angle offset = 0. Select reference as the first angle (lowest `angle.id`).
- Apply any operator manual sync nudge from Stage 3.3 (`angles.sync_offset_ms` if non-zero).

### 3. WAV update on audio_channels
- After channel extraction, update each `audio_channels` row's `wav_path` to the extracted WAV path.

### 4. Edge cases
- Project must have exactly 2 audio_channels rows for channel extraction.
- At least 2 angles with source files for sync.
- Sync offsets should be integer milliseconds.
- Guide tracks must have enough duration to correlate (minimum ~5s).

---

## Suggested API shape

- `POST /projects/{project_id}/sync`
  - Extracts channel WAVs and guide tracks.
  - Computes cross-correlation sync offsets.
  - Updates `angles.sync_offset_ms` and `audio_channels.wav_path`.
  - Returns computed offsets and channel extraction results.

---

## Tests first

Create `tests/test_audio_sync.py` covering:

1. Sync route requires auth when auth is enabled.
2. Missing project returns 404.
3. Extracting channels updates `audio_channels.wav_path`.
4. Extracting channel with missing `audio_channels` rows returns 400.
5. Sync computes correct offset for a known-delay guide track (generated numpy signal with known lag).
6. Reference angle offset is exactly 0.
7. Operator manual nudge is additive to computed offset.
8. Band-pass filter passband 300–3000 Hz is applied.
9. Cross-correlation peaks correctly for clean signals.
10. Sync offsets are integer milliseconds.

---

## Fixture strategy

**No real media needed.** All tests use:
1. Generated numpy audio arrays (sine waves, chirps, impulses) saved as temporary WAVs.
2. `unittest.mock.patch` on `subprocess.run` for ffmpeg calls — the mock writes generated WAV files and returns a successful subprocess result.
3. Cross-correlation tested in isolation with pure numpy arrays.

---

## Implementation files

- **Create:** `src/autoedit/audio.py` — `extract_channel()`, `extract_guide_track()`, `compute_sync_offsets()`, `bandpass_filter()`
- **Modify:** `src/autoedit/api.py` — add `POST /projects/{id}/sync` route
- **Create tests:** `tests/test_audio_sync.py`
- **Modify:** `pyproject.toml` — add numpy, scipy deps if not present

---

## Verification commands

```bash
env -u VIRTUAL_ENV uv run pytest tests/test_audio_sync.py -v -q
env -u VIRTUAL_ENV uv run pytest -q
```

---

## Definition of done

- Channel extraction updates `audio_channels.wav_path`.
- Cross-correlation produces correct offsets for known-delay signals.
- Reference angle offset is exactly 0.
- Operator nudge is additive.
- All offsets are integer milliseconds.
- Local full suite passes.
- Update `AI_HANDOFF.md`, `jobs/BACKLOG.md`, `docs/plans/TESTING_STRATEGY.md`.
