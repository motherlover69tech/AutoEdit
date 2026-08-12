# AI-GPU-1 Application Acceptance Gates

**Status:** DESIGN_APPROVED
**Scope:** acceptance specification only; no product implementation or production mutation
**Production constraint:** keep `WHISPER_BACKEND=mock` and `DIARIZE_BACKEND=mock` until this plan's gates and the later explicit rollout decision pass
**Authoritative sources:** `docs/plans/ai-gpu-1-corrective-pickup.md`, `docs/plans/whisperx-speaker-aware-ai-roadmap.md`, `docs/ai/whisperx-evaluation-protocol.md`, `jobs/BACKLOG.md`, `AI_HANDOFF.md`, `docs/plans/TESTING_STRATEGY.md`, and `docs/DEPLOYMENT.md`
**Current implementation inspected:** `7b0d27ffe1332236d3e56967739e13c9eced7886` plus the pre-existing dirty changes listed in Section 2.1; this Designer task did not alter those product files
**Provider preflight:** the active `autoeditdesigner` profile declares `custom:9Router` / `cx/gpt-5.6-sol`; the card has no conflicting route override, and a minimal completion on that exact declared route returned `ROUTE_OK`. OpenRouter was not used as primary, fallback, auxiliary, MoA, or delegation.

## 1. Decision and scope

The remaining AI-GPU-1 application-acceptance work is split into four ordered,
controlling requirements. These IDs are stable and must be used in the acceptance
record, Kanban evidence, compliance matrix, and any correction cards:

1. **GATE-1** — aligned word timing on the program-audio master timeline;
2. **GATE-2** — operator-confirmed speaker identity mapping with current-voice revalidation;
3. **GATE-3** — speaker-turn-driven cut acceptance end to end; and
4. **GATE-4** — valid peak-VRAM and Ollama/Dots coexistence measurement.

A gate passes only from the current immutable worker image, current source, a hash-bound consent-cleared fixture, and complete evidence. Historical post-job VRAM snapshots, an isolated diarization smoke, anonymous speaker labels, mock output, or another agent's summary are not substitutes.

Passing these gates establishes that the application path is eligible for an explicit per-project opt-in decision. It does not itself authorize a production deployment, change either mock backend default, make WhisperX the global cut authority, or complete the broader three-interview superiority benchmark and Phase 8 rollout.

## 2. Verified facts, assumptions, unknowns, and human decisions

### 2.1 Verified facts

- The active profile route and live route check are recorded in the document header. The card has no provider/model override and no OpenRouter route was used.
- Corrective artifact and Phase 4 resolver reviews are recorded as `PASS`.
- A hash-bound queued ASR/alignment run and a constrained two-speaker diarization run completed on the V100. The latter sampled 8,024 MiB at one-second intervals; this is not a Dots coexistence result.
- The authoritative timeline convention is `source_ms = master_ms + sync_offset_ms`; worker results are projected with `master_ms = source_ms - sync_offset_ms` and negative pre-roll is clipped.
- `AIResultArtifact` stores strict integer-ms program-audio-master timestamps, anonymous diarization turns, speaker mappings, and resolved turns with provenance.
- `resolve_speaker_mappings()` supports current operator confirmation, current voice revalidation, anonymous-label swaps, audit-only transcript context, and fail-closed conflicts.
- The repository now contains the resolved-turn activity bridge, durable speaker-confirmation schema/API/UI, explicit VAD/WhisperX candidate generation, selected-cut persistence, trusted-host fixture validator, safe-wide cut integration, and an offline GPU evidence harness. Their existence is implementation progress, not acceptance evidence.
- The tracked `tests/fixtures/golden_interview/expected/*.json` files remain `not_labeled` placeholders. The trusted-host integration test skips when `AUTOEDIT_GOLDEN_MEDIA_ROOT` is absent, as required; no consent-controlled real fixture or passing live acceptance record was available in this Designer workspace.
- The current GPU harness validates redacted schemas, offline/mock behavior, bounded local read-only discovery, and fail-closed conditions. Its `execute` mode intentionally refuses live workloads. **GATE-4 therefore still needs a separately reviewed, explicitly authorized live executor/adapter before it can be run; mock harness output is ineligible.**
- The current cut engine consumes compatible `{start_ms, end_ms, active}` activity, protects safe-wide spans, and persists immutable candidates. Recent Phase 6 corrective work addresses confirmed raw-turn projection and terminal source-coverage policy. These seams still require exact-candidate compliance plus consent-controlled GATE-3 evidence.
- The worktree was already dirty before this card in `scripts/autoedit-deploy.sh`, `src/autoedit/api.py`, and `src/autoedit/web/player.js`. Those changes were inspected as context but are not modified or approved by this specification.
- Production remains mock-backed. Proxies are silent; program audio is the browser master clock; source media must not play in the browser.
- The opt-in worker is private on host loopback at `127.0.0.1:8011` through merged Compose, uses the V100, reads `/data` read-only, is single-concurrency, and pins ASR model, compute type, language, alignment, and maximum batch size server-side.

### 2.2 Assumptions to validate at acceptance preflight

- The acceptance project has two visible people, two known close cameras, and one wide camera.
- The target remains a Tesla V100 32 GB and Dots TTS shares that GPU.
- Ollama can be unloaded for the coexistence test without disrupting an approved production workload.
- Peter can access the consent-cleared media and can identify both voices and the intended camera treatment.
- Dots TTS can be made resident and can execute one representative quality workload during an approved acceptance window.

A false assumption blocks the affected gate; it is not silently replaced with synthetic evidence.

### 2.3 Unknowns that execution must discover without exposing secrets

