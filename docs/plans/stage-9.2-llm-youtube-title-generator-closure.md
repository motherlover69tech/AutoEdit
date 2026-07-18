# Stage 9.2 LLM-backed YouTube title generator closure

Status: **DESIGN_APPROVED**  
Design task: `t_e21f35dc`  
Scope: specification only; no product code, tests, production data, deployment, or publishing changed by this card.

## 1. Outcome

Stage 9.2 will replace the current four-category, template-only title endpoint with an explicit, opt-in title-generation service that can use the existing local Ollama client and that always returns a server-validated, strategy-grouped contract. The same service will have a deterministic mock backend for the ordinary suite and safe production baseline. The review player will expose generation, per-strategy regeneration, and per-title copy without persisting generated titles.

The five canonical strategies, in stable display order, are:

1. `curiosity_gap` — Curiosity gap
2. `controversy` — Controversy
3. `named_guest` — Named guest
4. `listicle` — Listicle
5. `plainspoken` — Plainspoken

The current `descriptive`, `clickbait`, `question`, and `short` taxonomy is a useful template proof, but it is not a compatibility contract for Stage 9.2. It must not be relabelled as model output. The new endpoint contract intentionally replaces that internal pre-release shape with the five source-spec strategies.

## 2. Evidence inspected

### Verified facts

- `jobs/BACKLOG.md:433-440` marks Stage 9.2 in progress because only a four-category template baseline exists.
- `AI_HANDOFF.md:88`, `AI_HANDOFF.md:121`, and `docs/plans/TESTING_STRATEGY.md:28` make the same template-only limitation explicit.
- `docs/source/multicam_autoedit_spec.md:790-800` requires topics plus summaries, five labelled strategies, grouped JSON, per-strategy regeneration, individual copy, defensive parsing, configurable prompt templates, context control, and input-hash caching.
- `src/autoedit/title_generator.py` is synchronous, template-based, and produces a flat `titles` array with `descriptive`, `clickbait`, `question`, and `short` types.
- `tests/test_titles.py` covers that template function but does not exercise the API, auth, model output, malformed JSON, a UI, or regeneration.
- `src/autoedit/api.py:3529-3545` exposes authenticated `POST /projects/{project_id}/titles`, reads `transcript/summary.json`, and calls the template function. It has no request body and no UI caller.
- `src/autoedit/report.py` shows that `summary.json` already contains topic labels, each topic's span summaries and speaker-time labels, and aggregate totals. No source media is needed for title generation.
- `src/autoedit/llm_client.py` already supports Ollama `/api/chat`, JSON Schema, `think=false`, `keep_alive`, bounded connect/read timeouts, and parsed JSON. Its current HTTP error log includes response text and therefore needs redaction before this feature relies on it for private summaries.
- `src/autoedit/config.py` has `OLLAMA_BASE_URL` and `LLM_MODEL` defaults but no explicit feature backend selector. Merely having those values must not activate title-model traffic.
- `docker-compose.yml` is one host-networked app behind Nginx Proxy Manager, with central MySQL, the existing local Ollama URL, `/data` media, and VAAPI `h264_vaapi`. Speech and diarization remain explicitly mock-backed.
- `src/autoedit/web/index.html`, `player.js`, and `styles.css` implement the review/refine/export surface. There is currently no title UI. The established responsive breakpoint is 900 px.
- `docs/source/multicam_ui_style_guide.html` requires restrained controls, one clear primary action, direct error copy, mono machine-state text, Signal Red for action, disabled states, and a linear refine/export flow.
- The deterministic checkpoint command explicitly clears Ollama/model settings. Stage 9.2 must strengthen this with an explicit title backend rather than depend on empty URL/model values.
- The repository was already dirty before this design card. The title generator, title tests, API title route, LLM client, review-player files, Compose file, and `.env.example` had no pre-existing diff when inspected.

### Provider preflight for this design card

- Effective Designer profile: `openai-codex` / `gpt-5.6-sol`.
- Fallback provider list: empty; MoA disabled; all auxiliary categories are pinned to the same route.
- Minimal live completion returned exactly `DESIGNER_ROUTE_OK`; its usage record reported `provider=openai-codex`, `model=gpt-5.6-sol`, `api_calls=1`, and no error.
- OpenRouter was not used.

### Assumptions

- An explicit, non-generic speaker label in `summary.json` is eligible for the `named_guest` strategy. Current summary data does not distinguish host from guest, so the UI will retain the source-spec label but will tell the operator to verify names and claims before publishing.
- Three titles per strategy is the UI default; the API supports one through five.
- A maximum title length of 100 Unicode characters matches the YouTube title limit and is an output-validation rule, not an editorial score.
- A bounded in-process cache is operational recompute avoidance, not user persistence. It is cleared on app restart and never written to project storage or the database.
- The existing single-process app can serialize title-model calls in-process for this bounded slice. A distributed queue is outside Stage 9.2.

