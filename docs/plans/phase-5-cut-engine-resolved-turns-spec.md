# AI-GPU-1 Phase 5 — resolved speaker turns drive cut activity

Status: DESIGN_APPROVED for bounded residual implementation
Author: autoeditdesigner
Date: 2026-07-20
Repository inspected: `f2d9d9d489dab4042dc14f7a4d203742870f3f85` (`master`)
Authoritative inputs: `jobs/BACKLOG.md`; Phase 5 of `docs/plans/whisperx-speaker-aware-ai-roadmap.md`; `docs/plans/ai-gpu-1-acceptance-gates.md`; the source specification, style guide, testing strategy, and deployment runbook.
Provider preflight: the active `autoeditdesigner` profile declares `custom:9Router` with primary `cc/claude-opus-4-8` and fallback `cx/gpt-5.6-sol`; this task's live completion used that declared fallback. The card has no conflicting model override. OpenRouter was not used as primary, fallback, auxiliary, MoA, or delegation.

## 1. Decision

Implement only the residual Phase 5 seams around the already-committed core bridge:

1. complete the resolved-turn activity contract with optional word/speech-quality evidence and explicit audit metadata;
2. make cut generation source-explicit (`vad` or `whisperx`) with no implicit fallback;
3. persist regenerated cuts as immutable candidates;
4. add an explicit, auditable selected-cut record so generation cannot silently replace the current cut;
5. let the review player preview VAD and WhisperX candidates, then save or discard the preview; and
6. make player, timeline, review, and export consume the same selected cut.

Production remains `WHISPER_BACKEND=mock` and `DIARIZE_BACKEND=mock`. This design neither deploys nor authorizes real speech backends.

## 2. Correction to the card premise

The card and current backlog text call Phase 5 “unstarted.” That is no longer true at HEAD.

Verified as built:

- `src/autoedit/ai/activity_from_turns.py` exists and constructs a contiguous WhisperX projection.
- `POST /projects/{id}/cut` validates the AI artifact, Gate 1 record, current speaker confirmations, and source hashes before projecting resolved turns.
- `src/autoedit/cut_engine.py` treats `safe_wide` as authoritative, preserves the 250 ms anti-chatter floor, and frame-snaps after activity construction.
- VAD remains `audio/activity.json`; projected AI activity is separate at `audio/ai/v1/activity-whisperx.json`.
- AI activity, candidate CDL, and `kind="ai"` database row publish atomically with rollback.
- The player exposes source/mapping/safety labels and shot reasons.

Verified residual gaps:

- The bridge accepts turns only; it does not accept optional word/speech-quality evidence or emit a complete nested audit record with source turn/evidence IDs.
- There is no explicit noisy-region input or `noise:wide` reason.
- The cut endpoint automatically chooses WhisperX whenever an artifact exists. It cannot explicitly regenerate VAD in that state and therefore does not provide an honest source choice.
- The player, timeline, and export hard-code the latest `kind="rough"` row. There is no durable selected-cut record.
- Regeneration can change the latest VAD rough row and the player also replaces its in-memory clips immediately, without a distinct preview/save contract.
- The UI does not offer VAD/WhisperX A/B controls or display the reported numeric confidence (or “not reported”).
- The roadmap-named `tests/test_activity_from_turns.py` does not exist; projection tests are distributed across acceptance/correction modules.

The accepted atomic publication and safe-wide logic must be preserved, not rebuilt.

## 3. Facts, assumptions, unknowns, and decisions

### 3.1 Verified facts

- Program audio is the master timeline and all imported AI times are strict integer master milliseconds.
- Source sync remains automatic energy-envelope cross-correlation. No normal manual nudge workflow is permitted.
- Browser playback uses silent proxies; source media is not requested or played.
- The current VAD artifact has stable historical semantics at `audio/activity.json`.
- The AI artifact schema already carries aligned words, diarization turns, overlaps, mappings, resolved turns, confidence, and provenance.
- Confirmed close-up authority requires a current, bijective operator confirmation for the current artifact version.
- The database has immutable `cuts` rows (`rough`, `ai`, etc.) but no selected-cut relation.
- Central MySQL is canonical; production is host-networked behind NPM; VAAPI `h264_vaapi` is the active proxy path.

