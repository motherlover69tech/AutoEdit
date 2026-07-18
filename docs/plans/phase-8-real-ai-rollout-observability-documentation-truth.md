# Phase 8 — Real-AI rollout, observability, and documentation truth

**Status:** `DESIGN_APPROVED`

**Scope:** Design and implementation plan only. This document does not enable a real backend, move private media, deploy, mutate production, or approve a production cut.

**Roadmap phase:** Real-AI modernization Phase 8. This is not AUTOEDIT product Stage 8 (NLE export).

**Hard dependencies:**

1. `docs/plans/ai-gpu-1-acceptance-gates.md` must have an exact-candidate `DESIGN_COMPLIANCE_PASS` and independent `TEST_PASS`, and its Peter-only and target-GPU gates must be complete for the candidate being rolled out.
2. `docs/plans/consent-safe-golden-media-fixture-acceptance.md` must have an exact-candidate `DESIGN_COMPLIANCE_PASS` and independent `TEST_PASS`; a `consent_real` fixture must be `accepted` for any live-media acceptance run.
3. The candidate must retain the reviewed versioned speech-artifact, last-known-good, speaker-identity, speaker-turn, cut-reason, and immutable-fixture contracts from those plans. Phase 8 consumes those contracts; it does not recreate or weaken them.

**Production boundary:** The deployed app remains `WHISPER_BACKEND=mock` and `DIARIZE_BACKEND=mock` until every activation precondition in this plan passes and Peter explicitly authorizes a Publisher deployment card. Phase 8 implementation may be merged and deployed dormant; dormant code must not submit media to WhisperX.

## 1. Decision

Phase 8 introduces a fail-closed, per-project rollout control plane around the accepted speech pipeline. It does not turn a global environment switch into an uncontrolled migration.

The rollout sequence is:

1. `mock_only` — current production authority; no live worker submission.
2. `shadow` — one explicitly assigned consent-cleared project may run the real worker, but the candidate artifact and candidate cut are non-authoritative and cannot change playback, export, selected cut, or existing transcript projections.
3. `canary_review` — a validated candidate artifact may be reviewed with confirmed speaker mapping and a separately named candidate cut; the prior selected artifact/cut remains authoritative.
4. `canary_live` — Peter may explicitly promote the accepted artifact and accepted candidate cut for that one project through a compare-and-swap selection transaction. No other project changes.
5. `live_all` — deliberately unsupported by this Phase 8 implementation. Broad enablement needs a later design and a separate Peter decision informed by canary evidence.

A live-path failure never produces mock transcript text, silently reclassifies a shadow result as accepted, or replaces a last-known-good selection. In `shadow` and `canary_review`, the current production selection remains untouched. In `canary_live`, failure preserves or restores the prior accepted selection and marks the candidate stale/failed for operator action.

## 2. Sources inspected

- `AI_HANDOFF.md`
- `README.md`
- `jobs/BACKLOG.md`
- `docs/source/multicam_autoedit_spec.md`
- `docs/source/multicam_ui_style_guide.html`
- `docs/plans/TESTING_STRATEGY.md`
- `docs/DEPLOYMENT.md`
- `docs/plans/whisperx-speaker-aware-ai-roadmap.md`
- `docs/plans/ai-gpu-1-acceptance-gates.md`
- `docs/plans/ai-gpu-1-corrective-pickup.md`
- `docs/plans/consent-safe-golden-media-fixture-acceptance.md`
- `docs/plans/phase-7-llm-topic-segmentation-conciseness.md`
- `docs/ai/whisperx-evaluation-protocol.md`
- `docs/status/AUTOEDIT_PROGRESS_REPORTING.md`
- `docs/status/autoedit-progress.html`
- `.env.example`
- `.dockerignore`
- `docker-compose.yml`
- `docker-compose.gpu-ai.yml`
- `docker-compose.prod.yml`
- `Dockerfile`
- `scripts/autoedit-deploy.sh`
- `src/autoedit/api.py`
- `src/autoedit/config.py`
- `src/autoedit/progress.py`
- `src/autoedit/plog.py`
- `src/autoedit/transcribe.py`
- `src/autoedit/diarize.py`
- `src/autoedit/db/schema.py`
- `src/autoedit/ai/artifacts.py`
- `src/autoedit/ai/activity_from_turns.py`
- `src/autoedit/ai/gpu_measurement.py`
- `services/whisperx_service/app.py`
- `services/whisperx_service/jobs.py`
- `services/whisperx_service/Dockerfile`
- `services/whisperx_service/requirements.txt`
- `services/whisperx_service/requirements.lock`
- relevant speech, worker, artifact, cut, progress, player, golden-fixture, and deployment tests

## 3. Facts, assumptions, unknowns, and user decisions

### 3.1 Verified facts

1. Production is explicitly mock-backed for Whisper and diarization. The base Compose file pins both backends to `mock`.
2. The current app has an opt-in WhisperX transcription client and a separate loopback-only CUDA service overlay. The worker has liveness/readiness and an in-memory single-concurrency job queue.
3. The current application pipeline runs sequentially in an in-process background thread. App restart recovery marks interrupted processing as error; it is not a durable distributed job system.
4. The current public `/health` endpoint reports only app liveness. It does not report database readiness, worker readiness, model identity, queue health, or rollout state.
5. The project progress API and processing UI expose top-level `queued`, `running`, `done`, and `error` stage states, but not rollout authority, worker substage, queue age, candidate/selected artifact identity, last-known-good preservation, or recovery actions.
6. The current global `WHISPER_BACKEND` selection cannot safely express a one-project shadow/canary rollout by itself.
7. Existing local work includes versioned AI artifacts, synchronized analysis audio, strict validation, last-known-good behavior, speaker mapping, speaker-turn activity, auditable cut reasons, and GPU acceptance helpers. Those changes are concurrent/uncommitted in the inspected checkout and require independent compliance before Phase 8 consumes them.
8. `tests/fixtures/golden_interview/` is not an accepted real fixture. The approved golden-fixture design requires an external immutable `consent_real` package and Peter-bound approvals.
9. Current worker dependency inputs are hash locked, and the worker image uses a digest-pinned CUDA runtime base. A lock file alone is not proof that the exact built image, model revisions, and target-GPU behavior are accepted.
10. AUTOEDIT uses host networking. The worker is bound to `127.0.0.1`; NPM exposes only the app. `/data` is read-only in the worker overlay.
11. The app uses central MySQL in production, `/mnt/user/automulticam:/data`, NPM at `ingest.peteflix.uk`, and VAAPI `h264_vaapi` for proxies. The QSV path remains rejected while MFX session `-9` is unresolved.
12. Program audio is the review-player master clock; proxies are silent and source media is not browser-played.
13. Existing deployment automation backs up the central database/configuration, tags the prior image, renders Compose, recreates the app, verifies health/auth/NPM, and can restore the prior image. It does not yet deploy and verify the GPU overlay as an atomic, provenance-bound rollout unit.
14. README, handoff, backlog, deployment, testing, progress-dashboard, and roadmap documents currently state that production remains mock-backed. Those statements must remain until a verified canary activation occurs.
15. No Prometheus, Alertmanager, or approved notification sink is established in the inspected repository. Structured logs, bounded JSON status, and the authenticated app UI are available foundations.
16. The repository has concurrent modified and untracked files from the AI-GPU and golden-fixture work. A Phase 8 Programmer must start from an integrated, reviewed dependency commit rather than this mixed checkout.
17. Designer provider preflight for this task resolved to `openai-codex` / `gpt-5.6-sol`, with no fallback providers, MoA disabled, and auxiliary routes pinned to the same provider/model. The route checker printed that effective provider/model and a fresh minimal completion returned the expected `OK`. OpenRouter was not used.

