# Stage 8.3 OTIO Fallback Closure

Status: DESIGN_APPROVED

Design owner: AUTOEDIT Designer
Date: 2026-07-16
Kanban card: `t_ed4fc827`
Design baseline: local `master` at `24b537a`; this workspace is dirty with unrelated in-progress work, so implementation must use a fresh project worktree and must not inherit or claim this workspace's uncommitted changes.

## 1. Decision and source-spec reconciliation

Stage 8.3 is not a request to replace the working exporters.

Verified current behavior already satisfies part of the source-spec Definition of Done:

- `src/autoedit/edl_writer.py` emits a direct CMX3600 EDL with non-drop timecode, clip-name comments, and `* LOC:` note locators.
- `POST /projects/{project_id}/export` keeps direct FCPXML as the default and accepts direct EDL through body `{"export_format":"edl"}` or query `?export_format=edl`; body key `format` is retained as a legacy alias.
- The player exposes direct `Export FCPXML` and `Export EDL` buttons.
- The direct FCPXML and direct EDL paths have automated coverage, and both are recorded as Resolve-verified. Direct EDL is already the source-spec's available secondary EDL option.
- Direct FCPXML has not proved fragile in Peter's Resolve build. The source spec says to switch the default to OTIO only if the hand-written FCPXML proves fragile; that condition is not met.

What remains is a real, independently selectable `CDL -> OpenTimelineIO -> adapter` path whose OTIO-generated FCPXML opens populated in Resolve. For complete fallback coverage and a common interchange seam, this plan also requires an OTIO-generated CMX3600 EDL. Both OTIO outputs are explicit API-only fallback formats. Existing `fcpxml` and `edl` names, output files, UI buttons, serializers, and defaults remain unchanged.

The new formats are:

| `export_format` | Engine | Fixed output | Purpose |
|---|---|---|---|
| `fcpxml` | existing direct writer | `edit/export.fcpxml` | unchanged default/preferred path |
| `edl` | existing direct writer | `edit/export.edl` | unchanged visible secondary path; Resolve locator path |
| `otio_fcpxml` | OTIO `fcpx_xml` adapter plus exact-rate normalizer/verifier | `edit/export.otio.fcpxml` | explicit FCPXML fallback |
| `otio_edl` | OTIO `cmx_3600` adapter plus deterministic LOC normalizer/verifier | `edit/export.otio.edl` | explicit OTIO/CMX fallback and adapter parity evidence |

No UI control is added in this package. The working direct choices remain the operator-facing choices; the fallback is deliberately an expert/API path until Peter's Resolve acceptance passes. A future change that remaps `fcpxml` to OTIO or exposes fallback controls requires a separate design/user decision and must preserve the existing API name.

AAF is not a Stage 8.3 closure gate. Although the build sentence in the source spec names adapters capable of FCPXML/EDL/AAF, the Stage 8.3 Definition of Done requires OTIO FCPXML and a secondary EDL. AAF adds a larger dependency and a separate Resolve acceptance surface without closing an unmet DoD item.

## 2. Evidence and boundaries

### Verified facts

