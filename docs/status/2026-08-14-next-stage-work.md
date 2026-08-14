# AUTOEDIT — Next-stage work (post round-7 / live window)

Date: 2026-08-14. Purpose: the single pickup list for the next stage. Every item = a verified finding + precise spec + owner + the decision it needs. Sources: round-7 check verdicts (`t_3d25e9ea`, `t_d8dffaa4`, `t_85c5cd26`), the live-window record (`docs/status/2026-08-14-live-window-record.md`), the checklist (`docs/status/2026-08-12-d2-gate4-live-test-checklist.md`).

## Gate status

| Gate | State |
|---|---|
| GATE-1 word timing | **PASS** (round-2 accepted; loudnorm prep fixed the quiet-fixture root cause) |
| GATE-2 speaker identity | **PASS** (both voices re-confirmed for `live-20260814T004600Z`) |
| GATE-3 cut review | **OPEN — decision needed (W1)** |
| GATE-4 coexistence | **PASS** (re-measured; min real headroom 17,176 MiB ≥ 3,277) |

Production remains `WHISPER_BACKEND=mock` / `DIARIZE_BACKEND=mock`; crons paused.

## Work items

### W1 — GATE-3: decision + post-gap fix (needs Peter's decision first)
- **Decision:** (a) accept the current candidate with findings (5 documented boundary-crossing post-gap clips — `20260814-live-window-gate4/browser-review.json`), or (b) resurrection card scoped to the check's findings (requires Peter's explicit go).
- **If (b), the spec (from check `t_85c5cd26`):**
  - `POSTGAP-R1` — GENERAL turn-onset snap: every projected turn that would cut into an earlier-started aligned word snaps to that word's start (frame-boundary ms) — not only inside the post-gap branch. Probe: turns `[0,1000]`/`[1000,2000]`, turn-2 word `[900,1100]` → projection must start the second turn at 900.
  - `POSTGAP-R2` — order-independent gap classification: silence-gap detection derived from the sorted timeline, never caller-order (`previous_end` in input order). A reordered `diarization_turns` input must produce identical output (no false post-gap → no spurious wide).
  - RED regression fixture committed FIRST (both probes above fail on current code, pass after); focused + full pinned suite green (`OLLAMA_BASE_URL='' LLM_MODEL='' env -u VIRTUAL_ENV uv run pytest -q -rs`).
- **Flow after PASS:** one final check (Designer) → merge (narrow diff) → deploy app-only via `scripts/autoedit-deploy.sh` (backup → push → rebuild → verify; mock stays) → regenerate the candidate from artifact `live-20260814T004600Z` + existing confirmations (no re-analysis, no re-listening) → Peter re-review.

### W2 — Package A: new approach required (parked; resurrection needs Peter's decision + a different approach)
Findings from `t_3d25e9ea` (three rounds of failure on the same security property — rethink the approach before any resurrection):
1. **Forged all-PASS still accepted:** `construction_proof` is serialized into the evidence, attacker-controlled, and fed back as validation context — an independent replay converted a validator-built BLOCKED/FAIL into an accepted PASS. The digest is unkeyed SHA-256 over public fields; the purported per-run secret is disclosed in the evidence and self-authenticates. → Requirement: keyed digest or real signature whose secret NEVER appears in the evidence payload; proof authority validator-side only.
2. **Direct on-disk regressions absent:** no committed tests for nonexistent artifact, wrong stored-byte digest, or stored-timestamp mismatch against the on-disk artifact.
3. **Corrected probe has no RED:** passes on BOTH ancestors `12c7ec0c` and `2aa9df4` (it exercises the digest-mismatch path, which passes on ancestors too) — the probe must target the actually-changed construction boundary.
4. **`artifact_valid` tautological:** equality rejection precedes the equality-based result (`golden_fixture.py:694-695` vs `:728`) — derive the result from an independent check.

