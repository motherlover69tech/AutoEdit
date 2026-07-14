# WhisperX Speaker-Aware Editing & AI Roadmap

> **For Hermes:** Use `subagent-driven-development` to implement this plan task-by-task. Do not enable a non-mock AI backend in production until the real-media acceptance gates have passed.

**Goal:** Replace AUTOEDIT’s energy-level-based speaker inference with GPU-backed WhisperX transcription, alignment, and diarization so camera decisions follow identified speech rather than mic loudness/bleed; then activate schema-validated topic and editorial features through an external-primary/local-fallback LLM chain.

**Architecture:** Keep the current FastAPI app as the authoritative ingest, review, export, project-data, and job-status service. Add a separately deployed NVIDIA/CUDA AI worker that reads only the project’s synchronised analysis audio and writes versioned JSON artifacts. The app validates and imports those artifacts into the existing database/timeline pipeline. The current level/VAD path remains a visible fallback and diagnostic source, but is no longer the authority for choosing the speaker/camera once WhisperX is enabled.

**Tech Stack:** Existing Python 3.12/FastAPI/SQLAlchemy/MySQL/pytest application; NVIDIA Container Toolkit + CUDA/PyTorch/CTranslate2; WhisperX (faster-whisper ASR + word alignment + pyannote diarization); **DeepSeek V4 Flash** as the planned external semantic primary with local Ollama **Qwen3.5 9B Q4_K_M** fallback; ffmpeg; existing NPM/MySQL/VAAPI app deployment.

---

## Documentation review / current state

The project documentation is aligned with the proposed direction:

- `AI_HANDOFF.md` explicitly marks transcription as `mock_transcribe()` and diarization as `mock_diarize()` / simple channel mapping. It names real Whisper, diarization, and LLM topic segmentation as outstanding blockers.
- `src/autoedit/config.py` already reserves `WHISPER_BACKEND`, `WHISPER_MODEL`, `DIARIZE_BACKEND`, `OLLAMA_BASE_URL`, and `LLM_MODEL`; production compose deliberately pins both speech backends to `mock`.
- Current audio activity is derived from 20 ms RMS loudness envelopes, percentile noise thresholds, and analysis-only level normalization. `level_normalization.py` corrects unequal mic gain, but cannot determine the physical talker when both lavaliers capture both voices. That is the observed failure mode.
- The current cut engine consumes an `activity.json` timeline. This is the correct contract to preserve: replace its speaker authority, not the player, CDL, exports, or automatic audio synchronization.
- The current Docker image contains ffmpeg and Intel VAAPI support but no CUDA/PyTorch/WhisperX dependencies. The app’s pipeline is also an in-process background thread. A dedicated GPU worker is safer than trying to make the public web container simultaneously serve Intel VAAPI and NVIDIA ML workloads.
- Existing Ollama support is only a client seam at present. The topic, transcription, diarization, and title stages remain mock/template/deterministic according to `AI_HANDOFF.md`.

## Key decision

**Use WhisperX, not level comparison, as the primary source of “who spoke when.”**

WhisperX will provide:

1. real transcript segments;
2. word-level timestamps aligned to the master timeline;
3. diarized speaker turns; and
4. a confidence/audit trail for downstream cut decisions.

It will **not** magically know that pyannote’s anonymous `SPEAKER_00` is “Speaker A” or which camera belongs to that person. AUTOEDIT must maintain a per-project speaker identity map. The worker should suggest that mapping from audio evidence, but the UI must require a lightweight confirmation when confidence is low. That is a one-time identity confirmation, not unacceptable manual timeline nudging.

## Non-goals / protected contracts

- Do not change the source-media ingest format, existing cross-correlation audio-sync algorithm, program-audio-master player design, FCPXML/EDL contracts, or the Direct cut profile as part of this work.
- Do not modify source WAVs or program audio to “fix” bleed. Analysis files are derived artifacts only.
- Do not silently fall back to mock output when a configured real backend fails. Mark the project/stage as an actionable error with logs and retain the prior successful artifacts.
- Do not enable `WHISPER_BACKEND=whisperx` or `DIARIZE_BACKEND=whisperx` in the live compose configuration until the fixture and real-interview gates below pass.
- Keep Stage 7.4’s XSS/multi-author manual gate separate. It should not block planning or implementation of this AI branch, but should not be accidentally relabelled as complete.

