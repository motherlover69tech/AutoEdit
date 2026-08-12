# Phase 6 terminal source-coverage truncation policy

Status: DESIGN_APPROVED
Author: autoeditdesigner
Date: 2026-08-12
Implementation base inspected: `0de62046bc53503a76789b0b617a8442b8677801`
Provider preflight: the active profile declares private `custom:9Router`, with `cx/gpt-5.6-sol` in its configured fallback chain. This card and its live session explicitly authorize that exact private route. A fresh minimal live completion completed successfully; its usage record reports model `cx/gpt-5.6-sol`, provider `custom`, and no failure. Public OpenRouter was not used.

Amendment authority: Peter, 2026-08-12. This amendment supersedes only BACKEND-P6TSC-004 conditions 2 and 4, the related classification/boundary language, and the exact regression topology. BACKEND-P6TSC-001..003 and 005..012 plus all SEC, TEST, and OPS requirements otherwise remain controlling, with only consistency edits needed to express the amended boundary.

## 1. Purpose and owner decision

Correct only the WhisperX candidate-generation source-coverage seam in `POST /projects/{project_id}/cut`.

Peter's amended decision is authoritative for this project class: “End the AI cut at the last frame where an authorized presenter/wide camera exists.” Define the boundary from the latest program-timeline coverage end among the exact current-confirmed camera or cameras authorized for the terminal presenter state and the configured wide camera, then end the non-destructive AI candidate at the greatest canonical frame boundary not later than that instant. A camera confirmed for another speaker is not in this boundary set merely because its recording continues. All material at or after that boundary is omitted, including later material that would be covered by another confirmed speaker camera. The interviewee camera is never substituted for presenter speech. The accepted AI result artifact, Gate 1 evidence, program-audio master, confirmations, and source timing evidence remain unchanged. The selected cut remains unchanged until the existing explicit “Save this cut” action succeeds.

This is a boundary-based terminal truncation policy, not a general “make the cut validate” clamp. Any source-uncovered instant strictly before the boundary, unsafe-wide state in the retained prefix, or arbitrary camera substitution continues to fail closed. Covered material after the boundary does not make truncation ineligible; it is deliberately omitted by Peter's decision.

## 2. Sources inspected

- `AI_HANDOFF.md`
- `jobs/BACKLOG.md`
- `docs/source/multicam_autoedit_spec.md`, especially CDL Section 2.4
- `docs/source/multicam_ui_style_guide.html`
- `docs/plans/TESTING_STRATEGY.md`
- `docs/DEPLOYMENT.md`
- `docs/plans/phase-6-confirmed-diarization-turn-projection-fix.md`
- `src/autoedit/api.py`, including `_confirmed_effective_turns`, `generate_cut`, source repair, validation, atomic publication, and selection handling
- `src/autoedit/ai/activity_from_turns.py`
- `src/autoedit/cdl_validator.py`
- `tests/test_ai_cut_atomicity.py`
- `tests/test_ai_gpu1_residual_findings.py`
- `tests/test_cut_selection_api.py`

No production files, private media, secrets, containers, or database rows were read or changed by this design task.

## 3. Facts, assumptions, unknowns, and decisions

### 3.1 Verified facts

- Candidate `0601b43` projects all 252 current confirmed raw diarization turns and initially generates 350 speaker-aware clips.
- The accepted artifact ends at `671296 ms` at `24/1 fps`.
- Synchronized program-timeline coverage ends at presenter `652720 ms`, wide `666185 ms`, and interviewee `671296 ms`.
- Confirmed presenter speech continues to `671292 ms`, after both the presenter and wide sources have ended.
- The live topology after wide exhaustion is silence `666185–667208 ms`, a covered interviewee segment `667208–668083 ms`, and presenter speech `668083–671292 ms`. Peter explicitly chose to omit all three spans rather than let the covered interviewee segment defeat truncation.
- Source/proxy durations agree with the database, so the failure is not stale duration metadata.
- Deployed candidate `0de6204` repairs an exhausted AI close camera only with the wide camera and uses a strict single-terminal-suffix classifier. It does not use another speaker camera. The covered interviewee segment splits the uncovered spans, so the live topology returns `422`; no AI row/file is published and selection remains unchanged.
- Current publication treats the WhisperX activity file, immutable candidate CDL, and AI cut row as one atomic unit. The compatibility `edit/cdl.json` mirror and selected cut are not changed by successful AI candidate generation.
- Program audio is the player master clock, source media is not played in the browser, and the production Whisper/diarization backends remain mock.