- The secure fixture root and current media hashes.
- The current Dots service/container API, image digest, resident/unloaded policy, and health endpoint.
- Current GPU process ownership, total/available VRAM, host RAM, Docker topology, container restarts, and model-cache state.
- Whether the current consent-cleared project contains every mandatory editorial scenario in Section 5.3.

### 2.4 Peter-only decisions

Peter must:

1. confirm consent and authorize use of the exact fixture;
2. identify each anonymous voice from program-audio snippets and associate it with an existing project speaker/camera;
3. approve or reject the selected word-boundary ground truth;
4. approve or reject the speaker-turn cut in the mandatory review windows; and
5. authorize the bounded Unraid/Dots acceptance run because it starts an opt-in GPU worker and exercises Dots.

Agents may prepare snippets, calculate errors, execute tests, inspect payloads, and capture sanitized evidence. Agents must not infer identity from names/transcript context or make the editorial sign-off for Peter.

## 3. Requirement catalogue

### Architecture

- **ARCH-AIGPU1-001:** The FastAPI app remains authoritative for project state, artifact validation, activity/CDL generation, review, and export. WhisperX remains an isolated private worker.
- **ARCH-AIGPU1-002:** All acceptance timestamps use integer milliseconds on the program-audio master timeline. Automatic cross-correlation offsets are applied exactly once; no manual sync nudge is introduced as a remedy.
- **ARCH-AIGPU1-003:** The accepted worker result is immutable and hash-bound. Failed, malformed, or superseded runs cannot replace the last-known-good result or the selected cut.
- **ARCH-AIGPU1-004:** Gate order is fixed: word timing -> identity confirmation -> speaker-turn cut -> coexistence. A downstream gate cannot compensate for an upstream failure.
- **ARCH-AIGPU1-005:** The VAD activity and its CDL remain preserved as versioned baseline/diagnostic evidence. WhisperX regeneration is non-destructive and cannot silently replace the current selected cut.

### Backend and data contracts

- **BACKEND-AIGPU1-001:** A live acceptance request must carry the exact analysis-audio SHA-256 and use the reviewed image digest, `large-v3`, FP16, English, alignment enabled, batch size 4, diarization enabled, and explicit two-speaker bounds for this fixture.
- **BACKEND-AIGPU1-002:** The imported artifact must validate ordered non-empty aligned words, bounded integer times, source/model provenance, the master timeline basis, anonymous turns, overlaps, mappings, and resolved-turn referential integrity before publication.
- **BACKEND-AIGPU1-003:** Operator confirmation must persist a bijective anonymous-label -> stable speaker ID -> camera association with `confirmed` status, operator identity, confirmation time, source run/artifact version, and evidence-turn IDs. Transcript/LLM evidence remains audit-only.
- **BACKEND-AIGPU1-004:** A new resolved-turn activity projection must cover the accepted timeline contiguously and deterministically. Confirmed solo speech selects the mapped close camera; true overlap, unresolved identity, low confidence, invalid mapping, and off-camera/uncertain regions select wide; silence keeps the Direct profile's wide behavior.
- **BACKEND-AIGPU1-005:** The speaker-turn cut must preserve frame snapping, source bounds, Direct `min_shot_ms=250`, no lead/tail, program audio, and complete shot-reason metadata. Every segment must have an auditable reason even when the visual angle does not change.
- **BACKEND-AIGPU1-006:** A configured real-backend failure is visible and failure-safe. It must not emit mock words/turns, select an arbitrary close-up, or overwrite the last-known-good artifact/CDL.
- **BACKEND-AIGPU1-007:** A rerun with anonymous diarizer labels swapped must retain stable identities only after current voice revalidation or fresh operator confirmation; stale label ordering alone is never authoritative.

### User interface and accessibility

- **UI-AIGPU1-001:** After a completed AI run, the app shows every anonymous speaker as `needs confirmation`, `suggested`, `confirmed`, `unresolved/conflict`, or `stale`; no speaker or camera is preselected.
- **UI-AIGPU1-002:** Each anonymous speaker offers at least two representative, non-overlapping snippets from distinct turns. Playback uses bounded ranges of `program.m4a`; silent proxies provide video, and browser source media is never requested or played.
- **UI-AIGPU1-003:** Confirmation is one identity association to existing speaker/camera labels, not a timeline or sync adjustment. The confirm action remains disabled until the mapping is complete, bijective, and explicitly acknowledged.
- **UI-AIGPU1-004:** A new artifact/model run makes prior displayed confirmation visibly stale until current voice revalidation succeeds or Peter reconfirms it. Conflicts show a clear safe-wide consequence and recovery action.
- **UI-AIGPU1-005:** The mapping panel is keyboard operable, uses native labels/buttons/radios, has visible focus, announces playback/status/errors, does not rely on color alone, and exposes snippet time ranges as text. Motion respects reduced-motion settings.
- **UI-AIGPU1-006:** At <=840 px the confirmation rows become a single column; labels, playback, and mapping controls remain visible without horizontal scrolling. Nonessential evidence detail may collapse, but status and confirmation controls may not be hidden.
- **UI-AIGPU1-007:** The review player shows analysis source, mapping status, confidence/safety state, and active shot reason in plain language. `Unresolved speaker` and `Low confidence` must visibly explain why wide was chosen.

### Operations and observability