---

## Delivery sequence

### Phase 0 — Capture a real-media benchmark before changing behaviour

**Objective:** Establish whether WhisperX improves cuts on the actual bleed/noise problem, rather than optimising only synthetic tests.

**Files:**
- Create: `tests/fixtures/golden_interview/README.md`
- Create: `tests/fixtures/golden_interview/expected/speaker_turns.json`
- Create: `tests/fixtures/golden_interview/expected/transcript_excerpt.json`
- Create: `tests/fixtures/golden_interview/expected/camera_decisions.json`
- Create: `docs/ai/whisperx-evaluation-protocol.md`
- Modify: `docs/plans/TESTING_STRATEGY.md`

**Steps:**

1. Obtain consent-cleared, non-sensitive excerpts from at least three real interviews (target 3–10 minutes each), including cross-mic bleed, interruptions/overlap, room noise, quiet speech, and normal alternating turns. Do not commit originals if licensing/privacy makes that inappropriate; document a secure local fixture path and a deterministic manifest instead.
2. Independently label a small ground-truth subset at word/turn level: speaker identity, start/end time, true overlap, and the intended camera. Label uncertainty explicitly rather than inventing exact boundaries.
3. Export the current artifacts for the same material: `loudness.json`, `level_normalization.json`, `activity.json`, `diarization.json`, `transcript.json`, and CDL. Preserve these as baseline measurements, not expected production output.
4. Define measurable gates: speaker-turn F1/DER, missed-overlap rate, word timestamp tolerance, transcript WER where transcripts are available, cut-agreement rate, and false cuts during bleed/noise. Set acceptance thresholds only after seeing the baseline; the initial requirement is a material improvement over the current energy-based route, not a made-up universal DER target.
5. Add a redacted evaluation command that runs the benchmark only when `AUTOEDIT_GOLDEN_MEDIA_ROOT` is supplied. The ordinary test suite must remain self-contained and fast.

**Verification:**

```bash
# Always runnable unit/contract suite
env -u VIRTUAL_ENV uv run pytest -q

# Only on the trusted fixture host; never commit media paths or credentials
AUTOEDIT_GOLDEN_MEDIA_ROOT=/secure/autoedit-fixtures \
  env -u VIRTUAL_ENV uv run pytest tests/integration/test_whisperx_golden_media.py -q
```

---

### Phase 1 — Define versioned AI artifacts and backend contracts

**Objective:** Make real AI outputs importable, inspectable, repeatable, and safely replaceable without breaking current projects.

**Files:**
- Create: `src/autoedit/ai/__init__.py`
- Create: `src/autoedit/ai/contracts.py`
- Create: `src/autoedit/ai/artifacts.py`
- Create: `tests/test_ai_contracts.py`
- Create: `tests/test_ai_artifacts.py`
- Modify: `src/autoedit/config.py`
- Modify: `src/autoedit/progress.py`
- Modify: `src/autoedit/api.py`
- Modify: `docs/plans/TESTING_STRATEGY.md`

**Design:**

1. Define a strict versioned artifact schema at `audio/ai/v1/result.json`, containing:
   - input manifest: source WAV paths, SHA-256/duration/sample rate, sync offsets, analysis mix strategy, model IDs, backend version, and run timestamp;
   - ASR segments with language, text, start/end milliseconds, and word timestamps/confidence;
   - diarization turns with anonymous diarizer IDs, start/end milliseconds, confidence where available, and overlap representation;
   - resolved `speaker_turns` with stable `speaker_id`, optional human label, confidence, and provenance;
   - `speaker_mappings` with status `confirmed`, `suggested`, or `unresolved` and evidence;
   - run warnings/errors and deterministic artifact version.
2. Keep output times as integer master-timeline milliseconds. Every worker input/output must use the existing sync convention and record the timeline basis explicitly.
3. Add explicit backend values and validation: `mock`, `whisperx`; reject unsupported values at startup. Add settings for worker URL, request timeout, device/compute type, batch size, language policy, diarization model, and a non-secret Hugging Face token reference/availability check.
4. Do not overload `audio/diarization.json` silently. Either emit a compatibility projection from the versioned artifact or make that path a documented generated view. Existing projects without the new artifact must keep using the current mock/VAD pipeline.
5. Extend progress data so UI distinguishes `AI speech analysis`, `speaker mapping required`, `AI failed`, and `fallback VAD mode`; avoid presenting placeholder output as verified AI.