### 3.2 Canonical exact result for the reported case

For the live case, the authorized boundary set contains the exact current-confirmed presenter camera ending at `652720 ms` and the configured wide camera ending at `666185 ms`; the later interviewee-camera end is not an authorized presenter boundary. Thus `boundary_instant = max(652720, 666185) = 666185 ms`. The greatest `24/1` canonical frame boundary not later than that instant is frame `15988`, represented as `666167 ms`. Frame `15989` is `666208 ms` and is outside coverage. Therefore:

- `original_artifact_end_ms = 671296`
- `candidate_end_ms = 666167`
- `omitted_tail_duration_ms = 5129`

These are acceptance values, not illustrative approximations.

### 3.3 Assumptions

- Angle durations and rebased sync offsets already use the authoritative convention in the current cut path. Eligibility must use those source-bound calculations rather than raw duration alone.
- An angle file's available interval is continuous. Any delayed start caused by rebased sync still participates in the existing leading-source checks and cannot be hidden when it falls strictly before the candidate boundary.
- The current confirmation row for the exact artifact version remains the sole authority for speaker-to-camera identity.
- The existing candidate activity projection is useful timing evidence and may remain full-artifact length; candidate shortening is represented by explicit metadata and the CDL clip end, not by deleting accepted speech evidence.

### 3.4 Unknowns that do not block this correction

- Whether future projects will need a separately configurable set of authorized fallback camera roles. This correction uses the current confirmed speaker camera plus the configured wide camera only.
- Whether a later UI will display candidate truncation. No UI change is authorized here; the API/CDL/activity metadata is the durable seam for later work.
- When real WhisperX/diarization will be enabled in production. Existing acceptance and rollout gates remain controlling.

### 3.5 User decisions already supplied

- End the AI cut at the last canonical frame where an authorized presenter/wide camera exists; for the live case, truncate at `666167 ms` and drop the final silence, interviewee interjection, and presenter closing.
- Never use the interviewee camera for presenter speech.
- Preserve accepted evidence and selection authority.
- Scope implementation to `src/autoedit/api.py`, focused API tests, and this approved plan.
- Do not change UI, schema, Compose, environment, deployment scripts, or private media.
- Use separate Programmer, compliance, Tester, and Publisher stages; this design card creates no downstream cards.

## 4. Requirements

### 4.1 Backend and data contract

- **BACKEND-P6TSC-001 — WhisperX-only terminal exception.** Apply this policy only while generating a validated `analysis_source="whisperx"` candidate from the current accepted artifact and current confirmations. VAD cuts, selected cuts, previously published candidates, and other endpoints keep their existing behavior.

- **BACKEND-P6TSC-002 — Authorized cameras.** For each current-confirmed solo speech segment, the authorized visual sources are (a) that confirmation's exact `camera_id` and (b) the configured wide angle. Keep the existing safe-wide choice for confidence, overlap, unresolved, and off-camera states. Never add another confirmed speaker camera, channel source, previous angle, interviewee camera, filename-derived angle, or list-position fallback to the AI path.

- **BACKEND-P6TSC-003 — Source-bound coverage basis.** Determine source availability in the existing program-timeline basis, using current rebased sync offsets and canonical source conversion. A span is covered only when its generated clip has non-negative `src_in_ms` and `src_in_ms + dur_ms` is no later than that angle's probed `duration_ms`. Missing/invalid duration, invalid offset conversion, or a source-bound calculation error does not authorize truncation.

