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

1. Let exact-directory Designer compliance card `t_0a292cd1` close cleanly with its seven bounded findings.
2. Create one Programmer correction card scoped exactly to those seven findings, tests first, on the existing exact candidate worktree; then one round-2 exact-directory compliance re-review.
3. Only after `DESIGN_COMPLIANCE_PASS`, create one independent Tester card with backend/API, real browser, actual vision, screenshots, console/network, responsive and privacy/invariance evidence. No Publisher/deploy card for this shadow slice.
4. Real L0 remains separately blocked on one locked consent-cleared external fixture and exclusive V100 window; synthetic tests are never real-media acceptance.

## Active continuation — Qwen documentation and board monitoring

- Scope: recover the live correction/review chain, research authoritative Qwen3.8/Ollama guidance for visual speaker-identification evidence, record the resulting constraints here, and reflect the research/verification work on the Kanban board.
- Context-control rule: query only bounded task/session columns and short log tails; never ingest full worker transcripts or unbounded test output into the coordinator context.
- Recovered checkpoint: exact implementation candidate remains clean at `7bcd124`; main contains the committed seven-finding handoff; the last observed correction run was task `t_4276a07b` on `autoedit-qwen3.8:100k` with Hermes reasoning `low`.
- Research completed against the official Qwen3.8-27B model card, official Ollama capability/API docs, and the installed aliases' live `/api/show` response.

### Documented Qwen3.8 policy for speaker-identification evidence

1. **Capability, not acceptance:** Qwen3.8-27B is a native vision-language model for images/video and supports per-request thinking control. This establishes technical eligibility for the shadow experiment, not proven active-speaker accuracy on AUTOEDIT media.
2. **Separate reasoning policies:** Kanban Programmer/Tester agents remain on Hermes reasoning `low`. The product visual assessor must explicitly send `think:false`; no Kanban reasoning level may leak into that request.
3. **Exact product request:** local `autoedit-qwen3.8:64k`; ordered base64 images; `stream:false`; strict JSON Schema in `format`; `temperature:0`; bounded output/retries; `keep_alive:0`.
4. **Permitted role:** classify supplied source-bound frames as `speaking`, `listening`, `reaction`, `off_camera`, or `unknown`, and state support/contradiction relative to the supplied bound WhisperX/camera hypothesis.
5. **Forbidden authority:** Qwen may not name or biometrically identify a person, establish/alter person-camera mappings, invent frame/turn/camera references, create timestamps, rewrite WhisperX boundaries, or select/change a cut. Operator-confirmed mappings remain identity authority.
6. **Fail closed:** missing, duplicated, reordered, invented, malformed, or thinking-bearing output is an explicit shadow-analysis failure; never an empty success.
7. **Promotion evidence:** only consent-controlled human-vs-WhisperX-vs-Qwen metrics can show usefulness. Model documentation and synthetic tests cannot pass real L0.

Sources checked:

- Qwen model card: `https://huggingface.co/Qwen/Qwen3.8-27B`
- Ollama thinking: `https://docs.ollama.com/capabilities/thinking`
- Ollama vision: `https://docs.ollama.com/capabilities/vision`
- Ollama structured outputs: `https://docs.ollama.com/capabilities/structured-outputs`
- Ollama chat API: `https://docs.ollama.com/api/chat`
- Live `/api/show`: base and `64k`/`100k` aliases advertise `vision`, `thinking`, `tools`, and 262,144 native context; aliases pin 65,536 and 100,000 context respectively.
- Installed template: thinking defaults to `xhigh`; accepts `xhigh|medium|low`; maps `high` to `xhigh`; `enable_thinking=false` bypasses reasoning instructions.

## Evidence log

Append timestamped entries below. Keep each entry terse: change, command/evidence, result, exact next gate.