- Source spec Stage 8.3 is optional/recommended, depends on Stage 8.1, and defines success as an OTIO-generated FCPXML populated in Resolve plus secondary EDL availability.
- Stage 8.1 validation and Stage 8.2 direct FCPXML are implemented and Resolve-verified.
- The direct export endpoint validates the rough-cut CDL before either direct writer runs, loads notes ordered by `t_ms`, writes fixed filenames under `edit/`, and returns `status`, `path`, `url`, and `format`.
- The authenticated edit-media allowlist currently permits only `export.fcpxml` and `export.edl`.
- `pyproject.toml` and `uv.lock` do not contain OpenTimelineIO.
- The latest published packages checked during design are `OpenTimelineIO==0.18.1`, `otio-fcpx-xml-adapter==1.0.0`, and `otio-cmx3600-adapter==1.0.0`. OpenTimelineIO core has only native OTIO adapters; external formats are plugins.
- `OpenTimelineIO-Plugins==0.18.1` pulls a broad adapter set and `otio-fcp-adapter`, not the required `otio-fcpx-xml-adapter`. The bounded package therefore needs direct adapter dependencies rather than the batteries-included metapackage.
- The `fcpx_xml` plugin advertises `.fcpxml`, multiple video tracks, audio, gaps, markers, and writing. Its current writer emits FCPXML 1.8 and uses a small floating-rate lookup. That lookup and its rational conversion are not sufficient proof of AUTOEDIT's exact `24000/1001` and `30000/1001` contract.
- The `cmx_3600` plugin writes only one enabled video track, accepts an explicit rate, and writes clip markers as `* LOC:` comments. Its writer uppercases marker names, so unverified raw adapter output is not sufficient proof of note-text preservation.
- AUTOEDIT's validator already defines canonical frame conversion through shared timeline boundaries. Integer milliseconds are canonical storage, while export truth is whole frame indices at `fps_num/fps_den`.
- Stage 7.4 note CRUD/UI exists, but independent exact-candidate acceptance remains open. Stage 8.3 design and implementation may proceed; Stage 8.3 cannot be marked done while the required Stage 7.4 note acceptance is unresolved.
- Production is exact non-`master` commit `c096e4e...`; it is not an ancestor of local `master`. This design card does not test, publish, deploy, or mutate production.
- Designer provider preflight passed before substantive work: profile configuration, current session, and a fresh one-call smoke all reported `openai-codex` / `gpt-5.6-sol`; fallback providers are empty and MoA is disabled. OpenRouter was not used.

### Assumptions

- One in-memory OTIO video track is sufficient because the CDL represents the selected program cut, not all camera lanes.
- Source files may be relinked by basename, matching the current direct FCPXML behavior; an exported artifact does not need or receive an absolute Unraid path.
- Notes within the program interval are expected. A note outside `[0, program_end)` is treated as invalid export input rather than silently dropped or clamped in the OTIO path.
- Synthetic source stubs and a deterministic CDL are sufficient for automated contract tests; Resolve import remains Peter-only because Resolve is not available in the agent environment.

### Unknowns to resolve with implementation evidence

- Exact XML structure emitted by the pinned adapter for AUTOEDIT's one-track timeline at every supported project rate.
- Whether Peter's Resolve build imports OTIO-FCPXML markers. Marker presence in XML is automated; visibility in Resolve is a manual observation and must not be inferred.
- Final correction/implementation SHA and the exact lockfile hashes do not exist yet.

### User decisions

No user decision is required to approve the bounded implementation. Existing Resolve evidence decides that direct FCPXML remains default. Peter is required only for the final Resolve acceptance described in section 10. A future default switch, AAF support, or new fallback UI would require a new decision.

## 3. Architecture requirements

- **ARCH-83-001 — Additive fallback seam.** Add one new module, `src/autoedit/otio_export.py`, that converts a validated AUTOEDIT CDL, project FPS, confined angle metadata, and notes into a deterministic canonical frame manifest and an in-memory OTIO timeline. It must not change the CDL contract.
- **ARCH-83-002 — Explicit engines.** `otio_fcpxml` and `otio_edl` are explicit opt-in formats. `fcpxml` remains the default direct writer and `edl` remains the direct writer. No environment variable or automatic retry may silently change engines.
- **ARCH-83-003 — Lazy isolation.** OTIO and adapter imports occur only when an OTIO format is requested. A missing or broken OTIO plugin must not prevent application startup, health checks, player use, or either direct export.
- **ARCH-83-004 — One selected program track.** The canonical OTIO timeline contains exactly one enabled video track, clips in CDL order, and no transitions, speed effects, LUT effects, source audio, or generated program-audio track. It represents the selected rough cut, not a multicam source stack.
- **ARCH-83-005 — Canonical frame manifest.** Before constructing OTIO objects, derive for every clip: `timeline_start_frame`, `timeline_end_frame`, `source_start_frame`, `duration_frames`, angle ID, source basename, and deterministic clip index. Derive duration only as `end_frame - start_frame`; never round start and duration independently.
- **ARCH-83-006 — Adapter-specific projection.** Both adapters consume data projected from the same canonical frame manifest. A bounded FCPXML temporal normalizer and a bounded CMX locator normalizer are permitted because current plugin rate/text serialization does not itself prove AUTOEDIT's exact-rate and case-preservation contracts. Normalizers may change only adapter-emitted temporal attributes, stable resource references, and marker/LOC fields; they may not synthesize the edit independently.
- **ARCH-83-007 — No persistent OTIO authority.** The CDL remains authoritative. The OTIO object is in-memory and may be serialized only in tests/debug evidence with private values removed. Do not add a database column, migration, authoritative `.otio` artifact, or pipeline stage.
- **ARCH-83-008 — Deterministic construction.** Sort source/resource definitions by stable angle ID, clips by CDL order, and notes by `(project_frame, note_id)`. Set a fixed timeline/event name such as `AUTOEDIT Export` so the adapter cannot substitute the current date. Repeated export of identical inputs and dependency versions must be byte-identical.

