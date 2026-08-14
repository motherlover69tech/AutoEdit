# 🔴 D2 / GATE-4 — LIVE PUSH TEST CHECKLIST / SINGLE SOURCE OF TRUTH

**Maintenance rule — READ THIS FIRST:** this is the one living checklist for every future AUTOEDIT live push, Tester acceptance, and AI-GPU-1 gate run. Do not create a parallel list in a card, handoff, or release note. Every related card must link here. After each run or deployment, update the exact candidate/image, checkbox state, evidence pointers, verdict, and residual blockers in this file before reporting completion.

**Current status (2026-08-13/14 live window, ~23:30–01:30 UTC):** Live window executed on project `01KXPHM8XCBKZ96Y2JN6T9Q2MC` (sm test cab — consent-cleared). Runs: `live-20260813T235000Z` (job `aa4f8e91`, 64 s) + `live-20260814T004600Z` (loudnorm job `cf7f4c57`, 30 s; analysis audio now loudnorm-normalized, hash `9d823b95…`). **Track root cause settled:** the analysis always used closeup2withaudio.mov L/R (old channel WAVs byte-identical to the fresh extraction — only speaker-label assignment was swapped; `/sync` + `/program-audio` re-ran, DB now correct). **GATE-2 PASS** (both labels confirmed bijectively, version-bound, API read-back verified). **GATE-1 FAIL ×2 on this fixture** (round-1: phantom words over noise; round-2 after loudnorm: words 1–2 inaudible under amplified noise floor; fixture SNR too low — sources −34/−36 dB, extreme crest). **GATE-4 MEASURED — FAIL on headroom:** all phases ran (baseline → Dots idle-resident → cold WhisperX restart+job → co-resident → overlap ×2 → 30 s post; 250 ms sampler, max gap 0.356 s; Ollama never resident on GPU ✓; both overlap jobs completed, no OOM/restart/health loss ✓) but min free VRAM = **294 MiB** during the Dots generation end-burst (Dots process spikes ~7 → 19.5 GB transiently; whisperx ~8.5 GB resident) vs required ≥ 3,277 MiB → **headroom FAIL**. Evidence root: `/mnt/user/automulticam/ai-gpu-1-acceptance/20260813-live-window/` (worker-results, gate1 review manifests, prep-trackfix.out) + `/tmp/gate4/` sampler data. D2/GATE-4 executor remains parked; production remains `WHISPER_BACKEND=mock` / `DIARIZE_BACKEND=mock`.
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
- [ ] Six boundary errors each `<= frame_tolerance_ms` — **NOT MET.**
- [x] Ground truth marked against `program.m4a` on the master timeline; automatic sync offsets displayed, never adjusted. — Cross-correlation analysis.wav vs program.m4a: lag 0 ms @ 30/200/400 s (peak 0.999) — timeline verified correct.
- [ ] Peter signs each audible boundary acceptable — **FAIL (2026-08-13):** words are not audibly identifiable. Root cause: fixture audio ~15–25 dB too quiet (sources −37/−44 dB, program −39.5 dB, analysis −42.4 dB mean @200 s); earliest-eligible words sit in the quietest regions (confidence 0.46–0.57); isolated re-transcription of word regions = silence; 10 s regions transcribe accurately (match artifact) → transcript mostly real, quietest words phantom/low-confidence. GATE-1 = **FAIL** (review.pending.json status FAIL, rounds 1–2 reasons recorded; failed run retained). Correction options: gain-normalize analysis-audio prep (product change) + re-run + re-review; or use a healthier consent-cleared fixture per TEST-AIGPU1-001. No manual sync nudges; production stays mock.

## 2. GATE-2 — Confirmed speaker identity (needs Peter's listening)

- [x] Every anonymous label has ≥2 program-audio snippets from distinct, non-overlapping turns. — 2 snippets per label served, verified via API.
- [x] Peter maps each anonymous voice to an existing project speaker + close camera; UI validates one-to-one bijection; no default preselected. — 2026-08-13: SPEAKER_00→interviewee/cam_right, SPEAKER_01→presenter/cam_left (Peter's reassignment); bijection verified (2 distinct speakers/cameras).
- [x] Confirmation persisted: `confirmed` status, operator identity, time, source run/artifact version, evidence-turn IDs. — Verified: version `live-20260813T235000Z`, operator + 2 evidence turns per row.
- [x] Page reload + public API/player-state read returns the same complete mapping. — API read-back verified post-save.
- [x] Stale artifact version cannot apply or display as current confirmation. — Old (phase6) confirmations showed `stale` for the new artifact until re-confirmed.
- [ ] Label-swap rerun: identities follow only current voice revalidation or fresh confirmation — automated resolver regression coverage; live rerun not executed in this window.
- [x] Transcript/LLM-only evidence cannot resolve identity; conflicts stay unresolved and route wide. — Resolver/UI contract verified in code + API (conflict states fail closed).
- [x] Peter signs both voices mapped to the correct people/cameras. — 2026-08-13 reassignment ("audio clips were fine for me to identify"). **GATE-2 = PASS.**

## 3. GATE-3 — Speaker-turn cut acceptance (needs Peter's per-window review)

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
- [ ] Ollama unloaded before, throughout, after (no loaded models).
- [ ] Dots in Peter's intended state; representative generation = 600-char workload, 12 steps, guidance 1.3 (+3dB/MP3 post-processing reported separately as non-residency load).
- [ ] Phases: 10s baseline → Dots resident/idle 10s → cold WhisperX readiness + full job with Dots resident → stable co-resident → active overlap (Dots + WhisperX inference overlapping ≥5s) ×2 → 30s post.
- [ ] Both Dots outputs non-empty/playable; both WhisperX jobs `done` with valid aligned words + 2-speaker turns + unchanged input hash.
- [ ] No CUDA OOM, CPU offload, model eviction/reload under pressure, readiness loss, queue overflow, container restart, app/Dots health loss.
- [ ] Headroom: max sampled used VRAM leaves ≥ `max(2048 MiB, 10% of total device memory)` free; report total / peak / min-free / threshold / phase / timestamp / contributing processes.
- [ ] Post-cleanup used VRAM within 512 MiB of preflight idle median (or explained by an intentionally resident approved service); app health OK; backends still mock.
- [ ] Peter authorizes the window and accepts the measured Dots state.

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
