# Stage 7.4 Exact-Candidate Acceptance Closure

Status: DESIGN_APPROVED

Design owner: AUTOEDIT Designer
Date: 2026-07-16
Baseline candidate: `c096e4e179291d910fbdb8864916318cbfd28c64`
Baseline worktree: `/opt/data/workspace/AUTOEDIT/.worktrees/autoedit-integrated`
Triggering Tester card: `t_77fce10d`
Triggering defect: `BUG-AE-P3-004`

## 1. Purpose and decision

This plan closes the distinct findings from the independent Stage 7.4 run without rewriting its recorded `TEST_FAIL` and without reopening the stale old-`master` delete-marker defect.

The exact `c096e4e` browser run passed the Stage 7.4 functional behaviors: two authors and times, XSS-safe text rendering, marker seek, synchronized list/lane deletion, and zero browser console/page/unexpected-network errors. It also reproduced a P3 note-metadata readability defect. The same Tester run executed a non-canonical, environment-sensitive full-suite command and reported two failures in Stage 9.1 natural-language intent tests.

Design decision:

1. `BUG-AE-P3-004` is an in-scope Stage 7.4 acceptance blocker. It requires one bounded frontend accessibility/layout correction based exactly on `c096e4e`, followed by independent design compliance and Tester regression.
2. The two NL-intent failures are not Stage 7.4 product-scope failures. The failing files and behavior belong to Stage 9.1, and the implementation/tests are unchanged from their original snapshot. They are separately owned test-isolation/root-cause work.
3. The NL failures still may not be silently discarded. The baseline `TEST_FAIL` remains immutable. Stage 7.4 may receive a later `TEST_PASS` only when the correction candidate passes the canonical deterministic full-suite command in TEST-74-005. If that command still fails, Stage 7.4 remains procedurally blocked even when the failure is owned elsewhere.
4. No publication, deployment, production mutation, or status change to `done` is authorized by this plan.

## 2. Evidence adjudication

### Verified facts

- Tester report `/opt/data/workspace/AUTOEDIT/.worktrees/autoedit-integrated/STAGE_7_4_ACCEPTANCE_REPORT.txt` identifies exact candidate `c096e4e179291d910fbdb8864916318cbfd28c64` and records `TEST_FAIL`.
- Candidate hashes recorded by Tester:
  - `player.js`: `a737e101e1da601dcf5fc6cd5d1a1c9c1d482219dcb4af63f172b9a44683c860`
  - `index.html`: `41e104941fb0bdb8b2a28154e185616a270dbfca468034502f429e2252779efb`
  - `player.css`: `6f5a5cbf51c9f02d6638a2934aa578bd002be1fb109214612ae78f7f47f30b6c`
- Browser behavior passed: two authors/times rendered; an injected script remained literal text and did not execute; marker seek reached 5 seconds; delete left one list item and one lane marker; the browser reported zero console/page/unexpected-network errors.
- `BUG-AE-P3-004` is visible in the exact-candidate screenshot: author, kind, time, and the `×` delete control are packed together without adequate grouping or target size.
- `player.js` creates distinct author, kind, time, and delete elements, and renders author/body through `textContent`.
- The shared stylesheet defines `.note-item-meta`, but `player.js` emits `.note-item-header`; therefore the intended flex spacing rule does not apply to the rendered header. This is the verified implementation mismatch; the correction must not be broadened beyond the note-header seam.
- The current delete control is a visible `×` button without a programmatic note-specific accessible name. The timestamp is a clickable `span`, not a native keyboard-operable control.
- The two reported full-suite failures are `tests/test_nl_intent.py::test_time_range` and `::test_no_matching_topics`. `src/autoedit/nl_intent.py` and `tests/test_nl_intent.py` at `c096e4e` are byte-identical to their original `1b724d9` snapshot versions.
- `parse_sub_edit_intent()` selects the LLM path when `Settings.llm_model` and `Settings.ollama_base_url` are non-empty; both settings have non-empty defaults. Project documentation defines the deterministic local suite by explicitly clearing `OLLAMA_BASE_URL` and `LLM_MODEL`.
- The deployed release is a non-`master` branch. `c096e4e` is not an ancestor of local `master`.

