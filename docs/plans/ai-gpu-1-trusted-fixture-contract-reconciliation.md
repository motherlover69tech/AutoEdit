# AI-GPU-1 trusted-fixture contract reconciliation

**Status:** `DESIGN_APPROVED`
**Scope:** downstream implementation brief for `TEST-AIGPU1-001`, `TEST-AIGPU1-002`, `TEST-AIGPU1-007`, `SEC-AIGPU1-001`, and `SEC-AIGPU1-005`
**Authoritative parents:** `docs/plans/ai-gpu-1-acceptance-gates.md` and `docs/plans/consent-safe-golden-media-fixture-acceptance.md`
**Production constraint:** keep `WHISPER_BACKEND=mock` and `DIARIZE_BACKEND=mock`; no deployment, private-media access, Peter-only gate, or production mutation is authorized

## 1. Decision

The shared tree already contains the golden-fixture contract. The implementation must extend it rather than create a second fixture model, alternate root variable, renamed evidence file, or parallel candidate-word schema.

The trusted-host path has three distinct outcomes that must not be conflated:

1. **Package readiness:** a private `consent_real` package is current, hash/probe/rights/retention/approval valid, and suitable as gate input. This is not an AI-GPU-1 pass.
2. **Fixture-set readiness:** at least three ready 3–10 minute excerpts exist for the broader benchmark. The explicitly selected bounded fixture must contain both speakers and all mandatory review categories. This is not an AI-GPU-1 pass.
3. **Run evaluation:** one explicitly selected accepted bundle and candidate `AIResultArtifact` are compared. Gate statuses are derived from the comparison, not trusted from caller-supplied `PASS` fields.

When `AUTOEDIT_GOLDEN_MEDIA_ROOT` is absent, the trusted-host tests report `unavailable`/skip. They must never emit `accepted`, `valid=true` for a real gate, or a passing gate status.

## 2. Facts, assumptions, unknowns, and human decisions

### Verified facts

- `src/autoedit/ai/golden_fixture.py` already defines strict `Manifest`, `GroundTruth`, `Approvals`, `RunEvidence`, `BoundaryEvaluation`, bundle hashing, path/root checks, redacted results, `validate_fixture()`, `evaluate_gate_one()`, and deterministic synthetic metadata.
- `src/autoedit/ai/contracts.py` already defines the canonical candidate `AIResultArtifact`. Its segment words, source manifests, model identities, turns, mappings, and timestamps must be consumed through an adapter; they must not be redefined in the fixture package.
- `AIResultArtifact` timestamps are already strict integer milliseconds on `program_audio_master`. Its source offsets use `source_ms=master_ms+sync_offset_ms`.
- The private package names are `fixture.manifest.json`, `ground_truth.json`, and `approvals.json`. Current run evidence is named `runs/<opaque-run-id>/run-evidence.json`.
- `scripts/validate-golden-fixture.py` is the existing validate-only CLI and `AUTOEDIT_GOLDEN_MEDIA_ROOT` is the existing external-root selector.
- `tests/fixtures/golden_interview/expected/*.json` are tracked `not_labeled` placeholders. They are documentation/scaffolding only and can never satisfy a real gate.
- No generated JSON schemas currently exist under `tests/fixtures/golden_interview/schemas/`.
- The current focused command returns `17 passed, 2 skipped`; both skips are caused by the intentionally absent external trusted root. This is self-contained test evidence only, not acceptance.
- Current `validate_fixture()` still mixes package readiness with required run evidence, while the current trusted-host module treats every external fixture as if it already had a passing run. Those semantics must be separated.

### Assumptions to validate later

- The trusted host can provide at least three separate 3–10 minute consent-cleared excerpts.
- One explicitly selected excerpt contains both speakers and all mandatory review categories; otherwise the bounded run must use an additional consent-cleared excerpt.
- A current candidate `AIResultArtifact` and private Peter decisions can be bound to the selected accepted bundle.

### Unknowns

- The real root, approved owner/service identity, ACL policy, media revisions, hashes, bundle IDs, run IDs, and candidate artifact are intentionally unknown.
- The exact external fixture and run to select are unknown. The harness must require explicit opaque selection and must not choose the first directory or newest run.

