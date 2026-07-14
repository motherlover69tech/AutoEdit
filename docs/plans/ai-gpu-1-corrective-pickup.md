# AI-GPU-1 Corrective Pickup Plan

**Status:** `in_progress / corrective review passed`
**Recorded:** 2026-07-10; live gate updated 2026-07-13
**Production backends:** `WHISPER_BACKEND=mock`, `DIARIZE_BACKEND=mock` — keep these defaults until every acceptance gate below passes.

## Purpose

This is the cold-start pickup document for the speaker-aware WhisperX work. Do not rely on chat history. Read this file together with `AI_HANDOFF.md`, `jobs/BACKLOG.md`, `docs/plans/TESTING_STRATEGY.md`, and `docs/plans/whisperx-speaker-aware-ai-roadmap.md`.

The corrective implementation now has an independent **PASS**. Hash-bound real queued ASR/alignment and two-speaker diarization have completed on the V100. The in-memory waveform path proves that the TorchCodec file-decoder warning does not block this worker route. Frame-level timing review, speaker-identity confirmation, speaker-turn cut generation, and production acceptance remain outstanding, so the production app remains mock-backed.

## Implemented locally

### Versioned AI artifacts

- `src/autoedit/ai/contracts.py`
- `src/autoedit/ai/artifacts.py`
- `src/autoedit/ai/__init__.py`
- `tests/test_ai_artifacts.py`

The current contracts include source/model/hash provenance, integer-ms master-timeline data, ASR words/segments, diarization turns, overlaps, speaker mappings, resolved speaker turns, warnings/errors, immutable run history, and last-known-good publication. Failed processing does not intentionally replace the last successful result.

### Analysis audio

- `src/autoedit/ai/analysis_audio.py`
- `tests/test_analysis_audio.py`
- `docs/ai/real-media-phase0-baseline.json`

The implementation creates deterministic mono 16 kHz PCM analysis audio, selects isolated mapped lavs where possible, applies synchronization offsets, records hashes/strategy/source metadata, and publishes audio plus manifest with rollback.

Real local outputs are private and ignored by Git:

- `testmedia/.analysis/whisperx_analysis.wav`
- `testmedia/.analysis/whisperx_analysis.manifest.json`
- The current analysis-audio fingerprint remains in the untracked consent-controlled local manifest.

Authoritative offset convention:

```text
source_ms = master_ms + sync_offset_ms
master_ms = source_ms - sync_offset_ms
```

Negative source pre-roll must be clipped/discarded at master time zero. Never ask for manual synchronization nudges as a substitute for automatic alignment.

### Isolated queued worker

- `services/whisperx_service/app.py`
- `services/whisperx_service/jobs.py`
- `tests/test_whisperx.py`
- `tests/test_whisperx_jobs.py`
- `docker-compose.gpu-ai.yml`

The worker has single-concurrency queued execution, job state/cancellation, SHA-256 input verification, path confinement, ASR/alignment controls, optional diarization and speaker-count bounds, normalized diarization turns, and no silent real-to-mock fallback.

## Verified checkpoint (2026-07-11)

