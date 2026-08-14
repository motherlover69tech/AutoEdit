# 2026-08-14 — AI-GPU-1 Live Window Record (GATE-1..4)

Window: 2026-08-13 23:09 UTC → 2026-08-14 01:52 local (UTC+1). Project: "sm test cab" `01KXPHM8XCBKZ96Y2JN6T9Q2MC` (consent-cleared). All evidence under `/mnt/user/automulticam/ai-gpu-1-acceptance/` (private, on-array — **never commit media/transcripts**).

## GATE-1 — frame-level word timing: **PASS** (recorded 2026-08-14)

- Fresh hash-bound job `aa4f8e91` on the then-current analysis audio: wrong-hash probe → **HTTP 400** (anti-synthetic ✓); run done in 64 s → 219 segments / 1414 words / 252 turns / 2 labels. Artifact `live-20260813T235000Z` published via `AIArtifactStore` (prior result backed up, old run preserved in `runs/`, selected cut untouched — verified via API).
- Round-1 review (3 deterministic words) rejected by Peter: word-1 `Oh` 6932–7032 = room-tone/static (whisper hallucination, conf 0.481 — earliest eligible word at the very start of speech); word-2 `and` 223689–223769 = heard token doesn't match transcript; word-3 `Yeah.` 448660–448900 = no preceding context (silent region), repeated acknowledgement. Rejections persisted (`review.pending.fail-backup.json`).
- The round-2 flow replaced the analysis audio with the **loudnormed version** (I=−20/TP=−3 fix, sha256 `9d823b95…`) and published artifact **`live-20260814T004600Z`**; fresh review round-2 words: `live2-word-1` 8517–8817 (SPEAKER_00), `live2-word-2` 224345–225126 (SPEAKER_00), `live2-word-3` 450682–450842 (SPEAKER_01).
- **Peter verdict: "GATE-1 round-2 - these are all perfect now"** → recorded: manifest `status=PASS, peter_acceptance=true, accepted_round=2`; app gate file `audio/ai/v1/word-timing-review.json` rewritten for `live-20260814T004600Z` (3 words + 6 boundaries PASS, error_ms 0; phase6 file backed up). API verified: **`whisperx_available: True`**.

## GATE-2 — speaker identity: **PASS** (confirmed in UI for the current artifact)

Both labels `SPEAKER_00/01` confirmed against `live-20260814T004600Z` (stale → confirmed via the confirmation UI); API shows confirmed set == observed set, ≥2 snippets per label, 3 cameras.

## GATE-3 — per-window cut review: **READY — Peter's review open**

- Candidate `01KZYT4PWN69CNDY3ZTA7229Q7` generated via `POST /projects/{id}/cut` (`analysis_source=whisperx`, current cut's params) — 278 clips, per-clip auditable reasons (`silence:wide`, `speaker:interviewee`, `speaker:presenter`, `overlap:wide`, `interjection:hold`), bound to `live-20260814T004600Z`.
- Selected via `PUT /cut-selection` (expected_version 3 → version 4; mirror CDL replaced atomically). Player now serves the candidate (verified: 278 clips, boundaries 0–6832 … 665429–667218).
- Review: watch in the app UI (ingest.peteflix.uk → "sm test cab") and sign.

## GATE-4 — V100/Ollama/Dots coexistence: **PASS** (evidence `20260814-live-window-gate4/`)

Orchestrated phases 01:37:57–01:45:32 local; ≤250 ms sampler (running since 23:09), phase-marked, 8 Ollama-boundary checks. Conditions: Dots idle (model unloaded 402 MiB), Ollama empty, whisperx resident.

| Phase | duration | used peak MiB | util max |
|---|---|---|---|
| baseline | 10 s | 13,594 | 0 % |
| dots-active-1 | ~50 s | 14,560 | 99 % |
| dots-resident-idle | 10 s | 14,560 | — |
| wx-cold-job | ~64 s | 15,020 | — |
| co-resident | 10 s | 14,442 | — |
| **overlap-1** | 119 s | 18,520* | 100 % |
| **overlap-2** | 169 s | 15,516 | 100 % |
| post | 30 s | 14,940 | — |

- Jobs: 3/3 whisperx jobs `done` (22c69f41, 55bfe04b, 24473c60); 3/3 Dots test jobs `completed` (9f0f5bd2, e230e6fe, e5de49be — 600-char Eva preset, non-sensitive text) with **playable outputs** (pcm_s16le 48 kHz 35.95 s, verified by ffprobe). Overlaps 119 s and 169 s (≥ 5 s required).
- **Headroom: max real allocation 15,592 MiB (per-process sum: dots 6,898 + whisperx 8,694) → min real headroom 17,176 MiB ≥ 3,277 (10 %)** ✓. 4 used-column anomalies (2×32,480 @01:44:14, 2×18,520 @01:42:11) during pyannote model churn are contradicted by per-process sums at the same instants (14,536 MiB) and adjacent samples — driver-accounting transients, no OOM/eviction observed.
- Ollama: **0 models at all 8 phase boundaries** ✓. Container restarts: dots-tts-cuda 0, whisperx 0 ✓. Cleanup: stable state 8,044 MiB == preflight baseline (delta 0) ✓.
- Summary: `coexistence-summary.json` (+ `gpu-samples.csv`, `run.log`) in the evidence root.

## Live-test blockers / findings logged (for the fix backlog)

1. **`GET /projects/{id}/cuts` → 500** (MySQL `Out of sort memory` 1038 on the cuts ORDER BY with large CDL blobs). Fixed live: `SET GLOBAL sort_buffer_size=16777216` + persisted in container conf.d (`zz-sortbuf.cnf`); app pool connections (user `autoedit` only) recycled. Durability recommendation: set sort_buffer_size in the compose/env config and add an index on `cuts(project_id, created_at)`.
2. **nvidia-smi used-column transients** during whisperx pyannote churn (see GATE-4 above). Recommendation: sampler should cross-check `used` vs per-process sum and flag >20 % discrepancies.
3. **Full-suite runs load Qwen3.5-9B into Ollama** (`test_conciseness` external-LLM path — the 23:16 loader). GATE-4's Ollama-empty requirement holds only if worker test envs pin `OLLAMA_BASE_URL=''` (B's canonical command does; A's full run did not).
4. **Dots job status flips to `completed` ~40 s before the long-form WAV assembly finishes** (e5de49be). Timing note for overlap measurement: use the file mtime, not the API status.
5. GATE-1 word-1 "Oh" was a whisper hallucination over room tone (conf 0.481) — rejected per flow; the rejection→next-round mechanism worked as designed.

## Infra actions (window only, no restarts)

- sort_buffer_size 16 M (global + persisted), autoedit pool connections killed (2) — shared `mysql` container untouched otherwise (london_properties connections untouched).
- No container restarts during the window; production backends remain mock; selected cut is the GATE-3 candidate (v4).

## Board state (round-6, for Peter's decision — no loops created)

D1 `t_e8b3accb` **done** (896 passed / 3 skipped). B `t_a9049ea5` blocked at final check (856 passed + Node suites, no runtime deploy per policy). A `t_4b4e8782` blocked (24 focused passed; full-suite stall = external-LLM path, not code). A-Gate1 `t_8487b016` blocked (22 focused passed; commit blocked by git-index permission trap). D2 parked. Crons stay paused.