### 3.2 Assumptions to validate

1. The accepted AI-GPU artifact layer will expose immutable run ID, artifact digest, source/config digest, model provenance, validation outcome, and selected/last-known-good operations without requiring Phase 8 to parse transcript content.
2. The accepted golden-fixture implementation will expose a redacted bundle ID and readiness state that Phase 8 can gate on without learning private paths, media hashes, names, or transcript excerpts.
3. The first production-topology canary can use a consent-cleared non-critical project or a separately imported fixture project without altering source media.
4. Peter can review the candidate artifact, speaker mapping, locked editorial windows, and candidate cut before any selection promotion.
5. Host monitoring can initially consume local structured status and logs. An external paging sink is useful but is not required to implement a safe one-project canary.
6. Adding new tables is compatible with the existing `metadata.create_all()` bootstrap; any future alteration of existing columns requires a separately accepted migration mechanism.

A false assumption fails the relevant gate. It does not authorize a substitute path.

### 3.3 Unknowns

1. The final accepted commit IDs, app image digest, worker image digest, model IDs/revisions, and config digest for the first canary.
2. The exact accepted private fixture bundle ID and first canary project ID.
3. The normal target-GPU latency distribution from enough accepted runs to set evidence-based runtime warnings.
4. The host-level GPU telemetry mechanism available to the container without broadening privileges.
5. Whether Peter wants a future external alert destination and, if so, which authenticated local service receives it.
6. Whether model caches are currently covered by backup and whether restoring them is desirable; model caches must not be treated as authoritative data.
7. The exact maintenance window for a future dormant deployment, shadow run, canary promotion, and rollback drill.

### 3.4 Peter-only decisions

Peter must explicitly decide or approve:

1. the exact consent-cleared fixture/project revision used for shadow and canary evidence;
2. consent, licensing, retention, backup treatment, and withdrawal handling through the golden-fixture contract;
3. the exact speaker identities/mappings and any unresolved/off-camera treatment;
4. every required word-timing and locked editorial-window verdict owned by AI-GPU-1;
5. the candidate cut before it becomes selected;
6. each transition from dormant to `shadow`, `shadow` to `canary_review`, and `canary_review` to `canary_live`;
7. the deployment and rollback window;
8. whether to configure a future external alert sink; and
9. any later broad rollout. `live_all` is not implied by approval of one canary.

The implementation may present evidence and choices, but it must not infer these decisions.

## 4. Architecture and authority model

### 4.1 Components

The accepted design adds four bounded components:

1. **Rollout policy store (main app / central MySQL):** immutable release records, per-project assignments, explicit transition records, and a selected release pointer. It stores no transcript text or private paths.
2. **Rollout coordinator (main app):** resolves the effective mode for one project, confirms prerequisites, submits accepted analysis input to the worker, records safe observations, and invokes upstream artifact validation/publication. It cannot itself validate identity or rewrite an artifact.
3. **Worker telemetry surface (loopback-only):** reports liveness, readiness, model/cache provenance, queue depth/age, active substage, aggregate counters, bounded failures, and GPU samples. It never exposes media paths or transcript content.
4. **Operator status/review surface (authenticated app):** shows whether a project uses production baseline, shadow candidate, review candidate, or accepted canary authority; displays recovery actions and evidence status; and reuses the accepted upstream speaker/cut review surfaces.

No new internet-facing service, message broker, or source-media endpoint is introduced.

### 4.2 Authority layers

For each project, the app maintains distinct references:

- `baseline_artifact_ref` and `baseline_cut_id`: the pre-rollout selected production state;
- `candidate_artifact_ref` and `candidate_cut_id`: immutable, non-authoritative evidence;
- `selected_artifact_ref` and `selected_cut_id`: current authoritative state;
- `last_known_good_artifact_ref` and `last_known_good_cut_id`: validated restoration target.

The candidate and selected references may be equal only after an explicit, audited compare-and-swap promotion. A shadow run must not write compatibility transcript rows, activity selection, cut selection, summary selection, player state, or export state.

### 4.3 Rollout state machine

Allowed effective project states are:

| State | Worker allowed | Candidate publication | Selected state may change | User-facing meaning |
|---|---:|---:|---:|---|
| `mock_only` | No | No | No | Production baseline is active |
| `shadow_queued` | Yes | No | No | Real analysis waits in a private queue |
| `shadow_running` | Yes | Non-authoritative immutable run only | No | Real analysis is being measured |
| `shadow_failed` | No automatic retry | Failure audit only | No | Baseline preserved; operator action required |
| `shadow_ready` | No | Valid candidate artifact | No | Candidate ready for review; baseline still active |
| `canary_review` | Optional explicit rerun | Candidate artifact/cut only | No | Peter reviews mapping, timing, safety, and cut |
| `canary_live` | Explicit runs allowed | Validated immutable runs | Yes, by explicit CAS promotion only | Accepted real AI is authoritative for one project |
| `paused` | No new submission | Existing evidence retained | No automatic change | Live path paused; selected/last-good is explicit |
| `rolled_back` | No until re-approved | Failure audit retained | Restored to recorded baseline/last-good | Prior authority restored and verified |

Terminal worker job states map to the rollout state; they do not directly drive authority. A `done` worker job is only a candidate until schema, source/config digest, referential integrity, timestamp, identity, and acceptance gates pass.

Allowed transitions are server-owned and compare the current state/version:

- `mock_only -> shadow_queued`: admin request + accepted dependencies + accepted fixture + Peter shadow approval;
- `shadow_queued -> shadow_running`: worker accepts the exact input hash;
- `shadow_running -> shadow_ready`: worker result validates and is persisted immutably;
- `shadow_running -> shadow_failed`: any worker, validation, hash, persistence, or timeout failure;
- `shadow_ready -> canary_review`: Peter accepts the evidence set for review, without selection change;
- `canary_review -> canary_live`: every mandatory gate passes, Peter approves exact artifact/cut, and CAS promotion succeeds;
- any non-terminal active state `-> paused`: readiness/alert/operator pause;
- `canary_live -> rolled_back`: explicit rollback restores the recorded prior selection and verifies it;
- `paused` or `rolled_back -> shadow_queued`: requires a new release revision and fresh approval.

There is no automatic transition to `canary_live`, no scheduled retry that crosses a state boundary, and no transition to `live_all`.

### 4.4 First-real-media sequence

The first run uses the accepted `consent_real` fixture or a consent-bound project created from it:

1. Validate fixture readiness without inference.
2. Snapshot current selected artifact/cut IDs and their complete payload digests.
3. Register an immutable rollout release from exact candidate commit/image/model/config/evidence.
4. Start in `shadow`; submit only the accepted analysis asset identified by source and analysis hashes.
5. Record queue, warm-up, inference, alignment, diarization, validation, persistence, and GPU evidence.
6. Compare output to locked truth and current baseline without publishing it.
7. Peter confirms timing, identity, mapping, editorial windows, and candidate cut.
8. Create a separately named candidate cut carrying complete auditable reasons. Do not overwrite the selected rough cut.
9. Exercise authenticated desktop/mobile review with program audio as master and silent proxies. Confirm no source-media request.
10. Promote exact artifact and cut atomically for that one project only.
11. Re-read database, disk artifact, player-state, timeline-state, and export projections; compare complete selected objects and digests.
12. Observe for the configured canary period and complete a rollback drill before declaring Phase 8 accepted.

