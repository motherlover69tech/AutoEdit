# AUTOEDIT Testing Strategy

## Current verification checkpoint — 2026-07-14 reconciliation

- Full mock-backed suite: `685 passed, 2 skipped`.
- Focused cut/player suite: `60 passed, 1 skipped`.
- Python compile and `git diff --check`: passed.
- The local pytest wrapper skipped its JS module test because Node is not installed in the workspace. The same `tests/player_logic.test.mjs` was then executed in `node:22-alpine` on Unraid and passed: `All player logic + timeline + LUT + angle-LUT tests passed`.
- New CDL reason metadata preserves visual timing while exposing same-camera editorial boundaries: speaking, crosstalk/hold, interjection hold, rapid exchange, silence, variety wide, source fallback, and future unresolved/low-confidence states.
- Live HTTPS verification passed: login `204`, projects `200`, player `200`, player-state `200`, and the player HTML contained `shotReason`. The existing project had 56 legacy-reason clips and zero structured clips; all are supported by the player fallback. Production remained `WHISPER_BACKEND=mock` and `DIARIZE_BACKEND=mock`.
- Review-fix deployment verification: 100 ms silence and short-crosstalk inputs both survived canonical 25 fps snapping as distinct 80 ms reason segments in the live container. Local and deployed `cut_engine.py` hashes matched. Production image `sha256:48e1a370d1c171d96baf25ac2de47e5438bb097aa97a76889ebfb9703b1b606e` stayed running with zero restarts.
- Final independent re-review: `PASS`, with no remaining shot-reason correctness or persistence findings.

This plan expands Appendix D of the source spec. Every implementation stage must add or update tests here as the project structure becomes concrete.

## Current verification checkpoint

- Active AI job: unresolved Phase 4/acceptance work in `docs/plans/ai-gpu-1-corrective-pickup.md`.
- Final local reconciliation checkpoint: `685 passed, 2 skipped`; delayed-review worker/artifact/transcript hardening checkpoint: `142 passed`.
- Artifact confinement/strictness/immutability and speaker-mapping corrections received independent `PASS` reviews and have direct regressions.
- Remote V100 `/ready`, queued real ASR/alignment, and constrained two-speaker diarization succeeded. These prove transport/structure, not frame-level timing, stable speaker identity, editorial cut quality, or production acceptance.
- Compilation and `git diff --check` remain mandatory after every reconciliation/code change.
- Production remains `WHISPER_BACKEND=mock` and `DIARIZE_BACKEND=mock`.
- MySQL integration skips unless DB env vars are supplied.
- Current remediation job: `CONFIG-REVIEW` / `docs/plans/central-mysql-deployment-and-docs-remediation.md`; implementation and live deployment verification are complete.
- Stage 7.0 deployment is behind Nginx Proxy Manager, not Caddy; docs/config now reflect that.
- Current local code has mock/template/in-process areas that must remain labelled accurately: transcription, diarization, YouTube titles, and pipeline worker model. Sync low-confidence handling now fails loudly with diagnostics.
- Auto-cut responsiveness change verified: `env -u VIRTUAL_ENV uv run pytest tests/test_cut_engine.py tests/test_player_state.py -q` → `39 passed` after switching defaults to the Direct profile and adding player-state cut params.
- Level-normalization stage verified: `env -u VIRTUAL_ENV uv run pytest tests/test_level_normalization.py tests/test_activity.py tests/test_progress.py tests/test_cut_engine.py -q` → `61 passed`; full suite above also passed after adding analysis gain offsets for uneven mic levels.
- Ingest UI/probe mapping clarification verified: `env -u VIRTUAL_ENV uv run pytest tests/test_probe_channel_mapping.py tests/test_ingest_ui_static.py -q` → `25 passed`; broader web/API subset `tests/test_player_static.py tests/test_security_smoke.py tests/test_probe_channel_mapping.py tests/test_ingest_ui_static.py` → `41 passed`.

