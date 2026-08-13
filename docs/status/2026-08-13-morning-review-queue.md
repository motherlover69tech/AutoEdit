# AUTOEDIT — Morning review queue (2026-08-13)

Night-shift outcomes (2026-08-12 22:25 → 2026-08-13 01:05): queue driven autonomously; every card that could move did. This file is the consolidated list of **what needs Peter** and **what was logged for live testing**. Nothing below blocks the pipeline; all items are decisions or live-window tests for when you're back.

## ⚡ Pickup checklist (updated 01:31 UTC — coordinator worked the queue)
1. **Stage 7.4 loop active — Tester v3 `t_619890f0` DONE: delete-marker fix ACCEPTED, NEW bug found.** v3 ran the FULL acceptance: multi-author ✓, XSS-inert ✓, marker seek ✓, **delete-from-list-and-lane 2→1 and stable after refresh ✓ (BUG-7.4-DELETE-001 fix verified live)**; zero pageerrors. But **TEST_FAIL BUG-7.4-UI-RESPONSIVE-001 (medium)** — player page horizontal overflow at ≤800px (coordinator reproduced with measurements: scrollWidth 876@800 / 875@768 / 870@640; culprits `.player-controls` row + `.sync-nudge` cluster). **Correction `t_a58ec354` (wt/fix-7.4-ui-responsive) RUNNING (pid 453695)** → on READY_FOR_REVIEW: Designer review → Publisher deploy → Tester re-run.
   - **Harness-contract fix that unblocked the acceptance (v2 → v3):** explicit mutation authorization (named test project + create/delete notes), three-field login guidance (USERNAME + PASSWORD + DISPLAY NAME), scoped console criterion (zero pageerror + zero >=500 on player page; benign landing 401/404 + ERR_ABORTED media range requests ignored).
2. **Six acceptance chains await Peter's round decision — STILL PENDING (clarify sent 01:16 UTC, timed out).** Coordinator did NOT create the six next-round cards without explicit authorization (contract: "no further loop without Peter"). Suggested default when you're back: authorize one more round for all six — reviewers' line-level findings are the spec; D1's reviewer named the 16 remaining accepted forged mutations to encode as tests. D2's synthetic-PASS class → accept-with-risk stays off the table. One clarify answer → six cards created immediately (bodies already spec'd by the table below).
3. **Dispatcher lesson (do not repeat):** never re-queue a completed kanban card under its old idempotency key — the dispatcher won't claim it (stuck-spawn warnings). Clear terminal fields or create a fresh card; if the dispatcher wedges, restart it with `docker exec hermes-gateway /command/s6-svc -r /run/service/gateway-coordinator`. Blocked cards (no result) CAN be safely re-queued by clearing block fields — verified working 01:15.
4. **Browserless test container** (devops box): running on Tower :3002 (token in ops-stack/browserless/compose.yaml). Driver shim (append `?token=` to the CDP ws URL) still TBD before the Tester can use it; gateway chromium remains the active runtime. Optional.
5. Crons stay paused (Peter drives the queue via check-ins); verify pause state on the GATEWAY copy of jobs.json before trusting it.

## 1. Compliance decision queue — **ALL SIX CHAINS PARKED (FINAL round-4 verdicts: DESIGN_COMPLIANCE_FAIL, 2026-08-13 02:00–02:26 UTC)** ⛔

Peter authorized one final round for all six ("Create the cards and run them. If they can't be passed document it and move on"). All six round-4 implementations were executed against the exact findings and ALL SIX final checks returned **DESIGN_COMPLIANCE_FAIL** — per the authorization, **each chain is now DOCUMENTED and PARKED; no further loop.** The full numbered verdicts live in the check-card comments (below); candidates remain committed in their worktrees as the audit trail.

| Chain | Round-4 impl card | Final check card | Verdict | One-line reason (from the check) |
|---|---|---|---|---|
| **A** | t_f850829c (12c7ec0c) | t_e7dc0820 | **FAIL** | Five mandatory direct regressions absent (only 1 nominal test); probe is implementation-independent (raises before build_run_evidence); hand-authored PASS still forgeable (model_validate accepted rewritten status/results/gates); artifact_valid still tautological + derive_gate_statuses outputs overwritten |
| **A Gate-1** | t_0f4a83d4 (47f1636+d0c5411) | t_ddb46861 | **FAIL** | `_FIXTURE_SET_VALIDATION_TOKEN` is an importable module singleton — leading underscore is not an access boundary; tests themselves import it and mint accepted instances; independent replay still reproduced FORGED_TYPED_SET_ACCEPTED PASS. Trusted-host selected-run separation also not implemented. (Artifact path/run/bytes identity hardening PASSED.) |
| **B** | t_603fa02b (bb315e5+0da3212) | t_b0e2fe1a | **FAIL** | Swap is destructive (two-row swap ends with one row); current-voice evidence below the resolver's minimum-two rule so conflicts never derive (Bob contradiction stayed `confirmed`); silent proxy video URLs fabricated → HTTP 400 from media API; UI bijection incomplete (one blank can save alone; two-way swap blocked). UI-AIGPU1-005 (status live region) PASSED. |
| **C** | t_68ccc838 (a7305c8) | t_b672a111 | **FAIL** | Preservation assertions themselves are correct (both findings closed functionally) but the mandatory parent-RED gate is not met: the strengthened probes pass 34/34 against pre-fix 330e67e — no RED evidence |
| **D1** | t_9db0d442 (3076209+70e85d2) | t_da25a2f0 | **FAIL** | 28-mutation replay: **20 rejected / 28, 8 accepted-invalid**; all ten findings remain open (discovery forgeable, no RenderOnlyComposeAdapter, tick spacing fail-open, workload interval forgeable, empty process evidence passes, health/incident disconnected, drift/rollback unreconciled, JSON-pointer unenforced, deep scan absent, committed set not the mandated 28). **Reviewer: "Package D1 remains unsuitable as the semantic trust boundary for D2/live acceptance."** |
| **D2** | t_dc040f53 (78c16e1) | t_bb116b80 | **FAIL** | CRITICAL: caller-forged live PASS still possible (execute() accepts any injected adapter; forged evidence yielded {'verdict':'PASS','mode':'live',...}); ConcreteLiveAdapter not a concrete CLI-runnable boundary (CLI --execute unavailable; wraps caller callables; forces ineligible failure) |

**Consequences (documented, standing):** GATE-4 stays `NOT_RUN`. D1 cannot serve as the evidence trust boundary for D2. Production remains `WHISPER_BACKEND=mock` / `DIARIZE_BACKEND=mock` — none of these chains gate live deployment since none passed. Any future resurrection of a chain requires a NEW explicit Peter decision with a different approach (the findings are the spec); the two-round cap + this final authorization are exhausted.

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

## 3. Stage 7.4 — **CLOSED ✅ (03:36 UTC)**

- Tester acceptance on deployed `ac8407e` → **TEST_FAIL BUG-7.4-DELETE-001** (stale note markers in timeline lane after delete) → fix deployed 00:23 (69f5486d) → accepted by Tester v3 `t_619890f0` (all green except NEW BUG-7.4-UI-RESPONSIVE-001).
- Responsive fix loop: 5 review/correction rounds (probe executability, 1024 geometry, wide-geometry preservation, reachability) → **DESIGN_COMPLIANCE_PASS (t_b03e978a)** → deployed 03:32 (styles.css 232c551, image d60d773c, byte-verified) → **Tester v4 `t_e42b0506` TEST_PASS 03:36 UTC** — Stage 7.4 closed. Both fixes merged to master `1ba1783`.

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
