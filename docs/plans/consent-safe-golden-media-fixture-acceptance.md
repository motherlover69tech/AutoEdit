# Consent-Safe Golden Media Fixture Acceptance

**Status:** `DESIGN_APPROVED`
**Scope:** design and acceptance contract only; no product code, tests, private-media movement, live GPU execution, publishing, or deployment
**Consumes:** `docs/plans/ai-gpu-1-acceptance-gates.md`
**Production constraint:** `WHISPER_BACKEND=mock` and `DIARIZE_BACKEND=mock` remain unchanged

## 1. Decision and boundary

AUTOEDIT needs two deliberately different fixture classes:

1. A deterministic, non-identifying `synthetic_contract` fixture exercises schema, sync, frame-grid, activity, cut, proxy, and export contracts in the ordinary test suite. It may be generated or tracked and can satisfy the source specification's small approximately 30-second three-angle test need. It cannot establish ASR quality, audible word truth, human identity, diarization quality, or editorial acceptance.
2. A `consent_real` fixture set remains outside Git under a root selected only through `AUTOEDIT_GOLDEN_MEDIA_ROOT`. It provides the hash-bound real evidence required by AI-GPU-1. One excerpt may serve the bounded four-gate acceptance only if it contains all required cases; the broader release benchmark still requires at least three 3–10 minute excerpts.

The smallest accepted private fixture package consists of three JSON files plus the referenced media:

- `fixture.manifest.json` — rights/retention status, exact file identities, technical shape, project FPS, automatic sync facts, and derivation provenance;
- `ground_truth.json` — locked word, speaker, activity, overlap/silence, camera, uncertainty, and label-swap annotations; and
- `approvals.json` — Peter's decisions bound to the exact byte hashes of the first two files.

Per-run outputs are evidence, not fixture inputs, and live beneath a separate private `runs/` directory. No candidate output may rewrite the locked fixture package.

This specification does not repeat the confirmation UI, activity projection, cut integration, or GPU/Dots implementation already owned by `docs/plans/ai-gpu-1-acceptance-gates.md` and blocked Programmer card `t_bcee0e44`. It supplies the missing fixture/evidence contract those seams consume.

## 2. Facts, assumptions, unknowns, and decisions

### 2.1 Verified facts

- `AI_HANDOFF.md` and `jobs/BACKLOG.md` report no accepted real golden fixture; ordinary media tests use mocked ffprobe data and NumPy-generated audio.
- `tests/fixtures/golden_interview/` is a tracked metadata-only scaffold. Its three expected JSON files are `not_labeled` and must not pass acceptance.
- `docs/ai/real-media-phase0-baseline.json` records a privacy-safe aggregate for one local three-source fixture, but exact paths, hashes, durations, offsets, identities, transcript content, and evidence timestamps remain private.
- No `tests/integration/test_whisperx_golden_media.py` exists. The command in the testing strategy and AI plans is planned, not runnable coverage.
- The approved AI-GPU-1 plan requires a current immutable worker result, one-project-frame word timing, operator-confirmed speaker identity, locked editorial windows, safe-wide outcomes, and hash-bound evidence.
- The current source contracts use strict integer milliseconds on `program_audio_master` and SHA-256 source/analysis identities.
- The source specification asks for a tiny approximately 30-second three-angle clapper fixture, while the real-AI roadmap requires external 3–10 minute consent-cleared interview excerpts. One fixture class cannot honestly satisfy both purposes.
- The repository ignores `testmedia/`, but an ignore rule alone is not a privacy boundary.
- The base Compose deployment remains one host-networked app behind NPM with central MySQL, `/mnt/user/automulticam:/data`, VAAPI `h264_vaapi`, and explicit mock speech/diarization. The opt-in worker is loopback-only and reads `/data` read-only.
- Profile preflight for this Designer run found `openai-codex` / `gpt-5.6-sol`, no fallback providers, MoA disabled, all auxiliary categories pinned to the same route, and a fresh live response of `ROUTE_OK`. OpenRouter was not used.

### 2.2 Assumptions to validate, not treat as evidence

- A consent-cleared excerpt can be bounded without changing the source files.
- At least two independently addressable speaker audio channels and three synchronized camera angles are available for the selected real fixture.
- Peter can confirm consent/right-to-use, identify both voices, approve the audible word marks, and lock expected camera treatment.
- The selected real excerpt can represent every AI-GPU-1 Gate 3 category, or Peter can approve an additional excerpt.
- A trusted-host path can be made readable to the validator and later worker without becoming readable through NPM or the normal app container.

A false assumption blocks real-fixture readiness. It is never replaced with a synthetic pass.

### 2.3 Unknowns

- The exact trusted fixture root, owner/group/ACL, backup treatment, and capacity.
- The exact consent and licensing records, their scope, expiry/review dates, and withdrawal procedure.
- Which private media revision Peter will approve and its current hashes.
- Whether one excerpt has all mandatory word, overlap, silence/noise, bleed, short-interruption, off-camera/uncertain, and two-speaker windows.
- The final automatic sync offsets, project FPS rational, frame-grid annotations, and locked expected cameras for that excerpt.
- Whether the broader three-excerpt benchmark may reuse the bounded AI-GPU-1 excerpt.

### 2.4 Peter-only decisions

Peter alone must:

1. select the exact media revision and trusted storage root;
2. attest consent and right-to-use for automated speech/diarization/editorial evaluation, derived snippets, and retained evidence;
3. choose retention/review/delete dates and backup treatment consistent with those rights;
4. confirm the two opaque stable speaker identities and their existing close-camera roles;
5. approve or reject each selected audible word boundary;
6. approve the locked expected activity/camera treatment for every editorial window; and
7. approve or reject the later candidate cut per window.

Agents may validate, hash, probe, calculate, redact, and present choices. Agents must not infer consent, license, identity, or editorial truth from transcript text, filenames, mic levels, anonymous label ordering, or LLM output.

No unresolved decision prevents this design from being approved. It prevents a private package from reaching `accepted` and therefore blocks live evidence execution.

## 3. Requirement catalogue

### Architecture

- **ARCH-GOLD-001:** Fixture classes are explicit: `synthetic_contract` and `consent_real`. Synthetic evidence cannot satisfy a real-media or Peter-decision gate.
- **ARCH-GOLD-002:** `AUTOEDIT_GOLDEN_MEDIA_ROOT` is the only selector for external real fixtures. Absence causes a clean trusted-host test skip; it never downloads, guesses, scans production projects, or falls back to bundled media.
- **ARCH-GOLD-003:** A real fixture is immutable once accepted. Candidate runs write only to a separate run root and cannot alter media, manifest, ground truth, or approvals.
- **ARCH-GOLD-004:** Every media and annotation time uses strict integer milliseconds on the program-audio master timeline. Automatic cross-correlation offsets are recorded and applied exactly once; no manual sync adjustment is introduced.
- **ARCH-GOLD-005:** Project rate is an exact positive `fps_num/fps_den` rational. Editorial transition annotations store both an integer `frame_index` and its canonical integer-ms projection; audible word boundaries remain unsnapped integer ms and use the exact one-frame rational as tolerance.
- **ARCH-GOLD-006:** Fixture identity is content-bound by SHA-256 at each media file and by byte hashes for `fixture.manifest.json` and `ground_truth.json`. Peter approvals reference both document hashes.
- **ARCH-GOLD-007:** The fixture contract is read-only input to the already-approved AI-GPU-1 gates. Existing VAD baseline, selected cut, source media, program audio, proxies, and versioned AI artifacts retain their own authority and immutability rules.
- **ARCH-GOLD-008:** Production app, central MySQL, NPM, VAAPI, program-audio-master playback, silent-proxy behavior, FCPXML, and mock backend defaults are outside the fixture package and unchanged.

### Backend and data contracts

- **BACKEND-GOLD-001:** `fixture.manifest.json` validates against a strict versioned model with unknown fields rejected and no coercion of booleans, floats, or numeric strings into integer fields.
- **BACKEND-GOLD-002:** A `consent_real` manifest references exactly three video assets with unique roles `close_1`, `close_2`, and `wide`; each path is relative and confined, each file hash/size/probe result is locked, and their overlapping master-timeline coverage includes every annotated window.
- **BACKEND-GOLD-003:** Each real video asset records codec, width, height, exact stream FPS, duration, and audio-stream layout. Acceptance expects the project shape of three 1920x1080 H.264 angles unless Peter explicitly records a source-spec variance; a variance cannot silently satisfy proxy/export claims tied to 1080p H.264.
- **BACKEND-GOLD-004:** The audio map contains exactly two accepted, independently addressable speaker channels for the bounded two-person gate, each with source asset ID, channel index, opaque stable speaker ID, sample rate, duration, and integer automatic sync offset. It does not infer identity from channel/angle order.
- **BACKEND-GOLD-005:** The manifest locks `program_audio` and `analysis_audio` identities and derivation provenance where those derivatives are inputs to review or inference. Proxies are silent, and no source-media browser URL is part of the fixture contract.
- **BACKEND-GOLD-006:** `ground_truth.json` references the exact manifest hash, fixture ID/revision, project rate, timeline basis, and timeline bounds; mismatch is stale input, not a warning.
- **BACKEND-GOLD-007:** Word truth includes opaque segment/word IDs, private token text or a private token digest as rights permit, reviewed start/end ms, boundary uncertainty/rejection reason, timeline-third selection, and anonymous voice-cluster association where available. At least the first/middle/final three-word protocol can be selected without inspecting model error.
- **BACKEND-GOLD-008:** Speaker truth uses opaque stable speaker IDs separate from names, camera labels, mic channels, and diarizer labels. Identity approval binds each stable speaker to an existing close-camera role; anonymous label swaps are represented as a test transformation, not as new identities.
- **BACKEND-GOLD-009:** Activity truth is ordered and non-overlapping and represents solo speech, overlap, silence/noise, unresolved/low-confidence/off-camera treatment, and confidence/uncertainty. It must either cover the labelled evaluation span contiguously or declare every intentionally unlabelled gap.
- **BACKEND-GOLD-010:** Each locked editorial review window has a category, start/end frame index and canonical ms, expected active opaque speaker IDs, expected camera role, expected reason/safety outcome, uncertainty status, and one-frame transition policy.
- **BACKEND-GOLD-011:** The bounded real fixture includes both speakers and at least one certain window for solo speaker 1, solo speaker 2, alternation in both directions, true overlap, short acknowledgement/interruption, bleed/unequal levels, laughter/cough/room noise or silence, and unresolved/low-confidence/off-camera speech. Missing coverage blocks readiness or requires another consent-cleared excerpt.
- **BACKEND-GOLD-012:** `approvals.json` contains independent decisions for consent/right-to-use, retention/backup, speaker identity, word truth, and locked editorial truth. Each decision records status, UTC time, opaque operator ID, scope, manifest hash, ground-truth hash where applicable, and optional non-content reason code.
- **BACKEND-GOLD-013:** `approvals.json` cannot approve itself. The accepted bundle ID is `SHA256(uint64_be(manifest_length) || manifest_bytes || uint64_be(ground_truth_length) || ground_truth_bytes)` over the exact files; approval records bind to that bundle ID.
- **BACKEND-GOLD-014:** Candidate results, baseline artifacts, browser evidence, and Peter's later per-window candidate verdict live in `runs/<opaque-run-id>/` and reference the accepted bundle ID. They are never copied into `ground_truth.json` after candidate generation.
- **BACKEND-GOLD-015:** Validator output uses bounded machine-readable error codes and redacted messages. It never emits transcript text, names, absolute private paths, media hashes, snippets, consent-record details, or credentials.
- **BACKEND-GOLD-016:** An accepted fixture cannot be automatically upgraded across schema versions. Migration creates a new revision, recomputes hashes, reruns validation, and requires fresh affected approvals.