## 5. API and data contracts

### 5.1 Database records

Implementation adds new tables rather than altering existing enums/columns:

- `ai_rollout_releases`: immutable release ID, source commit, app/worker image digests, dependency-lock digest, model IDs/revisions/digests, inference config digest, upstream contract versions, redacted fixture bundle ID, evidence-set digest, created time, and creation actor.
- `ai_rollout_assignments`: project ID, release ID, desired mode (`mock_only`, `shadow`, `canary_review`, `canary_live`, `paused`, `rolled_back`), optimistic version, created/updated time, and actor. At most one current assignment per project.
- `ai_rollout_runs`: run ID, project/release/assignment version, upstream worker/artifact IDs, safe input/config digest prefixes, state/substage, queue/start/finish timestamps, bounded error code, candidate artifact/cut references, validation booleans, last-good-preserved boolean, GPU summary, and evidence digest. No transcript, names, media path, or arbitrary error body.
- `ai_rollout_transitions`: append-only prior/new mode, prior/new selected references, request ID, actor, reason code, approval/evidence digest, and UTC timestamp.
- `ai_rollout_alerts`: bounded alert code, severity, first/last seen time, count, active/acknowledged/resolved state, release/project/run reference where safe, and actor/time for acknowledgement. No free-form upstream content.

Project deletion follows existing project-data deletion behavior for assignments/runs/alerts while immutable private run artifacts follow the accepted retention contract. Release records referenced by other projects are not deleted with one project.

### 5.2 Safe read APIs

All routes are authenticated and same-origin. Rollout mutations require `admin`; reviewers may read project-specific status and perform only the upstream review actions explicitly permitted by that plan.

- `GET /ai-rollout/status` — deployment-wide redacted state: dormant/active release, worker reachability/readiness, active alerts, aggregate queue facts, and whether activation gates are complete. It does not enumerate project names or private content.
- `GET /projects/{project_id}/ai-rollout` — effective mode, release/run safe provenance, baseline/candidate/selected distinctions, worker substage, queue age/ahead count, last-good status, review prerequisites, bounded warnings/errors, and allowed actions for the caller.
- Existing `GET /projects/{project_id}/progress`, player-state, and timeline-state gain additive `ai_rollout`/stage-detail fields. Legacy clients continue to receive their existing fields.
- `GET /internal/ai/metrics` is loopback/admin-only JSON for bounded machine scraping. It is not routed through NPM and carries no project label by default.

### 5.3 Mutation APIs

- `POST /projects/{project_id}/ai-rollout/shadow` requires release ID, assignment version, fixture bundle ID/evidence digest, and idempotency key.
- `POST /projects/{project_id}/ai-rollout/review` moves a valid shadow candidate to review; it does not select it.
- `POST /projects/{project_id}/ai-rollout/promote` requires exact candidate artifact digest, candidate cut ID/digest, prior selected refs, assignment version, Peter approval evidence ID, and idempotency key.
- `POST /projects/{project_id}/ai-rollout/pause` blocks new submissions without deleting evidence.
- `POST /projects/{project_id}/ai-rollout/rollback` requires expected current selected refs and restores the recorded prior refs atomically.
- `POST /ai-rollout/alerts/{alert_id}/acknowledge` records acknowledgement only; it does not suppress the underlying health gate.

Every mutation returns the resulting full safe rollout state and request/transition ID. Duplicate idempotency keys return the original result. Stale versions/digests return `409`; missing prerequisites return bounded `422`; worker unavailability during submission returns `503`; no route silently changes mode.

### 5.4 Worker telemetry contract

The loopback-only worker keeps `/health` as process liveness and `/ready` as model/GPU readiness. It adds or extends a redacted status/metrics response with:

- service/schema version, build/source/lock digest, image digest when injected, uptime, restart-safe boot ID;
- configured and loaded model IDs/revisions, compute type, batch allowlist selection, and cache readiness without token/cache paths;
- queue depth, oldest queue age, active count, queue capacity, aggregate accepted/rejected/completed/failed/cancelled counts;
- active stage enum (`queued`, `warming`, `transcribing`, `aligning`, `diarizing`, `normalizing`, `validating`, `publishing`) and elapsed duration without media identity;
- duration summaries for queue, model warm-up, each stage, and total jobs;
- GPU total/used/free MiB, headroom threshold/result, optional utilization/temperature only when available read-only, sample cadence/gaps, and telemetry freshness;
- bounded last failure code/time and readiness reasons.

The app validates the telemetry schema, caps lengths/counts, treats stale telemetry as unavailable, and never displays arbitrary worker exception text.

## 6. Requirement catalogue

### 6.1 Architecture

- **ARCH-P8-001:** Rollout shall be per project and default to `mock_only`; a global live-backend environment value alone shall never enroll all existing projects.
- **ARCH-P8-002:** `shadow`, `canary_review`, and `canary_live` shall keep baseline, candidate, selected, and last-known-good artifact/cut references distinct and auditable.
- **ARCH-P8-003:** Shadow execution shall be non-authoritative: it shall not replace compatibility transcript rows, activity/cut selection, player state, export state, or summaries.
- **ARCH-P8-004:** Candidate promotion shall be an explicit Peter-approved compare-and-swap transaction binding the exact artifact digest and cut digest; no successful worker job shall self-promote.
- **ARCH-P8-005:** Real-path failure shall fail closed. It shall not produce mock text, silently use a mock result, or replace a valid selected/last-known-good artifact.
- **ARCH-P8-006:** Phase 8 shall consume, not duplicate, the accepted AI-GPU artifact/identity/turn/cut contracts and accepted golden-fixture readiness contract.
- **ARCH-P8-007:** Program audio shall remain the player master clock, video shall follow within one frame, proxies shall remain silent, and source media shall not be browser-played.
- **ARCH-P8-008:** Automatic energy-envelope cross-correlation remains the synchronization authority. Phase 8 shall not introduce or normalize manual sync nudging.
- **ARCH-P8-009:** Every candidate and selected shot/hold shall retain structured auditable reason metadata through API, disk, database, player, rollback, and export projections.
- **ARCH-P8-010:** `live_all` is outside Phase 8. One canary approval shall not change another project or authorize broad production rollout.
- **ARCH-P8-011:** App liveness shall remain independent from optional AI readiness; mock-only production stays available when the optional worker is absent.
- **ARCH-P8-012:** Worker execution shall remain isolated from the web image and exposed only over loopback under host networking.

### 6.2 Backend and data