## 4. Backend and API requirements

- **BACKEND-83-001 — Existing contract preservation.** Preserve method, route, authentication, default format, body/query precedence, legacy body `format` alias, validation order, fixed direct output names, response fields, and error behavior for existing `fcpxml` and `edl` requests.
- **BACKEND-83-002 — New format contract.** Extend the accepted format allowlist with exactly `otio_fcpxml` and `otio_edl`. Successful responses retain `{"status":"ok","path":...,"url":...,"format":...}` and return the requested exact format string.
- **BACKEND-83-003 — Fixed artifacts.** Write only `edit/export.otio.fcpxml` and `edit/export.otio.edl`; add only those exact basenames to authenticated `kind=edit` media delivery. No client-supplied filename, directory, suffix, adapter name, or output path is accepted.
- **BACKEND-83-004 — Validate first.** Run the existing `validate_cdl()` gate before OTIO construction. Preserve the existing clip-indexed 400 response when the CDL is invalid. OTIO must never be used to coerce, fill, reorder, or repair an invalid CDL.
- **BACKEND-83-005 — Angle completeness.** Every CDL angle must resolve to exactly one project angle and one existing confined source file. Unknown/duplicate angles, missing source files, and empty source basenames fail before adapter invocation with a non-secret 400 diagnostic identifying the clip index/angle ID.
- **BACKEND-83-006 — Note completeness.** Load note ID, `t_ms`, kind, author, and body. Every note must map to one project frame within `[0, program_end_frame)`. Boundary notes map to the following clip under half-open intervals. Out-of-range/unmappable notes fail visibly; no OTIO export may silently omit or clamp one.
- **BACKEND-83-007 — Atomic publication.** Generate and verify into a temporary file created inside the project's `edit/` directory, `fsync`/close it, then replace the fixed output atomically. On any conversion, adapter, normalization, verification, write, or replace failure, remove only the temporary file and preserve the last-known-good OTIO export.
- **BACKEND-83-008 — Media response.** The authenticated returned URL must download the exact verified bytes. Unauthenticated access remains 401. Unknown edit filenames, temporary files, source media, and `.otio` intermediates remain unavailable.
- **BACKEND-83-009 — Direct-output independence.** An OTIO export must not read, overwrite, rename, compare as authority, or depend on `export.fcpxml` or `export.edl`. A direct export similarly must not overwrite either OTIO output.

## 5. Frame, rate, source, and marker requirements

