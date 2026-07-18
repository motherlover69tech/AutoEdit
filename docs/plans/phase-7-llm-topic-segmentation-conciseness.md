# Phase 7 LLM-backed topic segmentation and conciseness design

Status: **DESIGN_APPROVED**

Date: 2026-07-16

Kanban task: `t_c04c7b0a`

Scope: Stage 5.2 topic segmentation and Stage 5.3 conciseness. Stage 9.2 title generation is a downstream consumer of this contract, not part of this implementation.

## 1. Outcome

Replace the current opportunistic, weakly validated topic/conciseness LLM calls with an explicit provider-neutral semantic analysis boundary. The production default remains a deterministic mock baseline and makes no network request. An explicitly configured local Ollama backend may produce real semantic topic boundaries, summaries, and LLM conciseness scores after its acceptance gates pass. A direct external provider can be added later through the same protocol, but only after its exact direct endpoint/model, credential handling, consent, and data-processing decision are approved. OpenRouter is forbidden.

The semantic model proposes meaning; AUTOEDIT remains authoritative for source identities, timestamps, span coverage, ordering, colour, persistence, and score provenance. A malformed, partial, stale, or unavailable live result never silently becomes a mock result and never replaces the last-known-good topic run.

## 2. Sources inspected

- `AI_HANDOFF.md`
- `jobs/BACKLOG.md`
- `docs/source/multicam_autoedit_spec.md`, especially Stages 5.2 and 5.3
- `docs/source/multicam_ui_style_guide.html`
- `docs/plans/TESTING_STRATEGY.md`
- `docs/DEPLOYMENT.md`
- `docs/plans/whisperx-speaker-aware-ai-roadmap.md`
- `docs/plans/ai-gpu-1-acceptance-gates.md`
- `docs/plans/stage-9.2-llm-youtube-title-generator-closure.md`
- `src/autoedit/topics.py`
- `src/autoedit/conciseness.py`
- `src/autoedit/llm_client.py`
- `src/autoedit/ai/contracts.py`
- `src/autoedit/ai/artifacts.py`
- `src/autoedit/transcribe.py`
- `src/autoedit/config.py`
- `src/autoedit/db/schema.py`
- `src/autoedit/db/migrate.py`
- `src/autoedit/api.py`
- `src/autoedit/progress.py`
- `src/autoedit/report.py`
- `src/autoedit/plog.py`
- `src/autoedit/web/app.html`, `app.js`, `index.html`, and `player.js`
- `docker-compose.yml` and `docker-compose.gpu-ai.yml`
- `tests/test_topics.py` and `tests/test_conciseness.py`

The working tree already contains an unrelated modification in `src/autoedit/ai/contracts.py`. This design does not require editing that file; implementation must preserve that concurrent work.

## 3. Facts, assumptions, unknowns, and decisions

### 3.1 Verified facts

1. `mock_segment_topics()` is not reliably mock-only. When default LLM settings are populated it attempts Ollama, catches any exception, and silently continues with a random fallback.
2. The current fallback uses `random.choice()` and `random.randint()`, so repeated runs are not deterministic.
3. The current LLM output accepts coercive dictionaries, clamps model values, repairs overlaps after parsing, permits gaps, does not bind boundaries to source segment IDs, and has no durable provider/source/prompt provenance.
4. The current topic route deletes the selected DB rows before replacement and writes `topics.json` separately. Disk and DB are not one recoverable selection transaction.
5. The current conciseness route commits each span separately and replaces the semantic summary with a metrics/rationale string. A mid-run failure can leave mixed scores, and downstream summary/title context can lose the semantic summary.
6. The current `OLLAMA_BASE_URL` and `LLM_MODEL` settings are populated by default. They must not implicitly activate a semantic provider.
7. Production Whisper/diarization remains mock-backed pending the documented AI/GPU gates. The versioned speech artifact and last-known-good store exist, but the authoritative speaker-attributed transcript path is not yet accepted for production.
8. The current progress and processing UI already support queued/running/done/error rows, but do not expose semantic backend, score source, cache status, fallback provenance, or stale last-known-good state.
9. The database bootstrap is `metadata.create_all()` rather than a versioned altering migration system. This design therefore adds tables only and avoids altering existing columns.
10. Program audio remains the master timeline; this feature must consume synchronized integer millisecond timestamps and must not adjust synchronization.

### 3.2 Assumptions to verify during implementation

1. The selected local Ollama model supports deterministic JSON-schema output sufficiently for the strict contract. Fake-provider tests do not count as local-model acceptance.
2. The Phase 7 fictional fixtures can be stored in Git because they contain no real or identifying media/transcript content.
3. Existing topic and topic-span tables may remain the current selected projection while a new immutable run table records the authoritative semantic provenance.

### 3.3 Unknowns and deferred human decisions

These do not block the local provider-neutral implementation:

1. The exact currently available direct external model and endpoint corresponding to the roadmap's historical “DeepSeek V4 Flash” name.
2. Whether Peter consents to sending private interview transcript text to that direct provider, and whether the provider's retention/data-processing terms are acceptable.
3. The direct provider credential source and account/credit acceptance evidence.
4. Availability of consent-cleared real interview fixtures for Peter's editorial quality gate.
5. Final production acceptance of the speaker-attributed upstream transcript and of local-GPU/Ollama resource coexistence.

A future direct-provider card must resolve items 1–3. A real-media acceptance card must resolve items 4–5. No arbitrary compatible endpoint may be substituted.

### 3.4 Existing user/project decisions

- OpenRouter is prohibited for agent and product routing.
- Production remains mock-backed until documented acceptance gates pass.
- Derived private/consent-controlled transcript and semantic artifacts stay outside Git.
- Audio synchronization remains automatic energy-envelope cross-correlation; this feature must not add manual sync nudges.
- Program audio is the master clock and proxies remain silent.
- VAAPI `h264_vaapi` remains the active proxy path; this feature does not touch proxy encoding.

## 4. Architecture

### 4.1 Data flow

1. Resolve the selected, versioned speech result and its source digest.
2. Build a strict `SemanticTranscriptDocument` containing only accepted, speaker-attributed source segments on the synchronized program-audio timeline.
3. Canonicalize and hash that document.
4. Build deterministic, whole-segment chunks. Each chunk has non-overlapping `owned_segment_ids` and optional neighbouring `context_segment_ids`. Context helps the model; only owned segments may be assigned by that response.
5. Execute one semantic provider for the whole run. A provider response assigns every owned source segment exactly once to an ordered local topic group using opaque segment IDs, not model-authored timestamps.
6. Strictly validate every response. One schema-focused repair attempt is permitted. If any chunk remains invalid, discard the provider's whole candidate run.
7. Deterministically stitch chunk groups, assign server-owned timestamps and colours, and calculate deterministic conciseness metrics.
8. Generate grounded summaries and LLM scores for final spans through the same provider, with exact source segment IDs as citations. Validate again.
9. Build and validate a complete immutable `SemanticTopicArtifact`.
10. Write the immutable artifact. In one DB transaction, insert the run metadata, replace the legacy selected `topics`/`topic_spans` projection, and point the project selection to that run.
11. Regenerate `transcript/ai/topics/v1/result.json` and legacy `transcript/topics.json` as derived pointers/projections. The DB selection plus immutable artifact is authoritative if a derived file is missing.
12. Build `summary.json` from the selected validated run. Stage 9.2 can later consume this summary and its semantic provenance without accessing a provider directly.

### 4.2 Backend modes

- `TOPIC_BACKEND=mock` (default): deterministic, explicitly labelled baseline; no HTTP and no provider fallback path.
- `TOPIC_BACKEND=ollama`: real local semantic provider. It fails closed if unavailable or invalid.
- Future direct provider: a named, explicit adapter added in a separate card. The provider-neutral runner accepts ordered provider instances, so a direct-primary/Ollama-fallback policy can be added without changing topic contracts. No generic arbitrary-base-URL or OpenAI-compatible adapter is accepted as a shortcut.

The mock mode is not a fallback member in any live provider chain. Changing from a failed live backend to mock requires server configuration and a new explicit run.

### 4.3 Provider consistency and fallback

One run uses one semantic provider from segmentation through summaries and LLM scoring. If a provider fails after its bounded repair attempt, its entire in-memory candidate is discarded. A configured next live provider starts a new complete attempt; chunks from different providers are not mixed. The artifact records all non-sensitive attempts and the selected provider.

The initial implementation supports the protocol, mock backend, Ollama adapter, and fake-provider chain tests. The direct external adapter and its live fallback acceptance are deferred, not simulated.

## 5. Contracts

### 5.1 Semantic transcript input

`SemanticTranscriptDocument` is strict and versioned. Required root fields:

- `schema_version="semantic-transcript.v1"`
- `project_id`
- `source_speech_run_id`
- `source_speech_schema_version`
- `source_artifact_sha256`
- `timeline_unit="ms"`
- ordered `segments`

Each segment requires:

- stable `segment_id`
- strict integer `start_ms` and `end_ms`, with `0 <= start_ms < end_ms`
- non-blank bounded `text`
- one or more authoritative `speaker_ids`; overlap may carry more than one
- optional safe display labels kept separate from stable IDs
- source segment/word references sufficient to audit any upstream split

Unknown fields, strings/floats/booleans for timestamps, duplicate IDs, inverted ranges, unordered segments, and an unresolved speaker attribution fail before any live provider call. Mock mode may use the legacy test transcript only through a separately labelled mock adapter; legacy input can never masquerade as an accepted live semantic transcript.

### 5.2 Provider request and response

The provider receives:

- schema and prompt version
- stable chunk ID
- ordered context segments
- explicit owned segment IDs
- transcript text and safe speaker display values required for semantics
- no source paths, channel paths, user names, credentials, or unrelated project metadata

The segmentation response is a strict object with ordered `groups`. Each group requires:

- `owned_segment_ids`: non-empty, contiguous, exact IDs from the chunk's owned set
- `label`: non-blank, bounded plain text
- `summary_seed`: non-blank, bounded plain text

The final summary/scoring response for each stitched span requires:

- exact `span_id`
- `summary`: non-blank, bounded plain text
- `llm_conciseness_score`: strict integer 1–5
- non-empty `evidence_segment_ids`, all within that span
- bounded `rationale`

Responses forbid extras, coercion, HTML, provider thinking fields, `<think>` content, source-authored timestamps, colours, stable DB IDs, paths, and authoritative speaker assignments.

### 5.3 Final artifact

`SemanticTopicArtifact` is strict and versioned at `semantic-topics.v1`. It contains:

- run identity, timezone-aware creation time, status, and timeline basis
- source speech run/version/hash and canonical semantic-input hash
- cache/config hash
- mode (`mock` or `live`), selected provider/model, prompt/schema/chunk-policy versions
- bounded attempt records: provider, outcome code, duration, and response hash; never raw prompts or responses
- cache-hit flag
- complete ordered topics and spans
- warnings, including score-signal disagreement

Each span contains:

- stable span/topic IDs
- source first/last IDs and the complete ordered `source_segment_ids`
- authoritative server-mapped `start_ms`/`end_ms`
- stable speaker IDs present in the source span
- label, semantic summary, and server-assigned colour
- nullable LLM score
- deterministic advisory score
- canonical selected `conciseness_score`
- `score_source` (`llm` or `deterministic`)
- deterministic metrics: word count, duration, words/minute, filler density, duration-to-median ratio, and metric rationale
- LLM rationale and evidence segment IDs when live

For live runs, `conciseness_score` equals the validated LLM score; deterministic metrics remain separately visible and a significant disagreement emits a warning rather than silently blending values. For mock runs, the LLM score is null and `conciseness_score` is the deterministic score with `score_source=deterministic`.

### 5.4 Database projection

Add only these tables:

- `semantic_topic_runs`: run ID, project ID, schema version, source hash, config hash, backend, provider/model, immutable artifact relative path/hash, created time, and unique `(project_id, source_hash, config_hash)` cache key.
- `semantic_topic_selections`: one row per project pointing to the selected run with selection time.

Existing `topics` and `topic_spans` remain the selected compatibility projection. `topic_spans.summary` remains the semantic summary and is never replaced by metric text. `topic_spans.conciseness_score` contains the selected canonical score. Rich metrics and provenance live in the immutable artifact and API/summary response.

The selected DB run plus its immutable artifact is authoritative. `result.json` and `topics.json` are recoverable projections. Legacy projects with no semantic selection continue to read their current rows and are labelled `legacy_unversioned`; the next explicit run upgrades them.

### 5.5 Cache key

The canonical cache/config hash includes:

- canonical semantic transcript hash and source artifact hash
- backend and exact provider/model identity
- provider options affecting output
- segmentation prompt/schema version
- summary/scoring prompt/schema version
- deterministic chunk policy version and size/overlap settings
- deterministic metric version

Only a complete validated artifact is reusable. Failed or partial attempts are never cached as success. A repeated non-force request with the same key returns the same selected run without HTTP. Concurrent equal requests converge through a per-project lock plus the DB uniqueness constraint. A future force option must still create a distinct nonce/key and may not overwrite immutable history.

## 6. Stable requirements

### 6.1 Architecture

- **ARCH-P7-001**: Topic analysis shall expose an explicit backend mode; populated Ollama settings alone shall never activate network use.
- **ARCH-P7-002**: The default `mock` backend shall be deterministic and zero-network.
- **ARCH-P7-003**: Live semantic execution shall use a provider-neutral protocol separated from topic contracts and orchestration.
- **ARCH-P7-004**: The initial live adapter shall be Ollama; a direct external adapter shall be a separately accepted implementation of the same protocol.
- **ARCH-P7-005**: OpenRouter and arbitrary compatible endpoint routing shall not exist in configuration, code, tests, docs, fallback, or acceptance evidence.
- **ARCH-P7-006**: A live run shall use one provider consistently; mixed-provider chunks are forbidden.
- **ARCH-P7-007**: Mock shall not be an automatic fallback from live failure.
- **ARCH-P7-008**: The model may propose semantics only; source IDs, times, ordering, coverage, colours, and persistence selection remain server-owned.
- **ARCH-P7-009**: Stage 5.2 and 5.3 shall share one validated analysis service so semantic summary and both score classes are published together.
- **ARCH-P7-010**: Immutable semantic artifacts shall be authoritative, with DB rows as the selected compatibility projection.
- **ARCH-P7-011**: Stage 9.2 shall consume selected summary/provenance only and shall not call the Phase 7 provider directly.
- **ARCH-P7-012**: Live execution shall depend on an accepted versioned speaker-attributed transcript; it shall not promote legacy mock transcript data to authoritative status.

### 6.2 Backend and data