### Peter-only decisions

Peter must supply/approve consent and rights, retention/backup treatment, stable identities, audible word marks, locked editorial truth, and later candidate verdicts. Test data may exercise the schema with public-safe opaque values, but an agent-authored decision can never make a real fixture accepted.

## 3. Canonical contracts and naming to preserve

| Concern | Existing canonical contract | Required treatment |
|---|---|---|
| External root | `AUTOEDIT_GOLDEN_MEDIA_ROOT` | Keep as the only external-root selector; do not scan production or fall back to tracked media. |
| Fixture classes | `synthetic_contract`, `consent_real` | Preserve names. Synthetic may pass contract tests but is always ineligible for real/Peter gates. |
| Fixture package | `fixtures/<fixture-id>/fixture.manifest.json`, `ground_truth.json`, `approvals.json` | Preserve names and immutable package/run split. |
| Run evidence | `runs/<run-id>/run-evidence.json` and `RunEvidence` | Extend this format; do not introduce a competing `evidence.json` or rename the current file. Optional `summary.redacted.json` is a derived output, not source evidence. |
| Candidate result | `AIResultArtifact` in `src/autoedit/ai/contracts.py` | Parse and validate it directly. Do not create a second candidate artifact/word/turn model. |
| Gate-1 comparison | `evaluate_gate_one()` / `BoundaryEvaluation` | Extend to accept adapter-produced candidate words and derive errors/status. Do not compare truth to itself. |
| Error vocabulary | bounded `GOLD_*` codes through `redacted_result()` | Reuse and extend the allowlist only when a new bounded failure class is necessary. Never return exception text containing private values. |
| Field style | strict Pydantic, `extra="forbid"`, snake_case, schema version string `"1.0"`, integer `*_ms`, opaque `*_id` | Preserve. A changed schema requires an explicit revision decision; no silent auto-upgrade. |
| Tracked placeholders | `tests/fixtures/golden_interview/expected/*.json` with `status: not_labeled` | Leave ineligible. Do not relabel placeholders as accepted output. |

If JSON Schemas are added, generate them from the Pydantic source of truth under `tests/fixtures/golden_interview/schemas/` and byte-compare regeneration in tests. Do not hand-maintain a divergent schema.

## 4. Required adapter behavior

A narrow fixture-to-artifact adapter may live in `golden_fixture.py` or a new `src/autoedit/ai/golden_fixture_adapter.py`. It must import `AIResultArtifact`; it must not modify unrelated artifact, speaker-mapping, activity, cut, GPU, API, or UI ownership.

1. Validate the candidate with `AIResultArtifact` before deriving evidence.
2. Keep locked truth selection independent of candidate error: select the earliest accepted, certain, non-overlapped truth word in each actual timeline third.
3. Retain `WordBoundary.word_id` as the opaque evidence ID. Add a strict locked reference such as `artifact_word_index` if needed because `AIResultArtifact.WordTiming` has no word ID. Resolve by exact `segment_id` plus locked word index; never fuzzy-match transcript text or choose the nearest prediction after seeing error.
4. Where permitted, a private `token_digest` may prove the selected candidate word; no token text or digest enters redacted output.
5. Derive anonymous-cluster association from intersection with the validated artifact's diarization turns. Require both clusters when intersection makes both available. Do not treat human identity as known in Gate 1.
6. Evaluate candidate word timestamps exactly as stored in the validated `AIResultArtifact`, because they are already on `program_audio_master`. Do not subtract the sync offset a second time.
7. Prove one-time offset handling by matching candidate source manifests to the fixture channel/source offsets and by retaining the canonical convention. A mismatch fails; an evaluator-side second conversion fails.
8. Check candidate word ordering, segment containment, master-timeline bounds, and unchanged strict import before calculating both start and end errors.
9. Calculate tolerance as the exact rational `1000 * fps_den / fps_num`. Every one of six boundaries must be within tolerance; no averaging is allowed.
10. Recompute selected IDs, boundary errors, cluster coverage, offset consistency, and gate statuses. Caller-provided errors or `PASS` values are assertions to verify, never truth.

## 5. Gate-to-behavior and assertion matrix