- **BACKEND-P6TSC-004 — Eligible boundary truncation.** Truncation is eligible only when all of the following are true:
  1. ordinary AI source repair cannot cover the complete accepted artifact timeline;
  2. `boundary_instant` is the maximum program-timeline coverage end over the exact current-confirmed camera or cameras authorized for the terminal presenter state and the configured wide camera, using the source-bound basis in BACKEND-P6TSC-003; a camera confirmed for another speaker does not enter this set merely because it continues later;
  3. no source-uncovered instant exists strictly before `candidate_end_ms`, where `candidate_end_ms` is the greatest canonical frame boundary not later than `boundary_instant`;
  4. `candidate_end_ms` is positive; material at or after it is dropped even when a later span is fully coverable by its own current-confirmed camera;
  5. the omitted material contains at least one current-confirmed solo active-speech segment for which both its exact confirmed camera and the wide are unavailable; and
  6. the candidate has a positive, contiguous, source-bound prefix beginning at `0`.

  Silence and covered segments may occur in the omitted material because everything at or after the boundary is deliberately dropped; silence alone is not sufficient to authorize truncation. Unresolved, low-confidence, overlap, or off-camera/safe-wide source failure strictly before the boundary is not this exception and remains fail closed.

- **BACKEND-P6TSC-005 — Canonical candidate end.** Let `boundary_instant` be the BACKEND-P6TSC-004 maximum authorized coverage end. Set `candidate_end_ms` to the greatest canonical project-frame boundary not later than that instant for which the entire prefix remains source-bound. The frame-rounding sliver between `candidate_end_ms` and `boundary_instant`, if any, is part of the omitted tail. For the reported `24/1` case, `max(652720, 666185) = 666185 ms`, so the exact end is `666167 ms`.

- **BACKEND-P6TSC-006 — Candidate clip invariants.** The shortened CDL must be non-empty, start at `0`, remain sorted and contiguous with no gaps/overlaps, end exactly at `candidate_end_ms`, and retain exact canonical frame boundaries and source bounds for every clip. Shorten the final surviving clip if necessary and remove every clip at or after the candidate end. No later clip may survive, even if an arbitrary unauthorized camera has media there. Run the existing CDL validator before publication.

- **BACKEND-P6TSC-007 — Explicit metadata contract.** Add the same top-level `truncation` object to the candidate CDL/API response and the atomically published `activity-whisperx.json`:

  - `applied`: boolean;
  - `reason_code`: exactly `terminal_authorized_camera_coverage_exhausted` when applied, otherwise `null`;
  - `original_artifact_end_ms`: integer accepted artifact end;
  - `candidate_end_ms`: integer final CDL end;
  - `omitted_tail_duration_ms`: exactly `original_artifact_end_ms - candidate_end_ms`.

  Emit this object for both shortened and full-length WhisperX candidates. For a full candidate, `applied=false`, both ends are equal, omitted duration is `0`, and reason is `null`. The activity projection's existing full timeline and `total_duration_ms` remain at the accepted artifact end so speech/timing evidence is not erased; its `truncation.candidate_end_ms` states the shorter visual candidate boundary. The CDL contains no clip after that boundary.

- **BACKEND-P6TSC-008 — Evidence immutability.** Candidate generation must not rewrite, clip, or replace `result.json`, the accepted result artifact or its source/analysis hashes, `word-timing-review.json`, `program.m4a`, source/analysis WAVs, confirmations, synchronized angle durations/offsets, VAD `activity.json`, or Gate 1 evidence. The accepted program audio remains the master and is not physically shortened.

- **BACKEND-P6TSC-009 — Selection and publication immutability.** Publish the shortened activity metadata, immutable candidate CDL, and AI cut row through the existing atomic unit. Do not overwrite the selected-cut mirror or alter `project_cut_selections`. Selection changes only through the existing explicit save endpoint and optimistic version check. Any validation, write, replace, database, or commit failure rolls back all candidate publication sides and preserves prior bytes/rows/selection.

- **BACKEND-P6TSC-010 — Fail-closed retained-prefix behavior.** Any source-uncovered instant strictly before `candidate_end_ms`, a delayed source that creates an internal hole in the retained prefix, no positive source-bound prefix, no authorized source, malformed duration/offset data, or a candidate that does not satisfy BACKEND-P6TSC-004 returns `422` through the non-publication path. It must not be converted into a shorter candidate. A later recoverable/covered clip at or after the boundary does not prevent truncation and is omitted with all other post-boundary material.

- **BACKEND-P6TSC-011 — Existing authority and safety.** Preserve current artifact/version and Gate 1 validation, full current-confirmation coverage/bijection, current-confirmation identity precedence, confidence thresholding, overlap/unresolved/off-camera safe-wide behavior, shot reasons, source conversion, immutable candidate naming, atomicity, and selected-cut behavior. Truncation cannot make an unauthorized identity or camera authoritative.