- **BACKEND-P7-001**: Validate the semantic transcript strictly before cache lookup or provider invocation.
- **BACKEND-P7-002**: Canonical ordering and hashing shall produce identical hashes for identical semantic input and reject duplicate/ambiguous identities.
- **BACKEND-P7-003**: Chunking shall be deterministic, preserve whole source segments, use non-overlapping owned sets, and bound context size below the configured provider context.
- **BACKEND-P7-004**: Every accepted source segment shall be owned by exactly one chunk.
- **BACKEND-P7-005**: Provider output shall identify source segments by exact opaque IDs and shall not author timestamps.
- **BACKEND-P7-006**: Strict response models shall require all fields, forbid extras/coercion/non-finite values/thinking traces, and enforce bounded text and score ranges.
- **BACKEND-P7-007**: Every owned segment shall be assigned exactly once to a contiguous ordered group; missing, duplicate, foreign, or reordered IDs shall fail the attempt.
- **BACKEND-P7-008**: Stitching shall be deterministic and shall produce ordered non-overlapping spans on the program-audio timeline.
- **BACKEND-P7-009**: Accepted spans shall cover at least 95% of dialogue duration and 100% of accepted non-empty source segments; ordinary silence gaps do not count as dialogue.
- **BACKEND-P7-010**: Server mapping shall prevent negative times, zero/inverted spans, source overrun, or timeline-end overrun.
- **BACKEND-P7-011**: Colours shall come from the approved server palette by deterministic ordinal/hash; provider colours are forbidden.
- **BACKEND-P7-012**: Every semantic summary shall cite valid source segment IDs within its span; citations are audit evidence, not proof of editorial truth.
- **BACKEND-P7-013**: Deterministic metrics shall include word count, duration, WPM, filler density, duration ratio, advisory score, and rationale with a versioned algorithm.
- **BACKEND-P7-014**: Live and deterministic scores shall remain separate; no silent blending or overwrite is permitted.
- **BACKEND-P7-015**: `topic_spans.summary` shall remain semantic content and never be replaced with metric/rationale text.
- **BACKEND-P7-016**: A provider may receive at most one initial call and one repair call per operation/chunk; the total run call budget shall be calculated and logged before execution.
- **BACKEND-P7-017**: Timeout, 429, credit/quota, 5xx, empty, malformed, partial, and schema-invalid outcomes shall have stable non-sensitive error codes.
- **BACKEND-P7-018**: Authentication/configuration 4xx failures shall not be retried against the same provider; a configured next live provider may start a complete new attempt.
- **BACKEND-P7-019**: If all configured live providers fail, no topic projection or selected artifact shall change.
- **BACKEND-P7-020**: Cache identity shall include source, backend/provider/model, options, prompt/schema/chunk/metric versions, and any explicit regeneration nonce.
- **BACKEND-P7-021**: Identical non-force requests shall return the same validated run without provider traffic.
- **BACKEND-P7-022**: Immutable run and failure records shall be collision-safe and confined under the project root; output symlinks escaping the project shall fail.
- **BACKEND-P7-023**: Publication shall write the immutable artifact first and then atomically select the DB run and replace all legacy topic/span rows in one transaction.
- **BACKEND-P7-024**: Derived `result.json`/`topics.json` failures shall be recoverable from DB selection plus immutable artifact and shall not select partial state.
- **BACKEND-P7-025**: `POST /projects/{id}/segment-topics` shall preserve existing `topics`/`spans` response fields and add run, backend, provider, score-source, cache, and freshness metadata.
- **BACKEND-P7-026**: `POST /projects/{id}/conciseness` shall be zero-network and idempotently return/revalidate selected metrics without overwriting semantic summaries.
- **BACKEND-P7-027**: Progress, summary, timeline-state, cut, sub-edit, natural-language intent, and title consumers shall read only a selected artifact whose source hash matches the selected transcript.
- **BACKEND-P7-028**: A stale last-known-good topic artifact may be reported for audit but shall not make downstream processing ready.
- **BACKEND-P7-029**: Deleting a project shall remove semantic selection/run DB rows through the existing project cascade and delete only that project's artifact directory.
- **BACKEND-P7-030**: The legacy random fallback shall be removed; mock outputs shall be reproducible byte-for-byte apart from documented run/time fields.

### 6.3 UI and accessibility

- **UI-P7-001**: Processing status shall label the topic stage as `Deterministic baseline — not AI`, `Local LLM`, or a future explicit direct provider; generic “AI complete” is insufficient.
- **UI-P7-002**: Running status shall expose chunk progress and provider class without transcript text or provider payloads.
- **UI-P7-003**: Cache hits and live-provider fallback shall be visible in stage detail.
- **UI-P7-004**: Live failure shall show that previous topics were preserved and are stale; it shall not show success or imply fallback to mock.
- **UI-P7-005**: Topic review shall expose summary, canonical score, score source, deterministic metrics, and disagreement warning for each span.
- **UI-P7-006**: The topic lane shall retain approved colours, and each block shall have an accessible name containing label, time range, summary, score, and score source.
- **UI-P7-007**: Topic blocks shall be keyboard focusable; activation seeks the program-audio master clock without introducing sync adjustment controls.
- **UI-P7-008**: Status changes shall be announced through an appropriate polite live region; errors shall receive programmatic error semantics.
- **UI-P7-009**: At narrow/mobile widths, backend/freshness/error remains visible, metrics collapse to a compact disclosure, and the page shall not gain horizontal overflow.
- **UI-P7-010**: Provider/error strings shall be rendered as text/escaped content and shall not expose credentials, raw upstream bodies, prompts, or transcript excerpts.