### Assumptions

- The note panel continues to use the existing `480px` mobile breakpoint in `player.css`; this plan does not introduce a new application-wide breakpoint.
- A native button is acceptable for timestamp seeking and delete actions. This is consistent with the existing component system and improves keyboard behavior without changing API contracts.
- Synthetic note records are sufficient acceptance data; no real or private media is needed.

### Unknowns

- The Tester report does not retain the exact environment variables or external LLM response that produced the two NL-intent values. The evidence strongly identifies an environment-sensitive Stage 9.1 path, but does not prove which external model response was used.
- The exact post-correction commit SHA does not exist yet. It must be captured as the correction candidate identity.
- Production has not been tested or changed by this design card.

### User decisions

No user decision is required. The source specification, style guide, existing breakpoint, and accessibility requirements are sufficient to approve the bounded correction.

## 3. Requirements

### Architecture and boundary

- **ARCH-74-001 — Exact lineage.** The Stage 7.4 correction branch/worktree must be created from exact baseline `c096e4e179291d910fbdb8864916318cbfd28c64`. Before editing, record worktree path, branch, `git rev-parse HEAD`, and a clean tracked diff. At acceptance, record the new full correction SHA and prove `c096e4e` is its ancestor.
- **ARCH-74-002 — Presentation-only scope.** The required Stage 7.4 package may change only note-header presentation, semantic controls, and directly related regression coverage. It must not alter note persistence, timeline contracts, media playback, synchronization, cut logic, LUT behavior, or deployment configuration.
- **ARCH-74-003 — Non-master evidence.** All implementation, compliance, and Tester claims must name the exact integration-derived worktree and SHA. Evidence from `/opt/data/workspace/AUTOEDIT` `master` is historical only and cannot decide this correction.

### Backend and data contracts

- **BACKEND-74-001 — API preservation.** Preserve the existing contracts for `POST /projects/{project_id}/notes`, `GET /projects/{project_id}/notes`, `DELETE /projects/{project_id}/notes/{note_id}`, and the `notes` member of `GET /projects/{project_id}/timeline-state`.
- **BACKEND-74-002 — Note model preservation.** Preserve `t_ms` as a non-negative integer, `body` length `1..10000`, kinds `note|cut_suggestion`, author derived from the authenticated session, list ordering by `t_ms`, and the current response fields.
- **BACKEND-74-003 — No persistence change.** No migration, schema change, production-data rewrite, note backfill, or media/artifact mutation is permitted.

### Desktop visual design

- **UI-74-001 — Header hierarchy.** Every note card must render metadata in this fixed reading and DOM order: author, kind, timestamp, delete. The body remains a separate row beneath the metadata.
- **UI-74-002 — Desktop layout.** At `1440×900`, `.note-item-header` must use a bounded grid or flex layout with at least `12px` horizontal separation between author, kind, timestamp, and delete hit area, at least `8px` row gap if wrapping occurs, and at least `8px` between metadata and body. Author uses primary text, minimum `14px` size and weight `500`; kind uses mono uppercase, minimum `11px`; timestamp uses mono or data styling, minimum `13px`. Kind and timestamp must meet WCAG 2.1 AA `4.5:1` text contrast against the note-card surface.
- **UI-74-003 — Desktop growth behavior.** Author occupies the flexible column and may wrap. Kind, timestamp, and delete remain individually distinguishable. A maximum-length `120`-character display name, including an unbroken test value, must not overlap, clip another control, or create horizontal page/card scrolling.
- **UI-74-004 — Kind distinction.** `note` and `cut` labels must remain visibly distinct text; kind cannot be communicated by color alone. Existing note/cut marker colors and semantics remain unchanged.

### Mobile visual design

- **UI-74-005 — Mobile layout.** At `375×812` and the existing `max-width: 480px` breakpoint, author occupies its own full-width first metadata row. Kind, timestamp, and delete occupy a second row with at least `8px` horizontal and vertical separation. The delete control stays at the inline end. The note body begins at least `8px` below metadata.
- **UI-74-006 — No overflow.** At `375×812`, `1440×900`, and browser zoom `200%` at a CSS viewport equivalent to `640px` wide, the page, Notes panel, each note card, metadata header, author, body, timestamp, and delete control must satisfy `scrollWidth <= clientWidth` except for a one-pixel rounding tolerance. No pair of metadata bounding boxes may intersect.
- **UI-74-007 — Readability under real limits.** The mobile acceptance fixture must include both note kinds, two distinct authors, one maximum-length `120`-character author, the XSS probe text, and an unbroken long body token. Text may wrap but may not be truncated in a way that hides identity, kind, timestamp, or delete.