- **BACKEND-P6TSC-012 — Minimal implementation ownership.** One Programmer worktree owns only `src/autoedit/api.py` and one focused test module, preferably `tests/test_terminal_source_coverage_truncation.py`. Existing focused test files may be minimally extended only if fixture reuse is materially smaller. No production code module extraction or refactor is approved.

### 4.2 Security and privacy

- **SEC-P6TSC-001 — No identity or camera inference.** Camera authorization comes only from the current exact-version confirmed row and configured wide role. Do not infer from transcript text, speaker names, diarizer ordering, channel source, angle labels, filenames, prior mappings, suggestions, or another camera's remaining duration.

- **SEC-P6TSC-002 — Fail closed rather than conceal retained-prefix loss.** Truncation must never conceal an internal source failure or unsafe-wide failure strictly before `candidate_end_ms`, stale/missing timing metadata, non-bijective confirmation, or a malformed artifact. Later valid program material at or after Peter's approved boundary is deliberately omitted from the candidate but remains preserved in immutable evidence. An ineligible failure publishes no candidate activity/CDL/row and leaves selection unchanged.

- **SEC-P6TSC-003 — Minimized metadata and logs.** The new metadata contains only booleans, bounded integer times, and the fixed reason code. Do not include transcript text, speaker/display names, source paths, filenames, hashes, media payloads, confirmation payloads, or private identifiers in new logs/errors. Existing `candidate_requested`, `candidate_failed`, and `candidate_generated` events remain; the candidate can be audited by `cut_id` and its persisted bounded metadata.

- **SEC-P6TSC-004 — Auth and media boundary unchanged.** Do not add routes or relax authentication, media allowlists, range handling, origin checks, or source-media restrictions. Proxies remain silent and sources remain unavailable to the browser.

### 4.3 Tests and acceptance evidence

- **TEST-P6TSC-001 — Regression first, exact reported topology.** Before changing behavior, add a failing authenticated/API-level synthetic regression at `24/1 fps` with accepted artifact end `671296`, confirmed presenter coverage ending `652720`, wide coverage ending `666185`, silence `666185–667208`, covered interviewee speech `667208–668083`, and presenter speech `668083–671292`. After correction, `POST /cut` succeeds with an AI candidate ending exactly at `666167`, omitted duration `5129`, exact truncation metadata, no clip beyond `666167`, and no interviewee substitution for presenter speech.

- **TEST-P6TSC-002 — Metadata, total omission, and no substitution.** Assert the API response, persisted AI row CDL, immutable candidate file, and published activity file contain the exact `truncation` object. Assert the last CDL end equals `candidate_end_ms`; no clip begins or ends later; the covered interviewee segment `667208–668083` does not survive; and the interviewee angle ID never appears as a fallback for presenter speech.

- **TEST-P6TSC-003 — Evidence and selection snapshots.** Seed an accepted artifact, Gate 1 record, program audio, source/analysis timing artifacts, current confirmation rows, selected-cut row, and selected `edit/cdl.json`. Snapshot bytes/row payloads before candidate generation. Assert they are unchanged afterward, while exactly one separate AI candidate publication succeeds and remains unselected.

- **TEST-P6TSC-004 — Retained-prefix internal gap control.** Create a source-uncovered interval strictly before the computed boundary—for example, a presenter dropout mid-timeline while wide coverage still extends to the later boundary. Assert `422`, no truncation, no activity/CDL/AI-row publication, and unchanged selected cut. Repeat with a delayed-start/internal source hole if the fixture can express it without unrelated setup. A covered interviewee segment after the boundary belongs in TEST-P6TSC-001 and must not produce `422`.

- **TEST-P6TSC-005 — No authorized camera/non-empty control.** Make both the required confirmed camera and wide unavailable before the first complete candidate frame, while an unauthorized interviewee source remains. Assert `422`, no empty candidate, no interviewee substitution, no publication, and unchanged selection.

- **TEST-P6TSC-006 — Valid-wide full-length control.** Keep the confirmed presenter camera short but extend the wide source through the artifact end. Assert a full-length valid candidate, `truncation.applied=false`, equal original/candidate ends, omitted `0`, null reason, and normal wide fallback.