### UI, review, responsive, and accessibility

- **UI-GOLD-001:** No new public product screen is required by this package. Fixture readiness is exposed only to authenticated/local acceptance tooling and the existing AI-GPU-1 confirmation/review surfaces.
- **UI-GOLD-002:** Readiness has explicit states: `not configured`, `draft`, `consent pending`, `annotation pending`, `invalid/tampered`, `expired/revoked`, `stale`, and `accepted`. `not_labeled` placeholders render as incomplete and cannot show success.
- **UI-GOLD-003:** The existing player presents bounded `program.m4a` ranges with silent proxies for word/editorial review. It never requests source media, never reloads program audio for an angle switch, and explains that fixture review does not change sync.
- **UI-GOLD-004:** Review controls show opaque IDs, category, time/frame range, expected/actual role, uncertainty, and decision. Names, transcript excerpts, absolute paths, and hashes are omitted from retained screenshots and normal status views.
- **UI-GOLD-005:** Approval is never preselected or inferred. Peter must explicitly choose pass/fail (and mapping where owned by AI-GPU-1), with the action disabled for stale hashes, missing coverage, invalid annotations, or incomplete rights status.
- **UI-GOLD-006:** Fixture/review status is keyboard operable with native labels/buttons, visible focus, textual status plus color, live-region error/status announcements, reduced-motion support, and no time-limited interaction.
- **UI-GOLD-007:** At widths at or below 840 px, review rows become one column, ranges and decisions remain visible without horizontal scrolling, and nonessential technical detail may collapse. Private media is not used in a shared/mobile screenshot artifact.
- **UI-GOLD-008:** Invalid, revoked, expired, tampered, or stale fixtures show a fail-closed explanation and recovery action; they never retain a green/accepted badge from an earlier revision.

### Operations and observability

- **OPS-GOLD-001:** Fixture implementation and validation begin with read-only discovery of the selected root, filesystem type, capacity, owner/group/ACL, backup policy, mount visibility, Compose topology, and current mock backend values without printing secrets or content.
- **OPS-GOLD-002:** The exact real root is never hard-coded in source, tracked docs, Kanban, or logs. `AUTOEDIT_GOLDEN_MEDIA_ROOT` is supplied only in the trusted process environment.
- **OPS-GOLD-003:** Recommended external layout is `<root>/fixtures/<opaque-fixture-id>/` for immutable packages and `<root>/runs/<opaque-run-id>/` for disposable evidence. The root must not be inside a Git worktree, Docker build context, normal app writable data, or `/mnt/user/appdata/autoedit`.
- **OPS-GOLD-004:** Any later container access mounts the accepted fixture directory read-only and the run directory separately writable. The fixture root is not mounted into the public app unless a separately approved acceptance design proves it necessary.
- **OPS-GOLD-005:** Validation records schema/tool version, fixture class/revision, opaque bundle ID, file/count summaries, FPS rational, category coverage, and pass/fail error codes. It does not retain source hashes or private content in tracked evidence.
- **OPS-GOLD-006:** The validator recomputes file hashes with streaming reads, reprobes media with a pinned/documented ffprobe version, and compares exact technical facts before any GPU or browser gate begins.
- **OPS-GOLD-007:** Expiry, revocation, retention review due, changed bytes, changed probe facts, changed annotations, changed approvals, project-rate mismatch, or automatic-offset mismatch invalidates readiness before inference.
- **OPS-GOLD-008:** Cleanup is explicit and scoped. Validation never deletes. A separately authorized cleanup may remove only named run derivatives after evidence closure; source fixture deletion follows Peter's rights/retention decision and must not touch production projects.
- **OPS-GOLD-009:** Backups, if authorized, inherit the same classification, encryption/access, expiry, and deletion obligations. A restored fixture must reproduce every locked hash or be treated as a new revision.
- **OPS-GOLD-010:** The ordinary test suite remains self-contained, makes no network calls, does not inspect Unraid or production, and does not require `AUTOEDIT_GOLDEN_MEDIA_ROOT`.
- **OPS-GOLD-011:** This fixture package does not deploy or modify Compose. A later AI-GPU-1 acceptance run may consume it only after independent compliance, Peter authorization, and read-only infrastructure discovery.
- **OPS-GOLD-012:** Rollback from validator/harness implementation is code/schema rollback plus retention of the private immutable fixture. Rollback from a failed acceptance run is deletion/quarantine of only that run output, continued mock backends, and preservation of prior artifacts/cuts.