**Tests:**

- Schema rejects negative/non-integer times, inverted intervals, unknown resolution state, or source hashes that do not match the worker manifest.
- All imported word and speaker times remain on the synced master timeline.
- A failed/retried run cannot replace the last known-good artifact.
- Old projects and `mock` runs continue to satisfy the old artifact/read API contract.

---

### Phase 2 — Create an NVIDIA WhisperX worker, isolated from the web app

**Objective:** Provide a deployable GPU runtime without destabilising FastAPI, MySQL, NPM, or Intel VAAPI proxy encoding.

**Files:**
- Create: `services/whisperx-worker/Dockerfile`
- Create: `services/whisperx-worker/pyproject.toml`
- Create: `services/whisperx-worker/src/whisperx_worker/app.py`
- Create: `services/whisperx-worker/src/whisperx_worker/service.py`
- Create: `services/whisperx-worker/src/whisperx_worker/health.py`
- Create: `services/whisperx-worker/tests/test_contract.py`
- Create: `docker-compose.ai.yml`
- Modify: `docker-compose.yml`
- Modify: `.env.example`
- Modify: `docs/DEPLOYMENT.md`
- Create: `docs/ai/whisperx-worker-operations.md`

**Design:**

1. Build the worker from a CUDA/PyTorch-compatible base image that matches the incoming NVIDIA driver/GPU. **Tesla V100 is Volta (SM 7.0): use CUDA 12.x, not CUDA 13.x, because CUDA 13 removes Volta support.** Current WhisperX releases target Torch/CUDA 12.8; NVIDIA lists Linux CUDA 12.8 GA as requiring driver `>=570.26`. Before pinning the final image, run the GPU smoke check below and require `torch.cuda.get_device_capability() == (7, 0)` plus a successful FP16 WhisperX inference. Pin Python, Torch/CUDA, CTranslate2, WhisperX, and pyannote versions in a lockfile/image tag; do not use floating `latest` model/runtime dependencies.
2. Keep the existing `app` service’s `/dev/dri`/VAAPI setup unchanged. The worker gets NVIDIA GPU access through the host’s NVIDIA Container Toolkit and a read/write mount of the same project data root; it does not expose source media publicly.
3. Expose only private host/LAN routes or a Docker-internal network. Do not proxy the worker through NPM or expose it to the internet.
4. Implement private endpoints:
   - `GET /health` — runtime, CUDA availability, model availability, and no secrets;
   - `POST /v1/analyze` — validate project ID/input manifest and run ASR/alignment/diarization;
   - `GET /v1/jobs/{id}` — status/progress/log-safe error;
   - `POST /v1/jobs/{id}/cancel` — optional but useful for reruns.
5. Make the service single-job/concurrency-limited by default, with GPU memory settings configurable. A second job must queue rather than trigger OOM or unload a running model.
6. At container startup, perform a lightweight CUDA/WhisperX import check. Model downloads should be an explicit provision/warm-up operation, not an accidental request-time surprise.
7. WhisperX diarization commonly depends on pyannote gated models/Hugging Face authentication. Keep the token out of git, test its capability during worker readiness, and fail clearly if it cannot access the selected diarization model.

**Deployment gates:**

```bash
# On the Unraid host after NVIDIA runtime is installed and worker is deployed.
docker compose --env-file .env --env-file .env.production \
  -f docker-compose.yml -f docker-compose.ai.yml config

docker compose --env-file .env --env-file .env.production \
  -f docker-compose.yml -f docker-compose.ai.yml up -d --build whisperx-worker

curl -fsS http://127.0.0.1:<private-worker-port>/health
```

Expected health payload must identify CUDA as available and the pinned ASR/alignment/diarization models as ready, without leaking token/model-cache paths that expose secrets.

---

### Phase 3 — Prepare robust analysis audio and preserve sync