### Accessibility and interaction

- **UI-74-008 — Native timestamp action.** Timestamp must be a native `button` (or an equivalently complete keyboard control, if independently justified) with an accessible name that includes the formatted time. Enter and Space must seek program audio to the note time. It must retain the existing visual timestamp meaning and must not submit the add-note form.
- **UI-74-009 — Delete action.** Delete must be a native `button type="button"` with a minimum `44×44` CSS-pixel target and an accessible name containing the note author and formatted timestamp, for example `Delete note by Reviewer Beta at 0:05`. The visible glyph may remain `×`, but the accessible name cannot be only `×`.
- **UI-74-010 — Focus and states.** Timestamp and delete controls require a visible `:focus-visible` indicator with at least a `2px` outline and must remain distinguishable in default, hover, focus, active, and disabled/loading states. Focus indication must not rely on color alone.
- **UI-74-011 — Stable list states.** Zero, one, multiple, newly created, deleting, deleted, long-content, and failed network states must preserve layout. Existing note-create status feedback remains visible. This package must not introduce optimistic deletion or hide an API failure.
- **UI-74-012 — Existing behavior preservation.** Preserve multi-author identity, exact formatted note time, marker seek, timestamp seek, add-at-playhead behavior, and successful synchronized deletion from both list and lane.

### Security and privacy

- **SEC-74-001 — XSS-safe rendering.** Author and body remain assigned with `textContent`; no note-controlled value may enter `innerHTML`, event-handler HTML, a URL, CSS, or executable markup. The literal `<script>` probe must produce no script element and no global side effect.
- **SEC-74-002 — Authentication and authorization.** Do not change session-derived author behavior or route authentication. No client-supplied author field may become authoritative.
- **SEC-74-003 — Test-data privacy.** Use synthetic authors, notes, and generated audio only. Do not read, copy, commit, or mutate private media, production notes, credentials, `/mnt/user/appdata/autoedit`, or `/mnt/user/automulticam`.

### Operations, deployment, and rollback

- **OPS-74-001 — No deployment in closure implementation.** Programmer, compliance, and Tester cards are local/integration work only. They must not publish, deploy, hot-copy static files, recreate containers, change Unraid templates, or touch production data.
- **OPS-74-002 — Deployment impact declaration.** The required correction is static frontend code only. It adds no port, service, device, volume, permission, secret, database, health-check, reverse-proxy, VAAPI, Whisper, or diarization change.
- **OPS-74-003 — Future deployment gate.** A later, explicitly approved Publisher card must use the reviewed correction SHA and the canonical deployment script/runbook with backup, rendered Compose validation, health/auth/browser smoke, and automatic rollback. Rollback is restoration of the prior `c096e4e` image/static assets; no data rollback should be needed because BACKEND-74-003 forbids persistence changes.
- **OPS-74-004 — Runtime observability.** Browser acceptance must collect console messages, uncaught page errors, failed/unexpected responses, and request failures. Expected stub routes must all return intentional success responses; acceptance requires zero unexpected entries.

### Test and evidence gates