## CONFIG-REVIEW required verification

- Full suite: `env -u VIRTUAL_ENV uv run pytest -q`.
- Compile sanity: `python -m compileall -q src tests`.
- Central MySQL gate with real secrets supplied only through process env:

```bash
DB_HOST=192.168.50.50 \
DB_PORT=3306 \
DB_NAME=autoedit \
DB_USER=autoedit \
DB_PASSWORD='<from secret store>' \
  env -u VIRTUAL_ENV uv run pytest tests/test_mysql_integration.py -q
```

- Compose/render check: no MySQL service, explicit central `DB_*` variables for app, no real secret committed. Source-level YAML sanity passed locally and real `docker compose config` passed on Unraid.
- Live NPM checks after deploy: `/health` public, `/projects` returns 401 without cookie, login returns a secure session cookie, `/data` is not exposed. Latest Unraid/NPM check passed.

## Stage 7.3 required test additions

Automated tests added with the LUT implementation:

- `tests/test_luts.py` (16 tests) — upload, list, activate, deactivate, auth, invalid .cube rejection, path-traversal filename rejection, player-state active_lut integration.
- `tests/player_logic.test.mjs` extended with `.cube` parser tests: size, title, float data, comments/blank lines, missing LUT_3D_SIZE error.

Manual checks required before Stage 7.3 can be marked `done`:

- Toggling the LUT visibly changes the grade with no frame drop.
- A known `.cube` LUT file produces the expected colour transform.

## Stage 7.4 required test additions

Automated tests added with the notes implementation:

- `tests/test_notes.py` (17 tests) — create, list, delete, auth, author from session, invalid kind, negative t_ms, oversized body, XSS preservation (body stored as-is; rendering uses textContent), timeline-state note inclusion, empty notes.

Manual checks required before Stage 7.4 can be marked `done`:

- Two different reviewers' notes appear with correct authors and times.
- Clicking a note marker on the timeline seeks to the correct timestamp.
- Injected `<script>` in a note body renders as text, not executed.
- Delete removes the note from both the list panel and timeline lane.

## Stage 7.2 required test additions

Automated tests added with the timeline implementation:

- `tests/test_timeline_state.py` (10 tests) — contract/auth/missing data/happy path/deterministic colours/loudness inclusion/no data-root exposure.
- `tests/player_logic.test.mjs` extended with timeline helper tests: `formatTimelineMs`, `msToPercent`, `percentToMs`, edge cases.

Manual checks required before Stage 7.2 can be marked `done`:

- Timeline lanes render correctly from JSON in a browser with real summary/CDL data.
- Clicking a topic/angle block seeks to the correct time.
- Current angle label (coloured dot + text) tracks the CDL in real time during playback.
- Loudness waveform lane renders when `loudness.json` is present.

## Stage 7.1 required test additions

Automated tests to add with the player implementation:

- `tests/test_player_state.py` for auth-protected player bootstrap payloads and media URL allowlisting.
- `tests/test_player_static.py` for authenticated static shell delivery.
- A lightweight JS/player-logic test path for clip selection, current-video time math, drift-threshold decisions, manual override state, and proxy/proxy_low quality fallback. If Node is unavailable in CI, skip cleanly and keep pure helpers testable.

Manual checks required before Stage 7.1 can be marked `done`:

- Full rough cut plays without visible stutter at automatic switches.
- Manual angle switch reflects within about 1–2 frames and program audio does not reload/glitch.
- Forced angle remains within 1 frame of program audio on a clapper/sync test.
- Seeking picks the correct CDL angle/time.
- Throttled/poor-network test degrades gracefully via `proxy_low` or buffer-aware hold behavior.

## WhisperX speaker-aware AI benchmark

The real-AI roadmap requires a privacy-safe real-media benchmark before WhisperX
can replace VAD/mic-level activity as camera-decision authority. The scaffold lives
at `tests/fixtures/golden_interview/`; expected JSON files remain explicitly
`not_labeled` until consent-cleared external fixtures and ground truth exist.