### 3.2 Assumptions

- A project has at most one selected review/export cut at a time.
- Existing projects should initially select the latest valid VAD rough cut, matching current behavior, then become explicit-selection projects.
- Optional evidence may be absent. Absence must be represented as `not_provided`; it must not fabricate low confidence or silently invalidate an otherwise confirmed turn.
- Numeric confidence is displayed only when the backend supplied a valid value.

### 3.3 Unknowns that do not block implementation

- Real-media benchmark thresholds and whether the consent-cleared set contains all required noise/off-camera cases.
- Peter's later editorial acceptance of the WhisperX candidate.
- Whether production activation will eventually be per-project or global. This design supports per-project selection but does not activate a backend.

### 3.4 Design decisions

- The A/B preview/save flow lives in the review player, beside the current cut and cut parameters. Phase 6 owns speaker identity confirmation in the ingest/analysis flow; it must not duplicate this cut-selection UI.
- Add an explicit `project_cut_selections` table rather than hiding selected state in `projects.config_json` or inferring it from row creation time.
- Existing projects are backfilled to their latest valid rough cut before new regeneration behavior is enabled.
- Generation never changes an existing selection. The first valid VAD cut for a project with no cut may become the initial selection atomically so a newly processed project remains playable.
- A generated candidate is previewable immediately in the current browser session, but a reload returns to the persisted selected cut unless the operator chose **Save this cut**.

## 4. Architecture and data flow

```text
VAD path
  audio/activity.json (immutable historical semantics)
      -> explicit generate source=vad
      -> immutable cuts row kind=rough + versioned candidate CDL

WhisperX path
  audio/ai/v1/result.json
      -> strict artifact/source-hash validation
      -> Gate 1 + current confirmation checks
      -> resolved turns + optional evidence
      -> audio/ai/v1/activity-whisperx.json
      -> explicit generate source=whisperx
      -> immutable cuts row kind=ai + versioned candidate CDL

Both paths
  generated candidate (selection unchanged)
      -> review-player in-memory preview
      -> explicit PUT cut-selection
      -> project_cut_selections + edit/cdl.json mirror atomically updated
      -> player-state, timeline-state, cut review, and export read the same selection
```

No worker, Compose, sync, program-audio, proxy, source-media, or export-format contract changes are required.

## 5. Requirements

### 5.1 Architecture

- **ARCH-P5-001 — Master-time projection.** The resolved-turn bridge must produce an ordered, contiguous, deterministic timeline covering `[0, timeline_end_ms)` in integer program-audio-master milliseconds. Invalid, inverted, Boolean, non-integer, NaN, or out-of-range values fail closed; they are never clipped into validity.
- **ARCH-P5-002 — Source isolation.** VAD and WhisperX activity retain distinct paths and declared semantics. `audio/activity.json` remains VAD. WhisperX remains under `audio/ai/v1/`. Neither source may overwrite the other.
- **ARCH-P5-003 — Explicit authority.** A cut-generation request declares `analysis_source: "vad" | "whisperx"`. Artifact presence alone never changes the source. A failed WhisperX request never silently generates or selects VAD; VAD is used only by a separate explicit request or configured project action visible to the operator.
- **ARCH-P5-004 — Immutable candidate, explicit selection.** Generating a cut creates a new immutable candidate row and candidate CDL. It does not change an existing selected cut. Selection is a separate authenticated write.
- **ARCH-P5-005 — One selected-cut resolver.** Player state, timeline state, cut review, and export must call one backend helper that resolves the project's selected cut. They must not independently query “latest rough” or a stale disk file.
- **ARCH-P5-006 — Downstream timing order.** Speaker-turn construction and safety classification occur before existing editorial passes. Lead/tail, 250 ms anti-chatter, source-bound repair, and frame snapping remain downstream. Sync is not retuned to compensate for diarization.

### 5.2 Activity and audit contract

