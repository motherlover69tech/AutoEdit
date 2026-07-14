# GPU AI / WhisperX / LLM Integration Plan

## Status

- Stage: `AI-GPU-1`
- State: **in progress / corrective review passed**
- Corrective pickup and acceptance checklist: `docs/plans/ai-gpu-1-corrective-pickup.md`.
- Hardware verified 2026-07-10: NVIDIA Tesla V100-PCIE-32GB, 32 GB VRAM, driver 580.159.03.
- `/ready` verified with CUDA capability 7.0, `large-v3` FP16, about 50 seconds cold load, and 22,186 MiB maximum observed readiness VRAM.
- Consent-cleared isolated smokes completed real queued ASR/alignment and constrained two-speaker diarization. They established transport and structural output, not frame-level timing, stable identity, editorial quality, or production acceptance; runtime identifiers and media fingerprints remain outside Git.
- Existing GPU tenants: Dots TTS and Ollama. Ollama is configured to unload after requests.
- Current production truth: `WHISPER_BACKEND=mock`, `DIARIZE_BACKEND=mock`; the current Ollama client defaults to local Qwen3.5 9B. The planned DeepSeek-primary/provider-neutral fallback chain is not implemented.

## Sources, scope, and constraints

- The authoritative roadmap is `docs/plans/whisperx-speaker-aware-ai-roadmap.md`. This document records the first disabled adapter slice and its deployment gates.
- AUTOEDIT spec Stage 5.1 requires real transcript words on the synchronized master timeline; the broader roadmap also requires WhisperX/pyannote speaker turns to replace bleed-prone mic-level speaker authority.
- The app's current WhisperX transcription route still processes isolated mapped speaker WAVs. Versioned artifacts, analysis-audio preparation, queued diarization, and deterministic speaker-resolution contracts now exist locally, but the app does **not** yet import those resolved turns as camera-decision authority. This must not be presented as the first real-AI release.
- Phase 0 metadata-only benchmark scaffolding lives in `tests/fixtures/golden_interview/` and `docs/ai/whisperx-evaluation-protocol.md`. Consent-cleared isolated smoke evidence exists, but labelled benchmark acceptance remains incomplete.
- WhisperX 3.8.6 (PyPI/current stable checked 2026-07-10) supports Python 3.10–3.13 and uses faster-whisper plus forced alignment. The service uses a hash-locked Python dependency graph and a digest-pinned CUDA 12.8.1 cuDNN runtime image. Isolated V100 readiness/inference passed; the Compose-managed production-acceptance gates must still be rerun before enablement.
- WhisperX documents that diarization and overlapping speech remain imperfect. The later diarization stage requires a Hugging Face token, accepted pyannote model terms, confidence-aware speaker mapping, and real-media evaluation.
- The AUTOEDIT web image must stay small and retain Intel VAAPI support. CUDA/PyTorch/WhisperX belong in a separate internal service/worker.
- The initial service receives only `/data` paths. Both containers mount the same media root; no audio bytes are uploaded over HTTP.

## Architecture

```text
AUTOEDIT app (:8010, host network)
  POST /projects/:id/transcribe
    -> backend selector
       mock: existing deterministic test path
       whisperx: POST http://127.0.0.1:8011/v1/transcribe
                   {audio_path, model, language, batch_size, compute_type, align}

WhisperX service (:8011 published only on host loopback, NVIDIA GPU)
  /health (process liveness only)
  /ready  (CUDA/FP16 + configured model readiness)
  /v1/transcribe
  shared read-only /data mount
  validates/confines audio_path under /data
  transcribes + optional forced alignment
  returns normalized segment/word seconds

AUTOEDIT app
  validates service response
  converts seconds -> integer milliseconds
  adds channel sync offset exactly once
  adds speaker/channel identity
  failure-safely replaces transcript.json + DB rows, restoring the prior pair on persistence failure
```

## Stage AI-GPU-1 — service boundary and real transcription adapter

### Build

1. Add `WHISPERX_BASE_URL`, timeout, language, batch-size, compute-type, and alignment settings.
2. Add a strict WhisperX HTTP client that normalizes WhisperX output into AUTOEDIT's existing transcript contract.
3. Preserve the mock path and fail loudly when `WHISPER_BACKEND=whisperx` is unavailable; never silently generate fake transcript text.
4. Add an internal GPU service under `services/whisperx_service/` with lazy model loading and path confinement.
5. Add an opt-in Compose profile for the GPU service. Bind it to loopback, enforce server-side model/compute/batch allowlists, and keep production `WHISPER_BACKEND=mock` until a real WAV smoke test passes on Unraid.

### Required automated tests

- Backend selector rejects unknown backend names.
- WhisperX request contains the shared absolute audio path and configured model/options.
- Segment and word timestamps are rounded to integer milliseconds.
- Sync offset is applied exactly once to both segment and word times.
- Missing word timestamps are tolerated without inventing inaccurate values.
- Malformed/non-2xx service responses fail clearly.
- Service path confinement rejects traversal/out-of-root paths.
- Existing mock transcription tests remain green.

### Manual/live gates

- Build/start the WhisperX service on Unraid. Confirm `/health` reports liveness and `/ready` proves CUDA FP16 plus configured-model loading.
- Run a short real isolated speaker WAV through `large-v3` with alignment enabled.
- Verify three spoken words against the player timeline and source audio; error must be within one project frame.
- Measure peak VRAM while Dots TTS is resident and while Ollama is unloaded; tune batch size before enabling production.
- Only after all gates pass: set `WHISPER_BACKEND=whisperx` and record the tested service image/model/settings.

## Required roadmap continuation

The authoritative roadmap remains phase-ordered. Current implementation truth is:

1. Phase 0 has metadata-only scaffolding and isolated smoke measurements, but consent-cleared labels, frame-level review, and acceptance thresholds remain incomplete.
2. Strict versioned artifact contracts, source/model provenance, immutable run history, and last-known-good publication exist locally, but the application route does not yet publish its WhisperX result through them.
3. The service has a single-concurrency in-process queue, bounded pending/history retention, CUDA/model readiness, job status, and cancellation; durable recovery and configurable production tuning remain incomplete.
4. Synchronized derived analysis audio exists locally, but best-single-lav versus normalized-mix evaluation is not accepted.
5. WhisperX/pyannote diarization, overlap normalization, deterministic mapping, and context components exist locally; authoritative application import and operator-confirmation UI remain incomplete.
6. Speaker-turn activity/cut authority is not wired; uncertain/overlapping spans must continue to choose wide when that path is introduced.
7. Structured non-thinking LLM context validation exists, but the DeepSeek-primary → local-Qwen provider chain and accepted editorial provenance path remain future work.

These components are reviewable building blocks, not a production-complete AI phase.