### Unknowns and residual decisions

- The summary contract does not identify which named speaker is the guest. This is surfaced for operator verification rather than guessed.
- The model-quality threshold is editorial, not derivable from schema tests. Peter must provide the final quality confirmation described in Section 12; exact private titles need not be retained.
- No deployment is authorized. The production title backend remains mock until a separate approved release task changes it.

### User decisions

No blocking decision is required to implement and test this bounded design. Peter's later model-quality confirmation is an acceptance gate, not a prerequisite for implementation.

## 3. Architecture and data flow

```text
Authenticated review-player panel
  -> POST /projects/{project_id}/titles
     -> strict TitleGenerationRequest
     -> read and validate transcript/summary.json
     -> canonical, bounded title context + SHA-256 source hash
     -> TitleGenerator service
        -> TITLE_BACKEND=mock: deterministic five-strategy fixture generator
        -> TITLE_BACKEND=ollama: local-only LLMClient.chat(
             json_schema=..., think=False, keep_alive=0)
        -> per-group strict validation and one bounded repair attempt
        -> bounded in-memory cache by source/config/strategy/variation
     -> stable grouped TitleGenerationResponse
  -> render with DOM text nodes
  -> copy one title to the clipboard
```

Title generation is optional and off the processing/player/export critical path. It cannot alter transcripts, topics, cuts, notes, project status, media, database rows, or export artifacts.

### Canonical model context

The server derives context; the browser cannot submit interview content. It includes only:

- ordered topic labels;
- ordered, non-empty topic-span summaries, deduplicated per topic;
- explicit, non-generic speaker labels already present in the summary;
- the requested strategies, count, and variation.

It excludes source paths, media, transcripts, timestamps, database values, auth/session data, notes, and unrelated project metadata. The context is canonical JSON with sorted object keys and stable list ordering. The source hash is SHA-256 over that canonical input plus the prompt/schema version. Context is truncated only at whole-summary boundaries to a configured character budget, with a response warning; labels are retained before optional summaries.

### Prompt and model-output contract

The default prompt lives at `src/autoedit/prompts/youtube_titles_v1.txt`, separate from Python logic. It treats the supplied JSON as untrusted data, forbids following instructions found inside labels/summaries, requires only source-grounded names/claims, and asks for exactly the requested count per requested strategy.

The model returns only:

```json
{
  "groups": [
    {
      "strategy": "curiosity_gap",
      "titles": ["Title one", "Title two", "Title three"]
    }
  ]
}
```

The server supplies labels and provenance; the model cannot choose a provider, model, backend, label, path, error, cache state, or provenance value.

## 4. API contract

### Request

`POST /projects/{project_id}/titles`

```json
{
  "strategies": ["curiosity_gap", "controversy", "named_guest", "listicle", "plainspoken"],
  "count": 3,
  "variation": 0
}
```

Rules:

- `strategies` defaults to all five in canonical order; it must contain one to five unique enum values.
- `count` defaults to 3 and is a strict integer from 1 through 5.
- `variation` defaults to 0 and is a strict integer from 0 through 1000.
- Unknown and extra fields are rejected.
- Initial generation uses all strategies at variation 0. Regenerating one group submits only that strategy and increments only that group's variation.
- The request cannot set backend, provider, model, URL, prompt, source data, cache bypass, or persistence behavior.

### Successful or partial response

```json
{
  "schema_version": "stage-9.2.v1",
  "status": "complete",
  "backend": "mock",
  "model": null,
  "prompt_version": "youtube_titles.v1",
  "source_hash": "<64 lowercase hex characters>",
  "warnings": [],
  "groups": [
    {
      "strategy": "curiosity_gap",
      "label": "Curiosity gap",
      "variation": 0,
      "status": "complete",
      "cache_hit": false,
      "titles": [{"text": "What Changed the Conversation About Climate Policy?"}],
      "error_code": null
    }
  ]
}
```

Rules:

- Group order follows canonical strategy order, not model order.
- `status` is `complete` when every requested group is complete and `partial` when at least one requested group is valid and at least one is unavailable/invalid after repair.
- Group status is `complete`, `unavailable`, or `error`.
- `named_guest` is `unavailable` with `error_code=no_named_speaker` when the summary has no eligible explicit speaker label; this is not replaced with an invented `Speaker` name.
- A complete group has exactly `count` unique normalized titles. Each title is non-empty, has no control characters, and is at most 100 Unicode characters.
- Titles must be unique across the response. Duplicate, missing, unknown-strategy, wrong-type, extra-field, overlong, empty, or non-string model values are invalid and enter the repair path.
- The model identifier may be returned; the base URL, prompt text, source text, and internal exception are never returned.
- `warnings` may contain stable non-sensitive codes such as `context_truncated`; it never contains source excerpts.