- **BACKEND-83-010 — Supported rate identity.** Preserve the exact positive project ratio from DB/CDL. Automated acceptance must cover `24000/1001`, `25/1`, and `30000/1001`. No decimal FPS string is authoritative.
- **BACKEND-83-011 — Shared-boundary frame conversion.** Use the existing canonical millisecond-to-frame convention. For adjacent clips, emitted record/timeline frame `out(i)` must equal `in(i+1)` exactly. Source in and source out must be whole frames, and every duration must be positive.
- **BACKEND-83-012 — Exact FCPXML timing.** After adapter generation, FCPXML `frameDuration` must equal project `fps_den/fps_num` seconds, reduced only without changing value. Every emitted `offset`, `start`, `duration`, sequence duration, and marker start/duration must map to an integer frame at that exact ratio. The normalized clip manifest must equal the canonical frame manifest entry-for-entry.
- **BACKEND-83-013 — CMX timecode policy.** OTIO EDL remains CMX3600 non-drop, matching the direct EDL policy. Use nominal timecode base 24 for `24000/1001`, 25 for `25/1`, and 30 for `30000/1001`; explicit adapter rate is mandatory. Parsed source/record frame counts must equal the canonical manifest.
- **BACKEND-83-014 — Relinkable references.** OTIO media references and both outputs use the source basename/clip name needed for relinking. Generated artifacts must not contain `DATA_ROOT`, `/data`, `/mnt/user`, the repository path, a temporary directory, a credential, URL query, or an absolute host path.
- **BACKEND-83-015 — Marker identity.** The canonical visible marker value is `[<kind>] <author>: <body>`. Preserve kind, author, body, project frame, multiplicity, and deterministic same-frame order in both OTIO outputs. `cut_suggestion` is textually distinct and mapped red; a normal `note` is textually distinct and mapped to a non-red supported color. Color is supplemental, never the only kind signal.
- **BACKEND-83-016 — Marker coordinate projection.** Store the absolute project frame and clip-relative frame in OTIO marker metadata. FCPXML clip markers use the adapter's required clip/source-relative coordinate and are normalized back to the expected project-frame position on parse. CMX LOC timecode uses the absolute record/project frame. Tests must detect sign, clip-boundary, or source-vs-record coordinate drift.
- **BACKEND-83-017 — Safe text normalization.** Preserve printable Unicode and case. Replace CR, LF, tab, NUL, and other structural control characters with a single visible space in one-line EDL/FCPXML marker values; do not evaluate markup. XML escaping remains the adapter/XML serializer's responsibility. OTIO EDL LOC normalization must restore original case after the adapter's uppercase behavior and must not permit injected EDL events/comments.
- **BACKEND-83-018 — Structural verification.** Re-read each completed temporary output before publication. FCPXML verification checks XML parseability, expected root/version, resource/clip/marker counts, exact frame manifest, and no forbidden paths. EDL verification checks title/FCM, sequential event count, source/record frames, clip-name mapping, LOC count/frames/text, and no unrecognized injected event lines.

## 6. UI and accessibility requirements

- **UI-83-001 — No UI regression.** Preserve the existing Export panel copy, button order, labels, button semantics, responsive behavior, keyboard behavior, loading/disabled state, success status, failure status, and download flow for direct FCPXML and direct EDL.
- **UI-83-002 — No premature fallback control.** Do not add OTIO buttons, a selector, automatic fallback toast, or a default-engine setting in this package. The fallback is API-only until Resolve acceptance. Therefore no new mobile breakpoint, focus order, ARIA label, or browser state is introduced.
- **UI-83-003 — Honest failure.** Existing direct requests must never report an OTIO failure. If future separately approved UI exposes OTIO, it must name the selected engine and surface the API's plain failure; it may not silently download a direct artifact instead.

The UI remains responsive and accessible by preservation rather than new presentation. Browser/static regression evidence is required to prove that the two existing buttons still send only `fcpxml` and `edl`, restore their labels after success/failure, and trigger only the URL returned for that request.

## 7. Security, privacy, and observability requirements

- **SEC-83-001 — Project confinement.** Resolve each OTIO source through the project's expected source area using the existing project-root helpers. Reject absolute DB paths, `..`, separator tricks, and symlinks whose resolved target escapes the project. Do not broaden direct media streaming or export allowlists beyond the two fixed OTIO artifacts.
- **SEC-83-002 — Untrusted text.** Treat labels, basenames, author names, kinds, and bodies as untrusted data. They must never select a path, adapter, format, XML tag, EDL event, logger format, or executable command. Tests include XML metacharacters, EDL-like newlines, control characters, path tokens, and script text.
- **SEC-83-003 — Dependency minimization.** Pin direct production dependencies exactly to `OpenTimelineIO==0.18.1`, `otio-fcpx-xml-adapter==1.0.0`, and `otio-cmx3600-adapter==1.0.0`, then refresh `uv.lock`. Do not add `OpenTimelineIO-Plugins`, AAF, burn-in, FCP7 XML, XGES, or unpinned Git dependencies. Any version change requires rerunning every automated and Resolve acceptance gate.
- **SEC-83-004 — No private fixtures.** Tests and artifacts use synthetic IDs, names, notes, and source stubs or consent-cleared generated media. Do not read, copy, log, commit, or mutate production media, private notes, credentials, `/mnt/user/appdata/autoedit`, or `/mnt/user/automulticam`.
- **SEC-83-005 — Auth unchanged.** Export generation and edit-media download remain authenticated and subject to current session/origin controls. No public route, signed URL, CORS change, or source-media browser playback is added.
- **OPS-83-001 — Structured export logs.** Log format/engine, project ID, exact FPS ratio, clip count, note count, adapter package versions, elapsed milliseconds, outcome, and safe error class. Do not log note text, author, source path, generated XML/EDL, cookies, or credentials.
- **OPS-83-002 — Failure classification.** Distinguish input/validation/path failures (safe 400), unavailable/misregistered adapter or invariant mismatch (safe 500), and filesystem publication failure (safe 500). API details remain concise and non-secret; full safe diagnostics go to logs.
- **OPS-83-003 — No infrastructure change.** The implementation adds Python image dependencies only. It adds no service, port, network, reverse-proxy route, device, volume, database migration, health-check change, GPU use, VAAPI/QSV change, Whisper/diarization change, or production configuration variable.