- 2026-08-15 continuation pickup: recovered prior session `Advance Qwen 3.8 kanban integration`; switched monitoring to bounded SQLite/task fields after repeated context overflow; candidate still clean at `7bcd124`.
- 2026-08-15 docs/runtime: official Qwen card confirms native image/video understanding, controllable thinking, and 262,144 native context. Official Ollama docs confirm `images`, `think`, JSON Schema `format`, deterministic `temperature:0`, and `keep_alive`. Live `/api/show` confirms the installed Q4 parent and both aliases advertise vision.
- 2026-08-15 board correction: detected two simultaneous Programmer cards. `t_500689e0` was a Designer-created wrong-base worktree at `cd38b87` where `7bcd124` was not an ancestor; blocked as a superseded dependency duplicate and its run 480 ended blocked. Valid exact-directory correction `t_4276a07b` remains the sole active correction.
- 2026-08-15 review gate: created dependency-gated exact-directory Designer round-2 card `t_d00ab884`, explicitly requiring Qwen speaker-evidence constraints and separation of Kanban `low` reasoning from product `think:false`.
- 2026-08-15 context: 100K plain load 9.67s; `/api/ps` 100000 / 20,879,276,768 bytes VRAM; `ollama ps` 100% GPU; `nvidia-smi` 21,168 MiB used / 11,327 MiB free. Alias `autoedit-qwen3.8:100k` created; 64K preserved.
- 2026-08-15 reasoning: fresh 100K/medium exact-token Programmer probe produced no output after four minutes at 96% GPU and was terminated. Switched Programmer/Tester to explicit `low` based on template branch and prior execution behavior.
- 2026-08-15 route proof: Programmer session `20260815_034100_9de14f` ran 100K/low and returned `PROGRAMMER_LOW_100K_OK` in 33s. Tester session `20260815_034136_517627` ran 100K/low, issued real `vision_analyze` on the AUTOEDIT player screenshot, and returned `TESTER_VISION_OK`.
- 2026-08-15 tester hardening: `vision`, browser, computer-use and skills toolsets enabled; quality/browser/debug/local-LLM/backend/media/export skills enabled; `autoedit-ops` installed; SOUL aligned to 100K/low and actual-vision proof.
- 2026-08-15 RED→GREEN: added/fixed exact `/api/show` vision+parent preflight, typed fixture/camera/invariance/Qwen-outcome contracts, Qwen accuracy and safe-wide precision/recall, immutable frame publication, and pre-publication frame-byte revalidation. Strict synthetic example now validates but remains `l0_eligible=false`.
- 2026-08-15 gates: focused final 34 passed + Ruff/compile/diff PASS; post-schema invariance set 125 passed + Ruff/compile/diff PASS. WebUI full suite reached 927 passed / 5 environment skips / one ffmpeg-required environment failure. Exact `hermes-gateway` runtime (ffmpeg/ffprobe present) then passed the media requirement test and the full deterministic suite: **930 passed / 3 expected skips in 28.96s**.
- Independent read-only review children timed out and are not approvals. Their useful pre-fix observations were converted into executable regressions above; Designer compliance remains mandatory.
- 2026-08-15 candidate: the exact 15-file Tasks 1–5 boundary was committed as `7bcd124`; `git log -1` showed that SHA and `git status --short --branch` was clean.
- 2026-08-15 board advance: six superseded Programmer experiments were audit-commented and archived. First compliance card `t_f58c3d36` was caught reviewing rematerialized HEAD `d9163ec` rather than candidate `7bcd124`; it was safely blocked/archived before verdict. Exact-directory replacement `t_0a292cd1` preflighted exact clean `7bcd124` and returned `IMPLEMENTATION_CHANGES_REQUIRED` with seven bounded findings: bind/derive the audio hypothesis; make frame-time evidence strictly representable; enforce selector/window/frame budgets in the real runner; close traversal/symlink/hard-link/TOCTOU gaps; revalidate every bound private input and bind comparison evidence before publication; evidence GPU exclusivity across inference intervals; and enforce all visual derivative/retention rights. Tester remains dependency-gated on `DESIGN_COMPLIANCE_PASS`.
