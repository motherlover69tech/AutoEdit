# Audio-Visual Speaker Evidence Implementation Plan

> **For Hermes:** Use `autoedit-agent-team` and `subagent-driven-development` to implement this plan task-by-task. Keep production cut authority unchanged until every promotion gate passes.

**Goal:** Improve AUTOEDIT's speaker/camera decisions on mic bleed, rapid turns, post-gap ambiguity, overlap, and off-camera speech by adding auditable visual evidence without allowing a general vision LLM to invent authoritative timestamps.

**Architecture:** Preserve automatic audio synchronization and WhisperX word/diarization artifacts as the audio timeline. Add a shadow-mode visual evidence pipeline that extracts explicitly timestamped frames around ambiguous turns, obtains schema-constrained Qwen3.8 assessments, and stores them separately from authoritative activity. Benchmark that evidence first; if useful, add a specialist audio-visual active-speaker detector for timing and use Qwen only for identity assistance and ambiguous-window reasoning. A deterministic fusion policy may influence cuts only after real-media gates pass, and low-confidence/conflicting evidence always selects wide.

**Tech Stack:** Existing FastAPI/SQLAlchemy/MySQL AUTOEDIT app; existing isolated WhisperX/V100 worker and versioned AI contracts; ffmpeg/PyAV frame extraction; local Ollama 0.31.2 with `hf.co/unsloth/Qwen3.8-27B-GGUF:Q4_K_M`; JSON Schema/Pydantic; optional TalkNet-compatible active-speaker detector after the shadow benchmark; pytest; existing player/CDL audit metadata.

---

## Locked decisions

1. **Automatic audio sync remains authoritative.** Do not add manual timeline nudging or alter the existing cross-correlation sign convention.
2. **Qwen is not a timing authority.** It may classify explicitly timestamped inputs, suggest visual identity, and explain ambiguity, but it may not create, move, or rewrite word/turn boundaries.
3. **WhisperX remains the transcript/alignment source.** Visual evidence may corroborate or dispute a diarized turn; it does not replace ASR.
4. **A specialist audio-visual active-speaker detector is the preferred timing layer** if the Qwen shadow experiment proves visual evidence is useful.
5. **Operator-confirmed person/camera mappings remain identity authority.** Qwen suggestions are non-authoritative until confirmed.
6. **Shadow first, authority later.** Initial outputs must never change `activity.json`, a saved cut, playback, FCPXML, or EDL.
7. **Safe-wide on uncertainty.** Conflicts, low confidence, off-camera speech, missing faces, and true overlap route to wide once fusion is eventually promoted.
8. **Single-GPU sequential execution.** WhisperX, Qwen, Dots TTS, and any active-speaker model must not run concurrently on the V100. Qwen uses `keep_alive=0` for this workflow.
9. **No raw private media or identity claims in Git.** Store only schemas, synthetic fixtures, redacted aggregate metrics, and consent-controlled local manifests.

---

## Promotion ladder

| Level | Behaviour | May change cuts? |
| --- | --- | --- |
| L0 | Offline probe against consent-controlled windows | No |
| L1 | Project shadow artifact and UI comparison | No |
| L2 | Specialist active-speaker benchmark | No |
| L3 | Deterministic fusion generates an immutable candidate cut | Only a new unselected candidate |
| L4 | Operator may select the candidate per project | Yes, explicit selection only |
| L5 | Eligible to become the default after repeated real-project acceptance | Yes, separate rollout decision |

No level is implied by code completion alone; each requires its stated live/real-media gate.

---

### Task 1: Freeze the shadow-evidence contract

**Objective:** Define strict, source-bound visual evidence that cannot masquerade as speaker timing authority.

**Files:**
- Create: `src/autoedit/ai/visual_evidence.py`
- Test: `tests/test_visual_evidence_contract.py`
- Modify: `src/autoedit/ai/contracts.py`
- Modify: `docs/plans/TESTING_STRATEGY.md`

