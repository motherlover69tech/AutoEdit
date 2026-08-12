# 2026-08-12 — WhisperX Live Session: Selection, Tail Handling, and Cut-Review Fixes

**Status: ALL SHIPPED + LIVE + VERIFIED by Peter ("all confirmed working").** Master at `ac8407e` (remote == local).

## Session goal

Take the Phase 6 WhisperX work from "deployed candidate" to "Peter can actually use it":
make the WhisperX cut selectable/active, make the player behave per Peter's product
decision on the audio tail, and fix the cut-review preview/save UX so the param
tweaks he wants actually take effect and save cleanly.

## What shipped (5 commits, in order)

| Commit | Change | Live image / proof |
|---|---|---|
| `743d801` | **Player tail handling** — player stops at the end of the cut content (`cutEndMs(clips)` + render() pause; play at/past end replays from top). Program-audio tail after the last covered frame is deliberately disregarded (Peter decision: *"player to stop when the first feed has ended"*). | player.js `77c586c9`, image `4d892aee` (frontend deploy) |
| `322cfe8` | **`whisperx_available` in player-state** — the P5-C cut-review panel disabled the WhisperX radio unless the backend reported `analysis.whisperx_available`, but player-state never sent it, so the radio was **always disabled even when all gates passed**. Now computed mirroring the `/cut` gates: artifact present + Gate 1 accepted for current version + every observed speaker confirmed + wide angle exists. | api.py `818f9aa8`, image `1fcb0c9a`; live response: `whisperx_available: true` |
| `53f50bb` | **Regenerate sends all 8 cut-param controls** — the handler only forwarded 5 of 8 (`wide_interval_ms`, `overlap_min_ms`, `interject_max_ms` were silently dropped, so changing them or the presets had no effect). | player.js `d5334307`, image `1733f214` |
| `ac8407e` | **Save-cut fix** — `setupCutReview` read `selection_version` from `statePayload.selection_version` but player-state exposes it at `statePayload.cut.selection_version`, so save always sent `expected_version: 0` → backend 422. Plus: structured FastAPI 422 `detail` (an array) rendered as `[object Object]`; new `apiErrorMessage()` flattens array/object details into readable text in both save and regenerate paths. | player.js `09abb60b`, image `0d6228f7` |
| (docs) | WhisperX cut selected live; handoff ID typo corrected (`01KZT3372CDNV7SBKK18STZR2Z`, not `...STZRZ2`). | — |

## Live selection state (project "sm test cab")

- **Project:** `01KXPHM8XCBKZ96Y2JN6T9Q2MC`
- **Selected cut:** WhisperX candidate `01KZT3372CDNV7SBKK18STZR2Z` — **version 2**, selected 2026-08-12 ~17:14 UTC via `PUT /projects/{id}/cut-selection` (selected_by `autoedit-test` reviewer account).
- **348 clips, last clip end 666,167 ms** (terminal truncation applied: `applied=true`, `reason_code=terminal_authorized_camera_coverage_exhausted`, omitted tail 5,129 ms).
- `edit/cdl.json` mirror rewritten with the WhisperX CDL; `analysis_source: whisperx`.
- Revert anytime: `PUT` VAD cut `01KXPJJDCFSM377W46WDS1CJZ3` with `expected_version: 2`.
- Note the **handoff ID typo**: docs originally said `01KZT3372CDNV7SBKK18STZRZ2`; the real ID ends `STZR2Z`.

## How the cut-review workflow works (documented for operators)

The Cut Parameters panel is a **preview workflow**, not a direct editor:

1. Change params (or use Direct / Steady / Looser presets).
2. **Regenerate Cut** → creates a new **candidate** (immutable, versioned) and previews it. The persisted selected cut is deliberately untouched — the "current cut unchanged" status line is the non-destructive A/B design.
3. **Save this cut** (Cut Review panel, under the source radios) → commits the preview as the selected cut via `PUT /cut-selection` (optimistic concurrency on `expected_version`).
4. **Discard preview** → drops the candidate, back to the saved cut.

All 8 controls are effective on regenerate: `min_shot_ms`, `overlap_to_wide`, `lead_in_ms`, `tail_ms`, `silence_behaviour` (wide|hold), `wide_interval_ms`, `overlap_min_ms`, `interject_max_ms`. For the sub-second wide flashes Peter found jarring: raise `min_shot_ms` (~600–900) and/or `silence_behaviour → hold`.

## Verification (all independently confirmed on Tower)

- Every deploy: Publisher JSON `verdict: DEPLOYED_AND_VERIFIED`, `remote_rc: 0` — the wrapper parser fix (`a2ac9a8`) means no more manual adjudication.
- Every file: deployed sha256 == local commit content (player.js `09abb60b`, api.py `818f9aa8` at the final state).
- Container: `running`, restarts **0** throughout; backends `WHISPER_BACKEND=mock` / `DIARIZE_BACKEND=mock` preserved.
- Public: `/health` 200, unauthenticated `/projects` 401.
- Live player-state: `analysis.whisperx_available: true`, `cut.selection_version: 2` (confirms the save-fix root cause: top-level `selection_version` is absent by design).

## Test state

- Deterministic suite on the integrated tree: **852 passed, 3 skipped, 1 env-fail** — the env-fail is `TEST-P6-002` needing ffmpeg, absent in the WebUI sandbox (Tester's runtime has it; reconciles exactly with their 851/3).
- Node player logic + speaker-mapping suites pass (run with standalone node when sandbox lacks it).
- New coverage this session: `cutEndMs`, `apiErrorMessage` (7 cases), player-state `whisperx_available` (3 cases: no artifact → false, all gates → true, confirmations missing → false).

## Remaining work (next pickup)

1. **Four AI-GPU-1 application-acceptance gates** per `docs/plans/ai-gpu-1-corrective-pickup.md`: frame-level timing, confirmed speaker identity, speaker-turn cut acceptance, coexistence measurements. Production stays `WHISPER_BACKEND=mock` / `DIARIZE_BACKEND=mock` until those and a rollout decision pass.
2. **Stage 7.4 UI acceptance** may proceed independently — fresh rerun should target deployed `743d801`+ (image `0d6228f7` at session end), not old `c096e4e`.
3. Stage 8.3 OTIO fallback and Stage 9.2 LLM title generator remain open per the main backlog.

## Ops notes carried forward

- Deploy wrapper parser fixed (`a2ac9a8`): last bare `RESULT:` line wins; `remote_rc` in JSON. Do not re-add the "wrapper may misparse" caveat to Publisher cards.
- Deploy worktree in use: `/opt/data/workspace/AUTOEDIT/.worktrees/phase6-confirmation-projection-spec` (HEAD `7b0d27f`); files are synced to the target commit before each Publisher card and verified by hash after.
- Reviewer API account for live checks: secret at `/mnt/user/appdata/hermes/kanban/secrets/autoedit-test-account.json` (password stays on Tower).