- **BACKEND-P5-001 — Compatible shape.** Every activity segment retains `start_ms`, `end_ms`, and sorted `active`. Additive fields are `schema_version`, `source`, `confidence`, `mapping_status`, `authority_status`, `safe_wide`, safety flags, `reason`, and `audit`.
- **BACKEND-P5-002 — Optional evidence.** `activity_from_turns()` accepts optional bounded evidence intervals with this normalized shape:

```json
{
  "evidence_id": "opaque-id",
  "start_ms": 1200,
  "end_ms": 1480,
  "kind": "word | speech | noise | uncertain",
  "confidence": 0.93
}
```

  Word evidence may be derived from artifact segment/word index without retaining text. Evidence is validated on the same timeline. `noise` or `uncertain` overlapping an otherwise solo region forces safe-wide. If no evidence is supplied, the segment records `evidence_status: "not_provided"`; no confidence is invented.
- **BACKEND-P5-003 — Confidence.** Segment confidence is the deterministic minimum of available contributing turn and applicable evidence confidences. If none were reported, it is `null`. A configured threshold applies only to reported values. It must not convert `null` into a made-up score.
- **BACKEND-P5-004 — Audit metadata.** `audit` contains only bounded, non-secret identifiers and decisions: artifact version, source turn IDs, anonymous diarizer IDs, stable speaker IDs where confirmed, mapping provenance, evidence IDs/kinds, and a stable decision code. It excludes transcript text, model prompts, tokens, hashes, filesystem paths, names, and raw audio data.
- **BACKEND-P5-005 — Camera policy.** One confirmed, on-camera speaker at or above policy confidence selects that speaker's mapped close camera. True overlap/two speakers, unresolved or stale identity, low confidence, supplied noise/uncertainty, off-camera speech, or missing camera authority selects wide. Silence uses Direct-profile wide.
- **BACKEND-P5-006 — Protected safety spans.** `safe_wide` spans cannot be absorbed into a close-up by overlap hold, interjection suppression, dominance, rapid-exchange handling, or minimum-shot merging. Same-wide adjacent reason boundaries remain auditable even when they do not create a visual switch.
- **BACKEND-P5-007 — Reason vocabulary.** Stable reasons include `speaker:<stable-id>`, `overlap:wide`, `unresolved:wide`, `low_confidence:wide`, `noise:wide`, `off_camera:wide`, `silence:wide`, and existing source fallback reasons. Each maps to `reason_code`, `reason_label`, and `reason_detail`.
- **BACKEND-P5-008 — WhisperX gate.** A WhisperX candidate requires strict artifact validation, source-hash verification, current Gate 1 acceptance, complete current confirmed mappings, required wide camera, and valid source bounds. A failure returns an actionable 409/422 and preserves every prior artifact, candidate, and selection.

### 5.3 Cut generation and selection API

- **BACKEND-P5-009 — Generation request.** Extend `CutRequest` with `analysis_source`, defaulting to `vad` for backward safety. The response remains CDL-compatible and adds `cut_id`, `analysis_source`, `selected`, and candidate metadata. Existing clients that read `clips` continue to work.
- **BACKEND-P5-010 — Candidate persistence.** VAD candidates use `kind="rough"`; WhisperX candidates use `kind="ai"`. Both preserve params, analysis source, artifact version where applicable, conditions, validation, and complete projection metadata in `cdl_json`. Candidate files are versioned; a non-selected regeneration must not replace `edit/cdl.json`.
- **BACKEND-P5-011 — Selection schema.** Add `project_cut_selections(project_id PK/FK, cut_id FK, selected_by, selected_at, version)`. Selection rows refer only to a cut owned by the same project. `version` increments on every real change and supports optimistic concurrency.
- **BACKEND-P5-012 — Candidate list.** `GET /projects/{id}/cuts` returns bounded metadata sorted newest first: cut ID, name, kind, analysis source, artifact version, params, created time, validation status, and `is_selected`. It does not return all CDL JSON unless a specific cut is requested.
- **BACKEND-P5-013 — Explicit save.** `PUT /projects/{id}/cut-selection` accepts `{cut_id, expected_version}`. It rejects missing/cross-project/invalid cuts, stale versions (409), malformed CDLs, and unaccepted WhisperX candidates. Idempotently selecting the current ID does not create a new version.
- **BACKEND-P5-014 — Atomic selection mirror.** Selection update and the compatibility mirror `edit/cdl.json` are one recoverable publication unit: stage bytes, update selection in an open DB transaction, replace the mirror, commit; on failure restore prior bytes and selection. Candidate rows/files are never deleted.
- **BACKEND-P5-015 — Existing-project compatibility.** Migration/backfill selects each existing project's latest valid `kind="rough"` cut without rewriting that cut. A project with no cut remains unselected. The first successful VAD generation may establish an initial selection only when none existed; later generations never auto-select.
- **BACKEND-P5-016 — Selected consumers.** `GET player-state`, `GET timeline-state`, `POST cut/review`, and `POST export` use the same selected row. Player state returns selection ID/version and selected analysis metadata. Export response records the selected cut ID/source used.