### 6.4 Operations and deployment

- **OPS-P7-001**: Add a typed `TOPIC_BACKEND` setting defaulting to `mock`; do not reuse non-empty `OLLAMA_BASE_URL` as an activation switch.
- **OPS-P7-002**: Ollama URL, exact model, connect/read timeouts, context/chunk bounds, retry budget, and maximum output size shall be server-controlled and validated.
- **OPS-P7-003**: The initial production Compose configuration shall explicitly pin `TOPIC_BACKEND=mock`.
- **OPS-P7-004**: Compose and deployment examples shall not add an external credential or OpenRouter variable.
- **OPS-P7-005**: Structured logs shall contain project/run IDs, hash prefixes, backend/provider/model, chunk counts, attempt/result codes, cache state, and durations, but no transcript/prompt/response or secret.
- **OPS-P7-006**: Progress errors shall use stable operator-safe messages while detailed non-sensitive codes remain in pipeline logs/failure metadata.
- **OPS-P7-007**: The additive DB tables shall be created by an explicit pre-start migration command after a verified DB backup; app startup shall not rely on accidental seed-script migration.
- **OPS-P7-008**: Production deployment shall render merged Compose, verify central MySQL and existing volumes/network/health checks, and make no proxy/GPU topology change.
- **OPS-P7-009**: Ollama live acceptance shall measure latency, context fit, memory/VRAM impact, concurrent speech-worker coexistence, and service health on Unraid before enabling it.
- **OPS-P7-010**: Rollback shall pin `TOPIC_BACKEND=mock` and restore the prior app image; additive tables and immutable artifacts may remain because the old app ignores them.
- **OPS-P7-011**: No production container recreation, template mutation, DB migration, backend flip, or real transcript submission is authorized by this design card.

### 6.5 Security and privacy

- **SEC-P7-001**: OpenRouter shall not be used as primary, fallback, auxiliary, proxy, or test route.
- **SEC-P7-002**: Provider adapters shall be explicitly named and endpoint-allowlisted; no user-supplied provider URL/model is accepted through the API.
- **SEC-P7-003**: Provider credentials shall be server-side only, never accepted in request bodies, returned by APIs, logged, or persisted in artifacts.
- **SEC-P7-004**: The provider payload shall contain only the minimum transcript fields required for semantics and shall exclude source paths and unrelated project/user metadata.
- **SEC-P7-005**: Transcript content shall be treated as untrusted prompt-injection text; system instructions and response schemas shall state that transcript instructions are data, not commands.
- **SEC-P7-006**: Responses containing thinking traces, HTML/script, control characters, forbidden authority fields, or foreign source IDs shall fail validation.
- **SEC-P7-007**: Artifact input and output paths shall be resolved/confined before every directory creation and write, including symlink parents.
- **SEC-P7-008**: Private transcript and derived semantic artifacts shall remain under the project data root and untracked by Git.
- **SEC-P7-009**: Direct external submission shall remain disabled until Peter approves the exact provider/model, consent basis, retention/data-processing terms, and secret source.
- **SEC-P7-010**: Failure metadata shall retain only bounded redacted error codes/messages and response hashes; raw provider bodies shall not be durable audit data.

### 6.6 Tests and acceptance evidence

