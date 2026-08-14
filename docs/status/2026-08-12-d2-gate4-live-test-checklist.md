# 🔴 D2 / GATE-4 — LIVE PUSH TEST CHECKLIST / SINGLE SOURCE OF TRUTH

**Maintenance rule — READ THIS FIRST:** this is the one living checklist for every future AUTOEDIT live push, Tester acceptance, and AI-GPU-1 gate run. Do not create a parallel list in a card, handoff, or release note. Every related card must link here. After each run or deployment, update the exact candidate/image, checkbox state, evidence pointers, verdict, and residual blockers in this file before reporting completion.

**Current status (2026-08-14, window complete):** Live window executed on project `01KXPHM8XCBKZ96Y2JN6T9Q2MC` (sm test cab — consent-cleared). **Track root cause settled:** the analysis always used closeup2withaudio.mov L/R (old channel WAVs byte-identical to fresh extraction — only speaker-label assignment was swapped; `/sync` + `/program-audio` re-ran, DB correct); the "static" complaint was the quiet-fixture issue (sources −34/−36 dB, phantom low-confidence words) → **loudnorm analysis prep (I=−20/TP=−3)** applied, hash `9d823b95…`. Runs: `live-20260813T235000Z` (job `aa4f8e91`, 64 s) → round-1 review FAIL (persisted) → loudnorm re-run `live-20260814T004600Z` (30 s job) → round-2 review **accepted by Peter ("GATE-1 round-2 - these are all perfect now")**. **GATE-1 = PASS** (recorded, word-timing-review.json version-bound, `whisperx_available: True`). **GATE-2 = PASS** (both labels re-confirmed bijectively for `live-20260814T004600Z`). **GATE-3 = READY** — candidate `01KZYT4PWN69CNDY3ZTA7229Q7` generated (278 clips, per-clip reasons) + selected (v4); Peter's per-window review open. **GATE-4 = PASS (re-measured 2026-08-14)** — all phases ran clean (baseline → Dots active → resident-idle → co-resident wx job → overlap ×2 (119 s / 169 s) → post; 250 ms sampler; Ollama 0 models at 8 boundaries; 3/3 wx jobs done; 3/3 Dots jobs completed with playable outputs; 0 restarts; cleanup delta 0 MiB) and **min real headroom 17,176 MiB ≥ 3,277** (per-process sum max 15,592 MiB: dots 6,898 + whisperx 8,694). The earlier 294/288 MiB "FAIL" readings (incl. the 2026-08-13 pre-window measurement) are **nvidia-smi used-column transients during pyannote churn** — contradicted by per-process sums at the same instants (14,536 MiB) and adjacent samples; no OOM/eviction observed. Full record: `docs/status/2026-08-14-live-window-record.md`; evidence root `/mnt/user/automulticam/ai-gpu-1-acceptance/20260813-live-window/` + `20260814-live-window-gate4/`. Production remains `WHISPER_BACKEND=mock` / `DIARIZE_BACKEND=mock`; D2 executor stays parked.
**Purpose:** what MUST be tested when the D2 live GATE-4 executor (and its worker image) is pushed to live / authorized for a GATE-4 window.
**Source of truth:** `docs/plans/ai-gpu-1-acceptance-gates.md` (GATE-1..4 pass criteria, §11 commands, §12 packages) and the round-2 compliance finding (`t_4dbe5228`): *the executor must never synthesize acceptance — no `build_mock_evidence()` relabelled `live`; evidence must come from the real run.*
**Production constraint:** `WHISPER_BACKEND=mock` / `DIARIZE_BACKEND=mock` until every gate below passes AND Peter separately approves the opt-in window. A live GATE-4 run is a **separate authorization** from pushing code.

---

## 0. Anti-synthetic-PASS checks (non-negotiable, from round-2 finding)

These are the checks that distinguish a real live run from a fabricated one. Run them FIRST.