### 5.4 User interface

- **UI-P5-001 — Current authority.** The review player always identifies the persisted current cut by name and analysis source. Analysis status shows source, mapping state, safety state, and confidence as a percentage when reported or `Not reported` otherwise.
- **UI-P5-002 — Source choice.** Add a labelled two-option source control: **VAD baseline** and **WhisperX resolved turns**. VAD wording is diagnostic/baseline, not “AI.” WhisperX is disabled with a plain-language reason when required artifact/gates/mapping/wide data are unavailable.
- **UI-P5-003 — Non-destructive preview.** Regeneration displays the candidate immediately as a preview with a persistent banner: `Previewing <source> candidate — current cut unchanged.` The selected cut is retained in memory so **Discard preview** restores it without a network mutation.
- **UI-P5-004 — Explicit save.** A visible **Save this cut** action selects the preview through the versioned selection endpoint. Only successful selection changes the “Current cut” label. Failure keeps the preview and prior selected cut available and explains recovery.
- **UI-P5-005 — Timeline and reasons.** Angle blocks and the active-shot panel expose analysis source, confidence state/value, and reason. Safety uses text/icons in addition to colour. No transcript text, anonymous raw model output, hashes, paths, or model identifiers are shown.
- **UI-P5-006 — Honest states.** Define loading, no selected cut, no AI artifact, needs confirmation, stale confirmation, gate blocked, generating, preview ready, saving, saved, generation failure, selection conflict, and network failure. No empty success and no invisible fallback.
- **UI-P5-007 — Responsive behavior.** At `<=840px`, source, preview, and save controls use one column; at `<=640px`, nonessential audit detail may collapse but source, confidence/safety, preview status, Save, and Discard remain visible without horizontal scrolling. The video remains primary and controls never cover its center.
- **UI-P5-008 — Accessibility.** Use native buttons/radios or a correctly labelled radiogroup, visible focus, keyboard operation, `aria-live` for generation/save status, `aria-current` or equivalent for the selected source, and disabled-reason text associated with the disabled control. Motion respects reduced-motion settings.
- **UI-P5-009 — Visual system.** Reuse Ink/Parchment surfaces, IBM Plex Mono for machine truth, and one Signal Red primary action. Save is the single red primary action while a preview exists; Generate/Discard are solid-muted or ghost secondary actions.

### 5.5 Operations and observability

- **OPS-P5-001 — Structured events.** Emit log-safe events for candidate requested/generated/failed and selection requested/changed/conflicted/rolled back with project ID, cut ID, source, artifact version, selection version, duration, and stable error code. Do not log transcript, names, tokens, paths, or media hashes.
- **OPS-P5-002 — Production pins.** Base and overlay Compose continue to resolve application speech backends to mock until all four AI-GPU-1 gates and a later explicit rollout task pass. No Compose or Unraid mutation belongs to these implementation cards.
- **OPS-P5-003 — MySQL rollout.** Before deployment, back up central MySQL and app config, render Compose, and run migration/backfill against a non-production fixture or backup-restored DB. Verify selected-row counts and cross-project integrity without printing secrets.
- **OPS-P5-004 — Health evidence.** Post-deploy verification must include migrations, public health 200, unauthenticated protected route 401, authenticated current-cut/player/timeline agreement, export using the same cut ID, zero unexpected restarts, mock backend values, and no media mutation.
- **OPS-P5-005 — Rollback.** Roll back the app image/config through the approved deployment script. The additive selection table may remain. Candidate cuts and prior rough cuts are retained. Restore the DB backup only if selection backfill itself was incorrect; never delete AI/VAD artifacts as rollback cleanup.