**Objective:** Give WhisperX a clean, reproducible analysis input while treating the two bleed-prone lavs as evidence rather than speaker truth.

**Files:**
- Create: `src/autoedit/ai/audio_prep.py`
- Create: `tests/test_ai_audio_prep.py`
- Modify: `src/autoedit/audio.py`
- Modify: `src/autoedit/program_audio.py`
- Modify: `src/autoedit/api.py`
- Modify: `services/whisperx-worker/src/whisperx_worker/service.py`

**Design:**

1. Reuse existing extracted WAVs and automatic cross-correlation offsets. Never introduce a manual sync offset workflow and never zero low-confidence sync values; retain the current fail-loud sync diagnostics.
2. Produce a derived, mono `audio/analysis/whisperx_input.wav` at the worker-required sample rate. Its manifest records each source channel and offset.
3. Select the initial analysis strategy from measured audio quality—not from the person label. Compare at least: best single lav, synchronized gain-normalized mix, and an optional weighted mix. On real benchmark clips, choose the strategy with the best diarization/transcription score.
4. Do not use raw RMS dominance to declare who is speaking. Channel energy may be retained as weak, auditable evidence for mapping anonymous diarizer IDs to the two configured people, not as a cut decision.
5. If a waveform contains destructive double/echoed speech after synchronization, flag it and choose the best single-channel input rather than averaging it. Persist the selected strategy and quality scores.
6. Keep `audio/program.m4a` unchanged as the review-player master clock; analysis audio is never played to reviewers and never exported as the program mix.

**Tests:**

- Input manifest accurately applies known positive/negative offsets and duration boundaries.
- Source WAVs and program mix hashes do not change.
- Strategy selection is deterministic for fixture metrics.
- Invalid/missing WAVs fail before a worker request is made.

---

### Phase 4 — Implement WhisperX ASR, alignment, diarization, and speaker identity resolution

**Objective:** Generate reliable speaker turns and transcript data, including proper behaviour for overlap, bleed, noise, and uncertain identity.

**Files:**
- Create: `services/whisperx-worker/src/whisperx_worker/whisperx_backend.py`
- Create: `services/whisperx-worker/src/whisperx_worker/diarization.py`
- Create: `src/autoedit/ai/whisperx_client.py`
- Create: `src/autoedit/ai/import_results.py`
- Create: `src/autoedit/ai/speaker_mapping.py`
- Create: `tests/test_whisperx_client.py`
- Create: `tests/test_whisperx_import.py`
- Create: `tests/test_speaker_mapping.py`
- Modify: `src/autoedit/transcribe.py`
- Modify: `src/autoedit/diarize.py`
- Modify: `src/autoedit/api.py`
- Modify: `src/autoedit/db/schema.py`
- Create: `src/autoedit/db/migrations/00xx_ai_speech_metadata.py`

**Design:**

1. Run WhisperX ASR on the chosen analysis audio, then align words. Persist original segment/word data as returned plus normalized integer-ms projections; do not fabricate word confidence if the backend does not provide it.
2. Run WhisperX/pyannote diarization over the same synchronized master timeline. Preserve anonymous diarizer labels separately from the project’s human names.
3. Add data fields/tables only where required for durable identity and auditability: `speaker_id`, diarizer label, mapping status/confidence, model/artifact version, and transcript/turn provenance. Keep current `transcript_segments` compatibility fields populated from the imported artifact.
4. Resolve diarizer labels in this priority order:
   - previously confirmed project mapping, if its voice evidence remains valid;
   - high-confidence automatic proposal based on multiple turns and channel-quality/dominance evidence;
   - a small UI confirmation flow: present two short representative clips and ask the operator to match anonymous Speaker A/B to the existing visible person/camera labels;
   - `unresolved` if evidence conflicts. Unresolved turns go to wide/manual-review treatment, never arbitrary camera cuts.
5. Treat overlaps as first-class. If diarization represents overlapping speakers, emit both speaker IDs for the overlap. Do not collapse to the louder channel merely because it is louder.
6. Add a confidence policy: low-confidence/asr-uncertain/identity-unresolved spans should select the wide angle, be labelled in the timeline, and be reviewable. The system should prefer a stable wide shot over a confidently wrong close-up.
7. Make `POST /projects/{id}/transcribe` and `/diarize` dispatch based on the selected backend but preserve explicit mock behaviour for test/dev. A real configured backend failure returns an error; it must not generate mock words/turns.

