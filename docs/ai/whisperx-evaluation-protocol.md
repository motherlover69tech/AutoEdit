# WhisperX Real-Media Evaluation Protocol

## Purpose

Determine whether WhisperX ASR/alignment/diarization and confirmed speaker mapping
materially reduce wrong close-up cuts caused by lavalier bleed/noise. Synthetic unit
tests prove contracts but cannot establish this editorial outcome.

## Safety and fixture policy

- Use only consent-cleared, non-sensitive excerpts.
- Keep media and identifying transcripts outside git on a trusted fixture host.
- Track only opaque fixture IDs, schema definitions, aggregate metrics, and redacted
  failure descriptions.
- `AUTOEDIT_GOLDEN_MEDIA_ROOT` is required for benchmark execution; absence must
  produce a clean skip, never a download or fallback sample.
- Never alter source WAVs or `program.m4a`; derived analysis audio is disposable.

## Dataset coverage

Use at least three 3–10 minute excerpts collectively covering:

- normal alternating turns and quiet speech;
- cross-mic bleed and unequal mic levels;
- interruption and true overlapping speech;
- room noise, laughter, coughs, and short acknowledgements;
- off-camera speech and uncertain identity.

## Ground truth

For labelled regions, store integer milliseconds on the existing synchronized
master timeline:

- word text/start/end and explicit boundary uncertainty;
- anonymous voice identity plus confirmed project speaker/camera identity;
- speaker turns, overlap intervals, silence, and unresolved regions;
- intended camera (`cam_left`, `cam_right`, `wide`) with uncertainty;
- transcript reference where consent permits.

A second pass should review a representative subset. Disagreements remain labelled
as uncertain; do not invent exact boundaries to improve metrics.

## Baseline capture

Before running WhisperX, preserve current outputs for the same project/version:
`loudness.json`, `level_normalization.json`, `activity.json`, `diarization.json`,
`transcript.json`, and the selected CDL. Record hashes and configuration, not raw
content, in the benchmark report.

## Metrics

Report per fixture and aggregate:

- speaker-turn precision/recall/F1 and diarization error rate where measurable;
- missed-overlap and false-overlap duration/rate;
- aligned word-boundary absolute error (median, p95) and WER when a reference exists;
- camera-decision agreement and time-weighted wrong-close-up rate;
- bleed/noise false-cut count and duration;
- unresolved/low-confidence duration sent safely to wide;
- runtime, model versions, peak VRAM, and analysis strategy.

Do not set universal thresholds before measuring the current VAD baseline. Release
acceptance requires material improvement in wrong close-ups/bleed failures while
preserving automatic sync and frame-consistent exports.

## Commands

```bash
# Always-runnable contracts
env -u VIRTUAL_ENV uv run pytest -q

# Trusted fixture host only
AUTOEDIT_GOLDEN_MEDIA_ROOT=/secure/autoedit-fixtures \
  env -u VIRTUAL_ENV uv run pytest tests/integration/test_whisperx_golden_media.py -q
```

## Pre-flight gate

Entry requires consent, fixture accessibility, stable source hashes, and completed
ground truth. Failure leaves production on VAD/mock and does not block ordinary
unit tests.

## Revision gate

If WhisperX does not materially beat VAD on wrong close-ups, keep it disabled and
revise analysis-audio strategy, diarization settings, or speaker mapping. Never
compensate with manual timeline nudges.

## Production gate

Production speaker authority remains disabled until the benchmark, speaker mapping,
versioned artifact import, app/worker recovery, browser playback, and Resolve export
gates all pass. Record image/model versions and aggregate measurements without
private media or credentials.