### W3 — Package B: surgical fixes (parked; resurrection needs Peter's decision; do NOT deploy `080784f`)
Findings from `t_d8dffaa4`:
1. `BACKEND-AIGPU1-003` — the complete two-row swap must run as ONE transaction; today the endpoint rejects the one-row pending resolution (409) before the pair transaction can run. The swap must allow the pair resolution when current-voice evidence exists for both rows.
2. `UI-AIGPU1-003` — cross-row completeness: save must be disabled until ALL unresolved rows are filled (`app.js:449-450`, `speaker_mapping_logic.js:14-19` never inspect other blank rows).
3. Tests-first with parent RED (round-6 added no tests; focused 7 green covers neither surviving defect).
- After a check PASS: rollout decision still required before deploy (touches the speaker-confirmation flow). Resolver conflict GET + conflict UI rendering already PASS.

### W4 — A-Gate1 check completion (in progress; no decision needed)
- Both check attempts silent-exited without a verdict (`t_fe9c14a5`, then the re-dispatch `t_04f4a59e`). Worktrees verified clean at `64643f8`; production untouched; designer agent log ends 01:58:46 with normal tool activity, no traceback (session/route failure mid-check).
- Next: investigate the worker silent exit (agent.log / route) BEFORE a third attempt — do not re-dispatch blindly. Then complete the one mandated check (body = `Round-7 FINAL compliance check — Package A Gate-1`).

### W5 — D2 / GATE-4 executor rebuild (parked, multi-day; needs a separate Peter decision)
Unchanged scope: real concrete orchestration (Compose parse/render, worker/Dots/Ollama boundaries, health checks, continuous phase-marked sampler), provenance from observed boundary responses only, repair the 3 legacy tests. Note: the live window already produced GATE-4 evidence manually (PASS); D2's value = automating it. Reference: `docs/plans/ai-gpu-1-corrective-pickup.md`.

### W6 — Tech debt / live-window lessons (backlog; no decisions needed)
- **W6.1 `/cuts` MySQL sort-buffer (live 500, fixed ad hoc):** durable fix = `sort_buffer_size` in the compose/env config + index on `cuts(project_id, created_at, id)`; the live fix (SET GLOBAL 16M + container conf.d `zz-sortbuf.cnf`) is ephemeral to the container.
- **W6.2 GPU sampler cross-check:** validate the `used` column against the per-process sum; flag >20% discrepancies. nvidia-smi transients during pyannote churn produced false 294 MiB "headroom" readings (proven by per-process sums at the same instants).
- **W6.3 Worker test envs:** pin `OLLAMA_BASE_URL='' LLM_MODEL=''` — `test_conciseness` calls the external LLM path, loads Qwen into Ollama (8.9 GB), and stalls; breaks any Ollama-empty requirement.
- **W6.4 Dots job status timing:** the API flips to `completed` ~40 s before the long-form WAV finishes assembling — measure completion by output-file mtime.
- **W6.5 Diarization quality (worker-level):** post-gap cluster confusion (the GATE-3 root cause) — label-continuation validation via pre-gap cluster embedding similarity; W1's projection fail-closed is only the app-side mitigation.

## Protocol notes
- **Parked = permanent** without a new explicit Peter decision + a different approach (A, B, GATE-3 fix; D2 separately).
- Exactly one final check per chain; no correction loops.
- Worker silent-exit rule: verify no mutation, do not re-dispatch blindly.
- Docs pushed to GitHub through `eeb1584`.

## Evidence pointers (private, consent-controlled)
- `/mnt/user/automulticam/ai-gpu-1-acceptance/20260813-live-window/` — worker results, review manifests.
- `/mnt/user/automulticam/ai-gpu-1-acceptance/20260814-live-window-gate4/` — `browser-review.json`, `coexistence-summary.json`, `gpu-samples.csv`, `run.log`.
- Board cards: `t_3d25e9ea` (A), `t_d8dffaa4` (B), `t_85c5cd26` (GATE-3 fix), `t_04f4a59e` / `t_fe9c14a5` (A-Gate1 check), `t_31613627` (fix implementation).