### Error mapping

- `400`: summary missing, unreadable, oversized, malformed, or lacking any usable topic label/summary.
- `401`: authentication required through the existing middleware.
- `403`: existing Origin policy rejection.
- `404`: project not found.
- `422`: strict request validation failure.
- `502`: live backend returned no valid group after the initial and one repair attempt.
- `503`: selected title backend is unavailable/misconfigured, the local Ollama URL is not allowed, or the configured model is unavailable.
- `429`: optional bounded concurrency rejection if the one active plus one waiting request capacity is exhausted.

All failures use JSON and a stable, operator-actionable `detail`/error code. They do not silently substitute template titles in `ollama` mode.

## 5. Stable requirements

### Architecture

- **ARCH-9.2-01** — Add `TITLE_BACKEND` as an explicit `mock|ollama` setting whose default is `mock`; non-empty `OLLAMA_BASE_URL`/`LLM_MODEL` values alone must never activate title-model traffic.
- **ARCH-9.2-02** — Isolate title context construction, prompt rendering, model/mock execution, validation/repair, and cache behavior in `title_generator.py`; keep the API route thin and dependency-injectable for tests.
- **ARCH-9.2-03** — Use exactly the five stable strategy keys and canonical order defined in Section 1; do not present the old four-category templates as Stage 9.2 output.
- **ARCH-9.2-04** — The Ollama path must reuse `LLMClient.chat` with a JSON Schema, `think=false`, bounded token output, and `keep_alive=0`; it must not add a second AI HTTP implementation.
- **ARCH-9.2-05** — Derive a bounded context from topic labels, topic-span summaries, and explicit speaker labels only; title generation must not read or send source media or a full transcript.
- **ARCH-9.2-06** — Keep the default prompt in a versioned template file separate from Python behavior and include its version in cache keys, logs, and responses.
- **ARCH-9.2-07** — Use a bounded, process-memory-only LRU cache keyed by source hash, backend, exact model, prompt/schema version, requested strategy, count, and variation; configure a finite maximum and clear it on restart.
- **ARCH-9.2-08** — Make regeneration stateless and strategy-scoped through the `variation` request value; no database row, project artifact, cookie, or browser storage is required.
- **ARCH-9.2-09** — Serialize local title-model inference to one active request per app process and bound waiting work; UI actions remain request/response operations rather than pipeline jobs.
- **ARCH-9.2-10** — Keep Stage 9.2 additive and off the processing, player playback, cut, note, and export critical paths.

### Backend and API

- **BACKEND-9.2-01** — Implement the strict request contract in Section 4 with enum, uniqueness, range, and extra-field rejection.
- **BACKEND-9.2-02** — Implement the `stage-9.2.v1` response contract exactly, including stable provenance, per-group status, per-group cache state, and server-owned labels.
- **BACKEND-9.2-03** — Make the endpoint async so Ollama I/O does not block the event loop; preserve existing project lookup, authentication, and Origin behavior.
- **BACKEND-9.2-04** — Catch file, size, Unicode, and JSON failures while reading `summary.json` and map them to stable 400 responses rather than unhandled 500s.
- **BACKEND-9.2-05** — Canonicalize context deterministically and compute the source hash without exposing summary content.
- **BACKEND-9.2-06** — The mock backend must return all available requested groups deterministically for identical canonical input, count, and variation, and must produce a different deterministic set for the next supported variation.
- **BACKEND-9.2-07** — The mock backend must make zero DNS, HTTP, provider, GPU, or external-service calls even when Ollama/model environment values are populated.
- **BACKEND-9.2-08** — The Ollama backend must request only the requested groups and exact count, including the variation in the prompt/cache identity.
- **BACKEND-9.2-09** — Validate model output per group after JSON decoding; JSON mode alone is not acceptance.
- **BACKEND-9.2-10** — Retry malformed, missing, duplicate, or invalid groups once with a bounded repair request that names only invalid/missing strategy keys and contains no previously valid title text.
- **BACKEND-9.2-11** — Preserve valid groups and return `partial` with stable group error codes when repair still leaves some requested groups invalid; never mix rejected model values into the response.
- **BACKEND-9.2-12** — Return 502 when no requested group remains valid after repair; do not fall back silently to mock/template output in `ollama` mode.
- **BACKEND-9.2-13** — Serve an exact cache hit without a model call and set `cache_hit=true`; a new variation must use a distinct key.
- **BACKEND-9.2-14** — Treat generic/empty speaker labels as ineligible for `named_guest`; return the group as explicitly unavailable rather than inventing a person.
- **BACKEND-9.2-15** — Normalize surrounding/internal whitespace, preserve Unicode, enforce the 100-character limit, and reject controls, wrong types, and empty values.
- **BACKEND-9.2-16** — Enforce title uniqueness within and across returned groups; invalid duplicates take the repair path.
- **BACKEND-9.2-17** — Accept no client-selected backend/provider/model/URL/prompt or source-summary body.
- **BACKEND-9.2-18** — Redact `LLMClient` HTTP error logging so response bodies and model output cannot be logged; preserve status and error class only.
- **BACKEND-9.2-19** — Inject or construct one title service at app creation so tests can select mock/fake behavior without mutating global clients or making network calls.
- **BACKEND-9.2-20** — Remove/update old four-category assertions and document the pre-release response replacement; do not keep a misleading flat compatibility alias in the new API.

