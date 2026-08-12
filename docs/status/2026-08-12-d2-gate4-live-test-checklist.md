# 🔴 D2 / GATE-4 — LIVE PUSH TEST CHECKLIST / SINGLE SOURCE OF TRUTH

**Maintenance rule — READ THIS FIRST:** this is the one living checklist for every future AUTOEDIT live push, Tester acceptance, and AI-GPU-1 gate run. Do not create a parallel list in a card, handoff, or release note. Every related card must link here. After each run or deployment, update the exact candidate/image, checkbox state, evidence pointers, verdict, and residual blockers in this file before reporting completion.

**Current status (2026-08-12 22:02 UTC):** checklist not yet executed against a live D2/GATE-4 run. D2/GATE-4 remains `NOT_RUN`; production remains `WHISPER_BACKEND=mock` / `DIARIZE_BACKEND=mock`. Tester route is `custom:9Router / cx/gpt-5.6-luna`, live-smoked as `TESTER_ROUTE_OK`. Stage 7.4 is blocked separately on the missing reviewer secret and local Chromium runtime.
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

- [ ] One current, hash-bound real ASR+alignment job reaches `done`; imported artifact passes strict validation (ordered non-empty words, integer-ms master-timeline times, provenance).
- [ ] Three words selected: earliest clearly audible non-overlapped word in each of three equal timeline thirds, both start and end boundaries assessed, both anonymous clusters represented where word/turn intersection allows (no cherry-picking after seeing errors).
- [ ] Six boundary errors each `<= frame_tolerance_ms` where `frame_tolerance_ms = 1000 * fps_den / fps_num` — no averaging away an outlier.
- [ ] Ground truth marked against `program.m4a` on the master timeline (browser may show silent proxy; source media never played); automatic sync offsets displayed, never adjusted.
- [ ] Peter signs each audible boundary acceptable (PASS/FAIL per mark).

## 2. GATE-2 — Confirmed speaker identity (needs Peter's listening)

- [ ] Every anonymous label has ≥2 program-audio snippets from distinct, non-overlapping turns (different timeline parts where possible).
- [ ] Peter maps each anonymous voice to an existing project speaker + close camera; UI validates one-to-one bijection; NO default preselected from angle/channel/label-order/transcript/LLM.
- [ ] Confirmation persisted: `confirmed` status, operator identity, time, source run/artifact version, evidence-turn IDs.
- [ ] Page reload + public API/player-state read returns the same complete mapping.
- [ ] Stale artifact version cannot apply or display as current confirmation.
- [ ] Label-swap rerun: identities follow only current voice revalidation or fresh confirmation — never prior anonymous labels alone.
- [ ] Transcript/LLM-only evidence cannot resolve identity; conflicts stay unresolved and route wide.
- [ ] Peter signs both voices mapped to the correct people/cameras.

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