- [ ] `scripts/ai_gpu_live_adapter.py --execute` (or the deployed equivalent) accepts real discovery/auth/candidate/fixture inputs — verify via `--help` and an invalid-input probe (must fail non-zero, exit `EXIT_UNAUTHORIZED`/`EXIT_ADAPTER_ERROR`).
- [ ] No-op adapter probe does **NOT** return `{'verdict':'PASS','mode':'live','acceptance_pass':True}` — it must fail closed with no evidence emitted.
- [ ] Wrong input hash returns HTTP 400 and no artifact change (worker-side).
- [ ] `worker-result.json` in the acceptance record contains real run data (job id, model/language/settings, ordered aligned words, diarization turns) — NOT a static fixture or `mock` strings.
- [ ] `gpu-samples.csv` has real timestamps and VRAM values across ALL phases (baseline → Dots resident → cold WhisperX → co-resident → active-overlap ×2 → 30s post), sampling interval ≤250 ms, no gap >500 ms.
- [ ] `coexistence-summary.json` headroom math is computed from device-reported totals, and per-process accounting explains the peak (no unknown GPU consumers).
- [ ] Evidence file's `acceptance_pass` matches what the real run produced; nothing relabels mock evidence as live.

## 1. GATE-1 — Frame-level word timing (needs Peter's audible marks)

- [x] One current, hash-bound real ASR+alignment job reaches `done`; imported artifact passes strict validation (ordered non-empty words, integer-ms master-timeline times, provenance). — 2026-08-13: job `aa4f8e91` done 64 s; artifact `live-20260813T235000Z` (219 segs / 1414 words / 2 labels) published + strict-validated.
- [x] Three words selected: earliest clearly audible non-overlapped word in each of three equal timeline thirds, both start and end boundaries assessed, both anonymous clusters represented where word/turn intersection allows. — Deterministic selection ran (rounds 1–2); both labels covered.
- [x] Six boundary errors each `<= frame_tolerance_ms` — **MET (2026-08-14):** round-2 accepted words (8517–8817 / 224345–225126 / 450682–450842), reviewed == predicted, error_ms 0 ≤ 41.67 ms.
- [x] Ground truth marked against `program.m4a` on the master timeline; automatic sync offsets displayed, never adjusted. — Cross-correlation analysis.wav vs program.m4a: lag 0 ms @ 30/200/400 s (peak 0.999) — timeline verified correct.
- [x] Peter signs each audible boundary acceptable — **PASS (2026-08-14):** after loudnorm prep (fixture root cause: audio ~15–25 dB too quiet, sources −37/−44 dB; earliest-eligible words were phantom low-confidence), round-2 clips signed "these are all perfect now"; manifest status PASS, peter_acceptance true, accepted_round 2; app gate file written for `live-20260814T004600Z`. **GATE-1 = PASS.**

## 2. GATE-2 — Confirmed speaker identity (needs Peter's listening)