- **TEST-P6TSC-007 — Unsafe-wide states remain fail closed in the retained prefix.** Cover at least overlap and low-confidence/unresolved states strictly before `candidate_end_ms` with unavailable wide coverage. Assert this exception does not hide those states and does not choose an arbitrary close camera. Existing safe-wide behavior remains authoritative in the retained prefix.

- **TEST-P6TSC-008 — Frame rounding and source bounds.** At `24/1`, prove frame `15988 = 666167 ms` is accepted and frame `15989 = 666208 ms` exceeds `666185 ms`. Add one non-integer-rate or non-zero-sync case using shared canonical helpers. Assert every surviving clip is frame-aligned, source-bound, contiguous from `0`, and the final source end is no later than probed duration.

- **TEST-P6TSC-009 — Failure and atomicity controls.** Retain/run existing Gate 1, confirmation, malformed artifact, source-bound, write/replace/DB failure, immutable publication, and selection-version tests. An ineligible or failed shortened candidate must leave no temporary file or partial publication.

- **TEST-P6TSC-010 — No backend inference.** Run with `WHISPER_BACKEND=mock`, `DIARIZE_BACKEND=mock`, `OLLAMA_BASE_URL=''`, and `LLM_MODEL=''`; monkeypatch transcription, diarization, and model seams to raise if called. Successful exact-tail generation must consume only the already accepted synthetic artifact and must issue no WhisperX, diarization, or Ollama request.

- **TEST-P6TSC-011 — Determinism.** Identical fixture inputs produce structure-equivalent activity/truncation/CDL content and the same candidate boundary/reason. Exclude intentional candidate ULIDs and creation timestamps from equality.

- **TEST-P6TSC-012 — Verification commands.** Required Programmer evidence is the new focused regression module plus existing AI atomicity/selection suites, Python compile, `git diff --check`, and the deterministic full suite with model variables cleared. Report exact commands, counts, skips, base SHA, candidate SHA, and changed files. Only the credential-gated central-MySQL skip is pre-authorized when credentials are absent.

- **TEST-P6TSC-013 — Independent acceptance chain.** The Programmer cannot approve their own work. Designer compliance must inspect source/diff/tests/runtime evidence against every ID and return `DESIGN_COMPLIANCE_PASS`; an independent Tester must then return `TEST_PASS` for the same exact candidate SHA. Only afterward may a separately authorized Publisher deploy the canonical accepted SHA.

### 4.4 Operations, observability, deployment, and rollback

- **OPS-P6TSC-001 — Production boundary.** Keep production `WHISPER_BACKEND=mock` and `DIARIZE_BACKEND=mock`; keep VAAPI `h264_vaapi`, host networking, port `8010`, NPM at `ingest.peteflix.uk`, central MySQL, volumes, appdata/cache placement, permissions, health checks, and backup topology unchanged. Do not replace VAAPI with QSV.

- **OPS-P6TSC-002 — No production mutation before acceptance.** Programmer, compliance, and Tester tasks must not deploy, mutate `/mnt/user/appdata/autoedit`, access private media, alter Docker templates, recreate containers, or change production data. This plan itself authorizes no Unraid mutation.

- **OPS-P6TSC-003 — Observability.** Preserve existing bounded cut events and duration/error behavior. Successful truncation is observable in both atomically published artifacts through `truncation.applied`, exact ends/duration, and fixed reason code. Ineligible coverage remains a bounded `candidate_failed` outcome; if implementation adds an error code, use `terminal_source_coverage_ineligible` without payload details.

- **OPS-P6TSC-004 — Canonical deployment gate.** After compliance and Tester acceptance, a separate user-approved Publisher task must use `scripts/autoedit-deploy.sh` against the exact accepted commit, perform its backup/preflight/build/health/auth/TLS checks, preserve mock backends, and report structured deployment evidence. No ad-hoc SSH/Docker sequence is approved.

- **OPS-P6TSC-005 — Rollback.** Code rollback is re-deployment of the prior accepted image/commit using the canonical deployment script's rollback path. There is no schema or environment migration. Existing immutable shortened candidate rows/files may remain as auditable, non-selected history; the prior selected cut and full program audio remain authoritative. If deployment health fails, restore the prior image automatically and do not retry without a new decision.