- **BACKEND-P8-001:** Release records shall immutably bind source commit, app/worker image digests, dependency-lock digest, contract versions, model revisions/digests, inference-config digest, accepted evidence digest, and redacted fixture bundle ID.
- **BACKEND-P8-002:** Assignments and transitions shall use optimistic versions, server-owned state transitions, idempotency keys, UTC timestamps, and append-only audit records.
- **BACKEND-P8-003:** One project shall have at most one current assignment and one active worker run. Concurrent submissions/promotions/rollbacks shall produce deterministic original-result or `409` responses.
- **BACKEND-P8-004:** Worker submission shall bind source/analysis identities and configuration exactly once, use confined read-only paths, and reject hash/path/config mismatch before inference.
- **BACKEND-P8-005:** A worker `done` state shall remain non-authoritative until strict artifact schema, timestamp, source/config digest, speaker-reference, overlap, identity, and persistence validation passes.
- **BACKEND-P8-006:** The app shall persist a bounded run record for queued, running, failed, cancelled, invalid, shadow-ready, promoted, paused, and rolled-back outcomes, including last-good preservation.
- **BACKEND-P8-007:** Candidate promotion shall atomically select the exact artifact and cut or select neither. A partial database/artifact/projection write shall restore the previous selection and retain failure audit.
- **BACKEND-P8-008:** Rollback shall atomically restore the recorded prior artifact/cut refs, regenerate recoverable projections, and verify complete object/digest equality before reporting success.
- **BACKEND-P8-009:** Existing progress/player/timeline responses shall gain additive versioned rollout fields; existing clients and mock-only projects shall retain current behavior.
- **BACKEND-P8-010:** Queue/status responses shall expose bounded state, substage, queue age, jobs ahead, progress where meaningful, and safe recovery codes, but not other project IDs, names, paths, transcript, or arbitrary errors.
- **BACKEND-P8-011:** App and worker readiness shall be separate typed contracts. Worker telemetry older than the configured freshness window shall be `unknown/stale`, never green.
- **BACKEND-P8-012:** Alert evaluation shall be deterministic, stateful, deduplicated, and recorded without requiring an external notification provider.
- **BACKEND-P8-013:** Project deletion and retention shall remove or retain rollout metadata/artifacts according to the accepted project and fixture retention policies without affecting other projects/releases.
- **BACKEND-P8-014:** Mock-only execution shall make no worker HTTP request and shall not require CUDA, model cache, Hugging Face authorization, or the GPU Compose overlay.
- **BACKEND-P8-015:** A live failure shall preserve the last known good state and surface a bounded error/recovery action. The operator must explicitly retry with a new run; no infinite or cross-state retry is allowed.
- **BACKEND-P8-016:** Any real worker output consumed by cuts shall use accepted speaker turns and confirmed mapping. Unresolved, overlap, low-confidence, or off-camera evidence shall select/retain safe-wide behavior rather than a guessed close-up.

### 6.3 UI, responsive behavior, and accessibility

- **UI-P8-001:** Home/project status and the player processing view shall label the effective source plainly: `Production baseline`, `Real AI · shadow only`, `Real AI · awaiting review`, `Real AI · canary active`, `Paused`, or `Rolled back`.
- **UI-P8-002:** Candidate and selected results shall never share one ambiguous success badge. The UI shall state whether playback/export still uses the baseline or the promoted candidate.
- **UI-P8-003:** Queue UI shall show `queued`, jobs ahead, queue age, current worker substage, elapsed time, and a no-ETA explanation when no accepted estimate exists.
- **UI-P8-004:** Failure UI shall show a bounded error code, whether baseline/last-good was preserved, the affected operation, and an allowed recovery action (`Retry shadow`, `Resume review`, `Pause`, `Roll back`, or `Contact operator`).
- **UI-P8-005:** Promotion controls shall be admin-only, unselected by default, and disabled until exact artifact/cut, fixture, timing, identity, editorial, persistence, readiness, and evidence gates are complete.
- **UI-P8-006:** Before promotion, the UI shall summarize the exact project/release, current and candidate state, safe reason coverage, and the fact that promotion changes only this project's selected artifact/cut. Peter must confirm explicitly.
- **UI-P8-007:** The existing speaker-mapping and candidate-cut review surfaces shall be reused. Phase 8 shall not introduce a second identity editor or infer mapping from angle/channel order.
- **UI-P8-008:** Player review shall continue using bounded program-audio ranges and silent proxies; network evidence shall show no source-media request and no program-audio reload on angle changes.
- **UI-P8-009:** At widths at or below 840 px, rollout status, queue facts, warnings, and actions shall form a single column with no horizontal page overflow. Nonessential provenance may collapse; source/mode/error/recovery must remain visible.
- **UI-P8-010:** All statuses shall use text plus colour/icon, native labelled controls, visible focus, keyboard operation, logical heading order, and live-region updates for status/errors. Motion shall respect reduced-motion preferences.
- **UI-P8-011:** Polling shall preserve focus and expanded state, avoid reannouncing unchanged content, pause or back off when the page is hidden, and stop at terminal state.
- **UI-P8-012:** Normal UI and retained screenshots shall omit names, transcript excerpts, private paths/hashes, consent details, credentials, and raw worker errors; opaque IDs may be shortened for correlation.

### 6.4 Operations, observability, deployment, and rollback

- **OPS-P8-001:** Every infrastructure/deployment activity shall begin with read-only discovery of CPU/RAM/GPU/devices, Docker/Compose topology, host networking, ports, NPM, volumes, appdata/cache, UID/GID/ACL, central MySQL, health checks, backups, rollback images, model cache, and current backend values without printing secrets.
- **OPS-P8-002:** The base app shall retain explicit mock backend defaults. The GPU overlay shall remain opt-in, loopback-only, `/data` read-only, with no NPM route and no privileged/source-writable mount.
- **OPS-P8-003:** Active proxy encoding shall remain VAAPI `h264_vaapi`; Phase 8 shall not switch to QSV or share the CUDA worker image with the proxy path.
- **OPS-P8-004:** A dormant deployment shall prove that no worker request occurs and user-visible behavior is unchanged before any shadow activation.
- **OPS-P8-005:** Worker liveness, readiness, build/model/config provenance, queue depth/age, active stage duration, job outcomes, validation failures, last-good preservation, and GPU headroom shall be observable through bounded loopback telemetry and structured logs.
- **OPS-P8-006:** Metrics shall avoid transcript/media/project labels by default and shall define low-cardinality counters/gauges/duration summaries for queue, stage latency, failures, retries, readiness, alerts, and rollout transitions.
- **OPS-P8-007:** Structured events shall include UTC time, event code, release/run/transition IDs, safe digest prefixes, state/substage, duration/counts, result code, and last-good boolean. They shall exclude content, paths, tokens, headers, arbitrary upstream bodies, and full private hashes.
- **OPS-P8-008:** Telemetry sampling used for GPU acceptance shall be at most 250 ms apart, validate sample gaps, cover baseline/warm-up/inference/overlap/unload phases, and retain peak/headroom summaries. Sparse snapshots shall not be called peak measurement.
- **OPS-P8-009:** Readiness shall fail when CUDA/model/config/image provenance mismatches, required model loading fails, telemetry is stale, or measured free VRAM violates the accepted threshold. App liveness shall not falsely report worker readiness.
- **OPS-P8-010:** Alerts shall at minimum cover worker unreadiness, provenance mismatch, queue capacity/excess age, job runtime excess, repeated job failure, validation/persistence failure, GPU headroom violation, stale telemetry, unexpected fallback/mock result, and selection/rollback verification failure.
- **OPS-P8-011:** Until enough accepted latency evidence exists, defaults shall be configurable and conservative: queue warning at 15 minutes, critical at 30 minutes; job-runtime warning at 30 minutes; repeated-failure alert at 3 failures in 15 minutes; telemetry stale after 3 expected sample intervals; GPU violation immediately at less than max(10% total VRAM, 2 GiB) free. Acceptance evidence may lower/raise time thresholds but shall not weaken the GPU floor without a new design decision.
- **OPS-P8-012:** Critical provenance, unexpected-fallback, validation/persistence, GPU-headroom, or rollback-verification alerts shall automatically pause new live submissions. They shall not delete evidence or silently change a selected cut.
- **OPS-P8-013:** The operational runbook shall define observe, acknowledge, pause, drain/cancel when safe, preserve evidence, restore last good, verify, and escalate steps for every alert code. No external alert sink is claimed until configured and tested.
- **OPS-P8-014:** Deployment shall bind and transfer the exact reviewed source, Compose files, worker lock/Dockerfile, config examples, and migrations; render merged Compose; build/pull exact images; and verify image/config/model provenance before activation.
- **OPS-P8-015:** Pre-mutation backup shall cover central MySQL and app configuration, preserve prior app/worker image refs and rollout policy/selection, and record a tested rollback command. Model caches are reproducible cache, not authoritative backup.
- **OPS-P8-016:** A deployment shall start/verify the worker before enabling a project assignment, while the app remains mock-only. Failure before assignment requires no authority rollback; failure after assignment follows the recorded selection rollback.
- **OPS-P8-017:** First activation shall be one consent-cleared project in `shadow`, then `canary_review`, then optional `canary_live`. Each boundary needs separately retained evidence and Peter approval.
- **OPS-P8-018:** Rollback order shall be: pause submissions; capture safe status; restore prior project selection and verify complete refs/digests; return project policy to `rolled_back/mock_only`; recreate app with explicit mock backends if needed; verify app/DB/auth/NPM/player/export; then stop/remove only the optional candidate worker under an approved Publisher task.
- **OPS-P8-019:** Deployment and rollback shall not delete source media, accepted fixture input, failed immutable run audit, prior artifacts/cuts, or database history. Cleanup is separately authorized and retention-scoped.
- **OPS-P8-020:** Phase 8 acceptance requires a successful rollback drill from a promoted canary to its exact prior selected artifact/cut and a verified re-promotion only if Peter separately approves it.