### Security, consent, licensing, privacy, retention, and redaction

- **SEC-GOLD-001:** A real fixture is usable only when Peter attests active participant consent and a valid rights basis for the exact media revision and the purposes `speech_recognition_evaluation`, `speaker_diarization_evaluation`, `speaker_identity_confirmation`, `editorial_cut_evaluation`, and bounded derived evidence.
- **SEC-GOLD-002:** Rights metadata records an opaque consent-record reference, rights basis, allowed purposes, derivative/snippet allowance, model-processing allowance, redistribution prohibition/allowance, approval/review/expiry dates, and withdrawal status. The underlying signed records and names remain outside the fixture JSON and Git.
- **SEC-GOLD-003:** Consent or license status `pending`, `denied`, `revoked`, `expired`, or purpose-incomplete blocks acceptance. Revocation invalidates all later runs immediately and triggers the separately authorized deletion/quarantine procedure.
- **SEC-GOLD-004:** Retention metadata must contain a rights review date and explicit disposition for raw media, annotations, per-run derived media, machine JSON, and backups. Missing or overdue retention decisions block use; the validator does not invent a duration.
- **SEC-GOLD-005:** Per-run playable snippets and screenshots are ephemeral by default and receive a private `delete_by_utc` no later than 30 days after final gate closure unless Peter records a narrower or explicitly justified longer rights-compatible period. Aggregate redacted summaries may be retained with project documentation.
- **SEC-GOLD-006:** Classification is enforced: tracked schemas/synthetic data/redacted aggregates are `PUBLIC_SAFE`; exact hashes, paths, timestamps, and operational records are `PRIVATE_METADATA`; raw media, program/analysis audio, snippets, transcript content, identity evidence, and screenshots are `RESTRICTED_MEDIA`; credentials, tokens, cookies, and signed consent/license records are `SECRET_OR_LEGAL`.
- **SEC-GOLD-007:** `PRIVATE_METADATA`, `RESTRICTED_MEDIA`, and `SECRET_OR_LEGAL` never enter Git, Kanban text, build contexts, test reports, pytest node IDs/parameter reprs, browser artifacts, or public logs. Kanban receives only opaque IDs, counts, status, aggregate errors, and non-media candidate/tool digests.
- **SEC-GOLD-008:** Real assets and manifests use confined relative paths. Absolute paths, `..`, backslashes, device files, FIFOs, hard links outside the root, and symlinks at any component are rejected before read or probe.
- **SEC-GOLD-009:** The trusted root is not world-readable/writable. Access is limited to Peter and the explicitly approved test/service identity; actual UID/GID/ACL is discovered rather than guessed.
- **SEC-GOLD-010:** No validator or test downloads media, dereferences URLs, shells unquoted path content, embeds private paths in ffmpeg/ffprobe error output, or copies media into a worktree/container layer.
- **SEC-GOLD-011:** Annotation text is minimized. Stable speakers, cameras, words, segments, and turns use opaque IDs. Transcript token text exists privately only when required for WER/word selection and permitted by rights; tracked evidence uses IDs and numeric errors only.
- **SEC-GOLD-012:** Browser/API access used for Peter review remains authenticated and same-origin. Cross-project/run/fixture references and stale bundle IDs are rejected. The fixture root is never routed through NPM.
- **SEC-GOLD-013:** A privacy scan covers staged, unstaged, untracked, and Docker/package contexts for media extensions, absolute trusted paths, transcript excerpts, names, source hashes, and consent details before review. It reports locations, not leaked values.
- **SEC-GOLD-014:** OpenRouter is forbidden for fixture selection, annotation, transcription, review, summarization, or evidence processing. No external AI service receives private media or annotations under this package.

### Tests and acceptance evidence