### 5.6 Security and privacy

- **SEC-P5-001 — Auth and ownership.** Candidate listing, generation, selection, player, timeline, review, and export remain authenticated in production. Selection rejects cross-project cut IDs and stale expected versions.
- **SEC-P5-002 — Safe presentation.** Public API/UI projection metadata is allowlisted. It excludes secrets, source paths, transcript excerpts, raw interview names, model prompts/output, and private fixture identifiers.
- **SEC-P5-003 — Consent boundary.** Real-media A/B evidence, screenshots containing people, audio, transcripts, paths, and fingerprints remain in the ignored consent-controlled evidence root. Tracked tests use synthetic opaque IDs only.
- **SEC-P5-004 — Failure safety.** Invalid JSON, hostile strings, oversized audit arrays, duplicate evidence IDs, unsupported evidence kinds, and malformed confidence/times are rejected before persistence or rendering. UI uses `textContent` for server strings.

### 5.7 Tests and acceptance evidence

- **TEST-P5-001 — Dedicated projection suite.** Add `tests/test_activity_from_turns.py` covering empty/silence, confirmed solo, alternating speakers, overlap, unresolved/suggested/stale mapping, low/null confidence, optional word/speech evidence, noise/uncertain evidence, off-camera, bounds/types, deterministic merge, contiguity, audit allowlist, and no fabricated confidence.
- **TEST-P5-002 — Cut safety.** Extend cut tests for `noise:wide`, protected sub-250 ms safety spans, same-camera reason boundaries, explicit VAD versus WhisperX inputs, post-construction anti-chatter, frame snapping, source bounds, missing wide, and complete projection persistence.
- **TEST-P5-003 — Source API.** Prove an explicit VAD request uses `audio/activity.json` even when a valid AI artifact exists; an explicit WhisperX request enforces every gate; failure never falls back or changes selection.
- **TEST-P5-004 — Selection API and migration.** Cover backfill, initial selection, immutable regeneration, list metadata, save, idempotency, optimistic conflict, cross-project rejection, invalid CDL rejection, atomic mirror rollback, and SQLite/MySQL schema compatibility.
- **TEST-P5-005 — Consumer consistency.** Player state, timeline state, review, and export return/use the same selected cut ID/source. A generated but unsaved candidate changes none of them after reload.
- **TEST-P5-006 — Frontend logic.** Node tests cover source availability, confidence formatting, preview/save/discard, stale selection conflict, network/generation/save failures, no false current-cut update, accessible labels, and safe text rendering. Static tests cover required DOM and responsive CSS.
- **TEST-P5-007 — Broad regression.** Run the focused Phase 5 suite, deterministic full suite with Ollama variables cleared, Node player suite, Python compile, changed-file lint, dependency lock validation, privacy scan, and `git diff --check` on the exact candidate.
- **TEST-P5-008 — Real-media Gate 3.** On consent-cleared fixtures only, compare locked VAD and WhisperX windows for solo speakers, alternation, overlap, acknowledgement, bleed/unequal levels, laughter/cough/noise/silence, and unresolved/off-camera speech. Require zero wrong-close-up frames in safety windows outside one-frame transition tolerance.
- **TEST-P5-009 — Manual continuity.** Peter must approve the A/B editorial windows. Tester verifies program audio remains continuous/master, video follows within one frame, proxies remain silent, source media is never requested, and the selected cut exports to Resolve on the same frames.

## 6. API examples

### Generate a candidate

```http
POST /projects/{project_id}/cut
Content-Type: application/json

{
  "name": "WhisperX Direct candidate",
  "analysis_source": "whisperx",
  "params": {
    "min_shot_ms": 250,
    "lead_in_ms": 0,
    "tail_ms": 0,
    "overlap_to_wide": true,
    "silence_behaviour": "wide"
  }
}
```

Additive response fields:

```json
{
  "cut_id": "01...",
  "analysis_source": "whisperx",
  "selected": false,
  "selection_version": 3,
  "clips": []
}
```

### Save a preview

```http
PUT /projects/{project_id}/cut-selection
Content-Type: application/json

{
  "cut_id": "01...",
  "expected_version": 3
}
```

```json
{
  "project_id": "01...",
  "cut_id": "01...",
  "analysis_source": "whisperx",
  "version": 4,
  "selected_at": "2026-07-20T00:00:00Z"
}
```

## 7. Failure modes

| Failure | Required behavior |
|---|---|
| VAD requested, AI artifact present | Use VAD only; do not inspect AI as authority. |
| WhisperX artifact/gate/mapping invalid | 409/422; keep selected cut and VAD baseline unchanged. |
| Noise/uncertainty evidence overlaps a confirmed turn | Wide with `noise:wide`; retain contributing audit IDs. |
| No evidence supplied | Record `not_provided`; do not invent a score. |
| Missing wide camera | Fail WhisperX candidate visibly; no arbitrary close-up or partial CDL. |
| Candidate file/DB publication fails | Restore prior bytes; no orphan row or selection change. |
| Selection mirror/DB update fails | Restore prior `edit/cdl.json` and selection; candidate remains available. |
| Two tabs save from stale version | 409 with reload/review instruction; neither silently wins. |
| Candidate generated but browser reloads | Reload persisted selected cut; candidate remains listed, unsaved. |
| Export requested during preview | Export persisted selected cut, not unsaved in-memory preview; UI states this plainly. |
| Backend/network failure in UI | Keep selected playback usable; show bounded retry action. |

## 8. Work packages and file ownership

Each package fits one Programmer worktree and requires independent Designer compliance. Packages are sequential where they share `api.py`.

### Package P5-A — projection evidence and dedicated tests

Owns:

- `src/autoedit/ai/activity_from_turns.py`
- narrowly required `src/autoedit/cut_engine.py` reason mapping
- `tests/test_activity_from_turns.py`
- projection-specific additions to `tests/test_cut_engine.py`

Requirements: ARCH-P5-001/006; BACKEND-P5-001..007; TEST-P5-001/002.

Must not modify API selection, database schema, UI, Compose, or production configuration.

### Package P5-B — explicit source generation and selected-cut backend

Depends on P5-A.

Owns:

- `src/autoedit/db/schema.py`
- `src/autoedit/db/migrate.py`
- new focused helper such as `src/autoedit/cut_selection.py`
- `src/autoedit/api.py`
- `tests/test_cut_selection_api.py`
- focused updates to player/timeline/export/review API tests

Requirements: ARCH-P5-002..005; BACKEND-P5-008..016; OPS-P5-001; SEC-P5-001/004; TEST-P5-003..005.

Must preserve the accepted AI publication rollback path and must not implement UI.

### Package P5-C — review-player A/B preview and save flow

Depends on P5-B.

Owns:

- `src/autoedit/web/index.html`
- `src/autoedit/web/player.js`
- `src/autoedit/web/styles.css`
- `tests/player_logic.test.mjs`
- `tests/test_player_static.py`
- narrowly required player-state fixtures

Requirements: UI-P5-001..009; SEC-P5-002/004; TEST-P5-006.

Must not implement Phase 6 speaker-confirmation controls and must not change player audio/video clocking.

### Package P5-D — integration evidence and documentation truth pass

Depends on P5-A through P5-C and independent compliance.

Owns only focused test/runbook/backlog/handoff updates. Tester executes TEST-P5-007..009; a later Publisher task, if explicitly authorized, executes OPS-P5-002..005. Private acceptance evidence remains untracked.

## 9. Verification commands

```bash
OLLAMA_BASE_URL='' LLM_MODEL='' env -u VIRTUAL_ENV uv run pytest \
  tests/test_activity_from_turns.py \
  tests/test_activity.py \
  tests/test_cut_engine.py \
  tests/test_cut_selection_api.py \
  tests/test_player_state.py \
  tests/test_timeline_state.py \
  tests/test_export.py \
  tests/test_export_contiguity.py -q -rs

node tests/player_logic.test.mjs

OLLAMA_BASE_URL='' LLM_MODEL='' env -u VIRTUAL_ENV uv run pytest -q -rs
python3 -m compileall -q src tests
uv lock --check
uv run ruff check src tests
# Perform the acceptance-plan privacy scan and record only pass/fail; no private values.
git diff --check
```