- **TEST-P7-001**: Contract tests shall reject unknown/missing fields, coercive timestamps/scores, booleans, non-finite values, duplicates, foreign IDs, invalid order/ranges, and thinking traces.
- **TEST-P7-002**: Source-gate tests shall prove live mode rejects legacy/unresolved/stale speaker-attributed input before network use.
- **TEST-P7-003**: Chunk tests shall cover empty input, one oversized segment, exact boundary, overlap context, Unicode, long interviews, and every segment owned exactly once.
- **TEST-P7-004**: Stitch tests shall prove deterministic ordering, no overlap, source bounds, 100% source-segment assignment, and >=95% dialogue-duration coverage.
- **TEST-P7-005**: Grounding tests shall reject fabricated/foreign citations and citations outside the claimed span.
- **TEST-P7-006**: Conciseness tests shall prove semantic summary preservation, 1–5 score ranges, score-source separation, deterministic metric reproducibility, and disagreement warnings.
- **TEST-P7-007**: Mock isolation tests shall set live-looking Ollama variables and prove `TOPIC_BACKEND=mock` opens no socket and returns deterministic output.
- **TEST-P7-008**: Outbound Ollama tests shall inspect the actual URL/payload/options, timeout, schema, deterministic temperature, non-thinking configuration where supported, and output-size limit.
- **TEST-P7-009**: Retry tests shall cover success, one repair, timeout, 429, credit/quota, 4xx auth, 5xx, empty, partial, malformed, and exhausted provider chains with exact call counts.
- **TEST-P7-010**: Coherence tests shall prove a failed chunk discards the provider's whole candidate and never publishes mixed-provider output.
- **TEST-P7-011**: Cache tests shall prove exact hits avoid HTTP and changes to every cache-key component cause a new run.
- **TEST-P7-012**: Concurrency tests shall prove equal requests converge and a duplicate run/config cannot mutate immutable history.
- **TEST-P7-013**: Persistence fault-injection tests shall cover immutable write failure, DB insert/delete/selection failure, derived pointer failure, restart reconciliation, and last-known-good preservation.
- **TEST-P7-014**: Symlink tests shall prove no semantic artifact write can escape the project root.
- **TEST-P7-015**: API tests shall cover auth, missing project/input, source prerequisite, success compatibility fields, cache hit, live failure, stale last good, idempotent conciseness, and project deletion.
- **TEST-P7-016**: Downstream tests shall prove stale/malformed semantic artifacts cannot drive summary, cut, sub-edit, intent, or title readiness.
- **TEST-P7-017**: Browser tests shall exercise desktop and narrow/mobile queued/running/mock/live/cache/fallback/error/stale states, keyboard topic blocks, live announcements, console errors, and network failures with screenshots.
- **TEST-P7-018**: The ordinary full suite shall run with mock backends and no network; local/external live suites shall require explicit markers and configuration.
- **TEST-P7-019**: A consent-cleared real-transcript editorial gate shall have Peter judge boundary coherence, summary grounding, label usefulness, and conciseness defensibility; automated schema checks cannot substitute.
- **TEST-P7-020**: Local Ollama acceptance shall record exact model digest/version, commands, timings, resource measurements, artifact hashes, and service-health evidence without transcript or secret disclosure.

## 7. API and visible failure states

### 7.1 Topic endpoint

`POST /projects/{project_id}/segment-topics` keeps current authentication and compatibility fields. The additive run envelope includes:

- `run_id`, `schema_version`, `backend`, `provider`, `model`
- `cache_hit`, `source_fresh`, `score_source`
- `attempts` with safe status codes
- `topics`, `spans`, and `warnings`

Errors use a safe response detail plus a stable internal stage code:

- source absent/legacy/unresolved/stale: prerequisite failure, no provider call
- backend configuration invalid: service configuration error
- provider unavailable/exhausted/invalid: upstream semantic failure
- persistence failure: internal failure with previous selection retained
- conflicting active request: conflict/retry response

Raw provider bodies are never returned.

### 7.2 Conciseness endpoint

`POST /projects/{project_id}/conciseness` performs no provider call. It loads the selected artifact, verifies freshness/integrity, and returns per-span semantic score, score source, deterministic metrics, and rationales. If the artifact is stale or malformed it fails and retains the previous projection; it does not recalculate a new semantic run implicitly.

### 7.3 Progress and player

The topic stage carries additive safe fields such as `backend_label`, `cache_hit`, `source_fresh`, `last_good_preserved`, and `warning_code`. Both ingest processing status and player interstitial render them consistently. The ready calculation requires a selected, fresh, valid topic artifact and matching selected DB projection.

The timeline-state/summary response includes semantic run provenance and each span's rich analysis. The topic lane remains a compact lane; focus/click reveals the accessible span detail rather than stacking large cards on mobile.

## 8. Failure and recovery matrix

| Failure | Behaviour | Last-known-good |
|---|---|---|
| Missing/unaccepted transcript | Fail before cache/provider; stage prerequisite error | Retained but stale if source changed |
| Timeout/429/5xx | One bounded retry/repair policy, then next configured live provider may restart the whole run | Unchanged |
| Auth/config 4xx | No same-provider retry; next explicit live provider or fail | Unchanged |
| Empty/malformed/partial output | Strict rejection; one repair; discard whole provider attempt if still invalid | Unchanged |
| Foreign IDs/timestamps/thinking/HTML | Security/schema rejection | Unchanged |
| Coverage/stitch failure | Reject before persistence | Unchanged |
| Immutable write failure | Record safe stage failure if possible | Unchanged |
| DB transaction failure | Roll back run selection and all compatibility rows | Unchanged |
| Derived pointer write failure | Mark reconciliation warning and rebuild from selected immutable run | New DB selection remains authoritative and complete |
| App restart during run | In-process run becomes error; any unselected immutable artifact remains audit-only | Previous selected run remains |
| Downstream sees source mismatch | Refuse readiness/use | Retained, labelled stale |

## 9. Test data

### 9.1 Git-tracked fictional fixtures

Create small fictional JSON fixtures containing:

- two speakers and an obvious topic shift
- a topic crossing a chunk boundary
- filler-heavy and concise spans
- silence gaps and adjacent segment boundaries
- overlap with multiple authoritative speaker IDs
- Unicode punctuation and names that are entirely fictional
- a transcript line attempting prompt injection
- malformed variants for every strict-boundary test

No real names, source paths, recordings, or copied private transcript text are allowed.

### 9.2 Consent-cleared acceptance data

After upstream speech acceptance, use the golden-set structure already defined in the WhisperX roadmap: single-speaker, multi-speaker, and overlap/noise excerpts. Topic acceptance also needs at least one longer interview excerpt that crosses multiple semantic chunks. Keep files under private DATA_ROOT; commit only a redacted manifest and hashes/aggregate metrics.

Peter's editorial checklist is required for each accepted live model:

1. Topic boundaries correspond to meaningful changes and do not omit a major section.
2. Labels distinguish topics and are useful in review.
3. Summaries contain no invented names, claims, or conclusions.
4. LLM conciseness scores are defensible next to WPM/filler/duration metrics.
5. Any disagreement warning is understandable and does not conceal either score source.

## 10. Observability

Emit one structured event per run start/cache/result, provider attempt, chunk operation, validation outcome, persistence selection, and reconciliation. Include only IDs, hash prefixes, safe provider/model identity, counts, duration, result/error code, and call budget. Do not log transcript excerpts, prompts, full provider responses, HTTP authorization headers, credential presence, or arbitrary upstream error bodies.

Failure artifacts are immutable and bounded. They contain stage/code, run/source/config identifiers, attempt metadata, and response digest only. Normal project deletion removes them with project data.

## 11. Unraid deployment, rollback, and acceptance gates

### 11.1 Read-only discovery before any future deployment

Verify on Peter's Unraid host without mutation:

- CPU/RAM and V100/VAAPI device visibility
- Docker/Compose topology and host-network implications
- ports, reverse proxy, volumes, appdata/cache placement, ownership, and permissions
- central MySQL connectivity and backup destination
- Ollama model identity/digest, context configuration, health, and competing GPU workloads
- existing AUTOEDIT health/readiness and rollback image

Do not print secret values.

### 11.2 Deployment sequence (future explicitly approved task only)

1. Confirm `TEST_PASS`, `DESIGN_COMPLIANCE_PASS`, and Peter's required live-backend/editorial gates.
2. Back up central MySQL and record current image/config identifiers.
3. Render merged Compose and verify `TOPIC_BACKEND=mock` for the first software deployment.
4. Run the additive migration command; inspect that only the two new tables were created.
5. Build/recreate only the AUTOEDIT app as authorized; do not prune production data or alter Unraid templates.
6. Verify health/readiness, auth, mock zero-network behaviour, progress UI, selected-run persistence, logs, and browser console/network.
7. Enable `ollama` only in a separate approved config change after local acceptance and upstream transcript acceptance.
8. Never enable a direct external provider without the separate consent/credential gate.

### 11.3 Rollback

1. Pin `TOPIC_BACKEND=mock` immediately for semantic-provider incidents.
2. Restore the prior app image and prior Compose environment.
3. Restore DB backup only if additive migration or selected projections are corrupted; otherwise leave additive tables/artifacts because the prior app ignores them.
4. Verify prior topic/summary/player behaviour and health.
5. Preserve failure evidence and do not delete private artifacts unless Peter authorizes cleanup.

## 12. Implementation packages and ownership

Each package is sized for one Programmer worktree. They must land in order and receive independent Designer compliance review before Tester execution.

### Package P7-A — strict contracts and deterministic pure core

Requirements: `ARCH-P7-003`, `ARCH-P7-008`, `ARCH-P7-012`, `BACKEND-P7-001`–`BACKEND-P7-015`, `SEC-P7-005`–`SEC-P7-006`, `TEST-P7-001`–`TEST-P7-006`.

Owned files:

- new `src/autoedit/ai/semantic_transcript.py`
- new `src/autoedit/ai/topic_contracts.py`
- new `src/autoedit/topic_analysis.py`
- refactor `src/autoedit/conciseness.py`
- new fictional fixtures under `tests/fixtures/semantic_topics/`
- new focused tests such as `tests/test_topic_contracts.py` and `tests/test_topic_analysis.py`

Acceptance: pure tests prove strict source/output validation, deterministic chunk ownership/stitching, source-owned times, coverage, summaries/citations, and separate scores. No HTTP, DB, API, or UI changes.

### Package P7-B — provider runner, Ollama adapter, cache, persistence, and API integration

Depends on P7-A.

Requirements: remaining `ARCH-*`, `BACKEND-P7-016`–`BACKEND-P7-030`, `OPS-P7-001`–`OPS-P7-007`, `SEC-P7-001`–`SEC-P7-004`, `SEC-P7-007`–`SEC-P7-010`, and `TEST-P7-007`–`TEST-P7-016`.

Owned files:

- new `src/autoedit/ai/semantic_providers.py`
- new `src/autoedit/ai/topic_artifacts.py`
- refactor `src/autoedit/llm_client.py`
- refactor compatibility facade `src/autoedit/topics.py`
- `src/autoedit/config.py`
- `src/autoedit/db/schema.py`
- `src/autoedit/db/migrate.py` plus an explicit migration entry script if needed
- relevant topic/conciseness/progress/summary/timeline/pipeline sections of `src/autoedit/api.py`
- `src/autoedit/progress.py`
- `src/autoedit/report.py`
- `docker-compose.yml` and environment documentation only to pin mock
- focused provider/artifact/API/migration tests and updates to existing topic/conciseness tests

Acceptance: fake-provider tests cover all retry/fallback/error paths and call counts; mock opens no socket; Ollama outbound payload is asserted; cache/concurrency/fault injection preserves last-known-good; targeted and full mock-backed suites pass.

Coordination: this package owns any shared `llm_client.py` hardening first. The in-progress Stage 9.2 title card must rebase and reuse the resulting client/provenance contract rather than independently overwriting it.

### Package P7-C — visible states and accessible review UI

Depends on P7-B compliance pass.

Requirements: all `UI-P7-*`, `OPS-P7-005`–`OPS-P7-006`, and `TEST-P7-017`.

Owned files:

- `src/autoedit/web/app.html`
- `src/autoedit/web/app.js`
- `src/autoedit/web/index.html`
- `src/autoedit/web/player.js`
- relevant CSS only
- JS/static/API rendering tests

Acceptance: real browser evidence for desktop and narrow/mobile mock/live/cache/fallback/error/stale states; keyboard and live-region checks; no console errors or failed unexpected requests.

### Package P7-D — local Ollama and editorial acceptance

Depends on P7-A through P7-C compliance and on accepted upstream speaker-attributed transcript evidence.

No product-code ownership unless acceptance exposes a bounded defect. Owns a private run log and redacted plan evidence under `docs/plans/`.

Requirements: `OPS-P7-008`–`OPS-P7-011`, `TEST-P7-018`–`TEST-P7-020`.

Acceptance: exact local model evidence, Unraid resource/coexistence evidence, consent-cleared artifacts, Peter editorial sign-off, and a production-readiness verdict. This is not permission to deploy or flip production.

### Future package P7-E — direct external provider

Blocked pending the human decisions in section 3.3. It must use a direct named adapter, preserve the same contracts, prove direct endpoint identity, pass privacy/security review, and test direct-primary/local-fallback coherently. It must not use OpenRouter. P7-E is not required for P7-A through P7-D local closure.

## 13. Non-goals

- Implementing Stage 9.2 title generation or Stage 7.1/7.2 natural-language editing.
- Changing speech transcription, diarization, identity authority, sync algorithms, proxy encoding, or source playback.
- Letting the model author timestamps, colours, speaker identity, cut decisions, or sync offsets.
- Adding a user-facing provider/model picker.
- Deploying, changing production Compose, migrating production DB, or enabling live providers.
- Treating fictional/fake-provider tests as editorial or hardware acceptance.
- Completing the future direct external provider decision by assumption.

## 14. Compliance evidence expected

For every requirement ID, compliance review must inspect the actual source and diff, execute focused tests, inspect the complete selected artifact/DB projection, and review browser/runtime evidence. The matrix must identify evidence and pass/fail per ID. Summaries from the Programmer are not proof.

Minimum commands/evidence after all code packages:

- focused contract/chunk/conciseness/provider/artifact/API tests
- migration and project-deletion tests on SQLite and, where available, a disposable MySQL database
- full mock-backed `pytest`
- changed-file lint/type/compile/static checks used by the repository
- rendered Compose proving mock pin and no external/OpenRouter variable
- browser screenshots at desktop and narrow/mobile widths
- console and network inspection
- artifact hash, cache, restart-reconciliation, and last-known-good fault evidence
- explicit route report: Designer, Programmer, and Tester effective providers; whether OpenRouter was used

## 15. Residual risks

1. Semantic grounding cannot be proven by schema/citations alone; Peter's editorial review remains mandatory.
2. Provider model/version drift can change quality under the same human-readable model tag. Live acceptance should capture an immutable digest where the provider exposes one.
3. Long interviews may make all-or-nothing provider fallback costly. The coherent-run rule is intentionally preferred over mixed-provider inconsistency; measured limits may justify later checkpointing without changing publication semantics.
4. The upstream accepted speaker-attributed transcript is a hard live prerequisite and is not yet production-authoritative.
5. `create_all()` is not a general migration framework. This design avoids column alteration, but explicit pre-start migration and backup evidence are still mandatory.
6. The working tree contains concurrent uncommitted work. Programmer cards must use project worktrees, inspect the final merge boundary, and avoid overwriting unrelated changes.

## 16. Verdict

**DESIGN_APPROVED**

P7-A through P7-C are implementable without external credentials, production mutation, private media, or an accepted local GPU. P7-D remains an acceptance gate, not a coding prerequisite. P7-E requires a future explicit user decision and direct-provider acceptance; its deferral does not justify OpenRouter or silent mock fallback.