- Protocol: `docs/ai/whisperx-evaluation-protocol.md`.
- External media is selected only with `AUTOEDIT_GOLDEN_MEDIA_ROOT`.
- Ordinary tests must remain self-contained and must not download media.
- Required metrics include speaker-turn F1/DER, overlap misses, aligned word error,
  WER where possible, wrong-close-up/cut agreement, and bleed/noise false cuts.
- Acceptance thresholds are set from the observed VAD baseline, not invented in
  advance. Failed acceptance keeps VAD/mock production behavior unchanged.
- Audio sync remains automatic; benchmark failures must never create a manual
  timeline-nudge workflow.

Planned trusted-host command (the integration test is not implemented yet):

```bash
AUTOEDIT_GOLDEN_MEDIA_ROOT=/secure/autoedit-fixtures \
  env -u VIRTUAL_ENV uv run pytest tests/integration/test_whisperx_golden_media.py -q
```

## Test categories

### 1. Unit tests

Use for pure or mostly-pure logic:

- FPS/time conversion helpers.
- ULID/id validation.
- Config loading and env defaults.
- CDL generation.
- CDL validation.
- Topic-span stitching/validation.
- FCPXML rational-time formatting.
- VAD interval merge/drop logic.

Expected command once code exists: record exact test command here, e.g. `pytest` or `npm test`.

### 2. Contract tests

These guard integration boundaries:

- Database schema columns/types/enums match spec Section 2.2.
- Project manifest `project.json` mirrors expected DB fields.
- CDL fixtures satisfy spec Section 2.4 and are accepted by player/exporter code.
- API response shapes match Appendix B.
- Media times are integer milliseconds only.

### 3. Golden-file media tests

Keep a tiny fixture set once available:

```text
tests/fixtures/golden_30s/
  source/
    angleA.mp4
    angleB.mp4
    angleC.mp4
  expected/
    probe.json
    sync_offsets.json
    cdl.json
    export.fcpxml
```

Fixture requirements:

- Around 30 seconds.
- Three camera angles.
- Clear clapper/transient near the start.
- Two isolated speaker channels if possible.
- Small enough to keep in repo, or documented external download if too large.

Golden tests should cover:

- ffprobe metadata extraction.
- Audio sync within ±1 frame.
- Proxy generation/keyframe cadence.
- Program audio alignment.
- Transcription offset math using known words if available.
- FCPXML generation against stable expected structure.

### 4. Integration smoke test

Once the backend exists, maintain a scripted smoke path:

1. Start test stack.
2. Run migrations.
3. Create project.
4. Upload or seed fixture angles.
5. Map channels.
6. Run process pipeline.
7. Assert project reaches `ready`.
8. Fetch CDL.
9. Validate CDL.
10. Export FCPXML.
11. Validate XML and expected references.

Expected command should eventually be documented here, e.g.:

```bash
./scripts/smoke-test.sh
```

### 5. Security tests

Required before public exposure:

- Auth required on all non-health/ACME routes.
- Brute-force lockout/rate limit triggers.
- Upload path traversal rejected.
- User-controlled display labels cannot affect generated filesystem paths.
- Oversized upload chunks are rejected before writing chunk parts.
- Note body XSS sanitized on render.
- Media endpoint returns `401`/redirect without session.
- Media endpoint honours `Range` with `206 Partial Content` when authenticated.
- Media endpoint serves only DB-known playback assets and returns player-friendly MIME types.
- Channel remapping invalidates dependent analysis rows instead of leaving stale intervals/transcripts.
- CORS/origin checks reject unexpected origins.

### 6. Manual gates

Some gates are explicitly manual and must be recorded in stage notes:

- Review player has no visible stutter at switches.
- Forced angle stays within one frame of audio on clapper test.
- LUT visibly changes the image and does not drop frames on target hardware.
- FCPXML opens populated in DaVinci Resolve.
- Cuts in Resolve land on the same frames as player preview.