- **OPS-P6TSC-006 — Post-deploy read-only evidence.** Publisher acceptance must show public `/health` `200`, unauthenticated `/projects` `401`, zero unexpected restarts, unchanged mock backend configuration, and a consent-safe API regression or bounded synthetic fixture proving the exact truncation metadata and selected-cut immutability. Do not use the private production transcript/media as a test artifact in Git or durable board logs.

## 5. Reference algorithm for the bounded correction

1. Run the existing project/artifact/Gate 1/current-confirmation validation and project confirmed turns exactly as today.
2. Generate the normal AI activity and CDL using current confidence/overlap/safe-wide rules.
3. Apply current source repair and calculate the exact current-confirmed camera coverage end or ends authorized for the terminal presenter state plus the wide coverage end in the existing program-timeline/source-bound basis. Do not add an otherwise longer other-speaker camera to the boundary set.
4. If the result covers the accepted artifact end, publish a normal full candidate with `truncation.applied=false`.
5. If it does not, set `boundary_instant` to the maximum of those authorized coverage ends and floor it to `candidate_end_ms` with the shared canonical frame helpers. Reject unless `candidate_end_ms > 0` and every instant strictly before it is source-covered under the existing authorization rules. Do not reject merely because a covered segment exists at or after the boundary.
6. Validate the retained prefix with existing sync/source-bound checks. Reject if it is non-contiguous, off-grid, not source-bound, or contains an unsafe-wide failure.
7. End the final surviving clip exactly at that boundary and remove every later clip. Validate the complete shortened CDL.
8. Attach the same deterministic `truncation` object to the full evidence-preserving projected activity metadata and shortened CDL.
9. Atomically publish the activity metadata, immutable CDL, and AI row through the existing transaction. Leave the selected cut and compatibility mirror untouched.

The exception belongs immediately around the current complete-source-bound assertion and source-repair result in `generate_cut`; it must not be implemented as a generic validator relaxation, a first-gap/single-suffix heuristic, or a post-publication file edit.

## 6. Failure-state matrix

| Condition | Required result |
|---|---|
| Exact reported presenter/wide exhaustion with later covered interviewee segment | Shorter valid candidate ending `666167 ms`; drop silence + interviewee interjection + presenter closing; fixed truncation metadata; unselected |
| Confirmed camera exhausted, wide valid to artifact end | Full candidate; no truncation |
| Interviewee source extends beyond presenter/wide | Do not extend the presenter boundary and do not substitute; drop all material at/after the boundary |
| Covered interviewee segment after the `666185` boundary, then presenter closing | Omit both segments; candidate still ends `666167 ms` |
| Presenter/wide source gap strictly before a later authorized coverage boundary | `422`; no publication |
| Delayed start or missing coverage strictly before candidate boundary | `422`; no publication |
| No positive authorized-camera prefix | `422`; no empty candidate |
| Tail contains only silence | `422`; silence alone cannot authorize this policy |
| Retained-prefix source failure is overlap/unresolved/low-confidence/off-camera | Existing safe-wide requirement; `422` when wide unavailable |
| Invalid/missing duration or offset | `422`; no inferred coverage |
| Candidate write/replace/DB/commit failure | Atomic rollback; selected cut/evidence unchanged |
| Explicit later Save this cut succeeds | Existing versioned selection path may select the already validated candidate; outside this correction |

## 7. API, UI, accessibility, responsive, and test-data impact

The request route and payload are unchanged. The successful WhisperX response is additively extended by `truncation`; the same object is persisted in candidate CDL/activity JSON and the cut row's CDL JSON. There is no database-schema migration.

No UI files or behavior change. Existing player/mobile/responsive/accessibility states are unchanged, so no screenshot or visual acceptance is required for implementation. The shorter candidate naturally reports its end through its final CDL clip when previewed later; program audio itself remains full length. A future display treatment would need a separate design card.

Tests use synthetic JSON, tiny generated byte fixtures, and SQLite only. The exact synthetic topology is presenter coverage end `652720`, wide coverage end `666185`, silence `666185–667208`, covered interviewee `667208–668083`, presenter speech `668083–671292`, and artifact end `671296`. They must not include Peter's media, transcript text, names, project IDs, hashes, or derived production artifacts. Central MySQL and Unraid are not required for Programmer tests.