- **OPS-AIGPU1-001:** An approved acceptance task begins with read-only discovery of GPU/CPU/RAM, Docker/Compose topology, network bindings, ports, volumes, permissions, Dots/Ollama state, health checks, and current production backend values. Secret values are never printed.
- **OPS-AIGPU1-002:** The merged base + GPU Compose render must retain the app's host networking, worker loopback-only exposure, read-only media mount, persistent model cache, readiness health check, single concurrency, and mock application defaults during acceptance.
- **OPS-AIGPU1-003:** GPU sampling runs at <=250 ms intervals from at least 10 seconds before model load until at least 30 seconds after both workloads finish. It records timestamp, total/used/free MiB, per-process PID/name/used MiB, container health/restarts, and job phase.
- **OPS-AIGPU1-004:** Coexistence includes (a) Dots resident/idle plus a cold WhisperX readiness+analysis run and (b) an actively overlapping Dots inference plus WhisperX analysis run. Ollama is unloaded for both.
- **OPS-AIGPU1-005:** The accepted maximum is the highest sampled total used VRAM across cold load, ASR, alignment, diarization, Dots-resident, and active-overlap phases. Available headroom must remain at least `max(2048 MiB, 10% of reported total VRAM)`; the harness calculates this from device-reported values.
- **OPS-AIGPU1-006:** Acceptance requires no OOM, CPU offload, model eviction, unexpected container restart, readiness loss, application health loss, queue overflow, or invalid output. Both active-overlap workloads must complete successfully.
- **OPS-AIGPU1-007:** Cleanup stops/removes only the explicitly approved temporary/opt-in worker resources, verifies GPU memory returns to the preflight range, verifies the app still reports healthy, and re-verifies `WHISPER_BACKEND=mock` and `DIARIZE_BACKEND=mock`.
- **OPS-AIGPU1-008:** Rollback for any failure is stop the acceptance workload/worker, leave or restore mock selection, preserve prior artifacts/cuts, and report the failed gate. No retry changes production defaults.

### Security and privacy

- **SEC-AIGPU1-001:** Only consent-cleared fixtures may be used. Raw media, names, transcript excerpts, snippets, exact private paths, runtime IDs, fingerprints, credentials, and HF tokens remain outside Git and durable Kanban text.
- **SEC-AIGPU1-002:** The HF token and any Dots/host credentials are supplied only through the approved secret source; logs and public errors are checked for leakage before evidence is retained.
- **SEC-AIGPU1-003:** The worker remains unreachable through NPM/LAN, accepts only path-confined read-only media, and is never exposed to make testing easier.
- **SEC-AIGPU1-004:** Mapping confirmation and acceptance evidence endpoints require an authenticated operator session and reject cross-project/run references and stale artifact versions.
- **SEC-AIGPU1-005:** Private evidence is stored under an ignored consent-controlled root with restrictive permissions. Only aggregate/redacted values and opaque fixture/run IDs may enter tracked docs or Kanban.

### Test and evidence

- **TEST-AIGPU1-001:** The secure fixture set contains at least three 3-10 minute excerpts for the broader benchmark. The bounded four-gate run may use one of them only if it includes both speakers plus every mandatory Section 5.3 review scenario; placeholder `not_labeled` JSON cannot pass.
- **TEST-AIGPU1-002:** Gate 1 checks at least three words distributed across the first, middle, and final timeline thirds, with both start and end boundaries assessed. Where turn intersection associates words with both anonymous diarizer clusters, at least one word from each cluster is included; human identity is deliberately deferred to Gate 2.
- **TEST-AIGPU1-003:** Gate 2 verifies confirmation persistence/reload, bijection, stale-version rejection, label-swap stability, transcript-only non-authority, conflict fail-closed behavior, and safe-wide output for unresolved mappings.
- **TEST-AIGPU1-004:** Gate 3 verifies exact mandatory scenario windows, contiguous activity, deterministic output, full reason metadata, frame/source bounds, safe-wide policy, browser playback, and persistence across API response, artifact, database, and player state.
- **TEST-AIGPU1-005:** Gate 4 verifies sampler continuity, valid phase markers, Dots resident and active overlap, Ollama unloaded, headroom, health/restarts, and successful outputs. A post-job snapshot cannot pass.
- **TEST-AIGPU1-006:** Targeted tests, the full mock-backed suite, compile, changed-file lint/static checks, dependency lock validation, privacy scan, and `git diff --check` pass on the exact candidate before live acceptance.
- **TEST-AIGPU1-007:** Evidence identifies source commit, worker image digest, model/runtime versions, Compose render hash, opaque fixture/run IDs, project FPS, automatic sync offsets, commands, results, and Peter's explicit decisions without private content.
- **TEST-AIGPU1-008:** Failure tests prove malformed worker output, wrong hash, unavailable worker, persistence failure, stale mapping, unresolved identity, missing wide camera, Dots failure, and VRAM threshold failure all fail closed.

### Controlling gate requirements

- **GATE-1 — Frame-level word timing.** This gate is `PASS` only when one current,
  hash-bound real worker artifact is compared with Peter-approved audible boundaries
  for exactly the deterministic selection protocol in Section 5. All six checked
  boundaries must be within one exact project frame; a structural word-count test,
  self-authored two-field `PASS` file, mock fixture, or historical run cannot pass it.
- **GATE-2 — Confirmed speaker identity.** This gate is `PASS` only when Peter's
  complete bijective mapping is persisted and reloaded for the current artifact,
  every anonymous label has representative current-voice evidence, stale versions
  are rejected, and an anonymous-label-swap rerun retains stable identity only via
  current voice revalidation or fresh confirmation. Suggested mappings, transcript
  names, LLM context, channel order, and prior anonymous labels are never identity
  truth.
- **GATE-3 — Speaker-turn cut acceptance.** This gate is `PASS` only when a candidate
  generated from the GATE-1 artifact and GATE-2 confirmations passes activity/CDL
  validation, immutable persistence, selected-cut/player evidence, all locked safety
  windows, program-audio-master continuity, and Peter's per-window editorial review.
  Generation alone, unit tests alone, or an unsaved in-memory preview cannot pass it.