- **TEST-GOLD-001:** Unit tests validate strict schemas, unknown-field rejection, integer typing, safe IDs, enum values, UTC timestamps, relative paths, and manifest/ground-truth/approval hash binding.
- **TEST-GOLD-002:** Tamper tests mutate each source class, manifest bytes, ground-truth bytes, approval reference, bundle ID, and probe fact and require deterministic non-zero rejection before inference.
- **TEST-GOLD-003:** Staleness tests cover revoked/expired consent, overdue rights review, purpose mismatch, retention missing/overdue, annotation revision mismatch, schema mismatch, project FPS mismatch, changed automatic offset, and restored-file hash drift.
- **TEST-GOLD-004:** Filesystem tests cover root escape, intermediate/final symlink, absolute path, traversal, hard-link policy, special file, unreadable file, duplicate file reference, and case-collision behavior without writing outside temporary roots.
- **TEST-GOLD-005:** Shape tests require exactly three unique camera roles, exact FPS consistency, bounded durations, two accepted audio channels, unique stable speakers/cameras, valid channel indices, program/analysis derivation references, and complete annotated-window source coverage.
- **TEST-GOLD-006:** Frame tests use 24/1, 25/1, 30000/1001, and 24000/1001. Review-window `frame_index` and canonical ms must round-trip through AUTOEDIT's shared frame helpers; word boundaries must remain unsnapped integer ms with exact rational tolerance calculation.
- **TEST-GOLD-007:** Annotation tests cover ordered/bounded words, deterministic first/middle/final selection, both anonymous clusters where available, boundary uncertainty, locked-before-candidate status, and no cherry-picking by model error.
- **TEST-GOLD-008:** Activity/camera truth tests cover solo speaker 1, solo speaker 2, both alternation directions, true overlap, short acknowledgement, bleed/unequal levels, noise/laughter/cough/silence, unresolved/low-confidence/off-camera, expected safe-wide outcomes, and contiguous/declared-gap rules.
- **TEST-GOLD-009:** Label-swap tests exchange anonymous diarizer IDs while stable opaque speakers and expected cameras remain unchanged only through current voice revalidation or fresh Peter confirmation. Transcript/LLM context alone cannot pass.
- **TEST-GOLD-010:** A fixed-seed `synthetic_contract` generator produces three short H.264-compatible test angles or deterministic stand-ins, a clapper/transient, two known audio channels, positive/negative offsets, overlap/silence/label-swap annotations, and locked expected activity/CDL. Generator version/arguments and expected hashes are test-controlled; no network or real person is used.
- **TEST-GOLD-011:** Synthetic tests exercise sync, proxy command/output contract, program-audio timing, source bounds, activity, safe-wide cut reasons, CDL/frame validation, and export structure. They explicitly assert that their result is ineligible for real ASR/identity/editorial acceptance.
- **TEST-GOLD-012:** `tests/integration/test_whisperx_golden_media.py` cleanly skips only when `AUTOEDIT_GOLDEN_MEDIA_ROOT` is absent. If the variable is present, missing/invalid/incomplete/private-package input fails rather than skips.
- **TEST-GOLD-013:** Trusted-host validation has a `validate-only` path that performs rights, hash, probe, schema, annotation, coverage, staleness, and privacy checks without starting containers, invoking a model, changing a project, or writing outside a named run directory.
- **TEST-GOLD-014:** The full trusted-host path consumes the accepted bundle and existing AI-GPU-1 seams; it records exact candidate source commit/image/model/tool versions privately and emits only a redacted summary. A fixture-ready result is not an AI-GPU-1 pass.
- **TEST-GOLD-015:** Peter decisions are directly captured for consent/license/retention, both opaque identities, all selected word boundaries, all locked expected windows, and later candidate windows. Missing, stale, agent-inferred, or blanket approval fails the affected gate.
- **TEST-GOLD-016:** Candidate expected/actual comparison checks activity coverage, camera/reason result, one-frame transition allowance, zero wrong-close-up safety frames, complete reason metadata, persistence, player sync, silent-proxy/source-network behavior, and immutable VAD/selected-cut baselines as required by `TEST-AIGPU1-004`.
- **TEST-GOLD-017:** Failure evidence is redacted and bounded. Tests inject transcript text, names, absolute roots, source hashes, tokens, and media-like payloads into errors and prove retained summaries contain none of them.
- **TEST-GOLD-018:** Before handoff, run focused schema/validator/synthetic tests, the mock-isolated full suite, compile, changed-file lint/static checks where configured, lock validation, privacy scan, `git diff --check`, and independent Designer compliance on the exact candidate.

## 4. Storage and package layout

The exact root is a Peter decision and is intentionally absent from tracked configuration. The layout contract is:

```text
$AUTOEDIT_GOLDEN_MEDIA_ROOT/
  fixtures/
    <opaque-fixture-id>/
      fixture.manifest.json
      ground_truth.json
      approvals.json
      media/
        close_1.<container>
        close_2.<container>
        wide.<container>
      derived/
        program_audio.<container>
        analysis_audio.wav
  runs/
    <opaque-run-id>/
      run.manifest.json
      baseline/
      candidate/
      browser/
      logs/
      summary.private.json
      summary.redacted.json
```

Rules:

- File names above are role names, not original/private names.
- `derived/` is optional until those hashes are needed; any derivative is reproducible from locked source/configuration or explicitly marked externally produced.
- `fixtures/<id>/` becomes read-only at acceptance. A revised file creates a new opaque fixture revision/directory.
- `runs/<id>/` is writable and disposable under the retention decision.
- Local developer experiments remain under ignored `testmedia/`, but no `testmedia/` content counts as accepted merely because it is ignored.
- The production application directory, production database, and normal project source directories are not fixture stores.

### 4.1 Access and backup

Implementation must discover and report only whether ACL/ownership is compliant, not the identities or path. At minimum:

- no world read/write;
- no public-app/NPM visibility;
- accepted fixture mounted read-only if a container must consume it;
- separate writable run root;
- backup either disabled by explicit Peter decision or protected by equivalent access/encryption/retention;
- restore verification rehashes all bytes before use.

## 5. Minimal private schema package

The exact Pydantic/JSON Schema definitions belong to the implementation package. These field sets are normative.

### 5.1 `fixture.manifest.json`

Required top-level fields:

```text
schema_version: "1.0"
fixture_id: opaque SafeId
revision: positive integer
fixture_class: "consent_real" | "synthetic_contract"
status: "draft" | "locked" | "revoked"
created_at_utc, locked_at_utc
classification: fixed classification map
rights: RightsStatus
retention: RetentionPolicy
project: ProjectTimeline
video_assets: exactly 3 VideoAsset
speaker_audio_channels: exactly 2 accepted AudioChannel for bounded real gate
program_audio: optional DerivedAsset
analysis_audio: optional DerivedAsset
annotation_relative_path: "ground_truth.json"
```

`RightsStatus` includes opaque legal-record reference, consent/license status, rights basis, allowed-purpose set, derivative/snippet/model flags, redistribution flag, approval/review/expiry UTC dates, and withdrawal status. No participant names or signed records are embedded.