## Test command

Current local command:

```bash
env -u VIRTUAL_ENV uv run pytest -q
```

Latest local result without MySQL URL: `17 passed, 1 skipped`.

Latest local result after Stage 3.2 chunked upload: `35 passed, 1 skipped`.

Latest local result after Stage 3.3 probe & channel mapping: `54 passed, 1 skipped`.

Latest local result after Stage 3.4 channel extraction + audio sync: `65 passed, 1 skipped`.

Latest local result after Stage 3.5 proxy normalisation: `73 passed, 1 skipped`.

Latest local result after Stage 3.5b low-bitrate proxy tier: `79 passed, 1 skipped`.

Latest local result after Stage 3.6 media streaming: `92 passed, 1 skipped`.

Latest local result after Stage 4.2 noise floor & threshold: `108 passed, 1 skipped`.

Latest local result after speaker diarization: `114 passed, 1 skipped`.

Latest local result after Stage 4.3 interval construction: `129 passed, 1 skipped`.

Latest local result after Stage 4.4 activity timeline: `141 passed, 1 skipped`.

Latest local result after Stage 4.6 program audio: `152 passed, 1 skipped`.

Latest local result after Stage 6.1 core cut algorithm: `172 passed, 1 skipped`.

Latest local result after Stage 6.2 anti-jitter & periodic wide: `183 passed, 1 skipped`.

Latest local result after Stage 5.1 transcription: `195 passed, 1 skipped`.

Latest local result after Stage 5.2 topic segmentation: `207 passed, 1 skipped`.

Latest local result after Stage 5.3 conciseness grading: `221 passed, 1 skipped`.

Latest local result after Stage 5.5 report output: `232 passed, 1 skipped`.

Latest local result after Stage 6.3 sub-edit generation: `248 passed, 1 skipped`.

Latest local result after internal review hardening: `257 passed, 1 skipped`; `python -m compileall -q src tests` passes.

Latest current verification after Direct auto-cut/player-state updates: focused `env -u VIRTUAL_ENV uv run pytest tests/test_cut_engine.py tests/test_player_state.py -q` → `39 passed`; full suite `env -u VIRTUAL_ENV uv run pytest -q` → `438 passed, 2 skipped`; `python -m compileall -q src tests` passes; `git diff --check` passes.

Stage 7.1 tests added:

- `tests/test_player_state.py` covers auth, missing project, missing rough cut, missing program audio, player bootstrap payload shape, media URL routing through `/projects/{id}/media/...`, no raw data/source path exposure, and proxy/proxy_low angle URL selection.
- `tests/test_player_static.py` covers authenticated player shell delivery and static asset serving.
- `tests/test_player_logic_js.py` runs `tests/player_logic.test.mjs` when Node is installed, and skips cleanly otherwise; current environment has no Node, so this accounts for one Stage 7.1 skip.

Canonical existing-MySQL integration commands:

```bash
# Preferred: provide DB_* variables directly so special characters in DB_PASSWORD
# do not need URL encoding.
DB_HOST=192.168.50.50 \
DB_PORT=3306 \
DB_NAME=autoedit \
DB_USER=autoedit \
DB_PASSWORD='***' \
  env -u VIRTUAL_ENV uv run pytest tests/test_mysql_integration.py -q

DB_HOST=192.168.50.50 \
DB_PORT=3306 \
DB_NAME=autoedit \
DB_USER=autoedit \
DB_PASSWORD='***' \
  env -u VIRTUAL_ENV uv run pytest -q
```

Latest canonical existing-MySQL result after Stage 7.0 backend auth gate: `25 passed in 1.90s`.

Stage 3.2 was verified with the local SQLite-backed suite after that: `35 passed, 1 skipped`. Existing-MySQL credentials must be supplied in process env to rerun the DB-enabled suite; never paste or preserve the real password in docs/log summaries.