**Tests:**

- Worker response handling: timeout, unavailable worker, invalid JSON/schema, model failure, retry, and last-good artifact preservation.
- Import converts sample/float timestamps to valid integer master milliseconds without out-of-range words/turns.
- Mapping confirmation makes later reruns stable even if pyannote swaps anonymous labels.
- A low-confidence or unresolved mapping never creates a close-up cut.
- Overlap emits both speakers and flows to the wide rule.
- Existing mock transcription/diarization tests continue to pass when mock is selected.

---

### Phase 5 — Make the cut engine consume speaker turns rather than mic VAD

**Objective:** Cut to the camera for the resolved speaker, while retaining VAD as fallback and diagnostics.

**Files:**
- Create: `src/autoedit/ai/activity_from_turns.py`
- Create: `tests/test_activity_from_turns.py`
- Modify: `src/autoedit/activity.py`
- Modify: `src/autoedit/cut_engine.py`
- Modify: `src/autoedit/api.py`
- Modify: `src/autoedit/web/player.js`
- Modify: `src/autoedit/web/styles.css`
- Modify: `tests/test_activity.py`
- Modify: `tests/test_cut_engine.py`
- Modify: `tests/test_timeline_state.py`

**Design:**

1. Build a new activity timeline from resolved diarization turns, with optional word/speech evidence. It must retain the current `{start_ms, end_ms, active}` shape so CDL/export/player remain compatible, plus `source: "whisperx"`, confidence, mapping status, and audit metadata.
2. Retain the old energy/VAD activity output as `audio/activity_vad.json` or a clearly versioned diagnostic artifact. Never overwrite it with a different semantic meaning without recording source/version.
3. Prefer WhisperX-derived activity only when artifact validation, mapping status, and benchmark gates pass. Otherwise choose the existing VAD activity only when explicitly configured/visible to the operator.
4. Cut policy:
   - one resolved, confident speaker → mapped close camera;
   - two speakers/true overlap → wide;
   - unresolved/low-confidence/noisy region → wide;
   - silence → current Direct-profile wide behaviour;
   - retain existing 250 ms anti-chatter/frame snapping, but apply it after speaker-turn construction rather than using it to mask diarization errors.
5. Add timeline UI indication of analysis source and confidence. Reviewers should be able to see why a shot stayed wide or why it selected a person, without exposing raw secret/model data.
6. Add a project-level processing option to regenerate cuts from `vad` or `whisperx` for A/B review. The current cut remains immutable until the operator selects/saves the regenerated one.

**Tests and real-media acceptance:**

```bash
env -u VIRTUAL_ENV uv run pytest \
  tests/test_activity_from_turns.py \
  tests/test_activity.py \
  tests/test_cut_engine.py \
  tests/test_player_state.py \
  tests/test_timeline_state.py -q

AUTOEDIT_GOLDEN_MEDIA_ROOT=/secure/autoedit-fixtures \
  env -u VIRTUAL_ENV uv run pytest tests/integration/test_whisperx_golden_media.py -q
```

Manual gate on actual interviews: inspect rapid alternation, cross-talk, both people talking, laughter/coughs, and one person speaking off-camera. Confirm the new cut makes fewer bleed-induced wrong close-ups than the baseline and preserves audio sync in the browser and Resolve export.

---

### Phase 6 — Add the minimal speaker-mapping review UI

**Objective:** Resolve the one ambiguity diarization cannot know automatically: which anonymized voice belongs to which visible person/camera.

**Files:**
- Modify: `src/autoedit/web/app.html`
- Modify: `src/autoedit/web/app.js`
- Modify: `src/autoedit/web/styles.css`
- Modify: `src/autoedit/api.py`
- Create: `tests/test_speaker_mapping_api.py`
- Modify: `tests/test_ingest_ui_static.py`

**Behaviour:**