`ProjectTimeline` includes `fps_num`, `fps_den`, `timeline_origin_ms`, `timeline_end_ms`, `sync_offset_convention="source_ms=master_ms+sync_offset_ms"`, and master-audio role.

Each `VideoAsset` includes opaque asset ID, one role, confined relative path, byte size, SHA-256, video codec/width/height/FPS/duration, audio stream/channel layout, master coverage, and probe tool/version.

Each `AudioChannel` includes opaque channel ID, source asset ID, stream/channel index, sample rate, duration, opaque stable speaker ID, and automatic integer sync offset plus measurement-artifact reference. It does not contain a person name.

Each `DerivedAsset` includes role, confined path, size/hash/probe shape, source asset/channel IDs, exact derivation command/config digest, tool versions, and whether it is immutable fixture input or disposable run output.

### 5.2 `ground_truth.json`

Required top-level fields:

```text
schema_version: "1.0"
fixture_id, fixture_revision
manifest_sha256
annotation_revision
status: "draft" | "locked"
created_at_utc, locked_at_utc
timeline_basis: "program_audio_master"
fps_num, fps_den, timeline_origin_ms, timeline_end_ms
stable_speakers[]
word_boundaries[]
activity_segments[]
review_windows[]
label_swap_cases[]
coverage_summary
```

A `stable_speaker` contains only opaque speaker ID and close-camera role. Actual person identity remains in Peter's external consent/identity record.

A `word_boundary` contains opaque segment/word IDs, optional private token/token digest, reviewed start/end ms, uncertainty, reviewer decision/reason, timeline third, anonymous cluster ID if known, and source selection status. Candidate/model times are forbidden in locked truth.

An `activity_segment` contains start/end ms, active stable speaker IDs, overlap/silence/uncertain/off-camera flags, and ground-truth confidence state. Gaps must be declared as `unlabelled`, never silently absent.

A `review_window` contains category, start/end frame indices and canonical ms, expected active IDs, expected camera role, expected reason/safety class, transition tolerance frames fixed at one, and uncertainty. Expected output is locked before candidate generation.

A `label_swap_case` declares only the deterministic anonymous-label permutation and expected stable-ID/camera invariants. It does not claim that old anonymous ordering is identity evidence.

### 5.3 `approvals.json`

Required top-level fields:

```text
schema_version: "1.0"
fixture_id, fixture_revision
manifest_sha256
ground_truth_sha256
bundle_id
approval_revision
rights_and_consent_decision
retention_and_backup_decision
speaker_identity_decisions[]
word_truth_decisions[]
editorial_truth_decisions[]
overall_fixture_decision
```

Every decision includes `decision=PASS|FAIL|REVOKED`, UTC time, opaque operator ID, exact scope, bound hashes, and an optional enum reason. Free text is private and bounded; tracked summaries retain only reason codes.

`overall_fixture_decision=PASS` is valid only when every required subordinate decision passes and the validator independently verifies the referenced bytes. A later candidate editorial verdict belongs to a run record, not this file.

## 6. Validation lifecycle

### 6.1 Draft

1. Peter selects media and rights scope outside Git.
2. An agent creates only the private package with opaque IDs and confined role paths.
3. The validator performs read-only schema/path/hash/probe/shape checks.
4. Ground truth is labelled without candidate output visible.
5. Missing or uncertain truth is explicit.

### 6.2 Lock

1. Set manifest and truth status to `locked` and write immutable bytes.
2. Compute exact document SHA-256 values and bundle ID.
3. Peter records bound approvals.
4. Re-run validation from a fresh process.
5. Make fixture package read-only; record only an opaque accepted ID and aggregate coverage externally.

### 6.3 Pre-run

The harness must recheck:

- rights/retention active;
- no symlink/path escape;
- every source/derivative hash and probe fact;
- project FPS, timeline, source coverage, and automatic offsets;
- manifest/truth/approval bindings;
- required cases and Peter decisions;
- candidate source/image/model/tool identifiers; and
- production mock state when the later acceptance task reaches infrastructure.

Any difference is `STALE_OR_TAMPERED` and blocks the run.

### 6.4 Post-run

- Write only beneath the named run directory.
- Preserve locked ground truth and VAD baseline.
- Compare expected/actual after candidate generation.
- Peter records per-word/per-window candidate decisions.
- Emit private and redacted summaries separately.
- Set and enforce derivative retention dates in a later explicit cleanup task.

## 7. Error and failure contract

| Code | Meaning | Required behavior |
|---|---|---|
| `GOLD_ROOT_NOT_CONFIGURED` | env absent | clean trusted-host skip only |
| `GOLD_ROOT_UNSAFE` | permissions/root/mount policy fails | stop before content read where possible |
| `GOLD_PATH_ESCAPE` | absolute/traversal/link/special file | reject; no external read/write |
| `GOLD_RIGHTS_NOT_ACTIVE` | pending/expired/revoked/purpose missing | reject; no inference |
| `GOLD_RETENTION_NOT_ACTIVE` | review/delete/backup decision missing or overdue | reject |
| `GOLD_SCHEMA_INVALID` | strict schema/type/version failure | reject with redacted field path |
| `GOLD_HASH_MISMATCH` | source or document bytes changed | reject as tampered/stale |
| `GOLD_PROBE_MISMATCH` | media shape changed | reject; new revision required |
| `GOLD_PROJECT_MISMATCH` | FPS/timeline/offset differs | reject; never nudge sync |
| `GOLD_ANNOTATION_INCOMPLETE` | words/speakers/windows/categories missing | reject real readiness |
| `GOLD_APPROVAL_MISSING` | required Peter decision absent/stale | reject affected gate |
| `GOLD_PLACEHOLDER_ONLY` | `not_labeled` scaffold supplied | reject real readiness |
| `GOLD_SYNTHETIC_INELIGIBLE` | synthetic offered for human/live gate | reject that gate while ordinary tests may pass |
| `GOLD_PRIVATE_OUTPUT_LEAK` | summary/log contains disallowed data | fail evidence retention and quarantine output |