**Contract:**

- `VisualFrame`: `frame_id`, `camera_id`, `master_time_ms`, `source_time_ms`, dimensions, SHA-256, relative path.
- `VisualEvidenceWindow`: existing `source_turn_ids`, requested start/end master milliseconds, ordered frame IDs, extraction FPS, source artifact version.
- `VisualAssessment`: per-camera `visible_face`, `mouth_activity` (`none|weak|strong|unknown`), `behaviour` (`speaking|listening|reaction|off_camera|unknown`), confidence, and bounded explanation.
- `VisualEvidenceArtifact`: run/model/prompt/schema versions, source hashes, ordered windows, assessments, warnings, and `authority: "shadow_only"`.
- The schema must contain no field that can replace `start_ms`/`end_ms` of a WhisperX word or diarization turn.

**TDD sequence:**

1. Write tests rejecting non-integer/out-of-range master times, duplicate frame IDs, unordered timestamps, unknown cameras, source turns absent from the bound WhisperX artifact, unverified paths/hashes, model-supplied timestamps, and any authority other than `shadow_only`.
2. Run the focused test and confirm RED for missing contracts.
3. Implement the minimal Pydantic contracts and source-binding validation.
4. Run focused tests and confirm GREEN.
5. Commit only the contract/tests/docs slice.

**Verification:**

```bash
env -u VIRTUAL_ENV uv run pytest tests/test_visual_evidence_contract.py -q
git diff --check
```

---

### Task 2: Build deterministic ambiguous-window selection

**Objective:** Select only the parts of an interview where visual evidence could materially change confidence.

**Files:**
- Create: `src/autoedit/ai/visual_window_selector.py`
- Test: `tests/test_visual_window_selector.py`
- Modify: `src/autoedit/ai/activity_from_turns.py` only if a reusable ambiguity reason enum is needed; do not change output behaviour.

**Initial triggers:**

- post-gap turn with a word crossing the diarization onset;
- WhisperX mapping unresolved or below configured confidence;
- rapid speaker alternation below a configured interval;
- overlapping diarization turns;
- off-camera/uncertain-camera metadata;
- conflict between current diarization and a prior confirmed mapping;
- known real-review marker supplied by the fixture manifest.

**Behaviour:**

- Produce deterministic windows with bounded pre/post roll and links to existing word/turn IDs.
- Merge overlapping requested windows without losing trigger reasons.
- Cap total windows/frame budget per project and retain a visible `budget_exhausted` warning.
- Never scan an entire interview at high frame rate during the first experiment.

**TDD sequence:** RED selector tests → minimal deterministic selector → focused GREEN → full relevant speaker/activity tests.

**Verification:**

```bash
env -u VIRTUAL_ENV uv run pytest \
  tests/test_visual_window_selector.py \
  tests/test_activity_from_turns.py -q
```

---

### Task 3: Extract timestamped frames without changing media

**Objective:** Generate small visual-analysis derivatives on the existing master timeline.

**Files:**
- Create: `src/autoedit/ai/visual_frames.py`
- Test: `tests/test_visual_frames.py`
- Modify: `src/autoedit/ffproc.py` only if the existing watchdog wrapper must be reused.

**Behaviour:**

- Use ffmpeg in the deployed app/worker environment; tests mock subprocesses and verify arguments.
- Initial extraction profile: 512-pixel longest edge, JPEG quality bounded by configuration, and 8 fps for short ambiguous windows.
- Derive `source_time_ms` from the existing sync convention while retaining `master_time_ms` separately.
- Burn no private names into pixels; camera labels and timestamps belong in metadata/prompt ordering.
- Write atomically beneath a versioned project derivative directory, verify every output hash, and reject source overrun/negative source time.
- Do not modify source files, proxies, program audio, WhisperX analysis audio, or player state.

**Verification:**

```bash
env -u VIRTUAL_ENV uv run pytest tests/test_visual_frames.py -q
```