- **GATE-4 — Coexistence measurements.** This gate is `PASS` only from a valid,
  explicitly authorized V100 run with continuous <=250 ms sampling, Ollama unloaded,
  Dots in Peter's intended resident/unloaded state, cold and active-overlap WhisperX
  phases, successful outputs, complete process attribution, required headroom, and
  cleanup/mock verification. Post-job snapshots, offline/mock harness data, readiness
  peaks without jobs, or unloading intended Dots residency cannot pass it.

Each gate records one of `NOT_RUN`, `BLOCKED`, `FAIL`, or `PASS`, plus exact-candidate
references and evidence pointers. `PASS` is immutable for that evidence bundle but
becomes inapplicable—not silently reusable—when its source commit, worker digest,
artifact version, fixture revision, FPS, automatic offsets, model/runtime settings,
or required human decision changes. A rerun creates a new record. The overall
AI-GPU-1 acceptance is `PASS` only when `GATE-1..4` are all current `PASS` records.

## 4. Gate entry criteria and shared evidence

All four gates use one acceptance record rooted outside Git, for example:

```text
<consent-controlled-root>/ai-gpu-1-acceptance/<opaque-run-id>/
  manifest.json
  compose-render.redacted.yaml
  worker-result.json
  word-timing-review.json
  speaker-confirmation.json
  activity-whisperx.json
  cdl-whisperx.json
  cdl-vad-baseline.json
  browser-review.json
  gpu-samples.csv
  coexistence-summary.json
  redacted-logs/
```

The actual root is private. A tracked/Kanban summary contains only opaque IDs, aggregate measurements, digests that do not identify private media, test counts, verdicts, and residual risks.

Shared entry conditions:

1. Peter has confirmed consent and the exact fixture.
2. Source commit, clean candidate diff, worker image digest, merged Compose render, model versions, and project FPS are recorded.
3. Current app production values are verified as mock without printing secrets.
4. The selected analysis WAV hash matches its manifest and queued request; a wrong hash still returns HTTP 400.
5. `/health` and `/ready` pass separately on the target V100, including enabled diarization readiness.
6. One queued ASR+alignment+two-speaker diarization job reaches `done`, and the imported artifact passes strict validation before any gate evidence is derived.
7. The prior selected artifact/CDL and VAD baseline remain preserved.

## 5. Exact acceptance gates

### GATE-1 — Word timing within one project frame

**Dependencies:** shared entry conditions only.

**Selection protocol:**

- Divide the accepted master timeline into three equal-duration thirds.
- In each third select the earliest clearly audible, non-overlapped word with both aligned start/end timestamps. Peter may reject a candidate as acoustically ambiguous; the rejection reason is recorded and the next qualifying word is used.
- Across the three selected words include both anonymous diarizer clusters where word/turn intersection makes that association available. Human identity is deliberately unknown until Gate 2. Do not select words after inspecting which candidates have the smallest model error.
- Ground-truth marks are made against `program.m4a` on the synchronized master timeline. A browser may show the silent proxy, but source media is never played. Automatic sync offsets are displayed as evidence, not adjusted.

For project FPS `fps_num/fps_den`, the tolerance is one exact project frame:

```text
frame_tolerance_ms = 1000 * fps_den / fps_num
start_error_ms = abs(aligned_start_ms - reviewed_start_ms)
end_error_ms   = abs(aligned_end_ms   - reviewed_end_ms)
```

**Pass criteria (all required):**

1. Three words and six boundaries are reviewed.
2. Every start and end error is `<= frame_tolerance_ms`; there is no averaging away an outlier.
3. Aligned and reviewed times are on the program-audio master basis, with the stored automatic offset applied exactly once.
4. All checked word ranges are ordered, inside their segment and timeline, and survive strict artifact import unchanged.
5. Peter signs that each manual boundary is an acceptable audible mark.

**Agent evidence:** exact FPS rational, selected opaque segment/word IDs, predicted/reviewed integer ms, per-boundary error, tolerance calculation, artifact validation result, and offset convention.

**Peter evidence:** explicit `PASS`/`FAIL` for each audible start/end mark and the overall gate. No transcript text or name is retained in tracked evidence.

**Failure:** keep mock, retain the failed immutable run, and correct alignment/audio-timeline handling. Manual sync adjustment is not an allowed remedy.

### GATE-2 — Confirmed speaker identity mapping with current-voice revalidation

**Dependencies:** GATE-1 passes; durable confirmation API/UI and artifact import exist.

**Confirmation protocol:**

- For every anonymous diarizer label, present at least two program-audio snippets from distinct, non-overlapping turns and different parts of the timeline where possible.
- Show the anonymous label and existing project person/camera choices neutrally. Do not infer a default from angle A/B, mic channel, anonymous label ordering, transcript names, or LLM output.
- Peter listens and selects the stable project speaker and close camera. The app validates a one-to-one mapping and records confirmation against the exact source run/artifact.
- Reload the page and read the mapping back through the public API/player state.
- Exercise a deterministic label-swap rerun test: stable identities may follow current qualifying voice evidence or fresh confirmation, never prior anonymous labels alone.

**Pass criteria (all required):**

1. Every anonymous label in the accepted two-speaker run has exactly one persisted `confirmed` mapping; every stable speaker and close camera is used at most once.
2. Every mapping retains operator, time, source run/artifact version, evidence-turn IDs, and `confirmed_mapping` provenance in resolved turns.
3. Page reload/API read returns the same complete mapping.
4. A stale artifact version cannot apply or display as current confirmation.
5. Transcript/LLM-only evidence cannot resolve identity; conflicting voice/operator evidence remains unresolved and produces no authoritative resolved turn.
6. The label-swap regression retains the same stable people only after current revalidation.
7. Peter explicitly signs that both anonymous voices were mapped to the correct visible people/cameras.

**Agent evidence:** redacted request/response shapes, persistence comparison, resolver tests, stale-version test, label-swap test, conflict test, and referential-integrity validation.