Security tests added in `tests/test_auth_gate.py` cover:

- `/health` public while auth is enabled.
- ACME challenge path bypasses auth.
- Project routes require a session.
- Login sets an httpOnly session cookie.
- Authenticated project creation works.
- `GET /auth/me` returns reviewer display name from the session.
- Failed login lockout returns `429` after threshold.
- Unexpected `Origin` returns `403`; configured `PUBLIC_DOMAIN` origin passes.

Upload tests added in `tests/test_uploads_api.py` cover:

- Upload routes require auth when auth is enabled.
- Missing project returns `404`.
- Filename path traversal is rejected.
- Invalid upload ids / chunk indexes are rejected.
- Interrupted upload can resume from highest contiguous chunk.
- Complete validates byte count and SHA-256, writes exact source bytes, and inserts an `angles` row.
- Wrong SHA is rejected and temp upload files are cleaned up.
- Three uploads to one project complete and create three `angles` rows.

Probe & channel mapping tests added in `tests/test_probe_channel_mapping.py` cover:

- Probe route requires auth when auth is enabled.
- Missing project/angle returns 404.
- Invalid angle ID format returns 400.
- Probe populates `angles` row with codec/dimensions/fps/duration from mocked `ffprobe` fixture.
- Non-1080p input produces a warning but still records metadata.
- Non-H.264 input produces a warning but still records metadata.
- Channel mapping creates exactly two `audio_channels` rows with correct `source_angle_id`, `channel_index`, and `speaker_label`.
- Channel mapping route requires auth.
- Manual sync nudge is stored as integer ms on the `angles` row (positive and negative).
- Invalid mapping payloads (fewer than 2 mappings, duplicate channel_index, empty speaker_label) are rejected with 400.
- Re-running channel mapping replaces existing `audio_channels` rows rather than duplicating.

Test fixtures in `tests/fixtures/ffprobe/`: `h264_1080p.json`, `h264_720p.json`, `hevc_1080p.json`.

Audio sync tests added in `tests/test_audio_sync.py` cover:

- `/sync` route requires auth when auth is enabled.
- Missing project returns 404; project without channel mappings returns 400.
- Band-pass filter (300–3000 Hz Butterworth) attenuates low (<300 Hz) frequencies and passes mid-band (1000 Hz).
- Cross-correlation finds a known 50ms delay in synthetic impulse signals.
- Cross-correlation returns zero lag for identical signals.
- Cross-correlation correctly identifies negative lag (leading) signals.
- Sync endpoint extracts channel WAVs and updates `audio_channels.wav_path`.
- Reference angle offset is exactly 0.
- Operator manual nudge is additive to computed sync offset (50 + 20 = 70ms).
- All returned offsets are integer milliseconds.

Proxy generation tests added in `tests/test_proxy.py` cover:

- Proxy routes require auth when auth is enabled.
- Missing project/angle returns 404.
- Single-angle proxy generation updates `angles.proxy_path`.
- Bulk proxy generation updates all angles in the project.
- ffmpeg command uses correct args: `-g`, `-an`, `-vf scale`, `-movflags +faststart`.
- Proxy generation is idempotent (same path on re-run).

Low-bitrate proxy tests added in `tests/test_proxy_low.py` cover:

- Low-proxy routes require auth.
- Single-angle low-proxy updates `angles.proxy_low_path`.
- Bulk low-proxy updates all angles.
- ffmpeg uses lower resolution (360p) and higher CRF (26) than main tier.
- Low-proxy generation is idempotent.

Media streaming tests added in `tests/test_media_streaming.py` cover:

- Media route requires auth when auth is enabled.
- Full file download returns correct content (200).
- Range requests: fixed byte range (206, correct Content-Range).
- Open-ended range (`bytes=900-`) returns 206 with last bytes.
- Suffix range (`bytes=-100`) returns 206 with last N bytes.
- Audio and proxy_low kinds are served.
- Missing file returns 404; missing project returns 404.
- Invalid kind (e.g. `source`) returns 400.
- Path traversal rejected.
- Source directory not accessible via media endpoint.