Manual fixture check must prove extracted frame timestamps correspond to the browser/player master time within one source frame.

---

### Task 4: Add a fail-closed Qwen3.8 visual assessor

**Objective:** Submit ordered timestamped frames to local Ollama and validate assessments as supporting evidence only.

**Files:**
- Create: `src/autoedit/ai/qwen_visual.py`
- Test: `tests/test_qwen_visual.py`
- Modify: `src/autoedit/config.py`
- Modify: `.env.example`

**Runtime policy:**

- Model: `autoedit-qwen3.8:64k`, the server-side 65,536-context alias of `hf.co/unsloth/Qwen3.8-27B-GGUF:Q4_K_M`.
- Endpoint: configured local Ollama URL; no public OpenRouter route.
- `think=false`, `temperature=0`, strict JSON Schema, bounded output, bounded retries, `keep_alive=0`.
- Submit explicitly ordered images with machine-generated camera/time metadata.
- Qwen must echo provided frame IDs in its assessment. Missing, duplicated, invented, or reordered frame references fail validation.
- The caller—not Qwen—owns frame count and timing. The live smoke showed that useful visual reasoning can coexist with an inaccurate self-reported frame count, so self-count is never trusted.
- Refuse the request if WhisperX/another GPU task is active; queue rather than overlap.
- Persist failure as a visible shadow-analysis error; never create empty success output.

**Tests:**

- valid structured response;
- malformed/partial schema;
- invented frame or timestamp;
- omitted frame references;
- thinking trace in non-thinking mode;
- timeout/5xx/retry exhaustion;
- GPU-busy queue behaviour;
- `keep_alive=0` and local endpoint enforcement;
- raw model text never becomes camera authority.

**Verification:**

```bash
env -u VIRTUAL_ENV uv run pytest tests/test_qwen_visual.py -q
curl -fsS http://192.168.50.50:11434/api/show \
  -H 'Content-Type: application/json' \
  -d '{"model":"autoedit-qwen3.8:64k"}'
```

---

### Task 5: Run the L0 real-media shadow experiment

**Objective:** Establish whether visual evidence helps on AUTOEDIT's actual failures before integrating it into normal project processing.

**Files:**
- Create: `scripts/evaluate_visual_speaker_evidence.py`
- Create: `tests/test_visual_evidence_metrics.py`
- Create: `docs/ai/audiovisual-evaluation-protocol.md`
- Modify: the local consent-controlled fixture manifest outside Git; commit only a redacted schema/example.

**Fixture selection:**

Use consent-controlled windows covering at least:

1. the known post-gap misclassification;
2. rapid back-and-forth speech;
3. cross-mic bleed;
4. true overlap/interruption;
5. laughter/cough/reaction;
6. a listening face with mouth movement or expression;
7. off-camera speech or missing close-up;
8. ordinary unambiguous turns as negative controls.

**Ground truth:**

For each window, label the intended active person/camera, overlap/off-camera status, and an uncertainty band. Do not require false millisecond precision when a human cannot determine the boundary.

**Compare:**

- WhisperX-only decision;
- Qwen shadow assessment;
- human truth;
- eventual specialist ASD score when Task 7 runs.

**Metrics:**