Commands for files that do not yet exist become mandatory when their package lands; a missing test is a blocker, not a passing skip. The trusted-host test remains conditional on `AUTOEDIT_GOLDEN_MEDIA_ROOT` and cannot be replaced by synthetic output.

## 10. Deployment and rollback constraints

This Designer card authorizes no deployment or Unraid mutation.

A later explicit deployment task must use the approved `scripts/autoedit-deploy.sh` path: backup central MySQL/config/image, render Compose, transfer exact reviewed files, build/recreate, verify health/auth/player/timeline/export consistency, and retain rollback evidence. It must not stop/prune unrelated containers, touch production media, expose the WhisperX worker through NPM, change mock backend pins, or replace VAAPI with QSV.

Rollback restores the prior app image/config. The additive selection table and immutable candidates may remain because old code ignores them. If and only if backfill corrupted selection data, restore the reviewed DB backup; do not delete media or AI/VAD artifacts.

## 11. Risks and mitigations

- **Existing latest-rough semantics:** backfill before enabling candidate-only regeneration; test existing projects.
- **Cross-database migration differences:** exercise SQLite and credential-gated central-MySQL integration before deploy.
- **Disk/DB split-brain:** retain staged-file plus open-transaction rollback used by current AI publication.
- **Two-tab selection races:** optimistic `expected_version` with 409 conflict.
- **Confidence overclaim:** show numeric confidence only when reported; otherwise `Not reported`.
- **Noise misclassification:** only explicit validated evidence can force `noise:wide`; do not infer from transcript prose or arbitrary model warnings.
- **UI confusion between preview/current:** persistent preview banner and separate Save/Discard actions; export always names the persisted selected cut.
- **Phase 5/6 overlap:** Phase 5 owns candidate source/selection; Phase 6 owns identity confirmation snippets/mapping.
- **Private-media leakage:** synthetic tests in Git, consent-controlled browser/media evidence outside Git.

## 12. Non-goals

- No manual sync/timeline nudge workflow.
- No source/program audio mutation and no source playback in the browser.
- No replacement of program-audio master clock or one-frame video-follow rule.
- No QSV change; VAAPI `h264_vaapi` remains active.
- No real-backend production activation or global WhisperX default.
- No Phase 6 identity-confirmation UI in this work.
- No LLM authority for speech, timing, identity, confidence, or cuts.
- No change to FCPXML/EDL formats or CDL frame-time invariants.
- No deletion or rewriting of prior cuts, VAD artifacts, or AI artifacts.

## 13. Acceptance matrix

| Requirement group | Required evidence before compliance pass |
|---|---|
| ARCH-P5-001..006 | source inspection, projection fixtures, selected-cut resolver usage, timing-order tests |
| BACKEND-P5-001..008 | dedicated projection tests, complete audit payload comparison, safe-wide and fail-closed cases |
| BACKEND-P5-009..016 | API/schema/migration tests, atomic rollback evidence, player/timeline/review/export cut-ID consistency |
| UI-P5-001..009 | DOM/Node tests plus desktop and narrow-browser screenshots, keyboard/focus/aria evidence, zero console errors |
| OPS-P5-001..005 | structured log samples and, only in an authorized deployment card, backup/render/health/rollback evidence |
| SEC-P5-001..004 | auth/cross-project/stale-version tests, allowlist/XSS/privacy scan |
| TEST-P5-001..009 | exact commands/results; trusted real-media and Peter decisions remain separate manual gates |

## 14. Verdict

**DESIGN_APPROVED**

The core resolved-turn bridge already shipped at `f2d9d9d`; implementation should not reopen it wholesale. Packages P5-A through P5-C close the verified Phase 5 residuals. Production stays mock-backed, and real-media Gate 3, GPU/Dots Gate 4, deployment, and production activation remain separately authorized work.
