# Qwen3.8 audiovisual shadow slice — live handoff (2026-08-15)

## Purpose

This is the cold-start continuation record for the Qwen3.8 audiovisual speaker-evidence addition. Update it after every material board, profile, code, test, or context-window change so the next coordinator can resume without reconstructing chat history.

## Safety boundary

- Tasks 1–5 shadow experiment only.
- No deployment, production cut change, selected-cut mutation, player authority, export authority, active-speaker promotion, or production backend change.
- WhisperX and automatic audio sync retain timestamp authority.
- Qwen output is review/evaluation evidence only and must fail closed on invented or mismatched frame/turn references.
- Private media, names, transcripts, exact private timestamps, and fingerprints stay out of Git.

## Authoritative design

- Plan: `docs/plans/audiovisual-speaker-evidence-plan.md`.
- Routing record: `docs/status/2026-08-15-kanban-qwen38-routing.md`.
- Designer card: `t_fc89cea1` — `done`, result `DESIGN_APPROVED`.
- Designer worktree: `/workspace/AUTOEDIT/.worktrees/t_fc89cea1`.
- Approved design commit: `4e86167` (`docs: approve audiovisual shadow slice requirements`).
- Implementation worktree/branch: `/workspace/AUTOEDIT/.worktrees/t_b0c0bd87`, `wt/t_b0c0bd87`.
- Verified implementation candidate: `7bcd124` (`feat: add audiovisual speaker-evidence shadow slice`); worktree clean after commit.

## Live board snapshot

At the start of this continuation there is no running Qwen worker. The Designer card is done. These Programmer cards all remain blocked as preserved route/execution experiments and must not be blindly unblocked or duplicated:

- `t_b0c0bd87` — original implementation card; blocked after excessive discovery/zero writes.
- `t_e192cfcd` — blocked because Hermes `xhigh` was rejected by Ollama.
- `t_c596c4df` — blocked because Ollama `high` mapped to effectively unbounded Qwen `xhigh` reasoning and produced zero writes.
- `t_7546266f` — medium continuation; blocked after read-only turns.
- `t_a8691f45` — low override raced with claim and actually inherited medium.
- `t_e39cf47c` — verified-low continuation; blocked after repeated turns with zero writes.

Do not create another implementation card until the existing worktree has been independently reviewed and verified. Archive superseded experiments only after preserving their comments/run history and after a successor gate is established.

## Current implementation snapshot

The implementation worktree is no longer empty. It is based on `4e86167` and currently has an uncommitted Tasks 1–5 implementation:

Modified tracked files:

- `.env.example`
- `docs/plans/TESTING_STRATEGY.md`
- `src/autoedit/config.py`

Untracked implementation/evaluation files:

- `docs/ai/audiovisual-evaluation-protocol.md`
- `scripts/evaluate_visual_speaker_evidence.py`
- `src/autoedit/ai/qwen_visual.py`
- `src/autoedit/ai/visual_evidence.py`
- `src/autoedit/ai/visual_frames.py`
- `src/autoedit/ai/visual_window_selector.py`
- `tests/fixtures/visual_evidence/`
- `tests/test_qwen_visual.py`
- `tests/test_visual_evidence_contract.py`
- `tests/test_visual_evidence_metrics.py`
- `tests/test_visual_frames.py`
- `tests/test_visual_window_selector.py`

Previous coordinator review reached these required hardening checks before its context overflowed:

1. Exact `/api/show` vision/parent preflight.
2. Forced activity/CDL/selected-cut invariance roles.
3. Explicit Qwen outcome accuracy and safe-wide precision/recall.
4. Immutable frame publication.
5. Revalidate frame bytes immediately before publishing artifacts.

The files, diff, tests, and these five findings must be revalidated against the current worktree; do not assume they are already fixed merely because files exist.

## Worker route state after hardening

Current route authority is:

- Programmer: `custom:ollama / autoedit-qwen3.8:100k`, reasoning `low`.
- Tester: `custom:ollama / autoedit-qwen3.8:100k`, reasoning `low`.
- Publisher: `custom:ollama / autoedit-qwen3.8:64k`, reasoning `low`.
- Designer unchanged on local `custom:9Router`.
- Public OpenRouter forbidden across worker primary/fallback/auxiliary/delegation routes.

Reasoning evidence: `extra_high` is invalid; Hermes `xhigh` is rejected by Ollama; Ollama `high` maps to Qwen internal `xhigh`. A fresh 100K `medium` Programmer probe produced no output after four minutes at 96% GPU and was terminated. The template's `low` branch explicitly instructs brief/focused/action-oriented thinking. A fresh Programmer/100K/low session returned `PROGRAMMER_LOW_100K_OK` in 33 seconds.

## Tester capability state after hardening

Verified in live config and session state:

- Main toolsets include `file`, `terminal`, `browser`, `vision`, `computer_use`, and `skills`; `skills` is no longer disabled by `agent.disabled_toolsets`.
- `agent.image_input_mode: auto`; `auxiliary_models.vision` is pinned to the 100K main route.
- Focused quality/browser/computer-use/debugging/local-LLM/backend/media/export skills are enabled, and `autoedit-ops` is installed in the Tester profile.
- `SOUL.md` matches `100K/low` and requires an actual vision smoke before visual verdicts.
- Named Tester session `20260815_034136_517627` ran `autoedit-qwen3.8:100k`/`low`, issued a real `vision_analyze` call against the AUTOEDIT player screenshot, and returned `TESTER_VISION_OK`.

## Context-window result

- Dots processing was disabled by Peter for the measurement window.
- Base model advertises 262,144 native context; Ollama uses `q8_0` KV cache.
- Plain 100K load completed in 9.67 seconds; `/api/ps` reported `context_length: 100000`, `size_vram: 20879276768`; `ollama ps` reported 100% GPU; `nvidia-smi` reported 21,168 MiB used and 11,327 MiB free.
- Dedicated alias `autoedit-qwen3.8:100k` was created. `autoedit-qwen3.8:64k` remains intact for rollback and for the bounded product visual-inference path.
- Reassess the 100K Kanban route before Dots resumes.

## Exact next actions

1. Let exact-directory Designer compliance card `t_0a292cd1` finish against `7bcd124`; do not duplicate or interrupt it while heartbeat/log/session activity remains fresh.
2. If it returns bounded findings, create one Programmer correction card scoped exactly to those findings, then one round-2 compliance re-review.
3. Only after `DESIGN_COMPLIANCE_PASS`, create one independent Tester card with backend/API, real browser, actual vision, screenshots, console/network, responsive and privacy/invariance evidence. No Publisher/deploy card for this shadow slice.
4. Real L0 remains separately blocked on one locked consent-cleared external fixture and exclusive V100 window; synthetic tests are never real-media acceptance.

## Evidence log

Append timestamped entries below. Keep each entry terse: change, command/evidence, result, exact next gate.

- 2026-08-15 pickup: board/profile/worktree reconstructed; no worker running; implementation worktree contains uncommitted Tasks 1–5 code; Tester skill/vision policy gaps identified.
- 2026-08-15 context: 100K plain load 9.67s; `/api/ps` 100000 / 20,879,276,768 bytes VRAM; `ollama ps` 100% GPU; `nvidia-smi` 21,168 MiB used / 11,327 MiB free. Alias `autoedit-qwen3.8:100k` created; 64K preserved.
- 2026-08-15 reasoning: fresh 100K/medium exact-token Programmer probe produced no output after four minutes at 96% GPU and was terminated. Switched Programmer/Tester to explicit `low` based on template branch and prior execution behavior.
- 2026-08-15 route proof: Programmer session `20260815_034100_9de14f` ran 100K/low and returned `PROGRAMMER_LOW_100K_OK` in 33s. Tester session `20260815_034136_517627` ran 100K/low, issued real `vision_analyze` on the AUTOEDIT player screenshot, and returned `TESTER_VISION_OK`.
- 2026-08-15 tester hardening: `vision`, browser, computer-use and skills toolsets enabled; quality/browser/debug/local-LLM/backend/media/export skills enabled; `autoedit-ops` installed; SOUL aligned to 100K/low and actual-vision proof.
- 2026-08-15 RED→GREEN: added/fixed exact `/api/show` vision+parent preflight, typed fixture/camera/invariance/Qwen-outcome contracts, Qwen accuracy and safe-wide precision/recall, immutable frame publication, and pre-publication frame-byte revalidation. Strict synthetic example now validates but remains `l0_eligible=false`.
- 2026-08-15 gates: focused final 34 passed + Ruff/compile/diff PASS; post-schema invariance set 125 passed + Ruff/compile/diff PASS. WebUI full suite reached 927 passed / 5 environment skips / one ffmpeg-required environment failure. Exact `hermes-gateway` runtime (ffmpeg/ffprobe present) then passed the media requirement test and the full deterministic suite: **930 passed / 3 expected skips in 28.96s**.
- Independent read-only review children timed out and are not approvals. Their useful pre-fix observations were converted into executable regressions above; Designer compliance remains mandatory.
- 2026-08-15 candidate: the exact 15-file Tasks 1–5 boundary was committed as `7bcd124`; `git log -1` showed that SHA and `git status --short --branch` was clean.
- 2026-08-15 board advance: six superseded Programmer experiments were audit-commented and archived. First compliance card `t_f58c3d36` was caught reviewing rematerialized HEAD `d9163ec` rather than candidate `7bcd124`; it was safely blocked/archived before verdict. Exact-directory replacement `t_0a292cd1` points to `/workspace/AUTOEDIT/.worktrees/t_b0c0bd87`, is assigned to `autoeditdesigner`, and reached Running as the board's only eligible card. Tester remains dependency-gated on `DESIGN_COMPLIANCE_PASS`.