A failure never changes production backend defaults, source media, program audio, selected cuts, or last-known-good AI artifacts.

## 8. Automated verification design

Recommended implementation ownership:

```text
src/autoedit/ai/golden_fixture.py
  strict Pydantic contracts, bundle hashing, redacted validator result
scripts/validate-golden-fixture.py
  thin CLI; validate-only by default; no model/container side effects
tests/test_golden_fixture_contracts.py
  schema, path, hash, rights, retention, staleness, redaction tests
tests/test_golden_fixture_synthetic.py
  deterministic generated fixture and expected activity/CDL tests
tests/integration/test_whisperx_golden_media.py
  external-root gate and later AI-GPU-1 consumer
tests/fixtures/golden_interview/README.md
  tracked boundary and exact commands
tests/fixtures/golden_interview/schemas/*.schema.json
  generated/checked schemas only
tests/fixtures/golden_interview/synthetic/*
  public-safe generator config/expected metadata only
docs/ai/whisperx-evaluation-protocol.md
  narrow references to this policy and runnable commands
docs/plans/TESTING_STRATEGY.md
  truthful coverage status after implementation
```

The implementation should use existing Pydantic and frame helpers rather than introduce a schema library or duplicate frame math. If JSON Schema files are committed, tests regenerate and byte-compare them to the Pydantic source of truth.

Planned commands after these files exist:

```bash
# Safe, self-contained contracts and synthetic behavior.
OLLAMA_BASE_URL='' LLM_MODEL='' env -u VIRTUAL_ENV uv run pytest -q \
  tests/test_golden_fixture_contracts.py \
  tests/test_golden_fixture_synthetic.py

# Trusted-host validation only. No GPU/model/browser side effect.
AUTOEDIT_GOLDEN_MEDIA_ROOT='<private root>' \
  env -u VIRTUAL_ENV uv run python scripts/validate-golden-fixture.py \
  --fixture-id '<opaque id>' --validate-only --redacted-summary '<private run path>'

# Trusted-host consumer; absence of root is the only clean skip.
AUTOEDIT_GOLDEN_MEDIA_ROOT='<private root>' \
  OLLAMA_BASE_URL='' LLM_MODEL='' env -u VIRTUAL_ENV uv run pytest -q \
  tests/integration/test_whisperx_golden_media.py

# Broad mock-isolated gates.
OLLAMA_BASE_URL='' LLM_MODEL='' env -u VIRTUAL_ENV uv run pytest -q -rs
env -u VIRTUAL_ENV uv run python -m compileall -q src tests
uv lock --check
git diff --check
```

The trusted integration test must have separable markers or phases so fixture validation can run without starting the worker. Missing real media cannot become an unconditional suite failure, but a configured invalid root must fail.

## 9. Reconciliation with AI-GPU-1 and `t_bcee0e44`

This plan refines AI-GPU-1 Package A only. It does not reopen Packages B–D.

| Fixture requirement | Existing AI-GPU-1 consumer |
|---|---|
| accepted bundle/hash/probe/FPS/offset | `BACKEND-AIGPU1-001/002`, Gate 1 shared entry |
| three selected locked words | `TEST-AIGPU1-002`, Gate 1 |
| opaque stable speakers and bound identity truth | `BACKEND-AIGPU1-003/007`, Gate 2 |
| overlap/silence/label-swap/uncertainty truth | `TEST-AIGPU1-003/004`, Gates 2–3 |
| locked expected activity/camera/reason windows | `BACKEND-AIGPU1-004/005`, Gate 3 |
| private run layout/redacted summary | `SEC-AIGPU1-001/005`, `TEST-AIGPU1-007` |
| deterministic synthetic substitutes | `TEST-AIGPU1-008` and ordinary mock suite |
| tamper/staleness rejection | `ARCH-AIGPU1-003`, `SEC-AIGPU1-004` |

The current blocked Programmer card already added preliminary safe-wide/activity and GPU-summary code. It did not create this fixture contract, trusted-host integration test, confirmation UI/API, or human evidence. Its existing code remains subject to independent compliance against the original AI-GPU-1 plan. The fixture implementation may import stable existing AI contracts/frame helpers, but it must not modify that card's cut, speaker-mapping, or GPU-measurement ownership without a separate correction requirement.

A fixture reaching `accepted` means only that Gates 1–3 have trustworthy inputs. It does not pass any gate, prove WhisperX superiority, authorize Gate 4 infrastructure mutation, or authorize a backend change.

## 10. Bounded work packages and dependencies

### Package GF-1 — contracts, validator, and synthetic substitute

**One Programmer worktree; no private media required.**

Owns:

- `src/autoedit/ai/golden_fixture.py`
- `scripts/validate-golden-fixture.py`
- `tests/test_golden_fixture_contracts.py`
- `tests/test_golden_fixture_synthetic.py`
- generated tracked schemas/synthetic metadata under `tests/fixtures/golden_interview/`
- narrow README/protocol/testing-strategy updates