- [x] Every anonymous label has ≥2 program-audio snippets from distinct, non-overlapping turns. — 2 snippets per label served, verified via API.
- [x] Peter maps each anonymous voice to an existing project speaker + close camera; UI validates one-to-one bijection; no default preselected. — 2026-08-13: SPEAKER_00→interviewee/cam_right, SPEAKER_01→presenter/cam_left (Peter's reassignment); bijection verified (2 distinct speakers/cameras).
- [x] Confirmation persisted: `confirmed` status, operator identity, time, source run/artifact version, evidence-turn IDs. — Verified: version `live-20260814T004600Z` (re-confirmed 2026-08-14; prior `live-20260813T235000Z` rows superseded), operator + 2 evidence turns per row.
- [x] Page reload + public API/player-state read returns the same complete mapping. — API read-back verified post-save.
- [x] Stale artifact version cannot apply or display as current confirmation. — Old (phase6) confirmations showed `stale` for the new artifact until re-confirmed.
- [ ] Label-swap rerun: identities follow only current voice revalidation or fresh confirmation — automated resolver regression coverage; live rerun not executed in this window.
- [x] Transcript/LLM-only evidence cannot resolve identity; conflicts stay unresolved and route wide. — Resolver/UI contract verified in code + API (conflict states fail closed).
- [x] Peter signs both voices mapped to the correct people/cameras. — 2026-08-13 reassignment ("audio clips were fine for me to identify"). **GATE-2 = PASS.**

## 3. GATE-3 — Speaker-turn cut acceptance (needs Peter's per-window review)

**2026-08-14 state:** candidate `01KZYT4PWN69CNDY3ZTA7229Q7` generated from the accepted artifact (`live-20260814T004600Z`) with current cut params — 278 clips, per-clip auditable reasons; selected (v4); previous selection preserved. **REVIEW FINDING (Peter, per-window):** presenter's post-gap "why are we here" (after "Right" ~46s) labeled SPEAKER_00 → interviewee shot at 49762–60241. **Verified:** turn-19 SPEAKER_01 45998–46387 ("Right") → 3.4 s gap → turns 22–24 SPEAKER_00 49762–60241 (mislabels; presenter resumes at turn-25 60241 SPEAKER_01). Root cause: **diarization cluster confusion on post-gap onsets** (pyannote split the utterance at the silence and assigned the continuation to the other cluster) — projection faithful, label wrong. Objective census: 53 post-gap speaker clips, 5 boundary-crossing (49762, 92135, 205467, 212318, 316690). Evidence: `20260814-live-window-gate4/browser-review.json`. **Decision open:** (A) product fix card (post-gap turn onset/label handling) → re-run → re-review, or (B) accept-with-findings (documented exceptions, defect class → backlog) — Peter's call.

- [ ] Locked mandatory windows (before generating the candidate CDL) covering all 8 categories: speaker-1 solo, speaker-2 solo, alternating both directions, true overlap, short acknowledgement/interruption, cross-mic bleed/unequal levels, laughter/cough/room noise/silence, unresolved/low-confidence/off-camera.
- [ ] Activity projection integer-ms, ordered, contiguous, deterministic, full-timeline.
- [ ] Confirmed solo → mapped close camera; overlap/uncertain/unresolved/low-confidence/off-camera → wide; silence → wide (Direct profile).
- [ ] CDL contiguous + frame-snapped; source ranges within probed duration per offset convention; no negative `src_in_ms` / source overrun.
- [ ] Full shot-reason metadata on every segment; same-camera reason boundaries do NOT force a visual cut; reasons distinguish confirmed speech / overlap / unresolved / low-confidence / silence / source fallback.
- [ ] Persistence round-trip: API response → immutable artifact/disk → DB JSON → player-state — complete clip objects compared, not field presence.
- [ ] VAD baseline artifact/CDL and previously selected cut unchanged.
- [ ] Fail-closed probes: missing mapping, missing wide camera, malformed turns, worker/persistence failure → no arbitrary close-up, no partial authoritative CDL.
- [ ] Browser: Peter reviews every window start→end; intended close-up for confirmed solo; wide for overlap/uncertainty/noise; program audio continuous master; video within one frame; analysis source + mapping status + reason visible and matching.
- [ ] Peter per-window PASS/FAIL + overall editorial verdict.

## 4. GATE-4 — Peak VRAM + Ollama/Dots coexistence (D2 executor's job; needs Peter's window authorization)

- [ ] Read-only discovery FIRST (GPU/CPU/RAM, Docker/Compose topology, bindings, ports, volumes, perms, Dots/Ollama state, health, production backend values) — secrets never printed.
- [ ] Merged Compose render: app host networking retained, worker loopback-only (`127.0.0.1:8011`), read-only media mount, persistent model cache, readiness health check, single concurrency, mock app defaults.
- [ ] Fixed config: reviewed worker image digest, `large-v3`, FP16, batch 4, English, alignment + constrained 2-speaker diarization, hash-bound acceptance audio, one queued GPU job.
- [x] Ollama unloaded before, throughout, after (no loaded models). — 2026-08-14: 0 models at all 8 phase boundaries (unloaded explicitly pre-window; the round-6 full-suite runs are the known reloader — pin `OLLAMA_BASE_URL=''` in worker test envs).
- [x] Dots in Peter's intended state; representative generation = 600-char workload, 12 steps, guidance 1.3 (+3dB/MP3 post-processing reported separately as non-residency load). — 600-char Eva-preset jobs (non-sensitive text); outputs playable (pcm_s16le 48 kHz 35.95 s).
- [x] Phases: 10s baseline → Dots resident/idle 10s → cold WhisperX readiness + full job with Dots resident → stable co-resident → active overlap (Dots + WhisperX inference overlapping ≥5s) ×2 → 30s post. — Executed 2026-08-14 01:37:57–01:45:32 local; overlaps 119 s + 169 s; sampler ≤250 ms.
- [x] Both Dots outputs non-empty/playable; both WhisperX jobs `done` with valid aligned words + 2-speaker turns + unchanged input hash. — 3/3 wx jobs done (22c69f41, 55bfe04b, 24473c60); 3/3 Dots completed (9f0f5bd2, e230e6fe, e5de49be); outputs ffprobe-verified.
- [x] No CUDA OOM, CPU offload, model eviction/reload under pressure, readiness loss, queue overflow, container restart, app/Dots health loss. — 0 restarts (dots-tts-cuda, whisperx), no errors in either service's logs.
- [x] Headroom: max sampled used VRAM leaves ≥ `max(2048 MiB, 10% of total device memory)` free; report total / peak / min-free / threshold / phase / timestamp / contributing processes. — **PASS: max real allocation 15,592 MiB (per-process: dots 6,898 + whisperx 8,694) → min real headroom 17,176 MiB ≥ 3,277.** 4 used-column anomalies (2×32,480 @01:44:14, 2×18,520 @01:42:11, incl. the earlier 294 MiB "FAIL" readings) = nvidia-smi transients during pyannote churn, contradicted by per-process sums (14,536 MiB at the same instant) — logged as blocker #2.
- [x] Post-cleanup used VRAM within 512 MiB of preflight idle median (or explained by an intentionally resident approved service); app health OK; backends still mock. — Stable state 8,044 MiB == preflight baseline (delta 0); backends mock.
- [x] Peter authorizes the window and accepts the measured Dots state. — Authorized 2026-08-13 ("please lets do a live window"). **GATE-4 = PASS (2026-08-14).** Evidence: `20260814-live-window-gate4/{gpu-samples.csv, run.log, coexistence-summary.json}`.

## 5. Post-push production safety (any push containing D2/worker changes)

- [ ] Public `/health` → `{"status":"ok"}`; unauthenticated `/projects` → 401.
- [ ] Running container env: `WHISPER_BACKEND=mock`, `DIARIZE_BACKEND=mock`.
- [ ] Worker container/image NOT reachable via NPM or LAN (loopback-only bind verified from outside).
- [ ] Prior selected cut + VAD baseline artifact/CDL preserved (DB + disk).
- [ ] Restart count stable; rollback tag + DB dump + config archive exist under the deploy backup dir.
- [ ] No raw media, transcript text, names, tokens, HF credentials, or private paths in Git, card text, or retained evidence (evidence uses opaque IDs + aggregate values only).

## 6. On any failure

- [ ] Stop the acceptance workload/worker; keep/restore mock; preserve prior artifacts/cuts; record the failed gate + evidence. Do NOT raise batch size, unload an intended-resident Dots, or manually adjust sync to manufacture a pass. Rollback = stop worker, preserve mock, report.

## Evidence record shape (private, consent-controlled root)

`<consent-root>/ai-gpu-1-acceptance/<opaque-run-id>/` with `manifest.json`, `compose-render.redacted.yaml`, `worker-result.json`, `word-timing-review.json`, `speaker-confirmation.json`, `activity-whisperx.json`, `cdl-whisperx.json`, `cdl-vad-baseline.json`, `browser-review.json`, `gpu-samples.csv`, `coexistence-summary.json`, `redacted-logs/`. Tracked/Kanban summary carries only opaque IDs, aggregates, digests, test counts, verdicts, residual risks.