### UI and accessibility

- **UI-9.2-01** — Add a full-width “YouTube titles” panel in the review player's refine area after Cut Parameters and before Export.
- **UI-9.2-02** — The idle panel must explain that suggestions use project topics/summaries, are not saved, and must be verified before publishing.
- **UI-9.2-03** — Provide one Signal Red primary `Generate titles` action; do not auto-generate on player load or page navigation.
- **UI-9.2-04** — Render all five strategy sections in canonical order, with headings and plain-language descriptions supplied by the UI, not the model.
- **UI-9.2-05** — Each complete strategy section must have its own `Regenerate <label>` button and each title its own visibly button-like `Copy` action.
- **UI-9.2-06** — Regenerating one strategy must increment only its variation, send only that strategy, preserve all other rendered groups, and replace that group only with the latest successful response.
- **UI-9.2-07** — While all groups generate, disable duplicate generation actions and announce concrete progress. While one group regenerates, disable only that group's action and preserve/copy other titles.
- **UI-9.2-08** — Ignore stale/out-of-order responses using a request sequence or cancellation mechanism so rapid actions cannot overwrite newer state.
- **UI-9.2-09** — Show the returned backend truth near the results as `Deterministic mock` or `Local LLM · <model>`; never label mock output as AI/model output.
- **UI-9.2-10** — Complete, partial, unavailable, empty, network/model failure, auth redirect, and copy success/failure states must use direct, actionable copy and retain valid prior groups where safe.
- **UI-9.2-11** — Render every model/title/error-derived value with `textContent`/text nodes; do not interpolate it into `innerHTML`.
- **UI-9.2-12** — Copy uses the secure Clipboard API with an explicit safe fallback or explicit failure state; it must never trigger save/publish behavior.
- **UI-9.2-13** — Use a polite `role=status`/`aria-live` region for generation and copy outcomes; errors use an assertive alert only when operator action is required.
- **UI-9.2-14** — Every action must be reachable and operable by keyboard, retain a visible focus indicator, have an unambiguous accessible name, and restore focus to the triggering control after completion/failure.
- **UI-9.2-15** — At widths above 900 px, strategy sections may use two columns with sufficient contrast; at 900 px and below they become one column without horizontal page scrolling.
- **UI-9.2-16** — At 390 px width, title text and its copy control must wrap/stack without truncating the title, action controls must remain at least 44 px high, and nonessential strategy descriptions may collapse while titles/actions remain visible.
- **UI-9.2-17** — Loading and state changes must not move focus, autoplay media, reload the page, or interrupt program-audio playback.
- **UI-9.2-18** — Generated titles exist only in current page memory; reload/navigation clears them and no local/session storage is used.

### Security and privacy

- **SEC-9.2-01** — The existing session and Origin gates protect the title endpoint; add direct unauthenticated and disallowed-Origin regressions.
- **SEC-9.2-02** — `TITLE_BACKEND=ollama` may call only an explicitly configured local Ollama endpoint whose hostname is `localhost` or a literal loopback/private/link-local IP; reject public/unknown hosts before I/O.
- **SEC-9.2-03** — Do not add OpenRouter as primary, fallback, auxiliary, delegated, or hidden routing. No OpenRouter URL, SDK, key, or environment variable belongs in this feature.
- **SEC-9.2-04** — Treat labels and summaries as untrusted prompt data, delimit canonical JSON from instructions, and tell the model not to execute embedded instructions.
- **SEC-9.2-05** — Never log prompt text, summary text, title text, model response bodies, source paths, cookies, secrets, or private media identifiers.
- **SEC-9.2-06** — Structured logs may contain only project ID, request/correlation ID, source-hash prefix, backend, model name, prompt version, requested strategy keys, variation, cache state, attempt count, elapsed time, outcome, and stable error code.
- **SEC-9.2-07** — Do not persist generated titles, prompts, summaries, or responses to MySQL, project directories, appdata, browser storage, analytics, or tracked fixtures.
- **SEC-9.2-08** — Keep model credentials and deployment secrets outside Git and never return them or the configured base URL to the browser.
- **SEC-9.2-09** — Bound request values, context size, model output tokens, title count/length, cache entries, retries, timeout, and concurrent work to prevent authenticated resource exhaustion.
- **SEC-9.2-10** — Render adversarial HTML/script strings as inert text and verify that copying does not execute or reinterpret them.