**Peter evidence:** one explicit mapping decision per anonymous label and an overall `PASS`/`FAIL`; tracked evidence stores opaque stable IDs rather than names.

**Failure:** the affected identity stays unresolved and all its intervals must route wide. No close-up authority is allowed.

### GATE-3 — Speaker-turn cut acceptance

**Dependencies:** GATE-1 and GATE-2 pass; a reviewed resolved-turn activity bridge and safe-wide cut integration exist.

**Mandatory labelled review windows:** the acceptance fixture must contain at least one certain ground-truth window for each applicable category below. If one fixture cannot provide them, add another consent-cleared excerpt rather than fabricating a case.

1. confirmed speaker 1 solo speech;
2. confirmed speaker 2 solo speech;
3. normal alternating turns in both directions;
4. true overlap/cross-talk;
5. short acknowledgement/interruption;
6. cross-mic bleed or unequal mic levels;
7. laughter/cough/room noise or silence; and
8. unresolved, low-confidence, or off-camera speech.

Ground-truth windows and intended cameras are locked before generating the candidate WhisperX CDL. Uncertain ground truth is labelled uncertain and expects wide; it is not scored as a close-up target.

**Automated pass criteria (all required):**

1. The projected activity is integer-ms, ordered, contiguous, deterministic, and covers the accepted timeline without gaps/overlaps.
2. Confirmed solo windows select the mapped close camera; overlap, uncertain/unresolved/low-confidence/off-camera windows select wide; silence selects wide.
3. Every certain mandatory window matches the locked intended camera after allowing at most one project frame at each labelled transition. Safety windows have zero wrong-close-up frames outside that transition allowance.
4. Repeating projection and CDL generation from identical inputs produces byte-identical semantic payloads.
5. The CDL is contiguous and frame-snapped; source ranges remain within probed source duration after the stored offset convention. No negative `src_in_ms` or source overrun is accepted.
6. Every reason boundary survives API response -> immutable artifact/disk -> database JSON -> player-state read. Complete clip objects, not field presence alone, are compared.
7. Reasons identify confirmed speech, overlap/cross-talk, unresolved identity, low confidence, silence, and source fallback accurately. Same-camera reason boundaries do not force a visual cut.
8. The VAD baseline artifact/CDL and previously selected cut remain unchanged.
9. Missing mappings, missing wide camera, malformed turns, or worker/persistence failure fail closed and do not create an arbitrary close-up or partial authoritative CDL.

**Manual browser pass criteria (Peter, all required):**

1. Review every mandatory window from before its first boundary through after its last boundary.
2. The intended speaker close-up appears for confirmed solo speech; overlap/uncertainty/noise safety windows stay wide.
3. Program audio plays continuously as master; video follows within one frame; silent proxies switch without source-media playback or an audio reload.
4. Active analysis source, mapping status, and shot reason are understandable and agree with what is seen/heard.
5. No selected window contains a bleed-induced wrong close-up, arbitrary unresolved close-up, visible discontinuity, or editorially unacceptable speaker-turn cut.

**Agent evidence:** locked redacted window manifest, VAD and WhisperX payloads, activity/CDL validators, persistence comparison, browser DOM/console/network evidence, screenshots or recording kept private where media is visible, and exact test commands.

**Peter evidence:** per-window `PASS`/`FAIL`, reason, and overall editorial `PASS`/`FAIL`.

**Failure:** retain VAD/mock and the prior selected cut. Create a bounded correction for activity projection, identity policy, cut policy, source bounds, player behavior, or evidence persistence as indicated; do not tune sync manually.

### GATE-4 — Peak VRAM and Ollama/Dots TTS coexistence

**Dependencies:** GATE-3 passes; Peter authorizes a bounded Unraid/Dots acceptance window; read-only discovery is complete.

**Fixed configuration:**

- target GPU: device-reported V100 total memory;
- WhisperX: reviewed image digest, `large-v3`, FP16, batch 4, English, alignment and constrained two-speaker diarization enabled;
- exact hash-bound acceptance audio and same queued job shape used by prior gates;
- Ollama: no loaded models for the full measurement;
- Dots: current approved quality configuration, using a non-sensitive 600-character workload, 12 steps, guidance 1.3; +3 dB/MP3 post-processing is reported separately because it is not the GPU model-residency load;
- worker concurrency: one queued GPU job.

**Measurement phases:**

1. Capture 10 seconds of GPU/process/container baseline with Ollama unloaded.
2. Load Dots and verify its resident/idle readiness; capture 10 seconds.
3. With Dots resident, cold-start WhisperX readiness and run the full ASR+alignment+diarization job.
4. Return to a stable co-resident state without unloading Dots.
5. Start one representative Dots generation and one WhisperX full analysis so their actual inference intervals overlap for at least 5 seconds. If the first attempt is too short to overlap, lengthen only the consent-cleared analysis excerpt or schedule start times; do not increase model/batch settings.
6. Repeat the active-overlap phase once without changing configuration.
7. Continue sampling for 30 seconds after both final workloads complete, then perform approved cleanup and idle verification.

Sampling gaps greater than 500 ms invalidate the affected run. Phase start/end times come from workload/job logs and must be reconciled with the GPU sample clock.

**Pass criteria (all required):**

1. The sampler covers every phase at <=250 ms nominal intervals and reports no gap >500 ms.
2. Both Dots generations produce non-empty playable output and both WhisperX jobs reach `done` with valid aligned words, two-speaker turns, and unchanged input hash.
3. The cold co-resident and both active-overlap runs have no CUDA OOM, CPU offload, model eviction/reload caused by pressure, readiness loss, queue overflow, container restart, app health loss, or Dots health loss.
4. Ollama reports no loaded model before, throughout, and after the measured phases.
5. The global maximum sampled used VRAM leaves at least `max(2048 MiB, 10% of total device memory)` free. The report includes total, peak used, minimum free, threshold, phase, timestamp, and contributing processes.
6. Per-process/container accounting explains the peak; unknown GPU consumers invalidate the run until identified.
7. Post-cleanup memory returns within 512 MiB of the preflight idle used-VRAM median, or the difference is explained by an intentionally resident approved service.
8. Production app backend values remain mock and application health passes after cleanup.