Must satisfy `ARCH-GOLD-*`, `BACKEND-GOLD-001..016`, `OPS-GOLD-002/005..010`, `SEC-GOLD-006..014`, and `TEST-GOLD-001..013/017/018` where executable without real media.

Must not own product UI, Compose, deployment, real model execution, or Peter approvals. Independent Designer compliance is required before GF-2.

### Package GF-2 — trusted fixture materialization and validation

**Private human/Tester operation after GF-1 compliance; no repository media changes.**

Inputs Peter's exact root, rights/retention decisions, opaque speaker truth, word marks, and editorial windows. Runs validate-only and records the accepted private bundle. Satisfies `OPS-GOLD-001/003/004`, `SEC-GOLD-001..005/009`, and `TEST-GOLD-014/015` input readiness.

If consent, license, retention, identity, word truth, or coverage is unavailable, GF-2 blocks with the exact missing decision. It does not fabricate a fixture or mark placeholders accepted.

### Package GF-3 — AI-GPU-1 integration consumption

**Depends on GF-1 compliance, accepted GF-2 bundle, and compliant AI-GPU-1 Packages B/C.**

Owns only `tests/integration/test_whisperx_golden_media.py` consumer behavior and narrow fixture-to-existing-gate adapters not already owned elsewhere. It executes `TEST-GOLD-014..016` and the relevant `TEST-AIGPU1-*` criteria. It must not duplicate confirmation persistence, cut projection, browser implementation, or GPU/Dots harness ownership.

Independent Designer compliance and Tester execution remain mandatory.

## 11. Acceptance evidence matrix

| Requirement family | Minimum evidence |
|---|---|
| `ARCH-GOLD-*` | source/diff review proving class separation, env-only selection, immutable package/run split, master timeline/FPS/hash bindings, and no production contract changes |
| `BACKEND-GOLD-*` | strict model/schema tests, public-safe synthetic package, byte-hash/bundle tests, exact shape/coverage/label-swap tests, redacted validator output |
| `UI-GOLD-*` | exact-candidate authenticated/local browser evidence for readiness/error/revoked/stale states, keyboard/focus/live-region checks, 1440x900 and 390x844 layouts, source-media network absence |
| `OPS-GOLD-*` | redacted read-only discovery, root/mount/ACL compliance booleans, validate-only transcript, no container/model mutation, cleanup/rollback record |
| `SEC-GOLD-*` | Peter's private bound attestations, path/link tests, privacy scan, redaction injection tests, no private artifacts in Git/Kanban/build context |
| `TEST-GOLD-001..013/017/018` | focused and broad command output from exact candidate, compile/lock/diff checks, independent compliance matrix |
| `TEST-GOLD-014..016` | accepted opaque bundle ID, private run evidence, redacted summary, direct Peter word/identity/editorial decisions, existing AI-GPU-1 gate evidence |

A compliance reviewer must map every individual ID to direct source, diff, test, runtime, UI, and operational evidence. Another worker's summary is not evidence.

## 12. Risks and mitigations

| Risk | Mitigation |
|---|---|
| Consent or license is assumed from ownership/location | explicit purpose-scoped Peter attestation bound to exact bytes |
| Exact hashes identify private media in durable logs | hashes stay private; tracked output uses random opaque IDs and counts |
| Ignore rules are mistaken for access control | external root, restricted ACL, path confinement, build-context/privacy scan |
| Ground truth is tuned after seeing candidate output | lock/hash/approve truth before candidate run; candidate writes elsewhere |
| One real excerpt lacks a required case | readiness fails or adds another consent-cleared excerpt |
| Synthetic success is presented as live quality | fixture class and eligibility checks fail the human/live gate |
| NTSC frame math is rounded inconsistently | use shared frame helpers; store frame index plus canonical ms; word truth unsnapped |
| Anonymous labels become identity | stable opaque IDs plus Peter confirmation and deterministic label-swap tests |
| Revoked/expired material continues to run | pre-run rights/retention validation and immediate fail-closed status |
| Restore/copy changes bytes or permissions | rehash/reprobe/recheck ACL; changed revision needs fresh approval |
| Tool errors leak transcript/path/hash | structured redacted codes, injection tests, private logs with expiry |
| Fixture mount broadens production attack surface | no public-app mount by default; read-only worker mount only in later approved task |

## 13. Non-goals

- No real media, transcript, identity evidence, exact private path, or source fingerprint is added to Git or Kanban.
- No implementation of speaker confirmation UI/API, activity projection, cut logic, GPU sampling, Dots coexistence, or rollout in this design card.
- No model execution, live browser acceptance, production project mutation, deployment, publishing, Docker recreation, or Unraid change.
- No replacement of automatic energy-envelope cross-correlation with manual sync.
- No playback of source media in the browser; proxies remain silent and program audio remains master.
- No QSV substitution, VAAPI change, MySQL/NPM change, FCPXML change, or backend-default change.
- No LLM/OpenRouter authority for consent, word timing, identity, annotations, or editorial decisions.
- No claim that one bounded fixture completes the broader three-interview superiority benchmark.

## 14. Verdict

**DESIGN_APPROVED**

The contract is implementable without private media in Package GF-1 and is safely blocked at materialization/execution until Peter supplies the exact consent, rights, retention, identity, word-boundary, and editorial decisions. Production remains `WHISPER_BACKEND=mock` and `DIARIZE_BACKEND=mock`; no OpenRouter, deployment, publishing, private-media copying, live GPU acceptance, or production mutation is authorized.