- **TEST-74-001 — CSS/layout regression.** A committed or durable browser regression must assert computed layout at `1440×900` and `375×812`: metadata order, minimum gaps, non-intersecting bounding boxes, `44×44` delete target, author/body wrapping, and no horizontal overflow. Screenshots must be saved for both viewports.
- **TEST-74-002 — Accessibility regression.** Browser evidence must assert native button roles, accessible names, Tab reachability, visible focus, Enter/Space timestamp seek, and keyboard activation of delete. An automated accessibility scan may supplement but not replace these direct assertions.
- **TEST-74-003 — Stage 7.4 behavior regression.** Against actual correction-candidate `index.html`, `player.css`, and `player.js`, independently verify: two authors/times; both kinds; XSS probe literal and inert; marker seek; timestamp seek; delete removes the same note from list and lane; reload retains the deletion; zero console/page/unexpected-network errors.
- **TEST-74-004 — Targeted code gates.** Run the candidate’s notes/player/static Python tests, direct Node player tests, Python compile, `git diff --check`, and any new browser test. Exact commands and observed outputs must be recorded.
- **TEST-74-005 — Canonical full-suite command.** The only deterministic full-suite result accepted for this closure is:

  `OLLAMA_BASE_URL='' LLM_MODEL='' env -u VIRTUAL_ENV uv run pytest -q -rs`

  It must report zero failures/errors. The credential-gated central-MySQL skip is permitted only when its stated credentials are absent; every other skip must be named and justified.
- **TEST-74-006 — No-silent-ignore rule.** Every failing or erroring test from any command must be retained in evidence with exact command, relevant non-secret environment, test node, expected/actual result, ownership, and disposition. A non-canonical failure cannot be relabelled as a pass. Stage 7.4 may proceed when the canonical deterministic suite passes and separately owned failures have a durable defect/card reference. If the canonical command fails for any reason, Tester must return `TEST_FAIL`; “unrelated” is not a waiver for a red canonical gate.
- **TEST-74-007 — Immutable baseline verdict.** Do not edit, overwrite, or reinterpret `t_77fce10d` or its report. The next independent run creates a new report and verdict for the new correction SHA.
- **TEST-74-008 — Independent sequence.** Required order is Programmer implementation → independent Designer requirement-by-requirement compliance matrix → independent Tester rerun. Only a `DESIGN_COMPLIANCE_PASS` followed by `TEST_PASS` can support marking Stage 7.4 done.

## 4. Bounded implementation packages

### Package A — required Stage 7.4 correction

Owner: one `autoeditprogrammer` project worktree/branch based exactly on `c096e4e`.

Permitted product files:

- `src/autoedit/web/player.css`
- `src/autoedit/web/player.js`

Permitted test files:

- `tests/browser/stage_7_4_notes.spec.cjs` or one equivalently named browser regression derived from the existing synthetic harness
- `tests/player_logic.test.mjs` only if a small pure helper is extracted for accessibility/seek semantics
- `tests/test_player_static.py` only for static shell/asset assertions that cannot be expressed in the browser test

Required implementation shape:

1. Correct the emitted `.note-item-header` seam; remove or leave no misleading dead `.note-item-meta` rule.
2. Use native semantic controls for timestamp and delete, including `type="button"` and programmatic labels.
3. Add only note-header responsive/focus/overflow rules. Do not refactor the player or shared design system.
4. Add the desktop/mobile/keyboard/browser regressions in TEST-74-001 through TEST-74-003.

Forbidden files unless a newly discovered requirement proves otherwise and Designer approves before edit:

- `src/autoedit/api.py`
- `src/autoedit/db/**`
- `src/autoedit/cut_engine.py`
- Compose/Docker/deployment files
- production data or media

### Package B — separately owned NL-intent test isolation

Owner: a different bounded `autoeditprogrammer` worktree. It is not part of Package A and must not share a commit.

Initial permitted files:

- `tests/test_nl_intent.py`
- a narrowly scoped test fixture/config file if needed
- `src/autoedit/nl_intent.py` only if RED evidence proves test-only isolation cannot fix the contract; product-semantic changes then require separate design review

Purpose:

- Reproduce and distinguish deterministic parsing from opt-in live-LLM parsing.
- Ensure deterministic NL-intent unit tests cannot call Ollama or depend on an ambient/default model.
- Preserve explicit, separately mocked tests for the live-LLM adapter rather than masking that path.

Relationship to Stage 7.4:

- Package B is not a Stage 7.4 feature dependency and must not be bundled into the note-layout commit.
- A passing TEST-74-005 canonical suite allows Stage 7.4 to proceed while Package B remains separately tracked.
- A failing TEST-74-005 suite blocks the Stage 7.4 verdict procedurally until the failure is corrected and independently rerun.

## 5. Browser fixture and acceptance method