1. After an AI run, show `confirmed`, `suggested`, or `needs confirmation` alongside each anonymous diarizer speaker.
2. For uncertain mappings, provide a small number of playable representative snippets and a one-click association to existing person/camera labels. Store the confirmation with artifact/model version and user/time provenance.
3. Do not ask for timeline nudges or individual-cut correction in this flow. The user only confirms identity; rerunning rebuilds the whole activity/CDL deterministically.
4. Provide `Use VAD fallback` and `Regenerate with WhisperX` actions with clear non-destructive wording.
5. Show a clear failure state if GPU worker, model access, or diarization fails—no empty success screen and no invisible mock fallback.

**Manual gate:** map two speakers from short sample snippets, regenerate, verify the cut selects the intended camera and playback/export timing remains frame-consistent.

---

### Phase 7 — Activate semantic LLM features after speech is real

**Objective:** Use an inexpensive external primary plus a fully local fallback for text understanding only after real speaker-attributed transcription is trustworthy.

**Files:**
- Modify: `src/autoedit/llm_client.py`
- Create: `src/autoedit/ai/llm_schemas.py`
- Modify: `src/autoedit/topics.py`
- Modify: `src/autoedit/conciseness.py`
- Modify: `src/autoedit/nl_intent.py`
- Modify: `src/autoedit/title_generator.py`
- Create: `tests/test_llm_schemas.py`
- Create: `tests/test_topics_llm.py`
- Create: `tests/test_nl_intent_llm.py`
- Modify: `docs/DEPLOYMENT.md`
- Create: `docs/ai/local-ollama-features.md`

**Design:**

1. Keep semantic LLMs separate from WhisperX: they improve topic/editorial work and are never the speech, timestamp, diarization, or speaker-identity authority.
2. Implement a provider-neutral chain in this order: `deepseek-v4-flash`; local `hf.co/unsloth/Qwen3.5-9B-GGUF:Q4_K_M`; then visible stage failure or an explicitly labelled deterministic non-AI result. Trigger fallback for timeout, rate limit, account/credit failure, 5xx, empty output, or invalid schema after one bounded retry.
3. Implement features in this order:
   - topic segmentation and concise summaries from attributed transcript chunks;
   - natural-language sub-edit intent that resolves against known topics/ranges;
   - title/description/clip suggestions from verified summaries;
   - optional LLM-assisted edit suggestions, always non-destructive and reviewable.
4. Add strict JSON-schema validation and bounded retries to every provider response. JSON mode alone is insufficient. Validate ranges, non-overlap, required labels, transcript-only evidence, and provenance before writing DB rows.
5. Chunk transcript context deterministically with overlap and source timestamps. Carry speaker labels and links to source turns; never allow an LLM to invent speaker times or rewrite the authoritative transcript.
6. **Production primary: `deepseek-v4-flash`.** Disable thinking for routine extraction/classification, require structured output, keep credentials only in deployment secrets, and persist provider, exact model, prompt/schema version, source hash, fallback status, and failure reason.
7. **Local fallback: `hf.co/unsloth/Qwen3.5-9B-GGUF:Q4_K_M` (approximately 6.6 GB).** Use `think=false`, strict schemas, and an AUTOEDIT request context around 16K rather than the Ollama server maximum. The host currently uses `q8_0` KV cache because `f16` spilled to CPU. Unload the model after work when GPU contention matters.
8. Keep the installed Qwen3.6 27B Q4_K_M (approximately 17 GB) only as an optional offline quality comparison, not a real-time default. Do not permit CPU offload or concurrent WhisperX inference to count as successful acceptance.
9. Remove randomized mock degradation from production LLM paths. If both providers fail, the API and stored artifact must say so; any deterministic non-AI fallback must be visibly identified and must not be represented as AI output.

**Verification:**

```bash
# Before production configuration changes: validate the local fallback runtime.
curl -s http://192.168.50.50:11434/api/tags | jq .
curl -s http://192.168.50.50:11434/api/ps | jq .

# Run the app’s schema/fallback tests.
env -u VIRTUAL_ENV uv run pytest tests/test_llm_schemas.py tests/test_topics_llm.py tests/test_nl_intent_llm.py -q
```

---

### Phase 8 — Production rollout, observability, and documentation truth pass

**Objective:** Deploy safely and leave the system accurately documented for later AI sessions.