## 8. Failure behavior

| Failure | Required result |
|---|---|
| Existing direct request | Existing writer and response only; OTIO is not imported or called. |
| Unknown format | 400 listing the four accepted values without internal paths. |
| Invalid/empty CDL | Existing validator 400 with clip index; no output touched. |
| Missing/escaping source | Safe 400; no adapter call and no output touched. |
| Unsupported/malformed FPS | Safe 400; no decimal guess or nearest-rate fallback. |
| Out-of-program note | Safe 400 identifying note ID/time only; no silent drop/clamp. |
| Adapter missing or plugin name absent | Safe 500 for OTIO request; direct exports and app health continue to work. |
| Adapter changes shape/count/rate | Post-verifier fails closed; old verified output remains. |
| Marker cannot be mapped | Fail the whole OTIO export; never publish a marker-incomplete artifact. |
| Atomic write/replace fails | Remove temporary file, retain old output, log safe failure. |
| Same input repeated | Byte-identical output and same manifest/marker ordering. |
| Stage 7.4 still open | Implementation may be accepted as code, but backlog Stage 8.3 remains `in_progress`. |

## 9. Bounded implementation package and file ownership

One `autoeditprogrammer` project worktree can own the full implementation. It must begin from the coordinator-selected integration baseline, record the exact base SHA before editing, and carry only this package's diff.

Permitted product/dependency files:

- `src/autoedit/otio_export.py` — new canonical manifest, OTIO construction, adapter projection, normalization, verification, atomic writer.
- `src/autoedit/api.py` — add the two formats, fixed filenames/media allowlist, confined OTIO source/note loading, lazy call, safe error mapping/logging.
- `pyproject.toml`
- `uv.lock`

Permitted tests/fixtures:

- `tests/test_otio_export.py` — new pure conversion/adapter/normalizer/verifier coverage.
- `tests/test_otio_export_api.py` — new authenticated API/media/failure/compatibility coverage.
- `tests/fixtures/export/stage_8_3_cdl.json` and a small synthetic angle/note manifest if fixture reuse materially improves clarity. No binary/real media is required.
- `tests/test_security_smoke.py` only if the existing auth test must be parameterized for the new formats; do not broadly refactor it.
- `tests/test_player_static.py` or the existing direct Node/browser harness only for the UI-preservation assertion in UI-83-001; no product web file is permitted.

Files explicitly out of scope:

- `src/autoedit/edl_writer.py`
- `src/autoedit/fcpxml_writer.py`
- `src/autoedit/cdl_validator.py`
- `src/autoedit/cut_engine.py`
- `src/autoedit/web/index.html`, `player.js`, and CSS
- database/migration files
- Docker/Compose/deployment files
- production data/media

If implementation evidence proves a direct writer, validator, web file, schema, or deployment file must change, stop and return to Designer review instead of expanding the card.

Required implementation order:

1. Add exact dependencies and lock them; prove plugin names `fcpx_xml` and `cmx_3600` are discoverable.
2. RED tests for canonical shared-boundary frame manifest, deterministic order, exact NTSC rates, marker coordinates/text, adapter-shape rejection, and atomic preservation.
3. Implement the isolated OTIO module and make the focused tests green.
4. RED API/security tests for the two formats, fixed media allowlist, auth, confinement, failures, and unchanged direct dispatch.
5. Integrate the endpoint without touching direct writers or UI.
6. Run focused, export-wide, dependency/compile/diff, and full-suite gates.
7. Hand the exact SHA/diff/evidence to an independent Designer compliance card, then an independent Tester card. Do not deploy.

