# Phase 6 confirmed diarization-turn projection fix

Status: DESIGN_APPROVED
Author: autoeditdesigner
Date: 2026-08-12
Implementation base inspected: `cb3f29861658519e4376720f0ff57efdfc9db29b`
Provider preflight: the active profile declares `custom:9Router` with fallback `cx/gpt-5.6-sol`; this card explicitly authorizes that private-local fallback, and a minimal live completion on that exact route returned `ROUTE_OK`. Public OpenRouter was not used.

## Purpose

Correct the `POST /projects/{project_id}/cut` WhisperX projection seam so current operator confirmations project the corresponding raw diarization turns even when the completed artifact intentionally contains no pre-resolved `speaker_turns`. This is a corrective backend-only change. It does not enable real AI in production.

## Evidence and boundaries

### Verified facts

- The defect was observed on deployed base `cb3f29861658519e4376720f0ff57efdfc9db29b` with non-empty `diarization_turns`, zero `speaker_turns`, and two current bijective confirmations.
- In `src/autoedit/api.py`, the WhisperX cut path loads confirmed rows scoped to `project_id`, current artifact version, and `status == "confirmed"`; it requires the observed label set to equal the confirmation-label set and builds `speaker_to_angle` from those rows.
- The same path currently projects confirmed activity only from artifact `speaker_turns`. Its raw-turn append explicitly excludes labels present in confirmations. Therefore a confirmed raw turn with no artifact `speaker_turn` disappears.
- `activity_from_turns` already enforces unresolved/low-confidence/overlap safe-wide behavior. The cut path already runs Gate 1, source-bound validation, atomic candidate publication, and failure event reporting.
- Production is mock-backed for Whisper and diarization. Program audio remains the master clock; this correction changes no timing.

### Assumptions

- `turn_id` is the canonical identity of a raw diarization turn within an artifact version, and artifact `speaker_turn.source_turn_id` references it.
- Existing artifact validation guarantees integer, bounded raw-turn times and valid source-turn references before this seam runs.
- Current confirmation persistence already enforces one-to-one label/speaker/camera constraints; the cut seam must nevertheless fail closed rather than infer or repair malformed rows.

### Unknowns not blocking this correction

- Whether future artifact producers will always emit `speaker_turns`. This design supports both zero and non-zero lists.
- When real WhisperX/diarization will be enabled in production. That remains behind existing acceptance and rollout gates.

### User decisions already supplied

- Implement the smallest correction in `api.py` plus focused tests; a tiny pure helper is permitted only if it makes precedence/dedup independently testable.
- No UI, schema, private artifact, media, timing, deployment, or production-default change.
- The coordinator owns downstream cards; none are created by this design task.

## Requirements

### Backend

- **BACKEND-P6CP-001 — Current-confirmation projection.** For every validated raw `diarization_turn` whose `diarizer_speaker_id` has a current confirmed row, construct exactly one effective turn using the canonical raw `turn_id`, overlap/confidence evidence, the confirmed row's stable `speaker_id`, `mapping_status="confirmed"`, and `provenance="confirmed_mapping"`. The effective turn uses raw timing unless BACKEND-P6CP-002 selects a valid pre-resolved representation. This applies when artifact `speaker_turns` is empty.
- **BACKEND-P6CP-002 — Source precedence and dedup.** Build effective turns by canonical raw `turn_id` in deterministic raw-artifact order. Index, but do not independently append, authoritative artifact `speaker_turns`. When exactly one valid artifact `speaker_turn` references a raw turn, its bounded timing/confidence representation takes precedence for that source turn; the current confirmation still supplies identity and current provenance. Otherwise use the raw representation. Emit no more than one effective turn per raw `turn_id`; equal timestamps are not a dedup key because concurrent turns can be distinct evidence. Duplicate authoritative references to one `source_turn_id` are ambiguous and fail closed rather than using first/last list order.
- **BACKEND-P6CP-003 — Current authority wins.** The effective `speaker_id`, `mapping_status`, and provenance for a currently confirmed label come from the current confirmation, not an artifact's older speaker identity or provenance. Thus even an accepted pre-resolved source is emitted as `provenance="confirmed_mapping"`; artifact data cannot override the current confirmation.
- **BACKEND-P6CP-004 — Unauthorized exclusion.** A raw label without a current confirmed mapping must never become active close-camera evidence. Preserve the existing fail-closed confirmation-coverage gate. If partial coverage reaches a lower-level helper in a unit test, emit the turn unresolved (`speaker_id=None`) rather than infer identity.
- **BACKEND-P6CP-005 — Safety invariants.** Preserve current artifact-version equality, confirmation bijection, Gate 1, confidence thresholding, overlap-to-safe-wide behavior, timeline/source bounds, CDL validation, immutable/atomic candidate publication, and existing failure behavior. Do not alter frame snapping or master/source time conversion.
- **BACKEND-P6CP-006 — Selection immutability.** WhisperX candidate generation may publish only the existing immutable candidate/activity artifacts and candidate cut row. It must not change the persisted selected cut or overwrite the VAD/current cut.
- **BACKEND-P6CP-007 — Minimal ownership.** Implementation is limited to `src/autoedit/api.py` and focused tests. A tiny pure helper may be placed in `api.py`; a new module requires explicit justification that circularity or test isolation makes it necessary.