**Files:**
- Modify: `docker-compose.yml`
- Modify: `docker-compose.ai.yml`
- Modify: `.env.example`
- Modify: `docs/DEPLOYMENT.md`
- Modify: `AI_HANDOFF.md`
- Modify: `jobs/BACKLOG.md`
- Modify: `docs/plans/TESTING_STRATEGY.md`
- Create: `docs/ai/operational-runbook.md`

**Steps:**

1. Create a feature branch and deploy the worker disabled/not selected first. Verify app health, current VAD processing, existing player, and existing FCPXML export are unchanged.
2. Deploy the worker privately, warm models, and run a one-project controlled analysis. Do not alter the current rough cut automatically.
3. Use the benchmark and human A/B review to compare VAD and WhisperX cuts. Require improvement on bleed/noise clips before changing the default project processing mode.
4. Enable WhisperX first per project, then make it the default only after repeated successful projects. Retain an explicit VAD fallback option for operational recovery.
5. Record worker image version, model versions, backend configuration, observed GPU VRAM/runtime, fixture results, and remaining manual gates. Do not record secrets, HF tokens, database passwords, or raw interview content.
6. Verify the full app suite, deployment render, worker health, a real browser playback run, and a Resolve export before declaring the stage complete.

**Final verification commands:**

```bash
env -u VIRTUAL_ENV uv run pytest -q
env -u VIRTUAL_ENV uv run python -m compileall -q src tests
git diff --check

# On Unraid, using deployment secrets only from the environment.
docker compose --env-file .env --env-file .env.production \
  -f docker-compose.yml -f docker-compose.ai.yml config
```

---

## Risks and mitigations

| Risk | Mitigation |
| --- | --- |
| WhisperX/pyannote anonymous labels swap between runs | Persist a project speaker-identity mapping and require confirmation when auto-mapping is not reliable. |
| Both lavs create a poor combined signal | Evaluate best-single-channel versus synchronized mix; retain selected strategy/quality metrics and never assume averaging is better. |
| Diarization is uncertain in overlaps, noise, laughter, or off-mic speech | Preserve overlap/uncertainty; select wide rather than a false close-up. |
| CUDA/PyTorch version conflicts or VRAM OOM disrupt the app | Separate GPU worker, pinned image/runtime, one-job queue, health/warm-up checks; keep public FastAPI/VAAPI container independent. |
| pyannote model access token/gated model unavailable | Explicit worker readiness check and actionable failure; no silent mock fallback. |
| In-process app thread cannot survive restarts | Keep long GPU work in a worker job model; app imports only completed validated artifacts. |
| LLM hallucination affects editorial metadata | LLM writes only validated, non-destructive semantic outputs; authoritative transcript/times/identity remain deterministic artifacts. |
| Existing working projects regress | Preserve VAD/mock path, immutable prior cuts, version artifacts, feature-gate real backend, and A/B before default switch. |

## Resolved constraints and remaining decisions

1. The worker target is the same Unraid host on a Tesla V100 32 GB; the pinned CUDA/Torch/WhisperX image and FP16 readiness have been exercised there.
2. The host-networked app reaches the bridge-networked worker through a loopback-only published port at `127.0.0.1:8011`; the worker must never be routed through NPM.
3. Privacy/consent rules and storage location for golden real-interview fixtures.
4. Preferred confirmation UX: identity mapping in ingest immediately after analysis (recommended) or a separate project-analysis panel.
5. Whether to retain both high-quality and low-latency WhisperX model profiles once benchmarked, or start with one quality-first profile only (recommended for the first release).

## Definition of done for the first real-AI release

- WhisperX ASR, alignment, diarization, artifact import, and speaker mapping run on the GPU worker using a validated real-media fixture set.
- Audio sync remains fully automatic and no source/program audio is modified.
- Camera activity/Cut decisions use confirmed or high-confidence diarized speaker turns; uncertainty and overlaps choose wide.
- Measured bleed/noise performance beats the current energy/VAD baseline on agreed real examples.
- Local Ollama semantic features are not enabled until they consume real, validated speaker-attributed transcripts.
- Existing mock/VAD mode remains selectable and a worker failure is explicit/recoverable.
- Full tests, browser playback, and Resolve export gates pass; all continuity/deployment/testing documentation reflects the actual deployed state.
