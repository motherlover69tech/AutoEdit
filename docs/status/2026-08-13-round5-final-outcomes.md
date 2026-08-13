# Round-5 final outcomes — six acceptance chains (2026-08-13 ~22:32 UTC)

Peter authorized ONE more round (round-5) for all six chains on 2026-08-13 pickup ("complete any checks needed and move on").
All six round-5 implementations ran; six final Designer compliance checks were dispatched at 22:12 UTC and all verdicts landed by 22:32 UTC.

## Verdict table

| Chain | Round-5 impl card / commit | Final check card | Verdict | One-line reason (from the check) |
|---|---|---|---|---|
| **A** | t_0f6cb9fb / 2aa9df4 | t_d63ed4dc | **FAIL** | 4 of 5 mandated direct regressions absent; corrected probe still passes on parent 12c7ec0c (no RED); hand-authored all-PASS forgeable via attacker-recomputed unkeyed `evidence_digest`; `artifact_valid` still tautological |
| **A Gate-1** | t_ee5e4c59 / f257f7f | t_12526b7f | **FAIL** | Provenance digest stored in an importable mutable module registry — caller minted distinct-ID set, registered digest, got `FORGED_CALLER_SET_ACCEPTED PASS`; `evaluate_current_run()` accepts a PASS record from a foreign run directory (`MISPLACED_RUN_EVIDENCE_ACCEPTED`) |
| **B** | t_27cc0a63 / 8ecad13 | t_0afea5ff | **FAIL** | Swap now fails closed (409, rows preserved — improvement) but the required complete bijection swap is never performed; GET still returns `confirmed` under contradictory current-voice evidence (status precedence over resolver); UI blank-row partial save + two-way swap still blocked (app.js untouched) |
| **C** | t_95f96841 / (evidence-only, a7305c8) | t_16a7312f | **PASS ✅** | Genuine RED proven by overlay on the true pre-fix ancestor 80fc8df (21 passed / 2 failed: 200 vs 422/409); candidate GREEN 34 focused + 857 full / 3 skipped |
| **D1** | t_9a9f2e1f / 5b31c21 | t_24bcb7fa | **FAIL** | Mandatory 28-mutation replay now rejects ALL 28 (20 anchors + 8 round-5 targets) and the deep private/name/token scan passes — but nine-category discovery still not collected/derived, lifecycle enforcement bypassable via mock `render_compose()` override, interval stats/anchors unenforced, `tests.results` + requirement statuses still prefilled PASS from `build_mock_evidence()` |
| **D2** | t_36144553 / a55094a+e8e86a2 | t_e8b5557c | **FAIL** | `ConcreteLiveAdapter` subclass with own public provenance token still yields `{'verdict':'PASS','mode':'live',...}`; shipped CLI `--execute` is a synthetic no-op PASS path built on `build_mock_evidence()` defaults; sampling not interleaved/phase-faithful; Compose topology checks incomplete (nested secrets + real backends pass); cleanup not try/finally; **all 3 legacy test failures ruled GENUINE REGRESSIONS**, not obsolete expectations |

## Consequences (standing, recorded)

- **C is CLOSED** (round-5 PASS). Its changes are test-only (`tests/test_ai_cut_atomicity.py`, 26+/8-) — no runtime code, **no deploy**. The preservation assertions (exact mirror bytes + prior selected cut_id/version unchanged in both contract-invalid scenarios) are the merged test authority for the atomicity/superseded-candidate contract.
- **A, A-Gate1, B, D1, D2 are PARKED permanently.** The two-round cap, the round-4 one-final-check authorization, and the round-5 authorization are all exhausted. Per the contract, any future resurrection requires a NEW explicit Peter decision with a different approach (the numbered findings are the spec). No further loop.
- **B is NOT deployed.** Round-5 changed `src/autoedit/api.py` (runtime) and failed compliance — the speaker-confirmation persistence changes remain on `wt/pkg-b-correction` @ 8ecad13 only.
- **GATE-4 stays NOT_RUN; production stays `WHISPER_BACKEND=mock` / `DIARIZE_BACKEND=mock`.** D1 remains unsuitable as the semantic trust boundary for D2/live acceptance; D2's live PASS path remains forgeable.
- **D1 full-suite stall was environmental, not code** — the reviewer ran the full mock-isolated suite independently: **896 passed / 3 skipped in 27.12s**, no hang (the worker's stall coincided with 6 concurrent workers sharing the box).
- Round-5 impl + check cards remain on the board as the audit trail (impl cards blocked `needs_input`; check cards done/blocked with verdicts).
- Live-test blockers (GATE-1 frame timing, GATE-2 identity confirmation, GATE-3 speaker-turn review, GATE-4 coexistence window) remain logged in `docs/status/2026-08-12-d2-gate4-live-test-checklist.md` — unchanged, not queue-blocking.
- Crons remain paused; dispatcher healthy; docs pushed to master (`c219274` + this update).

## Reviewer-run test totals (independent)

- A: focused 23 passed; full 858 passed / 3 skipped (2 trusted-root + 1 MySQL).
- A Gate-1: focused 23 passed / 3 skipped; full 860 passed / 4 skipped.
- C: atomicity+cut-selection 34 passed; full 857 passed / 3 skipped.
- D1: focused 132 passed; full 896 passed / 3 skipped.
- B, D2: full-suite evidence in the check-card comments (B: 856 passed / 3 skipped worker-side).