### Security and privacy

- **SEC-P6CP-001 — No identity inference.** Never derive speaker identity or camera authority from diarizer-label order, transcript text, channel, filename, prior run label, suggestion, human-readable label similarity, or list position. Only a current confirmed database row for the exact artifact version authorizes projection.
- **SEC-P6CP-002 — Fail closed on conflicts.** Duplicate raw turn IDs, duplicate/ambiguous authoritative artifact source turns, confirmation non-bijection, malformed source references, or invalid times must produce the existing non-public validation error path and must not publish a candidate. An artifact/current stable-speaker disagreement is not permission to trust the artifact: discard that pre-resolved representation and re-project the validated raw turn under the current confirmation; fail only if a valid one-turn raw re-projection is unavailable.
- **SEC-P6CP-003 — Data minimization.** Add no logs containing transcript text, speaker names, media paths, private artifact payloads, or confirmation payloads. Existing structured event fields and redacted error codes are sufficient.

### Tests

- **TEST-P6CP-001 — Regression first.** Before implementation, add a failing API regression with non-empty raw turns, zero `speaker_turns`, two current-version bijective confirmations, and valid Gate 1 evidence. After correction, `analysis_source="whisperx"` succeeds rather than collapsing to silence/source-bounds failure.
- **TEST-P6CP-002 — Confirmed activity and candidate.** Assert each confirmed raw label creates the expected stable-speaker activity and the resulting candidate selects the associated close camera during isolated, sufficiently confident speech.
- **TEST-P6CP-003 — Provenance.** Assert the effective-turn list passed to `activity_from_turns` records `mapping_status="confirmed"` and `provenance="confirmed_mapping"`; assert the resulting activity records confirmed authority. This may be tested directly through a tiny pure `api.py` helper or with a call spy because the existing activity contract does not expose per-turn provenance.
- **TEST-P6CP-004 — Unauthorized label.** Assert an unconfirmed/suggested/stale-version label never yields stable-speaker activity or a close-camera candidate; retain expected 409/fail-closed behavior where full current confirmation coverage is required.
- **TEST-P6CP-005 — Deterministic dedup.** With valid artifact `speaker_turns` and matching raw turns, assert one effective turn per raw `turn_id`, stable raw order, no doubled activity, and structure-equivalent projected activity across identical fixtures. Cover artifact/current identity disagreement by proving current-confirmed raw re-projection, and cover duplicate authoritative source references as a fail-closed 422 with no publication. Do not compare candidate IDs or creation timestamps, which are intentionally unique.
- **TEST-P6CP-006 — Safety preservation.** Retain focused assertions for confidence below threshold, overlap safe-wide, source bounds, Gate 1 rejection, version mismatch, and bijection rejection.
- **TEST-P6CP-007 — Selection unchanged.** Seed a selected cut, generate the WhisperX candidate, and assert selected-cut identity/content remains byte-for-byte unchanged while the candidate is separately available.
- **TEST-P6CP-008 — Mock boundary.** Run the regressions with `WHISPER_BACKEND=mock`, `DIARIZE_BACKEND=mock`, `OLLAMA_BASE_URL=''`, and `LLM_MODEL=''`, with synthetic JSON only. Spy/monkeypatch the transcription and diarization backend seams to raise if called; a successful cut then proves this path consumes an existing completed artifact without external WhisperX, diarization, or Ollama inference.
- **TEST-P6CP-009 — Verification commands.** Minimum implementation evidence: focused projection/API tests, existing AI cut atomicity/acceptance tests, `python -m compileall -q src tests`, `git diff --check`, and the deterministic suite with `OLLAMA_BASE_URL='' LLM_MODEL=''` when runtime permits. Report exact commands and results.

### Operations

- **OPS-P6CP-001 — Production boundary.** Keep `WHISPER_BACKEND=mock`, `DIARIZE_BACKEND=mock`, VAAPI `h264_vaapi`, Compose topology, ports, volumes, permissions, central MySQL, and NPM routing unchanged.
- **OPS-P6CP-002 — No deployment in implementation/review.** Implementation, compliance, and Tester tasks must not mutate Unraid or production. A separate Publisher task is permitted only after Designer compliance pass and Tester PASS, with explicit user-approved deployment scope.
- **OPS-P6CP-003 — Rollback.** Code rollback is removal/reversion of the bounded projection correction. Because there is no schema or data migration and candidate publication is immutable, rollback requires no database/media migration; any generated candidate remains an auditable immutable row and the previously selected cut remains authoritative.
- **OPS-P6CP-004 — Observability.** Preserve existing `candidate_failed`/success event behavior and durations. If a new failure code is necessary, use a bounded non-sensitive code such as `turn_projection_invalid`; do not log payload values.