Use no real media. The route harness must serve the correction candidate’s actual `index.html`, `styles.css`, `player.css`, and `player.js`, plus successful synthetic routes for progress, player-state, timeline-state, notes CRUD, LUT list, proxy, and valid generated program audio with byte-range behavior.

Fixture set:

- Reviewer Alpha: normal note with literal `<script>window.__xss=1</script>` body.
- Reviewer Beta: cut suggestion with normal body.
- Long identity: a synthetic `120`-character unbroken author.
- Long content: a synthetic unbroken token sufficient to force wrapping.
- Timeline duration: deterministic and long enough to assert exact 5-second seek.

Required artifacts:

- desktop `1440×900` screenshot with at least two notes
- mobile `375×812` screenshot with at least two notes and long identity
- post-delete screenshot showing one list item and one lane marker
- machine-readable or text report containing candidate SHA/hashes, bounding-box/gap/overflow assertions, keyboard/accessibility assertions, browser error arrays, commands, and outputs

A screenshot alone is not proof of spacing. The test must record computed dimensions or DOM rectangles.

## 6. Failure modes and required behavior

| Failure | Required behavior/evidence |
|---|---|
| Long author/body | Wrap within the card; preserve all metadata and controls; no horizontal overflow. |
| Narrow viewport/zoom | Reflow to the specified two-row mobile metadata layout; no overlap. |
| POST failure | Existing visible status remains; draft is retained; no false note/marker appears. |
| DELETE failure/network exception | Existing note and marker remain; no optimistic disappearance; error must not be hidden by this correction. |
| DELETE success | List and lane remove the same note and remain correct after reload. |
| Missing timeline state | Note list remains usable under existing behavior; no new exception. |
| Malicious note/author text | Render as inert text only. |
| Non-canonical full-suite failure | Record it and its owner; never convert the baseline or new run to a pass. |
| Canonical full-suite failure | New Tester verdict is `TEST_FAIL`, regardless of feature ownership. |
| Wrong worktree/SHA | `BLOCKED_TEST_ENVIRONMENT`; do not produce candidate acceptance. |

## 7. Compliance matrix expected from the Designer

The compliance reviewer must inspect the actual correction SHA, full diff from `c096e4e`, source, tests, browser artifacts, and command outputs. The report must include every ID in this plan with evidence and pass/fail. Approval cannot rely on Programmer summaries. Any failed requirement returns `IMPLEMENTATION_CHANGES_REQUIRED` with a bounded correction request.

## 8. Definition of closure

Stage 7.4 may be reported `done` only when all of the following are true:

1. Package A is based on exact `c096e4e` and has a recorded full correction SHA.
2. Every requirement in this plan receives `DESIGN_COMPLIANCE_PASS`.
3. Independent Tester evidence for the correction SHA returns `TEST_PASS` under TEST-74-001 through TEST-74-007.
4. The canonical deterministic full suite is green.
5. The P3 crowding defect is closed with desktop/mobile/zoom evidence.
6. Existing multi-author, XSS, seek, synchronized deletion, API, auth, player clock, silent-proxy, automatic-sync, VAAPI, and mock-AI invariants remain unchanged.
7. Backlog/handoff status is updated only after the evidence above; deployment remains a separate explicit decision.

## 9. Risks and non-goals

Risks:

- A broad shared-CSS change could regress unrelated app screens; mitigate by scoping rules under `.player-shell .note-item-*` and browser-testing both target viewports.
- A visual-only change could leave timestamp/delete inaccessible; mitigate with native controls and direct keyboard assertions.
- Ambient Ollama settings could make a full suite nondeterministic; mitigate with the exact canonical command and separate Package B ownership.
- Testing `master` could recreate the stale delete-marker finding and produce invalid release evidence; mitigate with ARCH-74-001 and ARCH-74-003.

Non-goals:

- No note API/schema redesign, rich text, grouping/filtering, optimistic mutations, author editing, or note permissions redesign.
- No repair or retest of the stale old-`master` delete-marker defect.
- No Stage 9.1 product-semantics change in Package A.
- No player architecture refactor, source-media playback, audio clock change, sync nudge redesign, proxy encoder change, Whisper/diarization promotion, deployment, or production mutation.

DESIGN_APPROVED