Loudness envelope tests added in `tests/test_loudness.py` cover:

- `compute_loudness_envelope` produces correct number of samples (1s / 20ms = 50 values).
- Full-scale sine wave values are near 0 dBFS.
- Silence produces values below -60 dB.
- Hop_ms parameter doubles/halves the array length.
- Loudness route writes `audio/loudness.json` with correct shape.
- Auth required, 404 on missing project, 400 without channel mappings.

Noise floor & threshold tests added in `tests/test_noise_floor.py` cover:

- `compute_noise_floor` returns 10th percentile floor + margin from RMS-dB list.
- Custom margin produces proportionally higher threshold.
- Silence (all -100 dB) produces floor near -100.
- Noise floor route writes `noise_floor_db` and `vad_threshold_db` to `audio_channels`.
- Route requires loudness.json to exist first (400 if not).
- Auth required, 404 on missing project.

Speaker diarization tests added in `tests/test_diarize.py` cover:

- `mock_diarize()` returns properly structured `{speaker, start_ms, end_ms}` segments.
- Stereo projects use existing channel→speaker mapping; writes `diarization.json`.
- Mono projects run diarization on the mixed WAV; creates `audio_channels` rows for discovered speakers.
- Auth required, 404 on missing project, 400 without audio channels.

Interval construction tests added in `tests/test_intervals.py` cover:

- `compute_speaking_intervals` detects speech above threshold and groups into intervals.
- All-silence envelope produces no intervals.
- 200ms gap at 300ms hangover does NOT split the interval (hangover merge).
- 400ms gap at 300ms hangover DOES split.
- Bursts shorter than `min_duration_ms` (default 150ms) are dropped.
- Custom hangover/min_duration parameters change behavior.
- Mean and peak dB per interval are correctly recorded.
- `start_ms` parameter shifts all output times.
- API route requires auth, rejects missing project, rejects missing loudness.json, rejects missing noise floor.
- Route writes `speaking_intervals` DB rows with correct fields.
- Route is idempotent (replaces old rows, does not duplicate).

Activity timeline tests added in `tests/test_activity.py` cover:

- Empty intervals → single silent segment.
- Single speaker → active throughout their intervals, silent elsewhere.
- Overlapping speech → segment with both speakers in active list.
- Timeline is contiguous (prev.end_ms == next.start_ms for all segments).
- Consecutive segments with identical active sets are merged.
- `total_duration_ms` extends timeline beyond last interval.
- Active list is alphabetically sorted.
- API route requires auth, rejects missing project, rejects missing intervals.
- Route returns valid timeline JSON and writes `activity.json` to disk.
- Fixture with known speaker patterns produces correct overlap region.

Program audio tests added in `tests/test_program_audio.py` cover:

- `generate_program_audio` invokes ffmpeg with correct args (filter_complex with adelay/apad/amerge, AAC, +faststart).
- Single-channel mode uses apad without amerge.
- ffmpeg failure raises RuntimeError.
- Empty channel list raises ValueError; >2 channels raises ValueError.
- API route requires auth, rejects missing project, rejects projects without WAVs.
- Route creates program.m4a output reference.
- ffmpeg receives correct WAV input paths and output path.
- Sync offsets from `angles.sync_offset_ms` are reflected in `adelay` parameters.

Cut engine tests added in `tests/test_cut_engine.py` cover:

- Single speaker → that speaker's angle (`speaker:label` reason).
- Overlap with `overlap_to_wide=true` → wide angle.
- Overlap with `overlap_to_wide=false` → first active speaker's angle.
- Silence with `silence_behaviour=hold` → extends last angle when explicitly selected as a legacy/looser override.
- Silence with `silence_behaviour=wide` → cuts to wide.
- Determinism: same input + params → byte-identical CDL.
- Frame-snapping: with 25 fps (40ms/frame), boundaries snap to frame multiples.
- `src_in_ms` applies sync offset (`timeline_in_ms − sync_offset_ms`).
- Anti-jitter: clips shorter than `min_shot_ms` are merged (incoming-speaker preference via `_enforce_min_shot_ms`).
- Lead-in/tail: clips start earlier / end later than raw activity boundaries.
- Empty timeline → valid CDL with no clips.
- CDL has all required top-level keys (`version`, `project_id`, `fps`, `audio`, `clips`, `luts`).
- Default params produce valid output without crashing.
- API route requires auth, rejects missing project, rejects missing activity.json.
- Route writes `edit/cdl.json` and persists to `cuts` table.
- Custom params (`min_shot_ms`, `lead_in_ms`) stored in `cuts.params_json`.
- Deterministic across repeated calls (same project → same CDL).
- Clips from activity.json cover expected duration range.
- Direct defaults are locked: `min_shot_ms=250`, `lead_in_ms=0`, `tail_ms=0`, `silence_behaviour=wide`, overlap→wide; silence cuts to wide without waiting for the old hold-last behavior.

Anti-jitter & periodic wide tests (Stage 6.2, also in `tests/test_cut_engine.py`) cover:

- Incoming-speaker preference: short clip between two different speakers merges into following (incoming), not preceding.
- Same-angle forward merge: short clip with same angle as following merges forward.
- Same-angle backward merge: short clip with same angle as preceding merges backward.
- Pathological rapid-fire back-and-forth input respects `min_shot_ms` after merging.
- Pathological input covers the full timeline after anti-jitter.
- Periodic/relief wide: with `wide_interval_ms > 0`, wide shots appear with `periodic:wide` reason.
- Periodic wide deterministic without jitter (same seed → same placement).
- Periodic wide respects `min_shot_ms` — never creates clips below threshold.
- No periodic wides injected when `wide_interval_ms = 0`.
- No periodic wides injected without a wide angle ID.
- Periodic wide does not inject into already-wide clips (e.g. overlap regions).

Transcription tests added in `tests/test_transcribe.py` cover:

- `mock_transcribe` returns properly structured segments with speaker, start_ms, end_ms, text, and words.
- `start_ms` parameter shifts all segment and word times (offset applied for master timeline).
- Empty audio produces no segments.
- Words have confidence scores between 0 and 1.
- API route requires auth, rejects missing project, rejects projects without WAVs.
- Route writes `transcript.json` to disk with correct structure.
- Route populates `transcript_segments` DB table.
- Sync offset is passed through to `mock_transcribe` as `start_ms`.
- Idempotent: running twice produces same number of rows.
- Word count in response matches expected text.

Topic segmentation tests added in `tests/test_topics.py` cover:

- `mock_segment_topics` produces non-overlapping spans (each span ends at or before next start).
- Spans cover >95% of the transcript duration.
- All conciseness scores are in the 1–5 range.
- Empty input produces empty output.
- Every topic has required fields: `label`, `colour`, `summary`, `start_ms`, `end_ms`, `conciseness`.
- API route requires auth, rejects missing project, rejects missing transcript.
- Route populates `topics` and `topic_spans` DB tables.
- Response spans are non-overlapping.
- Idempotent: running twice produces same table row count.
- Route writes `transcript/topics.json` to disk.

Conciseness grading tests added in `tests/test_conciseness.py` cover:

- `compute_filler_density` returns 0.0 for clean text and >0.25 for filler-heavy text.
- `compute_filler_density` on empty string returns 0.0.
- `compute_word_rate` calculates correct WPM (10 words in 60s = 10 WPM).
- `grade_conciseness` on clean text maintains or improves the score.
- `grade_conciseness` on filler-heavy text downgrades and includes "high_filler_penalty" in rationale.
- `grade_conciseness` identical inputs produce identical outputs (reproducibility).
- `grade_conciseness` always returns score clamped to 1-5.
- API route requires auth, rejects missing project, rejects missing spans.
- Route updates `conciseness_score` and `summary` on `topic_spans` rows.
- Response includes `span_id`, `conciseness`, `filler_density`, `word_rate_wpm`, `rationale`.