## 8. File ownership and task sizing

One bounded Programmer worktree:

- `src/autoedit/api.py` — authorized-coverage boundary calculation, retained-prefix validation, metadata, and existing atomic publication integration.
- `tests/test_terminal_source_coverage_truncation.py` — exact regression and controls; minimal reuse/import from existing helpers is permitted without refactoring those helpers into product modules.

No concurrent task should edit the `generate_cut` source-repair/publication block. The approved implementation does not own UI, database schema/migrations, Compose/env, deployment scripts, docs beyond this plan, private media, or production state.

## 9. Acceptance evidence matrix

| Requirement IDs | Required evidence |
|---|---|
| BACKEND-P6TSC-001..006, 010..011 | Bounded `api.py` diff plus exact-tail, internal-gap, no-source, valid-wide, unsafe-wide, frame/source-bound tests |
| BACKEND-P6TSC-007 | API response, immutable CDL, AI-row CDL JSON, and activity JSON exact metadata assertions |
| BACKEND-P6TSC-008..009 | Byte/row snapshots for artifact, Gate 1, program audio, timing evidence, confirmations, mirror, and selected row; atomic-failure tests |
| BACKEND-P6TSC-012 | Changed-file list contains only approved implementation/test files; no refactor/module extraction |
| SEC-P6TSC-001..004 | Diff inspection, no-substitution assertions, fail-closed/no-publication controls, no sensitive log/API additions |
| TEST-P6TSC-001..011 | Named focused test output and fixture assertions for every positive/control path |
| TEST-P6TSC-012 | Exact focused/full/compile/diff command outputs, SHAs, and skips |
| TEST-P6TSC-013 | Independent exact-SHA compliance matrix and Tester verdicts |
| OPS-P6TSC-001..003 | Diff confirms no env/Compose/schema/deploy changes; metadata/event evidence |
| OPS-P6TSC-004..006 | Separate approved Publisher record only after acceptance, including backup/health/auth/mock/rollback facts |

## 10. Risks and mitigations

- Risk: a generic boundary clamp hides an internal missing source. Mitigation: prove every instant strictly before the canonical boundary is source-covered; later coverage does not excuse a retained-prefix gap.
- Risk: the longer interviewee source is treated as convenient presenter coverage. Mitigation: exact confirmed-camera-plus-wide allowlist and explicit negative assertions.
- Risk: a later covered interviewee interjection accidentally keeps the candidate open. Mitigation: presenter/wide boundary calculation excludes other-speaker cameras, and every clip at or after the boundary is removed.
- Risk: flooring to raw milliseconds produces an off-grid or one-frame-over source end. Mitigation: shared canonical frame helpers, floor-before-source-end loop, and exact `666167`/`666208` regression.
- Risk: trimming activity erases evidence for the omitted speech. Mitigation: retain the full projected activity timeline and accepted artifact end; add candidate boundary metadata instead.
- Risk: a shortened candidate silently becomes authoritative. Mitigation: existing immutable AI publication and selected-row/mirror snapshots; selection only through explicit versioned save.
- Risk: unsafe-wide overlap/confidence behavior becomes truncation authority. Mitigation: these states remain outside eligibility and fail closed when the wide is absent.
- Risk: live behavior drifts from reviewed code. Mitigation: exact candidate SHA compliance, independent Tester, then canonical Publisher with rollback evidence.

## 11. Non-goals

- No interviewee or arbitrary-camera fallback for presenter speech.
- No general internal-gap repair, source-duration guessing, stale-metadata repair, first-gap/single-suffix classification, or validator relaxation.
- No changes to automatic energy-envelope cross-correlation or manual sync workflow.
- No accepted artifact, Gate 1, audio, confirmation, timing, database-schema, or selected-cut mutation.
- No UI, responsive, accessibility, player, export, Compose, environment, Docker template, deployment-script, reverse-proxy, MySQL, VAAPI, or Unraid change.
- No real WhisperX/diarization activation and no inference request.
- No private/consent-controlled media or derived production artifact in source control or board logs.

## 12. Verdict

DESIGN_APPROVED