**Agent evidence:** redacted merged Compose render, discovery summary, Dots/WhisperX configuration identifiers, sampler CSV, phase log, health/restart checks, Ollama process checks, output validity, calculated headroom, cleanup result, and production mock verification.

**Peter evidence:** authorization of the window and acceptance/rejection of the measured Dots service state. Peter need not calculate VRAM manually.

**Failure:** stop the bounded acceptance workloads/worker, retain mock, preserve evidence, and report whether the failure was capacity, concurrency, service health, measurement validity, or unknown process ownership. Do not raise batch size or unload an intended resident Dots service to manufacture a pass.

## 6. Manual versus automated responsibility matrix

| Activity | Agent | Peter |
|---|---:|---:|
| Verify consent and fixture choice | prepare manifest | approve |
| Hash, submit, poll, validate worker job | execute | — |
| Calculate frame tolerance and boundary errors | execute | — |
| Mark whether an audible word boundary is correct | assist/capture | decide |
| Infer person from transcript/name | forbidden | — |
| Listen to snippets and map voices to people/cameras | present/persist | decide |
| Verify mapping contracts, bijection, reload, label swap | execute | — |
| Validate activity/CDL/source bounds/reasons/persistence | execute | — |
| Judge editorial cut quality in real media | provide evidence | decide |
| Inspect browser console/network/player sync | execute | witness as needed |
| Discover/snapshot GPU and Docker state | execute read-only first | authorize mutation window |
| Run sampler and calculate VRAM headroom | execute | accept intended Dots state |
| Change production backend defaults | forbidden by this plan | separate explicit decision/task |

## 7. Fixture and test-data requirements

### 7.1 Consent-controlled real media

- One bounded gate fixture may be used only if it includes both identified speakers and all eight Gate 3 categories.
- The broader release benchmark still requires at least three 3-10 minute excerpts covering alternating speech, bleed, unequal levels, overlap/interruption, noise, quiet speech, laughter/cough, off-camera speech, and uncertainty.
- Media, transcript text, names, exact paths, and fingerprints remain outside Git. Tracked fixture files use opaque IDs and schema/status only.
- Ground truth uses integer master-timeline ms, records boundary uncertainty, and is locked before candidate generation.
- Preserve hashes/configuration for VAD activity, level normalization, transcript, diarization, AI artifact, and baseline/candidate CDL.

### 7.2 Synthetic/contract fixtures

Self-contained tests must cover:

- positive/negative automatic offsets and negative pre-roll clipping;
- strict timestamp/confidence typing and source bounds;
- anonymous label swap and stale confirmation;
- duplicate/conflicting mapping and missing wide camera;
- solo, overlap, short acknowledgement, silence, unresolved, low confidence, and off-camera activity;
- same-camera reason boundaries and minimum-shot behavior;
- sampler gap, unknown GPU process, OOM/restart, insufficient headroom, and Dots failure summaries.

Ordinary tests do not download media and skip trusted-host integration cleanly when the external root is absent.

## 8. UI state specification for speaker confirmation

### Ready / needs confirmation

Show an honest `Needs confirmation` badge, anonymous voice label, two or more snippet controls, existing speaker/camera options, and a short explanation: `Confirm who this voice belongs to. This does not change sync.` No option is selected by default.

### Suggested

Show the suggested person only as a labelled suggestion with evidence count/confidence. Peter must still actively confirm for this acceptance gate. Transcript/LLM context is not shown as identity proof.

### Confirmed

Show stable person/camera, confirmation provenance, and current artifact version. Provide a deliberate `Review mapping` action; do not silently remap on rerun.

### Unresolved/conflict

State `Wide will be used until this voice is confirmed.` Explain whether evidence conflicts, snippets are insufficient, or the mapping is non-bijective. Never show success or enable close-up authority.

### Stale

When the artifact/model run changes, mark the old mapping `Checking current voice evidence` or `Needs confirmation`. Do not present the prior anonymous label as current truth.

### Loading/error/empty

Use bounded, actionable messages for snippet loading, worker unavailable, artifact invalid, stale request, and no diarization turns. Keep the prior selected cut and last-known-good evidence visible. Do not show an empty success panel or fall back invisibly to mock.

## 9. Observability and evidence schema

The private acceptance summary must include:

- gate ID and pass/fail/block status;
- UTC start/end, source commit, image digest, merged Compose render hash;
- opaque project/fixture/run IDs and project FPS rational;
- backend/model/runtime settings and automatic offset convention;
- aggregate segment/word/turn/overlap counts;
- word-boundary reviewed/predicted times and errors without text;
- mapping status/provenance counts without names;
- mandatory cut-window category, expected/actual opaque angle, and result;
- baseline/candidate aggregate cut metrics;
- GPU total/peak/min-free, sampling interval/gaps, phase, process accounting;
- Dots/Ollama/worker/app health and restart state;
- exact commands and test results;
- Peter's decisions; and
- cleanup, rollback, residual risks, and production mock verification.

Never include secret values, HF token, DB password, source paths, transcript excerpts, names, cookies, raw media, or screenshots with private content in tracked/Kanban evidence.

## 10. Failure modes and rollback