- window-level correct active camera/person;
- wrong-close-up rate;
- safe-wide precision/recall;
- disagreement detection recall (did visual evidence flag WhisperX's known error?);
- false contradiction rate on clean controls;
- runtime, input frame count, prompt tokens, and peak VRAM;
- schema/grounding failure rate.

**L0 gate:**

Proceed only if Qwen flags the known bad transitions without introducing unacceptable contradictions on clean controls. Do not invent a universal threshold before labels are collected; record baseline counts first, then freeze the L1 thresholds before further tuning.

**Verification:**

```bash
AUTOEDIT_GOLDEN_MEDIA_ROOT=/secure/autoedit-fixtures \
  env -u VIRTUAL_ENV uv run python scripts/evaluate_visual_speaker_evidence.py \
  --backend qwen-shadow --output /tmp/autoedit-qwen-shadow-summary.json
```

The committed report may contain aggregate metrics only—no names, quotes, paths, raw frames, media hashes, or exact private timestamps.

---

### Task 6: Add project shadow processing and review UI

**Objective:** Make Qwen assessments reviewable beside WhisperX evidence without changing any cut.

**Files:**
- Modify: `src/autoedit/api.py`
- Modify: `src/autoedit/progress.py`
- Modify: `src/autoedit/web/app.html`
- Modify: `src/autoedit/web/app.js`
- Modify: `src/autoedit/web/styles.css`
- Test: `tests/test_visual_evidence_api.py`
- Test: `tests/test_visual_evidence_ui_static.py`

**Behaviour:**

- Explicit action: `Run visual speaker check`.
- Status states: queued, extracting frames, Qwen review, shadow complete, failed.
- Show WhisperX speaker/camera decision next to visual support/contradiction and confidence.
- Show the evidence frame strip/snippet only through authenticated project media routes.
- Allow `agree`, `disagree`, and `uncertain` review labels for evaluation.
- Display `Shadow only — current cut unchanged` prominently.
- No write path from this UI to `activity.json`, cut selection, or export.

**L1 manual gate:**

Run on one cloned/non-authoritative project, verify all evidence links/times, confirm the selected cut ID and CDL remain byte-identical, and verify authentication prevents media exposure.

---

### Task 7: Benchmark a specialist audio-visual active-speaker detector

**Objective:** Obtain deterministic temporal active-speaker scores rather than asking Qwen to generate timing.

**Files:**
- Create: `services/active_speaker_service/` or extend the isolated GPU service only after Designer review.
- Create: `src/autoedit/ai/active_speaker_client.py`
- Create: `src/autoedit/ai/active_speaker_contracts.py`
- Test: `tests/test_active_speaker_contracts.py`
- Test: `tests/test_active_speaker_client.py`
- Extend: `scripts/evaluate_visual_speaker_evidence.py`

**Design spike before implementation:**

- Evaluate TalkNet-compatible inference first because it combines audio and face motion over time.
- Verify license, current dependency/CUDA compatibility, face-detection/tracking requirements, V100 runtime, and maintenance status.
- If TalkNet is operationally stale, compare a maintained equivalent under the same artifact contract; do not bind AUTOEDIT's contract to a model-specific output format.
- Inputs are synchronized audio plus per-camera face tracks/windows; outputs are per-face timestamped active-speaker probabilities.
- Qwen remains optional for identity/reasoning and does not post-process score timestamps.

**L2 gate:**

The specialist ASD candidate must materially beat WhisperX-only and Qwen-only on wrong-close-up rate and active-speaker accuracy, including the post-gap and bleed fixtures, while fitting the single-GPU sequential budget. Failure leaves visual analysis as review-only.

---

### Task 8: Implement deterministic evidence fusion as a candidate-cut source

**Objective:** Generate a new immutable candidate cut from validated audio and visual evidence without replacing the selected cut.

**Files:**
- Create: `src/autoedit/ai/fuse_speaker_evidence.py`
- Test: `tests/test_fuse_speaker_evidence.py`
- Modify: `src/autoedit/ai/activity_from_turns.py`
- Modify: `src/autoedit/cut_engine.py` only to accept a new explicit source/reason; preserve existing modes.
- Modify: `src/autoedit/api.py`

**Initial conservative policy:**

1. Confirmed identity + confident WhisperX + supportive ASD → close-up.
2. WhisperX/ASD conflict → wide and `audio_visual_conflict:wide`.
3. True simultaneous active-speaker scores → wide.
4. No visible confirmed face/off-camera → wide.
5. Low confidence or missing required evidence → wide.
6. Qwen may add an explanation or identity suggestion, never override deterministic scores.
7. Frame snapping/minimum-shot logic runs after evidence fusion, preserving reason boundaries without creating fake visual cuts.

**L3 gate:**

- Candidate activity/CDL is versioned and immutable.
- Existing selected cut, VAD cut, and WhisperX-only cut remain available.
- Targeted and full suites pass.
- Real fixture metrics beat the currently selected baseline.
- Independent Designer and Tester verdicts pass.

---

### Task 9: Per-project selection, live A/B, and rollout decision

**Objective:** Let the operator explicitly select a proven audiovisual candidate and collect enough live evidence for a later default decision.

**Files:**
- Modify: existing cut selection/review UI and APIs only after L3.
- Modify: `AI_HANDOFF.md`
- Modify: `jobs/BACKLOG.md`
- Modify: `docs/plans/TESTING_STRATEGY.md`
- Create: `docs/ai/audiovisual-speaker-operations.md`

**L4 gates:**

- Backup, deploy through `scripts/autoedit-deploy.sh`, rebuild, and verify health.
- Process a cloned/project-safe run first.
- Human A/B review of rapid turns, bleed, overlap, post-gap, laughter, and off-camera cases.
- Verify browser playback and Resolve export preserve sync and source bounds.
- Verify Qwen/ASD failure is explicit and last-known-good cuts remain selectable.
- Verify peak VRAM/process sums and no concurrent GPU workloads.

**L5 default gate:**

A separate decision after repeated successful real projects. Do not make audiovisual fusion the default merely because one benchmark passes.

---

## Immediate execution slice

Start with **Tasks 1–5 only**. This produces evidence, not production behaviour.

Expected first deliverable:

1. a strict shadow artifact contract;
2. deterministic selection of known ambiguous windows;
3. timestamped frame extraction;
4. fail-closed Qwen3.8 assessment through local Ollama;
5. a redacted comparison report on the known problematic material.

**Explicitly defer:** active-speaker service integration, cut fusion, UI cut selection, deployment, and default changes.

---

## Verification matrix

| Claim | Required evidence |
| --- | --- |
| Qwen supports AUTOEDIT visual inputs | Live local schema-constrained multi-image request |
| Frame timing is correct | Source/master timestamp fixture plus player comparison |
| Shadow cannot alter cuts | Byte-identical selected cut/CDL before and after run |
| Visual evidence helps | Consent-controlled labelled-window metrics |
| Specialist ASD is better timing evidence | Side-by-side ASD/WhisperX/Qwen benchmark |
| Fusion is safe | Deterministic tests, unresolved/conflict→wide, immutable candidate cut |
| Production is ready | Deployed browser + Resolve + GPU + rollback gates |

---

## Stop conditions

Stop or keep the feature review-only if any of the following holds:

- Qwen frequently omits/invents frame references despite fail-closed validation.
- Visual evidence contradicts clean controls often enough to reduce trust.
- Face visibility/framing is insufficient for active-speaker analysis on the actual camera setup.
- Specialist ASD does not beat the WhisperX-only baseline on real material.
- Runtime/VRAM prevents reliable sequential coexistence on the V100.
- The only apparent improvement requires Qwen-generated timestamps or opaque prompting.
- Privacy handling cannot keep raw interview frames and identities out of logs/Git.

---

## Definition of done

The overall feature is complete only when:

- automatic audio sync remains unchanged and verified;
- Qwen outputs are strict, source-bound, auditable supporting evidence;
- a specialist active-speaker detector, if promoted, supplies timestamped face/audio scores;
- operator-confirmed person/camera mappings remain identity authority;
- conflicts/low confidence/off-camera/overlap select wide;
- audiovisual fusion creates an immutable candidate before any selection;
- real labelled fixtures show fewer wrong close-ups than WhisperX-only and VAD baselines;
- browser playback and Resolve export pass on deployed production-shaped infrastructure;
- failure/rollback preserves last-known-good artifacts and selected cuts;
- the default is changed only by a separate recorded rollout decision.