### 6.5 Security, privacy, consent, and provenance

- **SEC-P8-001:** Real inference shall run only for a fixture/project whose exact revision has active consent/right-to-use, purpose coverage, retention/backup decisions, and no expiry/revocation under the accepted golden-fixture contract.
- **SEC-P8-002:** The rollout coordinator and worker shall reject absolute/unconfined paths, traversal, symlinks, special files, changed bytes, changed probe facts, and source/analysis hash mismatch before inference.
- **SEC-P8-003:** The worker shall remain loopback-only and the app shall not proxy its internal job/metrics endpoints through NPM.
- **SEC-P8-004:** Hugging Face/model credentials shall be supplied only at runtime, never logged, returned by readiness/status, stored in artifacts, copied into images, or written to Kanban/docs.
- **SEC-P8-005:** Rollout read/mutation APIs shall require same-origin authenticated sessions; admin-only mutations shall retain current CSRF/origin protections and authorization checks.
- **SEC-P8-006:** Project/release/run/artifact/cut references shall be ownership-checked and digest-bound. Cross-project, stale, guessed, or replayed references shall fail.
- **SEC-P8-007:** Stored and displayed errors shall be allowlisted bounded codes. Arbitrary model/service/ffmpeg/traceback content shall remain private and redacted before persistence.
- **SEC-P8-008:** Logs, metrics, test names/reprs, screenshots, artifacts, docs, and Kanban shall not contain transcript excerpts, identities, absolute media paths, full private media hashes, consent details, cookies, tokens, or credentials.
- **SEC-P8-009:** Browser review shall use program audio and silent proxies only. Source media and accepted fixture roots shall never be exposed as public/static URLs.
- **SEC-P8-010:** OpenRouter and external AI services are prohibited for media, transcript, identity, semantic, rollout, alert, or evidence processing. Local accepted providers only.
- **SEC-P8-011:** Revocation/expiry shall block new inference and promotion immediately, pause affected assignments, invalidate candidate readiness, and trigger Peter-authorized retention/quarantine handling without erasing audit truth.
- **SEC-P8-012:** A pre-handoff privacy scan shall cover staged, unstaged, untracked, ignored-sensitive summaries, Docker build contexts, package contexts, test artifacts, browser artifacts, and structured logs, reporting locations rather than leaked values.

### 6.6 Tests and acceptance evidence

- **TEST-P8-001:** Unit tests shall cover every valid/invalid state transition, optimistic-version conflict, idempotency replay, stale digest, role restriction, missing prerequisite, and unsupported `live_all` request.
- **TEST-P8-002:** Concurrency tests shall race duplicate submission, promotion, pause, rollback, app restart, and project deletion and prove at most one active run/selection with no partial authority change.
- **TEST-P8-003:** Mock-only tests shall assert zero worker sockets/requests, no GPU/model credential dependency, unchanged progress/player/export behavior, and explicit mock provenance.
- **TEST-P8-004:** Shadow integration shall prove a validated candidate run can be queued/completed while complete DB rows, selected artifact/cut, player state, timeline state, summary, export, and disk baseline remain byte/object-equivalent.
- **TEST-P8-005:** Promotion fault-injection shall fail before/after artifact write, DB selection, compatibility projection, cut selection, and response serialization and prove atomic prior-selection restoration plus retained audit.
- **TEST-P8-006:** Rollback tests shall restore exact prior artifact/cut refs and complete objects across DB, disk, artifact API, player/timeline state, and export projection, including repeated/idempotent rollback.
- **TEST-P8-007:** Worker telemetry contract tests shall cover liveness vs readiness, cold/warm model, valid/stale/missing GPU data, queue full/age, every substage, restart boot ID, provenance mismatch, malformed/oversized fields, and redaction.
- **TEST-P8-008:** Alert tests shall exercise every mandatory alert, threshold boundary, deduplication/counting, acknowledgement/resolution, automatic pause, and absence of content/high-cardinality labels.
- **TEST-P8-009:** Failure tests shall cover worker unreachable, timeout, cancel, OOM, model load failure, CUDA loss, hash mismatch, malformed result, non-finite times/confidence, overlap/reference defect, persistence failure, stale acceptance, and changed fixture approval; no case may publish mock output.
- **TEST-P8-010:** Privacy tests shall inject names, transcripts, paths, hashes, tokens, headers, and tracebacks into worker/app errors and prove API, DB, logs, metrics, alerts, screenshots, test reports, and Kanban-safe summaries exclude them.
- **TEST-P8-011:** Authorization tests shall cover anonymous/reviewer/admin reads and mutations, CSRF/origin failure, cross-project references, stale sessions, and NPM attempts to reach worker/internal metrics.
- **TEST-P8-012:** Browser tests in real Chromium shall cover mock-only, queued, warming/running substages, shadow-ready, review, promoted, failed-last-good-preserved, paused, rollback, polling recovery, and unavailable/stale telemetry at desktop and 375x812/840px boundaries.
- **TEST-P8-013:** Browser accessibility evidence shall include keyboard-only operation, focus retention during polling, visible focus, labelled controls/status, live-region behavior without repeated announcements, colour-independent states, reduced motion, and no horizontal page overflow.
- **TEST-P8-014:** Browser network/clock evidence shall prove authenticated same-origin use, no worker/internal endpoint exposure, no source-media request, silent proxy requests, one continuous program-audio master, and video follow within one project frame through angle changes.
- **TEST-P8-015:** Auditable-cut tests shall compare complete clip objects and reason-boundary metadata through candidate creation, promotion, disk, DB, API, player, export, rollback, and re-read; unresolved/overlap/low-confidence cases shall have zero wrong-close-up safety frames.
- **TEST-P8-016:** Trusted-host shadow acceptance shall start only from an `accepted` fixture and record exact candidate provenance, stage durations, word/identity/editorial results, and redacted run summary without changing project authority.
- **TEST-P8-017:** Target-GPU tests shall sample at <=250 ms, reject sampling gaps, record warm-up and inference peaks, run accepted Dots coexistence conditions, enforce max(10%, 2 GiB) headroom, and prove OOM/headroom violation pauses new submissions.
- **TEST-P8-018:** Production-topology canary evidence shall include rendered Compose, loopback-only worker, read-only media mount, mock defaults before activation, central MySQL backup, exact image/model/config provenance, health/readiness, queue/job success, authenticated browser review, selected-state verification, logs/restarts, and NPM isolation.
- **TEST-P8-019:** Rollback drill evidence shall promote one accepted candidate, restore the exact prior artifact/cut and mock-only policy, verify app/DB/auth/NPM/player/export and zero restarts/errors, and retain failed/candidate audit without deleting media.
- **TEST-P8-020:** Documentation tests/review shall verify every truth-bearing document uses the same exact status vocabulary and provenance, distinguishes implemented/tested/integrated/deployed/activated, and does not call Phase 8 product Stage 8.
- **TEST-P8-021:** Full handoff gates shall run focused rollout/worker/API/UI tests, AI-GPU/golden regression suites, the deterministic mock-isolated full suite, compile/import checks, changed-file lint/static checks, worker lock validation, Compose renders for base/prod/GPU combinations, privacy/context scans, browser console/network checks, and `git diff --check`.
- **TEST-P8-022:** Independent Designer compliance shall map every P8 requirement to source/diff/test/runtime/UI/deployment evidence for the exact candidate; independent Tester acceptance shall follow compliance before any Publisher activation card.