| Failure | Required behavior |
|---|---|
| Wrong hash/path | Reject before GPU work; no artifact change. |
| Word error >1 frame | Gate 1 fails; retain mock; investigate alignment/timeline math. |
| Identity ambiguous/conflicting | Gate 2 fails for close-up authority; map affected spans to wide. |
| Stale mapping/run | Reject confirmation/import; preserve prior mapping as historical only. |
| Missing wide camera | Fail authoritative cut generation visibly; do not drop timeline segments. |
| Malformed/partial worker result | Record immutable failure; preserve last-known-good artifact/DB/CDL. |
| Persistence failure | Roll back DB and artifact replacement together; prior pair remains usable. |
| Browser media/snippet error | Show actionable error; do not request source media. |
| OOM/offload/restart/insufficient headroom | Gate 4 fails; stop acceptance worker; retain mock. |
| Dots or Ollama state differs from protocol | Measurement invalid; do not reinterpret as a pass. |
| Production health regression | Stop/rollback opt-in worker changes; verify mock app recovery. |

## 11. Verification commands and evidence expectations

Commands are executed only after the named tests/harness exist. Missing tests are implementation blockers, not skips that count as passes.

```bash
# Focused contracts and worker behavior
ENV_COMMAND='env -u VIRTUAL_ENV uv run pytest'
$ENV_COMMAND \
  tests/test_ai_artifacts.py \
  tests/test_analysis_audio.py \
  tests/test_speaker_mapping.py \
  tests/test_speaker_context.py \
  tests/test_whisperx.py \
  tests/test_whisperx_jobs.py -q

# New application acceptance seams
$ENV_COMMAND \
  tests/test_speaker_mapping_api.py \
  tests/test_activity_from_turns.py \
  tests/test_cut_engine.py \
  tests/test_player_state.py \
  tests/test_timeline_state.py -q

# Trusted-host real fixture; must not exist as a fake passing stub
AUTOEDIT_GOLDEN_MEDIA_ROOT='<secure external root>' \
  env -u VIRTUAL_ENV uv run pytest \
  tests/integration/test_whisperx_golden_media.py -q

# Broad local gates
ENV_COMMAND='env -u VIRTUAL_ENV uv run pytest'
$ENV_COMMAND -q
env -u VIRTUAL_ENV uv run python -m compileall -q src tests
git diff --check

# Render only with secrets already present in the approved host environment;
# redact values before retaining evidence.
docker compose -f docker-compose.yml -f docker-compose.gpu-ai.yml \
  --profile gpu-ai config
```

The live GPU/Dots harness must be a reviewed script, not an ad hoc shell transcript. It must fail non-zero on sampler gaps, missing phase markers, invalid jobs, unknown GPU processes, insufficient headroom, service restarts, Ollama residency, cleanup drift, or non-mock production values.

## 12. Bounded implementation and evidence work packages

Each package is small enough for one Programmer worktree. No package may self-approve; each requires independent Designer compliance before Tester execution.

### Package A — trusted fixture/evaluation harness and GATE-1 evidence

**Owns:** `tests/integration/test_whisperx_golden_media.py`, new fixture-schema helpers, `tests/fixtures/golden_interview/` schemas/README, and narrowly related protocol updates.

**Requires:** `TEST-AIGPU1-001`, `TEST-AIGPU1-002`, `TEST-AIGPU1-007`, `SEC-AIGPU1-001`, `SEC-AIGPU1-005`.

**Dependency:** consent-cleared secure fixture and Peter-approved ground truth. No private media in the worktree.

**Current disposition:** the tracked contracts, adapter, synthetic tests, and
trusted-host integration entry point exist. Acceptance remains blocked until a
private consent-cleared set of at least three excerpts is present, one qualifying
fixture is bound to a real current artifact, Peter has approved its word truth, and
the resulting GATE-1 evidence passes. Placeholder tracked JSON is ineligible.

### Package B — confirmation persistence/API/UI and GATE-2 evidence

**Owns:** speaker-confirmation DB migration/schema, API endpoints, confirmation service, `src/autoedit/web/app.html`, `app.js`, `styles.css`, and dedicated API/static tests.

**Requires:** `BACKEND-AIGPU1-003`, `BACKEND-AIGPU1-007`, all `UI-AIGPU1-*`, `SEC-AIGPU1-004`, `TEST-AIGPU1-003`.

**Dependency:** current reviewed artifact/resolver contracts. Must not modify cut projection.

**Current disposition:** schema, API, app UI, and contract tests exist. Before a
GATE-2 run, independent compliance must verify current-voice revalidation is wired
through the application path—not merely available in the lower-level resolver—and
Tester must capture authenticated reload, stale-version, conflict, and label-swap
evidence against the exact candidate. Peter's real identity decision remains required.

### Package C — artifact import, activity projection, cut integration, and GATE-3 evidence

**Owns:** a new importer/projection module such as `src/autoedit/ai/import_results.py` and `activity_from_turns.py`, narrowly required API orchestration, cut/timeline/player-state integration, and dedicated tests.

**Requires:** `ARCH-AIGPU1-002` through `005`, `BACKEND-AIGPU1-002`, `004`, `005`, `006`, `UI-AIGPU1-007`, `TEST-AIGPU1-004`, `TEST-AIGPU1-008`.

**Dependency:** Package B confirmation contract. Must preserve existing VAD artifacts and selected cuts.

**Current disposition:** the bridge, cut safety, explicit source, immutable candidate,
selection, player projection, and focused correction tests exist. Recent corrective
commits and the dirty exact-candidate files mean GATE-3 requires a fresh independent
compliance review, a clean/pinned Tester candidate, private locked review windows,
browser console/network/sync evidence, and Peter's per-window editorial decision.

### Package D1 — reviewed offline acceptance harness and runbook

**Owns:** the non-secret operations harness under `scripts/`, its tests, redacted evidence schema, and acceptance-runbook updates. It does not own Compose defaults or production deployment.

