# AUTOEDIT — Morning review queue (2026-08-13)

Night-shift outcomes (2026-08-12 22:25 → 2026-08-13): queue driven autonomously; every card that could move did. This file is the consolidated list of **what needs Peter** and **what was logged for live testing**. Nothing below blocks the pipeline; all items are decisions or live-window tests for when you're back.

## 1. Compliance decision queue (FINAL checks all FAILED — no further loop without you)

All five FINAL round-3 compliance checks were executed against the exact committed candidates (verified worktrees, real commits) and returned **DESIGN_COMPLIANCE_FAIL** with line-level findings. Per the review contract, no further round starts without your authorization.

| Chain | Candidate | Verdict | Gap in one line | Next round would need |
|---|---|---|---|---|
| **A** (t_745ed2cc) | cf915d9 | FAIL | bytes-hash fixed (PASS), but `build_run_evidence()` still hard-codes `fixture_result="PASS"` + derives SEC-AIGPU1-005 from a caller decision, and only 2 of 6 required direct regressions were added | wire the scoped `derive_gate_statuses()` into `build_run_evidence()`, add the 4 missing regressions |
| **A Gate-1** (t_1cda8d9b) | 444f4fc+3b00689 | FAIL | `FixtureSetValidation` is a forgeable 4-field dataclass (duplicate IDs probe → FORGED_TYPED_SET_ACCEPTED PASS); artifact binding caller-relative (trust root derived from the supplied path, not the configured root); readiness vs selected-run still not separated (integration test byte-identical to base) | provenance/digest on FixtureSetValidation + validator-produced instances only; trusted-root confinement + run_id identity proof; split the integration tests |
| **B** (t_2c9e2be6) | 38e964e | FAIL | `resolve_speaker_mappings` called without current-voice evidence or prior confirmations; implicit single-row swap not a trustworthy bijection transaction; GET doesn't use the resolver; conflict/revalidation UI states unreachable; several UI items unmet | full resolver wiring (evidence + prior confirmations), transactional swap, GET via resolver, UI states, tests |
| **C** (t_0abbb32c) | 330e67e | FAIL | product guards PASS (422/409/mirror) but the preservation tests still don't assert prior `cut_id`+`version` unchanged (mirror-bytes assertion incomplete; `prior_selection_project_id` is the project id, not the cut id) | snapshot + assert prior selection identity/version + exact mirror bytes in both scenarios |
| **D1** (t_a380c78d) | 5bf56a6+57163b4 | FAIL (2nd) | rebuild improved forged-probe rejection 6→12 of 28 but 16 of 28 forged-invalid mutations still accepted; all ten findings remain open (no RenderOnlyComposeAdapter symbol, nine-category discovery absent, deep scan incomplete, VAL-TEST mapping gaps) | the ten findings again, with the reviewer's 16 remaining accepted mutations as the test spec |
| **D2** (t_e629e9bf) | e1b6e93+1b60b2f | FAIL | ConcreteLiveAdapter still not runnable: `mutate()`/`sample()` raise unavailable, `evidence_from_run()` still calls `build_mock_evidence()`; forged adapter still yields live PASS; samples once per phase; no unload_ollama, no Compose renderer, no cleanup/rollback; regression set still missing the successful-path and response-derived-evidence proofs | implement the concrete boundary adapter with real orchestration + continuous sampler + rollback (all offline-testable) |

**Suggested default when you're back:** authorize one more round for the five failed chains (tests-first, same bounded findings) — they are all close, with the reviewers' line-level findings as the spec (D1's reviewers even name the 16 remaining accepted forged mutations to encode as tests). D2's synthetic-PASS class means accept-with-risk stays off the table.

## 2. Live-test blockers (logged, NOT queue-blocking — from the highlighted checklist)

`docs/status/2026-08-12-d2-gate4-live-test-checklist.md` is the single source of truth for these; all remain open:
- **GATE-1** — audible word marks / frame-level word timing on real media (V100 WhisperX window)
- **GATE-2** — voice-identity confirmation decisions (operator-in-the-loop)
- **GATE-3** — per-window speaker-turn cut review (editorial)
- **GATE-4** — V100/Ollama/Dots coexistence + peak-VRAM authorization window (production stays mock until passed)

## 3. Stage 7.4 — in background flow (no Peter action needed)

- Tester acceptance on deployed `ac8407e` → **TEST_FAIL BUG-7.4-DELETE-001** (stale note markers in timeline lane after delete).
- Fix committed (bfe6a5f); first review: **product logic PASS, probe defects FAIL** (test-only).
- Probe repair committed (3728b71, `STAGE_7_4_XSS_GATE_PASS` with real Chromium); two more test-only probe rounds (network observability, identity assertions + LUT fixture) → **DESIGN_COMPLIANCE_PASS (t_2144e23e, 00:15 UTC)**. **Publisher deploy `t_f8502a1c` (player.js 3728b71) + Tester re-run `t_2345969a` now RUNNING (background).**

## 4. Optional / infra
- **Browserless test container** (devops container): running on Tower :3002, token-authed. Driver shim (append `?token=` to the CDP ws URL) still TBD before the Tester can use it; gateway chromium remains the active browser runtime. Low priority.
- **Harness packages (A/A-Gate1/D1/D2)** are offline tooling — no deploy needed when they pass; only B and C touch runtime app code and would deploy through the normal Publisher flow.

## 5. Test totals (what ran green tonight)
- B correction: 854 passed / 3 skipped; node suites green
- C correction: 857 passed / 3 skipped
- D2 rebuild: 865 passed / 3 skipped
- D1 rebuild: 877 passed / 3 skipped (focused harness/exhaustive 99)
- A-Gate1: 857 passed / 3 skipped (focused 20)
- 7.4 fix: 854 passed / 3 skipped; node player_logic green
- Skips are always: 2 golden-media fixture (AUTOEDIT_GOLDEN_MEDIA_ROOT absent) + 1 central-MySQL credentials.