- Focused AI/transcription suite: `120 passed`.
- Artifact suite: `65 passed`.
- Speaker resolver suite: `15 passed`.
- LLM speaker-context suite: `37 passed`.
- Full mock-backed suite after speaker-resolution and LLM context hardening: `650 passed, 2 skipped`.
- Python compile checks and `git diff --check` passed.
- Staged remote Compose render passed.
- The isolated worker image was built and inspected under the local `autoedit-whisperx:phase0` test tag.
- V100 `/ready` passed with CUDA compute capability 7.0, `large-v3`, and FP16.
- Independent corrective review: `PASS`; no mandatory artifact regressions remain missing.
- Independent Phase 4 resolver and WhisperX diarization-import re-review: `PASS`; all requested direct regressions are present and no mandatory regressions remain missing.
- A consent-cleared queued ASR/alignment run completed in 20.93 seconds with 241 ordered/non-empty aligned segments, approximately 1,422 words, and no structural timing defects. The worker rejected a deliberately wrong hash with HTTP 400.
- GPU memory after readiness was 4,450 MiB and after the completed aligned job was 6,048 MiB. These are observed snapshots, not a sampled peak measurement.
- On 2026-07-13, a consent-cleared queued run completed ASR, alignment, and constrained two-speaker pyannote diarization in 28.99 seconds: 241 segments, 1,422 words, 322 turns, and two anonymous speaker labels. One-second GPU sampling observed an 8,024 MiB peak. A failed predecessor exposed a stale staged image still importing `whisperx.DiarizationPipeline`; the current reviewed source correctly imports from `whisperx.diarize`.
- Live output contained 56 intersecting different-speaker turn pairs without explicit overlap flags. Normalization now derives overlap from intersecting anonymous-speaker intervals and marks both turns; this has a direct regression test.
- Focused speech/AI suite after the overlap fix: `173 passed`. Full mock-backed suite: `651 passed, 2 skipped`. Compile and `git diff --check` passed.
- Independent review identified quadratic overlap normalization in the first corrected worker image. The replacement under the `autoedit-whisperx:phase1-overlap-sweep` local test tag uses an O(n log n) two-directional heap sweep, adds boundary/same-speaker/explicit/unsorted/malformed/concurrent regressions, and received an independent `PASS` including randomized oracle comparison; an in-image overlap/order probe passed. The canonical app uses host networking, so the reconciled opt-in Compose overlay publishes the worker only on `127.0.0.1:8011` and configures the app to use that loopback URL. It is not exposed to the LAN or NPM.
- Final delayed-review verification: worker/artifact/transcript hardening suite `142 passed`; full mock-backed suite `685 passed, 2 skipped`; Ruff on changed Python files, compile, lock/dependency, privacy, and `git diff --check` gates passed. The temporary smoke worker remained stopped and production remained `WHISPER_BACKEND=mock` and `DIARIZE_BACKEND=mock`.

These results establish real queued ASR/alignment/diarization transport and structural output, but not frame-level word-timing, confirmed speaker identity, speaker-aware cut acceptance, or production acceptance.

## Independent review: required corrections

The review of the first artifact implementation returned **REQUEST_CHANGES**. All findings below were corrected and the current implementation received an independent **PASS** on 2026-07-11.

### 1. HIGH — symlink-safe output confinement

`AIArtifactStore` must reject an artifact root or parent that resolves outside the project, including `audio/ai/v1` symlinked to an external directory.

Required work:

1. Resolve the project root once.
2. Resolve/validate artifact output parents before every directory creation or write.
3. Reject any resolved path outside the project.
4. Add a regression test that symlinks the artifact directory to an external temporary directory and proves no external file is written.

### 2. HIGH — resolved-speaker contract follow-up

Resolved speaker turns and mapping checks were added after the review. Re-review and test all of the following:

- stable `speaker_id` and optional human label;
- unique mapping per diarizer speaker ID;
- no orphan mappings;
- no conflicting duplicate mappings;
- resolved turns only reference valid mappings;
- confidence and provenance are retained;
- overlap/uncertain spans remain explicit and can route to wide.

### 3. MEDIUM — strict integer timestamps

Reject booleans, floats, and numeric strings rather than coercing them into milliseconds. Apply strict integer constraints to every timestamp/duration/origin field in nested contracts. Add direct validation tests for `1.5`, `"100"`, and `True`.

### 4. Failure-record immutability

The reviewer reproduced same-ID failure overwrite. Failure attempts must be immutable: generate collision-proof attempt IDs or fail if the destination exists. Add a regression test proving a second write cannot alter the first failure record.

### 5. Run a clean independent review

After corrections, request an independent review of the current—not historical—files. Do not advance until the result is `PASS`.

## Historical real inference attempt: invalid, do not quote as a benchmark

The attempted queued real-media run did not execute successfully:

1. It submitted stale hash `bc34b52b...`; the worker correctly returned HTTP 400.
2. The Unraid host harness used `python3`, which is unavailable in that host shell.
3. The empty job ID then caused HTTP 404 polling.
4. The process exited 255.
5. Observed GPU memory around 32,084 MiB is **not** a valid inference peak because no accepted job was proven.

The corrected rerun used the current hash and `jq`, required a non-empty job ID, reached `done`, and retained its result under the staged build directory. The original failed attempt remains invalid evidence.