## Effective-turn algorithm

1. Load and validate the current completed artifact and current confirmation rows using the existing version, status, coverage, and bijection gates.
2. Index authoritative artifact `speaker_turns` by `source_turn_id`; reject duplicate authoritative references.
3. Iterate validated raw `diarization_turns` in artifact order; reject duplicate raw `turn_id` values.
4. For a raw label with a current confirmation, optionally use its single matching authoritative artifact turn only for validated bounded timing/confidence fields when its source reference and current stable speaker agree. If identity disagrees, discard that representation and use raw timing/confidence. In both cases apply the current stable `speaker_id`, `mapping_status="confirmed"`, and `provenance="confirmed_mapping"`.
5. For a raw label without authorization, retain unresolved handling only where reachable after the outer coverage gate; never assign a speaker/camera.
6. Pass the deduplicated effective list to `activity_from_turns`, then leave the existing candidate-generation, validation, atomic publication, and selection paths untouched.

This algorithm deliberately keys dedup by canonical source-turn identity rather than by equal timestamps. Concurrent/overlapping turns are distinct evidence and must not be collapsed.

## Failure modes

| Failure | Required result |
|---|---|
| Zero artifact `speaker_turns`, valid current confirmations | Project all matching raw turns; continue normally |
| Missing/stale confirmation | Existing 409; no candidate publication |
| Suggested-only mapping | No identity authority; existing 409/unresolved safe-wide |
| Duplicate raw `turn_id` or authoritative `source_turn_id` | Fail closed; no publication |
| Artifact speaker disagrees with current confirmation | Discard that artifact representation and re-project from raw under current confirmation; never trust stale identity |
| Low confidence | Preserve confidence; safe-wide according to existing threshold |
| Overlap | Preserve both turns; existing overlap safe-wide |
| Source/timeline bounds invalid | Existing 422/validation failure; no publication |
| Persistence/publication failure | Existing atomic rollback; selected cut untouched |

## File ownership and bounded implementation task

One Programmer worktree owns:

- `src/autoedit/api.py`: effective-turn projection/dedup correction.
- Prefer additions to the closest existing focused module (`tests/test_ai_cut_atomicity.py`, `tests/test_ai_gpu1_design_compliance.py`, or `tests/test_speaker_mapping_api.py`); one new focused `tests/test_confirmed_turn_projection.py` is acceptable if it avoids unrelated fixture churn.

No concurrent task should edit the same API cut block. No UI/schema/Compose/deployment/documentation update is required from the Programmer.

## Acceptance evidence matrix

| Requirement | Required evidence |
|---|---|
| BACKEND-P6CP-001..004, SEC-P6CP-001..002 | Source diff plus zero-speaker-turn, raw-order precedence, unauthorized, stale/conflict, identity-disagreement, and duplicate-source fail-closed tests |
| BACKEND-P6CP-005 | Existing Gate 1, confidence, overlap, bounds, and atomicity tests pass |
| BACKEND-P6CP-006 | Seeded selection byte/identity comparison before and after candidate generation |
| BACKEND-P6CP-007, SEC-P6CP-003 | Bounded diff inspection; no unrelated files or sensitive logging |
| TEST-P6CP-001..008 | Named focused tests with exact command output; backend-call spies for mock boundary |
| TEST-P6CP-009 | Compile, diff check, focused and deterministic suite outputs |
| OPS-P6CP-001..004 | Diff confirms no env/Compose/schema/deploy changes; structured event behavior retained |

## Accessibility, responsive UI, API/schema, and test media

There is no UI change, so responsive and accessibility behavior are unchanged and no visual evidence is required. There is no public API request/response or database-schema change. Tests use synthetic, consent-safe JSON and existing generated fixtures only; no private media or derived production artifacts enter Git.

## Risks and mitigations

- Risk: double counting when raw and resolved turns coexist. Mitigation: canonical `turn_id`/`source_turn_id` precedence and one output per raw turn.
- Risk: stale artifact identity overrides a new operator decision. Mitigation: current confirmation is the sole identity authority and emitted provenance is current-confirmed.
- Risk: correction bypasses safe-wide rules. Mitigation: preserve confidence/overlap fields and continue through `activity_from_turns` unchanged.
- Risk: candidate silently replaces editorial selection. Mitigation: explicit selection immutability regression and unchanged publication seam.

## Non-goals

- No manual sync controls or timing changes.
- No speaker-mapping UI changes.
- No artifact schema migration or backfill.
- No transcript/channel/filename-based identity inference.
- No activation of real WhisperX/diarization.
- No deployment, production artifact inspection, or production data mutation.

## Verdict

DESIGN_APPROVED