## 10. Test and acceptance requirements

- **TEST-83-001 — Dependency/registry gate.** Under the locked environment, assert exact package versions and discovered adapter names/suffixes. `uv lock --check` and `uv sync --frozen` must pass. Broad metapackage/unrequested adapters must be absent.
- **TEST-83-002 — Canonical manifest matrix.** Parameterize `24000/1001`, `25/1`, and `30000/1001` with adjacent clips, non-zero source offsets, same-angle adjacent clips, and long timelines. Assert positive durations, exact shared boundaries, exact source frames, and deterministic byte-for-byte manifest serialization.
- **TEST-83-003 — FCPXML contract.** Parse OTIO FCPXML and compare every resource, clip, offset, start, duration, sequence duration, and marker against the canonical manifest. Assert exact rational project rate, no gaps/overlaps, no forbidden paths, correct escaping, and byte-identical repeat output.
- **TEST-83-004 — EDL contract.** Parse OTIO EDL at the explicit nominal rate and compare all event/source/record frames, reel/clip identity, and LOC values against the canonical manifest/notes. Cover multiple same-frame notes, clip-boundary notes, NTSC rates, case preservation, control/newline injection, and byte-identical repeats.
- **TEST-83-005 — Negative/fail-closed coverage.** Cover invalid CDL, unknown angle, missing source, absolute/traversal/symlink escape, zero/unsupported rate, out-of-range note, adapter import failure, missing plugin, malformed adapter output, shape/count/rate mismatch, temporary-write failure, replace failure, and verifier failure. Assert no partial file and preservation of a seeded last-known-good output.
- **TEST-83-006 — API/media compatibility.** Authenticated requests for all four formats return the expected fixed format/path/URL; downloads return exact bytes. Unauthenticated generation/download is blocked. Unknown edit/temp files are blocked. Direct formats invoke only direct writers even when OTIO imports are forced to fail.
- **TEST-83-007 — Existing export regression.** Run `tests/test_edl.py`, `tests/test_export.py`, `tests/test_export_contiguity.py`, relevant security/media tests, and the new OTIO tests together. Existing direct golden assertions must remain unchanged and green.
- **TEST-83-008 — UI-preservation regression.** Static/Node/browser evidence confirms the existing buttons still send `fcpxml` and `edl`, retain accessible native button behavior, preserve loading/success/failure labels, and use only the returned authenticated URL. Test desktop and mobile DOM behavior only if the existing harness supports it; no screenshot is required because no visual change is permitted.
- **TEST-83-009 — Repository gates.** Run the canonical deterministic full suite `OLLAMA_BASE_URL='' LLM_MODEL='' env -u VIRTUAL_ENV uv run pytest -q -rs`, Python compile, `uv lock --check`, `uv sync --frozen --no-dev`, a Docker image build or equivalent frozen production dependency install, and `git diff --check`. Name every skip/failure; only the credential-gated central-MySQL skip is pre-authorized when credentials are absent.
- **TEST-83-010 — Independent compliance.** Designer must inspect the actual base/candidate SHAs, full diff, source, lockfile, tests, command outputs, generated synthetic artifacts, and every requirement ID. A summary is not evidence. Required verdict is `DESIGN_COMPLIANCE_PASS` before Tester acceptance.
- **TEST-83-011 — Independent Tester acceptance.** Tester independently regenerates synthetic outputs from the reviewed SHA, reruns focused/full gates, parses both outputs, verifies API/auth/media behavior, and records exact package versions and hashes. Required verdict is `TEST_PASS` before Peter's Resolve gate.
- **TEST-83-012 — Peter-only Resolve gate.** From the exact reviewed SHA, produce a consent-cleared/synthetic three-angle `24000/1001` package containing source files, canonical frame manifest, `export.otio.fcpxml`, and `export.otio.edl`. Peter imports both into the target Resolve build and records: populated timeline; expected clip count/order/angles; every cut on the manifest frame; sources found or relinkable by basename; no conform warning; no audio drift across the timeline; both note kinds and same-frame multiplicity visible at expected frames where the format/Resolve supports them. Record Resolve version, candidate SHA, artifact hashes, and screenshots or a concise screen recording without private media. If FCPXML markers are not imported, this must be reported truthfully; OTIO EDL LOC markers are the required Resolve marker-delivery gate.
- **TEST-83-013 — Stage dependency gate.** Stage 8.3 may be marked `done` only after Stage 7.4 has its independent exact-candidate `TEST_PASS`, every Stage 8.3 requirement has compliance evidence, Tester returns `TEST_PASS`, and Peter's Resolve gate passes. Until then, wording is “OTIO implementation accepted; Stage 8.3 closure pending,” not “done.”