## TorchCodec/diarization risk

Worker logs reported a TorchCodec/PyTorch/FFmpeg shared-library compatibility warning with PyTorch 2.8.0+cu128 and TorchCodec 0.7.0. `/ready` passed because ASR model loading works, but this does not prove diarization decoding.

Before accepting diarization:

- verify actual audio decode in the image;
- reconcile TorchCodec/PyTorch/FFmpeg compatibility or preload waveform data as recommended by pyannote;
- run real diarization and record turn count, overlap behavior, runtime, failure details, and peak VRAM;
- do not suppress the warning without proving the path works.

Preflight on 2026-07-11 also found that WhisperX 3.8.6 exposes `DiarizationPipeline` from `whisperx.diarize`, not from the package root. The worker import was corrected and covered by regression. Its in-memory NumPy audio path converts to a waveform tensor before pyannote, avoiding TorchCodec file decoding. On 2026-07-13, authorized gated-model access retained in the isolated smoke container allowed the live diarization gate to pass. The credential has not been copied into Git or the normal deployment env files; an authorized private secret must be provisioned before the Compose-managed worker is enabled.

## LLM speaker-context checkpoint (2026-07-11)

The audit-only structured speaker-context seam was exercised through AUTOEDIT against the consent-controlled 241-segment transcript using `hf.co/unsloth/Qwen3.6-27B-GGUF:Q5_K_M`. With `think=false`, a strict JSON schema, and `keep_alive=0`, it returned three anonymous explicit-address candidates at confidence 0.40. It made no diarizer/voice-cluster assignments, then unloaded the model.

After independent review, this seam was hardened to reject fabricated quotes, timestamps outside or mismatched to the quoted segment, thinking traces, coercive/malformed transcript inputs, malformed/partial structured responses, non-finite or over-ceiling confidence, and attempted speaker/diarizer assignment fields. The hardened seam was rerun against the consent-controlled transcript and returned the same three grounded anonymous candidates; focused coverage is `37 passed`. Names, excerpts, exact evidence timestamps, runtime identifiers, and media fingerprints remain outside Git.

This contextual output is weak audit evidence only. It must never establish speaker identity without current voice evidence or operator confirmation.

## Exact pickup order

1. Inspect `git status`/diff; preserve current uncommitted work.
2. Add failing tests for symlink escape, strict integer rejection, immutable failure collisions, and speaker mapping references.
3. Implement the corrective fixes.
4. Run the focused tests and full mock suite; record exact counts.
5. Run compile and `git diff --check`.
6. Obtain an independent `PASS` review.
7. Rebuild the isolated worker image on Unraid.
8. Submit one valid queued ASR/alignment job using the current WAV hash and a harness that does not require host `python3`.
9. Record job state, language, segment/word counts, runtime, and real peak VRAM. Inspect selected word timing against source/player within one frame.
10. Resolve and test the TorchCodec path, then run real diarization with speaker bounds.
11. Test coexistence with Ollama unloaded and Dots TTS in its intended resident/unloaded state.
12. Only after all gates pass, update handoff/backlog/testing docs, commit/push, and consider an opt-in deployment. Do not change production backend defaults prematurely.

## Cleanup and operational safety

- A temporary Unraid container named `autoedit-whisperx-phase0` may still be running with the model loaded. Check before testing; stop/remove it when no longer needed.
- The staged remote build directory is `/mnt/user/appdata/autoedit-whisperx-build`.
- Production AUTOEDIT at `/mnt/user/appdata/autoedit` was not rebuilt or changed by this work.
- Do not commit raw media, transcripts, tokens, `.env` files, or identifying benchmark content.

## Completion gates

AI-GPU-1 remains `in_progress` until all are true:

- corrective artifact tests pass;
- independent review returns `PASS`;
- full mock suite passes with exact result recorded;
- real queued ASR/alignment succeeds on the supplied analysis audio;
- word timing is manually checked within one project frame;
- real diarization succeeds or is explicitly deferred with production still on mock;
- TorchCodec/audio-decode risk is resolved;
- peak VRAM and coexistence are measured from valid jobs;
- production defaults remain failure-safe and are changed only after explicit acceptance.