| Requirement | Required executable behavior | Minimum assertions |
|---|---|---|
| `TEST-AIGPU1-001` | Validate the secure set separately from a selected run. Require at least three distinct ready `consent_real` packages, each 180,000–600,000 ms. Require the explicitly selected bounded fixture to contain both speakers and every mandatory category. | Reject 0–2 excerpts, out-of-range duration, `synthetic_contract`, `not_labeled`, draft/revoked/stale package, reused/hard-linked camera assets, missing program/analysis audio, missing speaker, and missing category. Do not require all three excerpts to possess the selected run's Gate-1 evidence. |
| `TEST-AIGPU1-002` | Compare the selected locked truth words with actual validated artifact words on the master timeline. | Exactly one selected word per first/middle/final third; both clusters where available; three words/six boundaries; each start/end error within exact one-frame tolerance; actual candidate references exist; artifact source offsets equal fixture offsets; no second offset application; deterministic selection independent of candidate error. |
| `TEST-AIGPU1-007` | Bind one private run record to the exact bundle and candidate, and derive statuses from evidence. | Match run directory/name, fixture ID/revision, private document/bundle hashes, source commit, worker image digest, model/runtime versions, Compose render digest, FPS, source/channel offsets, candidate artifact identity, commands/results, and current Peter decision scopes. Reject missing, stale, inconsistent, caller-only, or arbitrarily `PASS` fields. |
| `SEC-AIGPU1-001` | Admit only purpose-complete, current, hash-bound consent evidence. | Require active consent/withdrawal state, all five allowed purposes, model/derivative permission, current rights dates, and distinct current Peter scopes for consent, retention, both identities, word truth, and editorial truth. Reject pending/denied/revoked/expired/purpose-incomplete or duplicate blanket decisions. Never infer consent from `fixture_class`, a path, or generated media. |
| `SEC-AIGPU1-005` | Keep packages and evidence in a restricted external tree and emit only bounded redacted summaries. | Reject repo/production roots, unsafe mode/owner policy, traversal, any symlink component, special files, hard links, run-directory/run-ID mismatch, writes into fixture packages, and redacted output containing paths, media values, transcript text, names, source/media hashes, credentials, cookies, runtime IDs, or private operator data. Root absence is unavailable/skip, never PASS. |

## 6. Evidence contract

### Private `run-evidence.json`

Private evidence may contain the exact bindings needed to recompute the run:

- fixture ID/revision and private manifest/truth/bundle hashes;
- run ID matching its directory;
- candidate artifact relative path and hash within the run tree;
- source commit, worker image digest, model/runtime identities, and Compose render digest;
- FPS rational, offset convention, and exact manifest/candidate source offsets;
- exact command records and results, stored privately without shell interpolation;
- bound approval/decision references;
- selected truth references, actual candidate references, six boundary calculations; and
- explicit derived statuses for all five scoped requirements.

A failed or blocked run must remain representable. `RunEvidence` must not require all gates and decisions to be `PASS` merely to parse the failure record. The evaluator derives `PASS`, `FAIL`, `BLOCKED`, or `UNAVAILABLE`; a final overall pass is allowed only when every scoped status is derived `PASS`.

### Redacted output

A redacted summary may retain only:

- opaque fixture and run IDs/revisions;
- non-media candidate/tool identifiers or digests (source commit, worker image, model/runtime, Compose render);
- schema/tool version;
- counts, category coverage booleans, FPS rational, offset convention/count (not private paths or media fingerprints);
- command IDs/digests and result status, not private argv values;
- Peter decision scope/status without names, operator IDs, text, or evidence content;
- derived gate statuses and bounded `GOLD_*` errors.

Keep private manifest/truth/media hashes, bundle bytes, exact paths, transcript/token content, names, snippets, screenshots, cookies, credentials, and legal records out of stdout, pytest node IDs, tracked files, and Kanban.

The CLI must call the shared redaction/result builder for missing-root and error output; it must not maintain a second, shape-incompatible result literal.

## 7. Narrow file ownership

Safe to modify for this implementation:

- `src/autoedit/ai/golden_fixture.py`
- optionally one new `src/autoedit/ai/golden_fixture_adapter.py`
- `scripts/validate-golden-fixture.py`
- `tests/test_golden_fixture_contracts.py`
- `tests/test_golden_fixture_synthetic.py`
- `tests/integration/test_whisperx_golden_media.py`
- generated schemas and public-safe metadata under `tests/fixtures/golden_interview/`
- narrow truth-status updates in `tests/fixtures/golden_interview/README.md`, `docs/ai/whisperx-evaluation-protocol.md`, and `docs/plans/TESTING_STRATEGY.md` after the commands are genuinely runnable

Do not modify in this package:

- `src/autoedit/ai/contracts.py` unless a separate reviewed incompatibility proves the adapter cannot consume it;
- speaker confirmation, speaker mapping, activity projection, cut engine, API, DB, player, GPU measurement, or GPU acceptance harness code;
- Compose/Docker/deployment files, production configuration/data, or backend defaults;
- tracked placeholder JSON to make it look accepted.

## 8. Required self-contained regressions

Extend the existing test modules; do not create a parallel fixture-test suite.

1. Reproduce the prior public-safe adversarial cases as deterministic temporary-root tests: draft/mismatched truth, absent program or analysis audio, hard-linked/reused cameras, duplicate blanket approvals, nonexistent selected word, wrong offset, and run-directory/run-ID mismatch.
2. Add candidate-adapter tests using a real `AIResultArtifact` object: valid six-boundary comparison, one boundary over tolerance, missing segment/index, mismatched token digest where used, cluster-coverage failure, source-offset mismatch, and proof that master-timeline words are not offset twice.
3. Add set-versus-run tests: three package-ready excerpts plus one explicitly selected complete bounded fixture; prove fixture-set readiness does not claim Gate 1 and does not require passing run evidence for every excerpt.
4. Add failure-record tests: `FAIL`, `BLOCKED`, and `UNAVAILABLE` parse and remain redacted; arbitrary caller `PASS` is rejected or recomputed.
5. Add redaction-injection tests for paths, transcript text, person names, media hashes, token/cookie/credential values, runtime IDs, and media-like filenames. Assert only opaque IDs/counts/statuses remain.
6. Keep the existing missing-root pytest skip and direct `GOLD_ROOT_NOT_CONFIGURED` validator result. Assert the skipped path cannot produce any passing gate status.
7. Keep synthetic metadata deterministic and explicitly ineligible for consent/word/identity/editorial acceptance.

Permitted verification:

```bash
OLLAMA_BASE_URL='' LLM_MODEL='' env -u VIRTUAL_ENV uv run pytest -q \
  tests/test_golden_fixture_contracts.py \
  tests/test_golden_fixture_synthetic.py \
  tests/integration/test_whisperx_golden_media.py -rs

env -u VIRTUAL_ENV uv run python -m compileall -q src tests
uv lock --check
git diff --check
```

The external-root command is intentionally not run until Peter supplies the accepted private root, explicit opaque fixture/run selection, and decisions. A missing external root is expected evidence of unavailability, not acceptance.

## 9. Failure, rollback, risks, and non-goals

- Any schema, hash, probe, rights, retention, path, approval, candidate, offset, boundary, or evidence mismatch fails before a passing gate is emitted.
- Validation remains read-only. Candidate output writes only beneath the selected private run directory; fixture packages remain immutable.
- Rollback is removal/revert of the narrow harness/schema changes while retaining private fixtures untouched. A failed run is quarantined or later deleted only by a separately authorized retention action.
- Production mock backends, prior artifacts/cuts, VAD baseline, program audio, silent proxies, automatic energy-envelope sync, VAAPI, NPM, central MySQL, and exports remain unchanged.
- No source media is played in a browser. No manual sync nudge is introduced. No OpenRouter or external AI service processes fixture content.
- This package does not prove WhisperX quality, pass Peter-only decisions, execute GPU/Dots acceptance, or authorize deployment.

## Verdict

**DESIGN_APPROVED**

The Programmer may implement only the bounded fixture-schema/adapter/evaluation work above. Real acceptance remains blocked until an external consent-controlled root, explicit fixture/run selection, and Peter's bound decisions exist.