Report output tests added in `tests/test_report.py` cover:

- `build_summary` computes per-topic speaker time by intersecting `speaking_intervals` with topic spans.
- Totals reconcile: sum of per-topic speaker times = `totals.speaker_time_ms`.
- Overlap and silence totals are computed from activity timeline segments.
- Empty inputs produce valid empty summary structure.
- Output has required top-level keys (`topics`, `totals`, `speaker_time_ms`, `talk_overlap_ms`, `silence_ms`).
- API route requires auth, rejects missing project, rejects missing topic spans.
- Route writes `transcript/summary.json` to disk.
- Response includes non-zero speaker time per topic.
- Totals include `talk_overlap_ms` and `silence_ms`.
- Sum of per-topic speaker times matches totals exactly (reconciliation).

Sub-edit tests added in `tests/test_sub_edit.py` cover:

- `select_topic_ranges` by labels returns only matching ranges.
- `select_topic_ranges` with exclude filters out specific labels.
- `select_topic_ranges` on empty input returns empty list.
- `extract_activity_ranges` keeps only segments fully inside selected ranges.
- `extract_activity_ranges` excludes segments that partially overlap range boundaries.
- `rebase_timeline` shifts all segments so the first starts at 0.
- `rebase_timeline` on empty list returns empty.
- `fill_to_duration` extends selected ranges with chronologically adjacent spans.
- API route requires auth, rejects missing project, rejects missing activity.
- `minus_topics` mode excludes Off-topic-labelled time (within frame-snapping tolerance).
- `by_topics` mode selects only specified topic spans.
- `custom_ranges` mode accepts explicit time ranges.
- Sub-edit saves CDL to `edit/cdl_sub_*.json` and persists to `cuts` table.
- Selected Introduction-only sub-edit stays within original span bounds (frame tolerance).

Latest temporary-dev-MySQL result: `1 passed in 1.58s`.

Latest full suite with temporary-dev-MySQL `AUTOEDIT_MYSQL_TEST_URL` set: `18 passed in 1.77s`.

The temporary Unraid `autoedit-mysql` container only proved MySQL compatibility and is not the canonical AUTOEDIT DB.

## Stage 3.1 initial test plan

Implemented tests for:

1. Migrations run on empty DB.
2. Migrations are idempotent when re-run.
3. `POST /projects` with valid `name`, `fps_num`, `fps_den` returns a 26-char ULID.
4. Project directory tree is created under configured `DATA_ROOT`:
   - `source/`
   - `proxy/`
   - `proxy_low/`
   - `audio/`
   - `transcript/`
   - `edit/`
   - `luts/`
5. `project.json` exists and matches the DB project row.
6. `GET /projects/:id` returns manifest data.
7. Invalid FPS values are rejected with HTTP 400:
   - `fps_num=0`
   - `fps_den=0`
   - non-integer values
   - missing values

Current coverage:

- `tests/test_migrations.py` verifies required tables are created, migration helper is idempotent, and media-time columns are integer-like.
- `tests/test_project_paths.py` verifies the spec directory tree and path-traversal/invalid-id rejection.
- `tests/test_projects_api.py` verifies `/health`, `POST /projects`, `GET /projects/:id`, manifest JSON, project skeleton creation, invalid FPS rejection, and missing-project 404.

Deployment DB gate:

- Complete: verified against Peter's existing MySQL server (`192.168.50.50:3306`, database `autoedit`, user `autoedit`, password not recorded). Full suite with DB enabled passed: `18 passed in 1.82s`.

## Rule for future AI sessions

Before marking any job done, update this file with the exact command(s) used and the observed result. If a test cannot yet be automated, document the manual gate and why.