## 7. Observability and alert definition

### 7.1 Low-cardinality measurements

Required measurements, with no project/media/transcript label by default:

- `ai_rollout_release_info{release_id_prefix,mode}` (single current record);
- worker ready and telemetry-fresh booleans;
- queue depth/capacity and oldest age seconds;
- current jobs by safe state/substage;
- accepted/rejected/completed/failed/cancelled jobs totals by bounded result code;
- queue, warm-up, ASR, alignment, diarization, validation, persistence, and total-duration summaries;
- artifact validation and selection transaction totals;
- last-known-good preserved/restored totals;
- active assignments by rollout mode;
- active alerts by code/severity;
- GPU total/used/free MiB, headroom requirement/result, sample age, and sample-gap maximum;
- worker/app restart boot IDs and uptime.

No metric shall use project ID, filename, source hash, transcript value, person, raw model error, or unbounded exception as a label.

### 7.2 Mandatory alerts and response

| Code | Trigger | Severity/action | Operator response |
|---|---|---|---|
| `AI_WORKER_UNREADY` | two consecutive readiness failures or stale readiness | warning; critical if active canary | pause submissions; inspect bounded readiness/provenance |
| `AI_PROVENANCE_MISMATCH` | source/image/lock/model/config differs from release | critical, auto-pause | reject run; rebuild/re-register release; never waive |
| `AI_QUEUE_CAPACITY` | queue full | warning | stop submissions; allow active job to finish; inspect demand |
| `AI_QUEUE_AGE_HIGH` | 15m warning / 30m critical by default | warning/critical; critical auto-pause | inspect active job and telemetry; cancel only if safe |
| `AI_JOB_RUNTIME_HIGH` | >30m default or accepted evidence threshold | warning | inspect stage/GPU; do not guess ETA |
| `AI_FAILURE_BURST` | 3 failed jobs in 15m | critical, auto-pause | preserve failures; verify worker/model/GPU before new release |
| `AI_VALIDATION_FAILED` | strict artifact/referential validation fails | critical, auto-pause | retain invalid run; do not publish; correct producer/contract |
| `AI_PERSISTENCE_FAILED` | artifact/DB/projection transaction fails | critical, auto-pause | verify prior selection and last-good restoration |
| `AI_GPU_HEADROOM_LOW` | free VRAM below max(10%, 2 GiB) | critical, immediate auto-pause | stop new work; unload competing accepted workloads or retune via new evidence |
| `AI_GPU_TELEMETRY_STALE` | >3 expected sampling intervals | critical during active measurement | invalidate measurement/acceptance; restore telemetry |
| `AI_UNEXPECTED_FALLBACK` | live run contains mock/fallback provenance or mock text path called | critical, auto-pause | quarantine run; verify no selection changed; investigate routing |
| `AI_SELECTION_VERIFY_FAILED` | read-after-write differs from promoted exact refs/digests | critical, auto-rollback attempt | restore prior selection; verify; escalate if restoration fails |
| `AI_ROLLBACK_VERIFY_FAILED` | prior exact refs/digests or health checks not restored | emergency | keep `rollback_required=true`; Publisher-only recovery; no retry/deploy |
| `AI_CONSENT_INVALID` | accepted rights become stale/revoked/expired | critical, auto-pause | block processing; follow Peter-authorized retention/quarantine |

Alerts are visible in authenticated status and structured logs. External notification is not claimed. If Peter later chooses a sink, a separate bounded adapter must sign/authenticate messages, send only allowlisted fields, retry without blocking rollback, and pass a delivery test.

## 8. Failure and recovery matrix

| Failure | Project authority | Evidence | Recovery |
|---|---|---|---|
| Worker absent in `mock_only` | baseline unchanged | optional worker unavailable | none required |
| Worker absent before shadow submit | baseline unchanged | failed submission record/code | restore readiness, explicit retry |
| Queue full/old | baseline unchanged | queue alert and run state | pause, drain/inspect, explicit retry |
| OOM/GPU floor violation | baseline/last-good unchanged | failure + sampled GPU summary | auto-pause, unload/tune under new accepted evidence |
| Model/provenance mismatch | unchanged | rejected run + critical alert | build/register exact release; no waiver |
| Invalid worker payload | unchanged | immutable failed validation audit | correct worker/contract; new release/run |
| Artifact persistence partial failure | prior selection restored | failure record; temporary cleanup bounded | reconcile exact prior state; explicit retry |
| Candidate fails timing/identity/editorial gate | unchanged | retained candidate + failed gate | no promotion; correct/rerun or stay baseline |
| Peter declines candidate cut | unchanged | decision status only | remain baseline; no automatic alternative |
| Promotion conflict | unchanged | `409` + current state | reload/review current refs; do not force |
| Post-promotion read-back mismatch | auto-rollback prior exact refs | critical alert/transition | verify restoration; Publisher recovery if not exact |
| Worker fails after promoted canary | selected accepted last-good preserved | visible stale/failure state | pause; explicit rerun or rollback; never mock-substitute |
| App restart during job | selected state unchanged; run interrupted/stale | restart/run audit | reconcile worker/run; explicit retry only |
| Rights revoked/expired | no new run/promotion | consent alert and invalid state | pause/quarantine per approved retention process |
| Rollback verification fails | authority uncertain; `rollback_required=true` | emergency record | stop; dedicated Publisher recovery; no redeploy |

## 9. Operational runbook contract

A new runbook under `docs/runbooks/` shall include copy-pasteable, secret-safe commands and expected outputs for:

1. read-only Unraid/app/worker/DB/NPM/volume/GPU discovery;
2. exact source/image/lock/model/config provenance capture;
3. base, production, GPU-overlay, and merged Compose render checks;
4. database/config/image/rollout-selection backup and restore validation;
5. dormant deployment and proof that mock-only opens no worker connection;
6. worker liveness/readiness/model warm-up/queue/GPU telemetry checks;
7. fixture validate-only and accepted-bundle gate;
8. creating one shadow assignment, watching it, and stopping safely;
9. reading bounded alerts and acknowledging them without changing authority;
10. candidate review and promotion prerequisites;
11. exact selected artifact/cut read-back through DB/disk/API/player/export;
12. pause and rollback with safety booleans (`mutation_started`, `candidate_live`, `rollback_required`, `rollback_verified`, `selection_restored`, `production_data_mutated`, `openrouter_used`);
13. post-rollback app/DB/auth/NPM/browser/log/restart checks;
14. retention-safe cleanup of only explicitly named disposable run outputs; and
15. escalation rules when any expected value is uncertain.

The runbook shall never embed credentials, private root paths, project/media names, transcript, exact private media hashes, or consent-record content.

## 10. Exact documentation-truth updates

Documentation changes happen in the final integration package and report exact evidence, not intent.

### 10.1 Before any activation

- `README.md`: retain “production mock-backed”; add that Phase 8 control/telemetry may be implemented dormant and broad rollout is unsupported.
- `AI_HANDOFF.md`: name exact dependency commits/verdicts, current dormant/shadow state, blockers, latest deterministic test result, and next approved gate.
- `jobs/BACKLOG.md`: add a distinct Phase 8 job with dependencies, package status, exact tests/manual gates, and no deployed/activated claim.
- `docs/plans/TESTING_STRATEGY.md`: add runnable focused commands, mock-isolation env, trusted-host skip/fail semantics, Compose/browser/privacy/rollback gates, and evidence paths.
- `docs/DEPLOYMENT.md`: replace the preliminary global-switch guidance with the per-project dormant -> shadow -> review -> canary sequence and exact rollback runbook link; retain mock defaults.
- `docs/plans/whisperx-speaker-aware-ai-roadmap.md`: mark Phase 8 as implemented/tested only when exact evidence exists; distinguish dormant, deployed, shadow-active, and canary-active.
- `docs/plans/ai-gpu-1-acceptance-gates.md` and the golden-fixture plan: append only cross-reference/evidence status; do not rewrite historical requirements or Peter decisions.
- `docs/ai/whisperx-evaluation-protocol.md`: point live evaluation at the accepted fixture validator and rollout run/evidence contract; remove commands that do not exist.
- `.env.example` and Compose comments: document safe defaults and loopback overlay without showing secrets or implying activation.
- `docs/status/AUTOEDIT_PROGRESS_REPORTING.md`: add the Phase 8 status vocabulary and evidence fields while preserving the separate product-stage/AI-phase taxonomy.
- `docs/status/autoedit-progress.html`: report the exact card/commit/verdict/deployment/activation state and link redacted evidence only; no private screenshots.
- new `docs/runbooks/phase-8-real-ai-rollout.md`: operational source of truth defined in Section 9.

### 10.2 Truth vocabulary

Every document shall use these independently:

- `designed` — plan approved;
- `implemented` — exact source exists;
- `compliance passed` — Designer mapped exact evidence to all requirements;
- `tested` — independent Tester passed the exact candidate;
- `integrated` — dependency/package commits combined and retested;
- `deployed dormant` — code/images present, production remains mock-only and no worker submission occurs;
- `shadow active` — one approved project runs non-authoritative real AI;
- `canary review` — candidate is visible but not selected;
- `canary active` — one exact project uses a Peter-approved selected real artifact/cut;
- `rolled back` — prior exact selection and mock-only policy restored and verified;
- `production-wide` — forbidden wording for this phase because `live_all` is unsupported.

A deployment success alone must not change AI phase acceptance or claim canary activation.

## 11. Implementation packages and ownership

All packages start from an integrated clean worktree containing accepted AI-GPU and golden-fixture dependency commits. No Programmer shall patch the current mixed checkout. Each package is one bounded Programmer worktree, followed by exact-candidate Designer compliance; Tester runs only after the integrated compliance pass.

### Package P8-A — rollout contracts and policy store

**Depends on:** accepted AI-GPU and golden-fixture commits.

**Owns:**

- new `src/autoedit/ai/rollout_contracts.py`
- new `src/autoedit/ai/rollout_store.py`
- `src/autoedit/db/schema.py` additions only
- `src/autoedit/config.py` safe rollout defaults
- focused contract/store/concurrency/privacy tests

**Does not own:** `api.py`, worker, web UI, Compose, deployment docs.

**Acceptance:** ARCH-P8-001–006, 010; BACKEND-P8-001–003, 006–008, 012–015; SEC-P8-006–008; TEST-P8-001–006, 008–010.

### Package P8-B — worker observability and provenance

**Depends on:** accepted AI-GPU worker; may proceed in parallel with P8-A if it does not touch app files.

**Owns:**

- `services/whisperx_service/app.py`
- `services/whisperx_service/jobs.py`
- worker-only telemetry/provenance helpers
- worker telemetry, queue, GPU, failure, and privacy tests

**Does not own:** main-app API/schema/UI, Compose, docs.

**Acceptance:** ARCH-P8-011–012; BACKEND-P8-004–005, 010–011; OPS-P8-005–012; SEC-P8-002–004, 007–008; TEST-P8-007–010, 017.

### Package P8-C — app coordinator, APIs, and progress integration

**Depends on:** integrated P8-A and P8-B.

**Owns:**

- new `src/autoedit/ai/rollout_service.py`
- `src/autoedit/api.py` rollout endpoints/integration only
- `src/autoedit/progress.py`
- `src/autoedit/plog.py` bounded rollout events
- API/orchestration/restart/fault-injection tests

**Coordination:** rebase after the accepted upstream AI-GPU API integration. Do not overwrite its artifact, mapping, activity, or cut implementation.

**Acceptance:** ARCH-P8-001–012; BACKEND-P8-001–016; OPS-P8-005–013; SEC-P8-001–011; TEST-P8-001–011, 015.

### Package P8-D — visible rollout status and recovery UX

**Depends on:** integrated P8-C and accepted upstream mapping/cut review UI.

**Owns:**

- `src/autoedit/web/app.html`
- `src/autoedit/web/app.js`
- `src/autoedit/web/player.js`
- `src/autoedit/web/style.css`
- web logic and browser acceptance tests/artifacts

**Does not own:** backend behavior or a duplicate speaker editor.

**Acceptance:** UI-P8-001–012; SEC-P8-005, 008–009; TEST-P8-012–015.

### Package P8-E — deployment overlay, runbook, and documentation truth

**Depends on:** integrated and compliance-passed P8-A–D. This package may make only dormant configuration deployable; it shall not deploy.

**Owns:**

- `docker-compose.gpu-ai.yml`
- only necessary safe-default comments/variables in `docker-compose.yml`, `docker-compose.prod.yml`, and `.env.example`
- `scripts/autoedit-deploy.sh` or a new bounded Phase 8 release helper, with self-tests
- `docs/runbooks/phase-8-real-ai-rollout.md`
- the truth-bearing docs listed in Section 10
- Compose, deploy-helper, docs-consistency, and privacy tests

**Coordination:** preserve VAAPI, central MySQL, host networking, NPM, `/data`, backup, and existing rollback behavior. Never include secrets or private media.