### Operations and deployment

- **OPS-9.2-01** — Pin `TITLE_BACKEND: mock` in canonical `docker-compose.yml`; stale `.env` values must not activate live title inference.
- **OPS-9.2-02** — Document `TITLE_BACKEND`, local-only URL rules, prompt/schema version, context/cache bounds, timeout, and model configuration in `.env.example` and `docs/DEPLOYMENT.md` without real credentials.
- **OPS-9.2-03** — Preserve one host-networked app, NPM at `ingest.peteflix.uk`, central MySQL, `/data` mounts, auth, health check behavior, and port 8010; add no database or public AI service.
- **OPS-9.2-04** — Preserve VAAPI `h264_vaapi`; do not add QSV, CUDA, media-volume, source-playback, Whisper, diarization, or proxy changes.
- **OPS-9.2-05** — `keep_alive=0` and serialized title inference must release the local model after a request and avoid concurrent title loads; do not claim GPU coexistence acceptance without measurement.
- **OPS-9.2-06** — `/health` remains app liveness. Title backend readiness is request-scoped and an Ollama failure produces an actionable title error without failing player/app health.
- **OPS-9.2-07** — No production mutation or deployment belongs to implementation/compliance/Tester cards. A later release task requires backup, rendered Compose review, controlled rebuild, health/auth/browser smoke, logs, and rollback evidence.
- **OPS-9.2-08** — Deployment rollback is the prior image/commit plus `TITLE_BACKEND=mock`; generated titles require no DB/data rollback because none are persisted.
- **OPS-9.2-09** — Update `AI_HANDOFF.md`, `jobs/BACKLOG.md`, and `docs/plans/TESTING_STRATEGY.md` only after implementation evidence; retain `in_progress` until design compliance, independent Tester acceptance, and Peter's quality gate pass.
- **OPS-9.2-10** — Private/consent-controlled summaries and derived titles remain untracked; committed fixtures use fictional names and topics only.

### Tests and acceptance evidence