**Requires:** all `OPS-AIGPU1-*`, `SEC-AIGPU1-002`, `SEC-AIGPU1-003`, `TEST-AIGPU1-005`, `TEST-AIGPU1-007`.

**Dependency:** none for offline validation. It cannot claim live acceptance.

**Current disposition:** the safe harness, canonical redacted schema, and extensive
offline tests exist. Its mock evidence correctly states `acceptance_pass=false`, and
its live `execute` mode is disabled. Independent compliance of the exact harness is
still required before adding a live adapter.

### Package D2 — authorized live GATE-4 executor/adapter

**Depends on:** Packages A-C compliance and GATE-1..3 `PASS`; Package D1 compliance;
current read-only Tower/Dots discovery; and Peter's exact host/fixture/window/action/
cleanup authorization.

**Owns:** a narrowly isolated live adapter/executor and direct tests for every external
boundary required by `docs/plans/ai-gpu-1-acceptance-runbook.md`. It may call only
reviewed allowlisted operations, must present the action plan before mutation, must
sample continuously, and must feed the existing canonical redacted validator. It
does not own Compose defaults, Unraid templates, production backend values, or Dots
quality settings. One Programmer worktree implements it; an independent Designer
reviews it before Tester may execute it.

**Acceptance blocker:** without D2, GATE-4 remains `NOT_RUN`/`BLOCKED`; a human may
not substitute an ad hoc shell transcript or manually mark mock evidence live.

### Package E — independent four-gate acceptance execution

**Owner:** Tester profile, after independent Designer compliance passes Packages A-C, D1, and D2.

**Requires:** execute all four gates in order, real browser evidence, console/network inspection, responsive/accessibility checks, live GPU/Dots evidence, and Peter's decisions. Tester reports `TEST_PASS` only if every criterion passes; otherwise it creates reproducible bounded defects. A final Designer compliance card then maps every requirement and GATE ID to direct evidence; Tester success alone is not rollout authority.

## 13. Deployment, cleanup, and later rollout

This plan authorizes no deployment. A later explicit acceptance task may start the opt-in Compose worker and exercise Dots after backup/read-only discovery and Peter approval. The app stays mock-backed and production data is not rewritten.

After all four gates pass:

1. record `FINAL_DESIGN_ACCEPTANCE_AI_GPU_1` only after independent requirement-to-evidence compliance;
2. keep production mock until Peter separately approves a per-project opt-in deployment;
3. deploy worker disabled/not selected first, render Compose, verify readiness and caller reachability, and preserve prior cuts/artifacts;
4. enable only one controlled project, never the global default;
5. run browser playback and Resolve/export continuity gates before broader authority; and
6. retain rollback to mock plus the explicit warning that running mock transcription on a real-transcript project can replace transcript content.

## 14. Risks and residual non-goals

### Risks

- Human boundary marking near soft phonemes can be ambiguous; deterministic selection plus explicit rejection reasons prevents cherry-picking.
- Anonymous labels may swap; current voice revalidation and stale-version UI prevent label-order authority.
- Current cut integration can drop unmapped solo spans; Package C must replace this with explicit safe-wide coverage.
- One-second VRAM samples can miss peaks; <=250 ms sampling and phase reconciliation are mandatory.
- Cold model load may be the true peak rather than inference; Gate 4 includes both.
- Dots service details are outside this repository; an approved read-only discovery and reviewed adapter are required before execution.
- Private media/evidence may leak through screenshots, logs, paths, or transcripts; all such evidence stays in the ignored consent-controlled root.

### Non-goals

- No manual sync or timeline-nudge workflow.
- No change to program audio, source WAVs, silent proxies, VAAPI `h264_vaapi`, NPM, central MySQL, or FCPXML contracts.
- No QSV substitution while MFX session `-9` remains unresolved.
- No LLM authority for timestamps, speaker identity, or cuts.
- No global production backend change or default promotion.
- No claim that one fixture replaces the broader three-interview benchmark or measured VAD-versus-WhisperX superiority gate.
- No production media/database mutation in this Designer task.

## 15. Acceptance evidence matrix

| Gate | Requirements | Required evidence | Decision owner |
|---|---|---|---|
| `GATE-1` | `ARCH-AIGPU1-002`, `BACKEND-AIGPU1-001/002`, `TEST-AIGPU1-002` | Valid artifact, FPS/offset record, three words/six boundary errors, Peter marks | Agent calculation + Peter audible decision |
| `GATE-2` | `BACKEND-AIGPU1-003/007`, `UI-AIGPU1-001..006`, `TEST-AIGPU1-003` | Two snippets/label, confirmed bijection, reload, stale/current-voice/label-swap/conflict tests | Peter identity decision + agent contract evidence |
| `GATE-3` | `ARCH-AIGPU1-003/005`, `BACKEND-AIGPU1-004..006`, `UI-AIGPU1-007`, `TEST-AIGPU1-004/008` | Locked windows, activity/CDL/persistence/selection validators, browser console/network/media evidence, Peter per-window result | Peter editorial decision + agent/tester evidence |
| `GATE-4` | `OPS-AIGPU1-001..008`, `SEC-AIGPU1-002/003`, `TEST-AIGPU1-005/007` | Discovery/render, <=250 ms samples, cold/resident/active phases, output/health/headroom/cleanup | Agent measurement + Peter window/state approval |

A final compliance reviewer must expand this table to every individual requirement ID and cite source, test, runtime, UI, and operational evidence. A summary without direct evidence cannot pass.

## Verdict

**DESIGN_APPROVED**

The plan is ready for bounded Programmer packages and independent compliance/testing. Execution remains dependent on consent-cleared fixtures, Peter's identity/editorial decisions, Dots/Unraid acceptance authorization, and completion of the currently missing application seams. Production remains mock-backed throughout.