**Acceptance:** OPS-P8-001–020; SEC-P8-001–012; TEST-P8-016–021.

### Integration, review, test, and publish sequence

1. Integrate accepted upstream dependencies.
2. Implement/review P8-A and P8-B.
3. Integrate them; implement/review P8-C.
4. Implement/review P8-D.
5. Implement/review P8-E.
6. Create one clean exact integration commit and rerun all Section 12 gates.
7. Independent Designer produces a requirement-by-requirement `DESIGN_COMPLIANCE_PASS` or corrections.
8. Independent Tester exercises backend, real browser, Compose, privacy, and dormant/mock isolation and returns `TEST_PASS` or defects.
9. Peter may authorize a Publisher card for **dormant deployment only**.
10. After dormant verification, Peter may separately authorize shadow execution.
11. After accepted shadow/review evidence, Peter may separately authorize one canary promotion.
12. Complete and verify rollback drill. No broad rollout card is created from this plan.

## 12. Acceptance gates and evidence matrix

### Gate P8-0 — dependency closure

Required evidence:

- exact accepted AI-GPU implementation commit, `DESIGN_COMPLIANCE_PASS`, and `TEST_PASS`;
- exact accepted golden-fixture implementation commit, `DESIGN_COMPLIANCE_PASS`, and `TEST_PASS`;
- accepted `consent_real` readiness summary and Peter decisions;
- target-GPU timing/identity/editorial/VRAM/coexistence gates complete;
- clean integrated base with privacy scan.

Any missing item blocks Phase 8 real execution. Synthetic/fake-provider evidence cannot substitute.

### Gate P8-1 — dormant implementation

Required evidence:

- complete requirement traceability for P8-A–E;
- focused and full mock-isolated suites green;
- mock-only opens no worker connection;
- base/prod/GPU Compose renders with safe defaults;
- worker/internal endpoints not exposed through NPM;
- browser desktop/mobile/accessibility states;
- privacy and cross-artifact consistency review;
- docs all say not deployed/activated.

### Gate P8-2 — dormant production deployment

Requires explicit Publisher task. Evidence:

- read-only Unraid discovery;
- exact commit/images/locks/configs;
- database/config/image/selection backup and rollback refs;
- controlled app/worker deployment with app still mock-only;
- app health, DB, auth, NPM/TLS, worker loopback liveness/readiness, model provenance, zero unexpected restarts;
- authenticated browser smoke;
- proof that ordinary project processing makes no worker request;
- `DEPLOYED_DORMANT_AND_VERIFIED`, not real-AI acceptance.

### Gate P8-3 — first shadow run

Requires a separate Peter-approved execution task. Evidence:

- accepted fixture/project revision and rights readiness;
- exact release registration/provenance;
- baseline artifact/cut snapshot;
- queue/stage/GPU samples and alert state;
- strict candidate validation and redacted summary;
- complete proof that selected DB/disk/API/player/export state did not change;
- no source-media browser request and program-audio/master sync evidence.

### Gate P8-4 — canary review and promotion

Requires Peter decisions. Evidence:

- frame-level word review within one project frame;
- confirmed identity/mapping and label-swap safety;
- locked editorial-window outcomes and zero wrong-close-up safety frames;
- candidate cut complete reason metadata/persistence/export;
- desktop/mobile authenticated review with clean console/network;
- exact promotion request, approval evidence, CAS transition, and read-back equality;
- no other project assignment/selection changed.

### Gate P8-5 — observation and rollback drill

Evidence:

- configured observation window completed with queue/latency/failure/GPU/readiness summaries;
- every alert path or safe test injection exercised without sensitive output;
- explicit rollback to exact prior artifact/cut and mock-only policy;
- DB/disk/API/player/export equality, app/DB/auth/NPM health, worker isolation, and zero unexpected restarts;
- retained audit, no source/fixture deletion;
- truthful docs updated to `rolled back` or `canary active` according to the final verified state.

### Compliance evidence template

The compliance reviewer shall fill one row per requirement, not approve from package summaries:

| Requirement ID | Source/diff evidence | Automated test | Runtime/UI/ops evidence | Result |
|---|---|---|---|---|
| `ARCH-P8-001` … `TEST-P8-022` | exact path:line / commit | exact test node/command | artifact path / redacted output | PASS/FAIL |

Any `FAIL`, missing exact-candidate evidence, privacy leak, stale dependency verdict, or unapproved production mutation returns `IMPLEMENTATION_CHANGES_REQUIRED` or `BLOCKED_NEEDS_USER_DECISION`.

## 13. Risks and mitigations

1. **Global-switch blast radius:** mitigated by per-project assignments, mock defaults, unsupported `live_all`, and one-canary limits.
2. **False success from worker `done`:** mitigated by separate strict validation and explicit promotion.
3. **Baseline corruption:** mitigated by shadow non-authority, distinct refs, CAS, complete-object snapshots, and rollback verification.
4. **GPU contention/OOM:** mitigated by sampled headroom, accepted coexistence conditions, bounded queue, auto-pause, and no automatic retune.
5. **In-memory queue loss on restart:** mitigated by app-side durable run state/reconciliation and explicit retry. Phase 8 does not claim exactly-once worker execution.
6. **Privacy leakage through observability:** mitigated by bounded codes, low-cardinality metrics, no content/path labels, redaction injection tests, and loopback-only telemetry.
7. **Consent drift:** mitigated by readiness revalidation before every run/promotion and immediate pause on expiry/revocation.
8. **Documentation overclaim:** mitigated by exact vocabulary, docs consistency tests, and independent evidence review.
9. **Concurrent upstream changes:** mitigated by hard dependency commits and sequential worktree packages; no work starts from the current mixed checkout.
10. **Rollback tool failure:** mitigated by pre-mutation backup, immutable prior refs/images, helper self-tests, explicit safety booleans, and Publisher-only emergency recovery.
11. **Polling/accessibility regressions:** mitigated by additive contracts, focus/live-region requirements, browser testing, and hidden-page backoff.
12. **Model/cache reproducibility:** mitigated by model revision/digest and lock/image provenance. Cache contents are disposable and never authority.

## 14. Non-goals

Phase 8 does not:

- implement or re-review upstream WhisperX ASR, alignment, diarization, identity resolution, activity derivation, cut algorithms, golden-fixture schemas, or semantic LLM contracts;
- authorize or perform a deployment, shadow run, canary promotion, production-data mutation, or cleanup;
- provide `live_all` or automatically enroll projects;
- replace central MySQL, the app's in-process non-AI pipeline runner, or the worker's bounded single-concurrency queue with Redis/Celery;
- add manual synchronization controls or change sync offsets;
- change program-audio-master playback, proxy silence, source-media browser policy, VAAPI, or NLE export authority;
- add an external alert vendor/sink without a Peter decision and separate adapter review;
- expose transcript/media/private fixture details in dashboards or operational evidence;
- treat synthetic media, fake providers, sparse GPU snapshots, or agent summaries as real-media production acceptance;
- activate Phase 7 semantic LLM output as authoritative. Semantic features retain their separately accepted backend/authority state.

## 15. Design verdict

`DESIGN_APPROVED`

This verdict approves only the bounded implementation plan. Real execution remains blocked by the two hard dependency compliance/test gates, accepted consent-real fixture and Peter decisions, exact target-GPU acceptance, clean integration, independent Phase 8 compliance/testing, and explicit Publisher/activation authorization. Production remains mock-backed until those gates pass.