- **TEST-9.2-01** — Unit-test the exact five-strategy taxonomy/order, context extraction, canonical hash, whole-summary truncation warning, normalization, limits, duplicate rejection, and named-speaker eligibility.
- **TEST-9.2-02** — Unit-test deterministic mock equality for identical input/variation and deterministic difference for the next variation across every strategy.
- **TEST-9.2-03** — Prove mock mode performs zero network/client calls even with populated Ollama settings.
- **TEST-9.2-04** — Test strict request rejection for duplicate/unknown/empty strategies, booleans masquerading as integers, count/variation bounds, and extra/provider fields.
- **TEST-9.2-05** — API-test auth, Origin, missing project, missing/malformed/oversized/empty summary, success, partial success, total model failure, and stable status/error mapping.
- **TEST-9.2-06** — Fake Ollama responses for malformed JSON, wrong top-level type, absent groups, unknown/duplicate strategy, partial group, wrong title type, empty/control/overlong title, extra fields, and duplicate titles.
- **TEST-9.2-07** — Verify exactly one repair attempt, repair scope contains only invalid/missing keys, valid groups are retained, and no template fallback occurs in live mode.
- **TEST-9.2-08** — Verify cache hit/miss identity includes source hash, backend, model, prompt/schema version, strategy, count, and variation; verify LRU bound and restart-local behavior.
- **TEST-9.2-09** — Verify the Ollama request uses JSON Schema, non-thinking mode, output bound, and `keep_alive=0`, and rejects non-local configured URLs before transport.
- **TEST-9.2-10** — Verify logs and API errors contain no fictional fixture summary/title text, prompt text, response body, base URL, or secret.
- **TEST-9.2-11** — Extend static player tests for panel structure, labels, live regions, button types, and absence of inline source/model HTML.
- **TEST-9.2-12** — Extend direct Node tests for state merge, per-strategy variation, stale-response rejection, safe title-node construction, and copy success/failure behavior.
- **TEST-9.2-13** — Run a real local mock-backed browser flow at 1440x900: generate all, verify five grouped results/backend badge, regenerate only one group, copy one title, and retain other groups.
- **TEST-9.2-14** — Repeat the browser flow at 390x844 and verify no horizontal overflow, title/action wrapping, 44 px action height, keyboard order/focus, live announcements, and no program-audio interruption.
- **TEST-9.2-15** — Browser-inject adversarial title/error strings and prove no script/HTML execution, no page error, and inert copied text.
- **TEST-9.2-16** — Browser-test partial, total failure, named-guest unavailable, slow, and out-of-order responses while checking console errors and title-endpoint network status/body.
- **TEST-9.2-17** — Run targeted Python, Node, and browser commands, then the deterministic full suite with `TITLE_BACKEND=mock OLLAMA_BASE_URL='' LLM_MODEL=''`; no live endpoint may be contacted.
- **TEST-9.2-18** — Run compile, changed-file lint/static checks if configured, `git diff --check`, and a redacted `docker compose config` assertion that the app remains one host-networked service with `TITLE_BACKEND=mock` and VAAPI.
- **TEST-9.2-19** — On an authorized non-production run, use local Qwen with a fictional/consent-cleared summary for ten uncached all-strategy variations plus two regeneration variations per strategy (20 calls total); every call must return `complete`, schema-valid grouped JSON after at most one repair, with zero leaked/private log content.
- **TEST-9.2-20** — Peter must confirm from at least one consent-cleared review that the five strategy groups are recognizably distinct, names/claims are grounded, regeneration produces useful alternatives, and copy works. Retain only pass/fail, model/prompt version, aggregate call/repair counts, durations, and screenshots with fictional/redacted titles.
- **TEST-9.2-21** — Independent Designer compliance must map every requirement ID to source/diff/test/runtime/UI evidence and return `DESIGN_COMPLIANCE_PASS` before Tester dispatch.
- **TEST-9.2-22** — Independent Tester must return `TEST_PASS` with backend/API execution, real browser screenshots, console/network evidence, desktop/mobile/accessibility states, and the exact candidate commit before Stage 9.2 can be marked done.

## 6. Failure behavior

| Failure | Backend behavior | UI behavior | Persistence impact |
|---|---|---|---|
| No summary / no usable topics | 400 stable prerequisite error | Explain that summary/topic processing is required; keep Generate available only after retry | None |
| Mock selected | Deterministic grouped result, zero network | Badge says `Deterministic mock` | None |
| Local URL disallowed / model unavailable | 503, no fallback | “Local title model is unavailable. Check title backend configuration.” | None |
| Invalid JSON | Repair once; 502 if no valid group | Retain prior results; show Retry | None |
| Some groups invalid/missing | Repair invalid groups once; return partial if valid groups remain | Keep valid groups, failed group shows Retry | None |
| No eligible named speaker | Explicit unavailable group | Explain that an explicit speaker name is needed; do not invent one | None |
| Duplicate/overlong/unsafe model values | Reject affected group and repair | Never render rejected values | None |
| Timeout/network error | Stable 502/503 according to cause | Retain prior results and offer Retry | None |
| Out-of-order browser response | Server response remains valid | Client ignores stale response | None |
| Clipboard unavailable/denied | No backend call | Explicit `Copy failed — select the title and copy it manually.` | None |
| App restart | Cache and unsaved UI state disappear | Generate again | No rollback needed |

## 7. UI specification

### Placement and hierarchy

The title panel belongs between Cut Parameters and Export in `src/autoedit/web/index.html`. It is full-width, visually distinct from adjacent panels, and contains:

1. heading and one-line privacy/editorial instruction;
2. backend/result status line;
3. primary Generate button;
4. strategy result grid;
5. per-strategy regenerate actions and per-title copy actions.

No decorative hero, media preview, modal, toast-only feedback, or publishing control is added.

### State details

- **Idle:** instruction, Generate enabled, no empty strategy cards.
- **Generating all:** button label `Generating 5 strategies…`; all title actions disabled; polite status update.
- **Complete:** five ordered groups (or explicit named-guest unavailable state), backend truth, titles, copy actions, and regenerate actions.
- **Regenerating one:** that section says `Generating alternatives…`; other groups remain stable and operable.
- **Partial:** top status says which strategies need retry; valid groups remain; failed groups include a direct retry action.
- **Total failure:** prior successful groups remain if present; otherwise show one concise inline error and Retry.
- **Copy success:** triggering button temporarily says `Copied`; live region names the strategy, without repeating the private title.
- **Copy failure:** focus remains on Copy and adjacent direct instruction explains manual selection.