Automated fixture characteristics:

- Three synthetic angle IDs/basenames, with at least one non-zero source offset.
- At least six contiguous cuts including repeated angles and boundaries that expose independent-rounding errors.
- Notes before a cut, exactly on a cut, two at the same frame, both kinds, mixed case, XML metacharacters, script text, Unicode, and EDL-looking newline/control probes.
- At least one note outside the program for fail-closed coverage.
- No original/private media or production identifiers.

## 11. Deployment and rollback

This design does not authorize deployment, publishing, container recreation, production export generation, or Unraid mutation.

A future explicit Publisher task must use the exact reviewed integration SHA and canonical deployment script. Deployment impact is a rebuilt app image with three pinned Python packages; Compose topology remains one host-networked app, central MySQL remains external, NPM remains the TLS boundary, `/data` remains the media mount, VAAPI `h264_vaapi` remains active, and Whisper/diarization remain mock-backed. Required deployment evidence includes backup/rollback tag, rendered Compose check, frozen image build, health/auth smoke, direct export regression, opt-in OTIO synthetic smoke, logs, and no production/private project use without explicit consent.

Rollback is restoration of the prior image/commit through the canonical deployment process. There is no DB rollback because no schema/data mutation is allowed. Existing direct and OTIO derived files are not authoritative; a failed new OTIO request must already preserve its last-known-good file through atomic publication.

## 12. Risks and non-goals

Risks and mitigations:

- Current adapter rational-rate behavior can drift at NTSC rates. Mitigation: canonical frame manifest, narrow temporal normalization, post-parse equality, three-rate tests, and `24000/1001` Resolve acceptance.
- Plugin output shape can change despite compatible dependency ranges. Mitigation: exact pins, direct package selection, shape verifier, byte determinism, and full reaccreditation on upgrades.
- CMX adapter uppercases marker names. Mitigation: deterministic LOC normalization from canonical note metadata, exact text/frame verification, and injection tests.
- An OTIO failure could regress working exports if imported globally. Mitigation: lazy isolated branch and direct-dispatch tests with forced OTIO failure.
- Note boundary or source-vs-record coordinates can move markers. Mitigation: absolute and clip-relative frame metadata plus boundary/same-frame/Resolve tests.
- A dirty `master` or wrong production lineage can produce misleading evidence. Mitigation: fresh project worktree, exact base/candidate SHAs, independent review, and no production claim from this design workspace.

Non-goals:

- No replacement or refactor of direct EDL/FCPXML writers.
- No default switch, automatic fallback, new export UI, or responsive visual change.
- No AAF, FCP7 XML, OTIO JSON download, multicam source stack, audio mix export, transitions, effects, LUT baking, or source-media browser playback.
- No CDL/schema/database/pipeline change.
- No Stage 7.4 repair or duplicate acceptance specification.
- No Whisper/diarization promotion, sync behavior change, manual sync workflow, QSV change, deployment, or production mutation.

## 13. Definition of closure

Stage 8.3 closes only when:

1. Both explicit OTIO formats are implemented from one canonical frame manifest without changing either direct path.
2. Every `ARCH-*`, `BACKEND-*`, `UI-*`, `SEC-*`, `OPS-*`, and `TEST-*` requirement above passes independent Designer compliance.
3. Automated evidence proves exact frame, source, marker, confinement, deterministic, atomic, failure, auth, and compatibility behavior.
4. Independent Tester returns `TEST_PASS` for the exact reviewed SHA.
5. Peter's Resolve evidence proves OTIO FCPXML imports populated with correct cuts/relink/rate and OTIO EDL imports with expected LOC markers.
6. Stage 7.4's independent exact-candidate acceptance is complete; until then, Stage 8.3 remains `in_progress` even if its implementation is otherwise accepted.
7. Production remains unchanged unless a separate explicit deployment task is approved.

DESIGN_APPROVED