Desktop may use two strategy columns; the fifth naturally spans or occupies the next row. Mobile uses one column. Content order remains canonical in both layouts.

## 8. Observability

Emit one structured start and one completion/failure event per API request, plus a repair event when used. Required fields are limited by `SEC-9.2-06`. Log levels:

- info: start, complete, partial, cache hit/miss, elapsed time;
- warning: context truncation, repair attempt, unavailable named-guest group;
- error: transport/schema exhaustion with stable error class only.

No new metrics service or public readiness endpoint is required. Tester evidence should capture logs with fictional inputs and assert that private/source text is absent.

## 9. Bounded implementation package

### Programmer card A — backend/API contract

Depends on: this approved design.  
Exclusive ownership:

- modify `src/autoedit/config.py`
- modify `src/autoedit/llm_client.py`
- replace/refactor `src/autoedit/title_generator.py`
- create `src/autoedit/prompts/youtube_titles_v1.txt`
- modify the title route and app injection seam in `src/autoedit/api.py`
- replace/extend `tests/test_titles.py`
- create `tests/test_titles_api.py`
- extend `tests/test_llm_client.py`

Acceptance: `ARCH-*`, `BACKEND-*`, `SEC-9.2-01` through `SEC-9.2-09`, and `TEST-9.2-01` through `TEST-9.2-10` pass without product UI changes.

### Programmer card B — review UI, operational pin, and documentation

Depends on card A's exact candidate.  
Exclusive ownership:

- modify `src/autoedit/web/index.html`
- modify `src/autoedit/web/player.js`
- modify `src/autoedit/web/styles.css`
- extend `tests/player_logic.test.mjs`
- extend `tests/test_player_static.py`
- create `tests/browser/stage_9_2_titles.spec.cjs`
- modify `docker-compose.yml`
- modify `.env.example`
- modify `docs/DEPLOYMENT.md`
- update `AI_HANDOFF.md`, `jobs/BACKLOG.md`, and `docs/plans/TESTING_STRATEGY.md` truthfully without marking done

Acceptance: `UI-*`, `OPS-*`, `SEC-9.2-10`, and `TEST-9.2-11` through `TEST-9.2-18` pass. No production access or deployment.

The two-card split prevents overlap between backend/API and player/UI implementation while keeping each worktree bounded. Card B must start from or integrate card A; it must not invent a different API contract.

### Independent gates

1. Designer compliance review of the integrated candidate and every requirement ID.
2. Tester backend/API plus real browser run with screenshots, console/network evidence, desktop/mobile/accessibility states, and deterministic full-suite evidence.
3. Authorized local-Qwen acceptance and Peter's editorial quality confirmation (`TEST-9.2-19` and `TEST-9.2-20`).
4. Only then may backlog/handoff status change from `in_progress` to `done`, while separately stating whether production remains mock.
5. Deployment, if requested later, is a distinct Publisher task.

## 10. Verification commands

Commands are requirements for implementation/acceptance, not evidence claimed by this design card.

```bash
# Backend/API targeted
TITLE_BACKEND=mock OLLAMA_BASE_URL='' LLM_MODEL='' \
  env -u VIRTUAL_ENV uv run pytest \
  tests/test_titles.py tests/test_titles_api.py tests/test_llm_client.py -q -rs

# UI/static/direct Node
TITLE_BACKEND=mock OLLAMA_BASE_URL='' LLM_MODEL='' \
  env -u VIRTUAL_ENV uv run pytest tests/test_player_static.py tests/test_player_logic_js.py -q -rs
node --check src/autoedit/web/player.js
node tests/player_logic.test.mjs
node tests/browser/stage_9_2_titles.spec.cjs

# Full deterministic isolation gate
TITLE_BACKEND=mock OLLAMA_BASE_URL='' LLM_MODEL='' \
  env -u VIRTUAL_ENV uv run pytest -q -rs

# Compile and diff hygiene
env -u VIRTUAL_ENV uv run python -m compileall -q src tests
git diff --check

# Render only; use non-secret placeholders and assert topology/backend pin.
SESSION_SECRET=redacted OPERATOR_PASSWORD=redacted DB_PASSWORD=redacted \
  docker compose config
```

The real-model acceptance command/script must be added by the Programmer or Tester and must target only the approved local Ollama endpoint. It must not print prompts, summaries, titles, or secrets.

## 11. Deployment and rollback

This card does not authorize deployment. For a later approved release:

1. Discover the current Unraid container/image/restarts, rendered Compose, host-network port 8010, NPM route, central MySQL reachability, `/data` mounts/ownership, `/dev/dri`, health, and Ollama availability read-only.
2. Back up current deployment configuration and database using the established release process even though Stage 9.2 adds no schema.
3. Render Compose with secrets resolved at runtime and prove `TITLE_BACKEND=mock` unless the release explicitly authorizes local Ollama activation.
4. Build/pull the exact reviewed candidate; preserve the rollback image/tag.
5. Recreate only through the approved controlled release action.
6. Verify `/health`, auth, project/player, title mock flow, browser console/network, logs, restarts, and existing export smoke.
7. If live Ollama is explicitly enabled, run the bounded consent-cleared acceptance and confirm the model unloads; do not enable it silently through stale `.env`.
8. Roll back to the prior image/commit and `TITLE_BACKEND=mock` on health, auth, UI, schema, privacy, or resource regression. No generated-title data restore is needed.

## 12. Acceptance evidence matrix

| Requirement set | Mandatory evidence |
|---|---|
| `ARCH-9.2-*` | source/diff review of service boundaries, settings, prompt template, cache, and critical-path isolation |
| `BACKEND-9.2-*` | targeted unit/API output, mocked transport assertions, malformed/partial matrix, cache and error-mapping evidence |
| `UI-9.2-*` | exact-candidate screenshots at 1440x900 and 390x844, keyboard/focus/live-region checks, network trace, and zero console/page errors |
| `SEC-9.2-*` | auth/Origin tests, local-host rejection, adversarial prompt/output tests, redacted-log inspection, no persistence/secret diff |
| `OPS-9.2-*` | redacted Compose render, one-service/host-network/VAAPI/mock assertions, documentation diff, explicit no-deploy statement |
| `TEST-9.2-01..18` | command transcripts and artifacts from exact integrated candidate |
| `TEST-9.2-19` | authorized local-Qwen aggregate report: 20 uncached calls, complete count, repair count, durations, model/prompt/schema versions, no content |
| `TEST-9.2-20` | Peter's recorded pass/fail editorial confirmation and redacted/fictional UI evidence |
| `TEST-9.2-21` | independent `DESIGN_COMPLIANCE_PASS` matrix |
| `TEST-9.2-22` | independent `TEST_PASS` with exact candidate identity |

## 13. Risks and mitigations

| Risk | Mitigation |
|---|---|
| Template output is accidentally presented as AI | Explicit backend, provenance badge, no live-to-mock fallback |
| Model emits valid JSON with unsafe or structurally wrong values | JSON Schema plus per-group semantic validation and one bounded repair |
| A partial model result destroys useful titles | Preserve validated groups; replace only the requested/latest group in UI |
| Prompt injection in topic summaries | Server-built context, data delimiters, non-thinking structured prompt, strict output validation |
| Private interview content leaks to logs/external service | Summary-only local route, local-host allowlist, redacted logs, no OpenRouter/external fallback |
| Named-guest title invents or misroles a person | Explicit-label requirement, unavailable state, operator verification copy |
| Regenerate appears to do nothing in mock mode | Variation is explicit and deterministic, with tested alternate fixtures |
| Cache defeats regeneration | Variation is part of the key; per-group UI increments it |
| Cache conflicts with “store nothing” | Bounded memory only, no DB/disk/browser persistence, clear on restart |
| Concurrent title calls contend for Ollama/GPU | One active call, bounded wait, UI duplicate-action guard, `keep_alive=0` |
| Existing player playback regresses | Panel is off playback path; browser verifies no audio interruption |
| Dirty repository causes cross-feature contamination | Programmer worktrees use explicit ownership and exact candidate/diff review |
| Stage is marked done from implementation alone | Compliance, Tester, local-model, and Peter quality gates are mandatory |

## 14. Non-goals

- Saving, favoriting, ranking, publishing, uploading, scheduling, or analytics for titles.
- YouTube API integration, descriptions, tags, thumbnails, social clips, or SEO scoring.
- Replacing the broader semantic-provider roadmap or implementing DeepSeek/provider chaining.
- OpenRouter or any external routing fallback.
- Enabling real Whisper/diarization or making LLM output authoritative for transcript, identity, timing, cuts, or exports.
- Database migrations, project artifact writes, background queues, multi-process distributed caches, or a new service/container.
- Production deployment or mutation.
- Manual audio-sync workflow, proxy/source playback changes, QSV, or media handling changes.

## 15. Verdict

**DESIGN_APPROVED**

The implementation may proceed as the two bounded Programmer cards above. Stage 9.2 remains `in_progress` until the integrated candidate has `DESIGN_COMPLIANCE_PASS`, independent `TEST_PASS`, the authorized local-model evidence, and Peter's editorial confirmation. Production remains explicitly mock-backed unless a separate deployment task authorizes otherwise.
