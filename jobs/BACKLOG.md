# AUTOEDIT Job Backlog

Statuses: `pending`, `in_progress`, `blocked`, `done`.

Do not mark a stage `done` unless its Definition of Done from `docs/source/multicam_autoedit_spec.md` has passed.

## Current next job

**Current engineering pickup: AI-GPU-1 application acceptance.** Artifact corrections, deterministic Phase 4 speaker resolution, queued ASR/alignment, and an isolated constrained-diarization smoke have passed. Next, verify selected WhisperX word timestamps against consent-cleared source/player media within one project frame, then complete operator-confirmed speaker identity, speaker-turn cut acceptance, and valid peak-VRAM/coexistence measurements. Keep production on mock backends.

The separate UI acceptance gate remains Stage 7.4 and may proceed independently. It now requires an independent rerun against exact deployed commit `c096e4e`: a candidate-local Chromium harness passed XSS safety, two-author rendering, marker seek, and delete synchronization, while Tester card `t_1a379f2a` accidentally tested old `master` at `87b9d47` and therefore cannot decide the deployed release.

Final deterministic local checkpoint (2026-07-16): `OLLAMA_BASE_URL='' LLM_MODEL='' env -u VIRTUAL_ENV uv run pytest -q -rs` → `691 passed, 1 skipped`; the only skip is the credential-gated central-MySQL integration test. V100 `/ready`, queued real ASR/alignment and constrained diarization, and the audit-only Qwen context pass succeeded; frame-level timing, confirmed speaker identity, speaker-turn cut acceptance, coexistence measurements, and the consent-cleared benchmark remain open.

Deployment note: Publisher card `t_26cf76c6` records `DEPLOYED_AND_VERIFIED` for exact non-`master` integration commit `c096e4e179291d910fbdb8864916318cbfd28c64` and image `sha256:3ac84cf4f23fa287fe40fc33a3121aae1680636ea6971d5aa23d408e11108d52`, with zero restarts, preserved DB backup/rollback tag, and no media/data mutation. Fresh public checks returned health 200 and unauthenticated projects 401. Direct auto-cut defaults remain live (`min_shot_ms=250`, no lead/tail, overlap/silence→wide); existing cuts retain stored params until regenerated.

## Detailed jobs

### Job AI-GPU-1-CORRECTIVE — artifact review fixes and real inference acceptance

- **Status:** in_progress / corrective review passed
- **Depends on:** AI-GPU-1 adapter, versioned artifact slice, synchronized analysis-audio slice, queued worker slice
- **Goal:** correct the independent artifact-review findings, obtain a clean review, and complete valid V100 ASR/alignment and diarization acceptance without changing production mock defaults prematurely.
- **Build/fix:** symlink-safe artifact output confinement; strict integer timestamp validation; immutable failure-attempt records; resolved-speaker mapping/reference integrity; host-compatible queued-job harness; TorchCodec/audio-decode remediation for diarization.
- **Latest automated results:** delayed-review worker/artifact/transcript hardening suite `142 passed`; deterministic full mock-isolated suite `691 passed, 1 skipped`.
- **Live evidence:** V100 `/ready` passed for CUDA capability 7.0 and `large-v3` FP16. A consent-cleared hash-bound queued run completed in 20.93 seconds with 241 aligned segments and about 1,422 words; wrong-hash rejection returned HTTP 400. Post-job VRAM snapshot: 6,048 MiB. Runtime identifiers and media fingerprints remain outside Git.
- **Review gate:** independent artifact status is `PASS`.
- **Manual/live gates:** valid queued ASR/alignment; selected word timing within one project frame; real diarization/audio decode; overlap/uncertainty behavior; valid peak-VRAM and Ollama/Dots coexistence measurements.
- **Production gate:** retain `WHISPER_BACKEND=mock` and `DIARIZE_BACKEND=mock` until every acceptance gate passes explicitly.
- **Planning doc:** `docs/plans/ai-gpu-1-corrective-pickup.md`

### Job AI-GPU-1-PHASE4 — speaker identity evidence and mapping

- **Status:** in_progress / resolver, import review, and isolated real-diarization smoke passed; production acceptance remains blocked
- **Goal:** resolve anonymous diarizer labels into stable project speaker IDs without allowing transcript/LLM guesses or cross-run label ordering to become identity truth.
- **Implemented:** strict current-turn evidence references; multi-turn/high-confidence voice threshold; current operator confirmation; current voice revalidation before prior-confirmed reuse; deterministic label-swap handling; audit-only transcript context; fail-closed conflicts; provenance-preserving resolved turns.
- **Review gate:** independent Phase 4 resolver and WhisperX 3.8.x diarization-import re-review returned `PASS`; no mandatory regressions remain missing.
- **Latest automated results:** `tests/test_speaker_mapping.py` → `15 passed`; `tests/test_speaker_context.py` → `37 passed`; delayed-review worker/artifact/transcript hardening suite → `142 passed`; deterministic full mock-isolated suite → `691 passed, 1 skipped`.
- **Live LLM evidence:** AUTOEDIT's strict context module called local Qwen 3.6 27B over the consent-controlled transcript and returned three anonymous explicit-address candidates at confidence 0.40. It assigned no diarizer IDs and unloaded immediately. Names, excerpts, exact timestamps, and runtime identifiers remain outside Git.
- **LLM fail-closed correction:** independent review found that initial schema validation did not prove quotes/timestamps came from the transcript. The seam now requires quote and timestamp grounding to the same source segment and rejects thinking traces, malformed/coercive transcript input, partial model responses, non-finite confidence, and assignment fields. The hardened real Qwen rerun passed.
- **Production blocker:** the deployment does not carry the private Hugging Face authorization/cached gated models or a completed Compose-managed acceptance record. Production remains mock-backed.

### Job CONFIG-REVIEW — Central MySQL deployment + docs remediation

- **Status:** done — local remediation implemented and live-verified on Unraid/NPM/central MySQL
- **Depends on:** DB-0, 7.0 deployment experience, current project review
- **Spec stage:** supporting infrastructure / documentation truth pass
- **Goal:** make deployment/docs match reality before more feature work: central MySQL is canonical, NPM is the TLS boundary, compose env vars are explicit, and mock/template/in-process features are accurately labelled.
- **Build:** `docs/plans/central-mysql-deployment-and-docs-remediation.md` tasks: update `docker-compose.yml`, deprecate or reconcile `docker-compose.prod.yml`, fix `.env.example`, rewrite `docs/DEPLOYMENT.md` for NPM + central MySQL, standardize `OLLAMA_BASE_URL` and `UPLOAD_MAX_CHUNK_BYTES`, fix low-confidence sync zero fallback, and update README/handoff/backlog/testing docs.
- **Required tests:** full local suite; targeted sync/config tests after code changes; central MySQL integration gate with real `DB_*` env vars when credentials are available.
- **Latest local result:** `env -u VIRTUAL_ENV uv run pytest -q` → `438 passed, 2 skipped`; `env -u VIRTUAL_ENV uv run python -m compileall -q src tests` → passed; `env -u VIRTUAL_ENV uv run pytest tests/test_audio_sync.py -q` → `18 passed`.
- **Compose source sanity:** local YAML check shows exactly one `app` service, `network_mode: host`, no MySQL/MariaDB service, no `env_file`, explicit central `DB_*`, `OLLAMA_BASE_URL`, `UPLOAD_MAX_CHUNK_BYTES`, and secure cookies.
- **Live deployment result:** Unraid render shows one `app` service, no MySQL/MariaDB service, host networking, explicit central `DB_*`, secure cookie, `WHISPER_BACKEND=mock`, and `DIARIZE_BACKEND=mock`. Public `/health` returned 200, `/projects` returned 401 without a session, login returned 204 with `HttpOnly; SameSite=lax; Secure`, `/data/` returned 401, and app health stayed 200 after stopping historical `autoedit-mysql`.
- **Manual gates:** next remaining manual work is a real browser/media-flow smoke: login, create/open project, upload fixture media, channel map, sync, proxy, and player open.
- **Planning doc:** `docs/plans/central-mysql-deployment-and-docs-remediation.md`

### Job PROGRESS — Pipeline progress tracking

- **Status:** done — project status DB column updated by all pipeline endpoints. New `/progress` and `/process` endpoints. Processing UI with polled progress table in Ingest view. Player blocks with processing interstitial when project isn't ready.
- **Depends on:** all pipeline endpoints (3.4–6.1)
- **Goal:** monitor processing progress after upload + channel mapping; block player until all stages complete.
- **Build:** `src/autoedit/progress.py` — 12-stage pipeline definitions, on-disk/DB evidence checks, `compute_progress()`. `GET /projects/{id}/progress` returns per-stage status. `POST /projects/{id}/process` runs full pipeline in background thread. Frontend: processing view in Ingest, "Start Processing" button, 2s polling, player blocking gate with interstitial.
- **Required tests:** `tests/test_progress.py` (10 tests) — stage ordering, status transitions, progress empty project, progress 404, process requires channels, project list includes status.
- **Latest automated result:** full suite `418 passed, 2 skipped`.
- **Manual gates:** verify in browser that processing UI shows stage progress, player opens after completion.

### Job HWENC — Intel VAAPI proxy encoding; QSV investigation

- **Status:** done for VAAPI / blocked for QSV — live deployment uses `PROXY_ENCODER=h264_vaapi`. Docker compose passes `/dev/dri`; `proxy.py` requests VAAPI decode frames, `scale_vaapi`, and `h264_vaapi` encode. A rebuilt-container `generate_proxy()` smoke produced a 720p H.264 proxy. QSV remains blocked because `h264_qsv` fails with `Error creating a MFX session: -9`.
- **Depends on:** 3.5
- **Goal:** faster proxy generation using Intel Quick Sync on the Unraid host (i7-13700T).
- **Build:** `proxy.py` has software, QSV, and VAAPI branches. The active VAAPI branch uses `/dev/dri/renderD128`, `-hwaccel vaapi`, `-hwaccel_output_format vaapi`, `scale_vaapi=w=-2:h=<height>`, `-c:v h264_vaapi`, and `-qp <PROXY_CRF>`. Active compose pins `PROXY_ENCODER: h264_vaapi` so stale `.env` cannot override it back to software.
- **Required tests:** `tests/test_proxy.py::test_generate_proxy_uses_vaapi_hw_decode_and_encode_args` plus existing proxy/proxy-low coverage.
- **Latest automated result:** local full suite `438 passed, 2 skipped`; live rebuilt-container VAAPI `generate_proxy()` smoke passed; live QSV smoke failed.
- **Manual gates:** verify proxy generation completes with Peter's real source files and compare encode speed/quality vs libx264; investigate QSV MFX session failure separately if QSV is still desired.

### Job DB-0 — Existing MySQL wiring

- **Status:** done
- **Depends on:** Stage 3.1 code implementation
- **Spec stage:** 3.1 deployment verification / Section 2.2 DB contract
- **Goal:** verify AUTOEDIT migrations and project API against the existing MySQL server, not the temporary dev container.
- **Required tests:** `tests/test_mysql_integration.py` passes against existing-server DB; full suite passes with existing-server DB enabled.
- **Verified target:** `192.168.50.50:3306`, database `autoedit`, user `autoedit`; password intentionally not recorded.
- **Latest result:** `DB_HOST=192.168.50.50 DB_PORT=3306 DB_NAME=autoedit DB_USER=autoedit DB_PASSWORD=*** env -u VIRTUAL_ENV uv run pytest -q` → `18 passed in 1.82s`.
- **Planning doc:** `docs/plans/EXISTING_MYSQL_REQUIREMENTS.md`

### Job 7.0 — Auth gate + reverse proxy

- **Status:** done — app deployed to Unraid, NPM terminates TLS at `ingest.peteflix.uk`, auth gate (401), login (204), session cookies working. Live-browser verified.
- **Depends on:** 3.1 + DB-0 for deployment DB verification
- **Spec stage:** 7.0
- **Goal:** require TLS/session auth before any public exposure; Docker deployment with reverse-proxy TLS.
- **Required tests:** `/health` public; protected API routes blocked without session; login creates httpOnly session; brute-force/rate-limit behavior covered; reviewer display name persisted for later notes; origin check blocks wrong host; security smoke tests in `tests/test_security_smoke.py`.
- **Latest local result:** 13 security smoke tests pass; full suite `438 passed, 2 skipped`.
- **Deployment:** canonical `docker-compose.yml` with host networking, explicit central MySQL env, and NPM proxying `ingest.peteflix.uk` → `192.168.50.50:8010`. `docker-compose.prod.yml`/Caddy references are historical/non-canonical for this deployment.
- **Live verified:** health `{"status":"ok"}`, auth gate 401, login 204 + Set-Cookie, authenticated access passes auth middleware.
- **Browser verified 2026-06-03:** login page → redirect → player, ping-pong angle switching (cam_left → cam_right → wide), manual angle override + back-to-auto working. LUT pipeline gracefully disabled (WebGL sampler3D precision fix).

### Job 3.3 — Probe & channel mapping

- **Status:** done
- **Depends on:** 3.2
- **Spec stage:** 3.3
- **Goal:** capture media metadata and let the operator declare which audio channel is which speaker.
- **Build:** `POST /projects/{id}/angles/{id}/probe` runs ffprobe and fills angle metadata; `POST /projects/{id}/channels` creates channel mappings and optional sync nudges.
- **Required tests:** probe populates angles row, non-1080p/non-H.264 warns, channel mapping creates audio_channels rows, sync nudge stored as integer ms, invalid payloads rejected.
- **Latest local result:** `env -u VIRTUAL_ENV uv run pytest -q` → `54 passed, 1 skipped`.
- **Planning doc:** `docs/plans/stage-3.3-probe-channel-mapping.md`

### Job 3.4 — Channel extraction + audio sync

- **Status:** done
- **Depends on:** 3.3
- **Spec stage:** 3.4
- **Goal:** extract speaker channels and compute per-angle sync offsets from audio.
- **Build:** `POST /projects/{id}/sync` extracts channel WAVs + guide tracks, cross-correlates with scipy.signal.correlate, applies operator nudges from 3.3.
- **Required tests:** bandpass filter (+pass/-attenuate), cross-correlation finds known lag/zero/negative, operator nudge additive, integer ms roundtrip.
- **Latest local result:** `env -u VIRTUAL_ENV uv run pytest -q` → `65 passed, 1 skipped`.
- **Planning doc:** `docs/plans/stage-3.4-channel-extraction-audio-sync.md`

### Job 3.5 — Main proxy normalisation

- **Status:** done
- **Depends on:** 3.3
- **Spec stage:** 3.5
- **Goal:** produce silent 720p short-GOP H.264 playback proxies.
- **Build:** `POST /projects/{id}/proxy` and `POST /projects/{id}/angles/{aid}/proxy`; ffmpeg with scale/-g/-an/-movflags faststart.
- **Required tests:** proxy generates, DB updated, correct ffmpeg args, idempotent, single + bulk routes.
- **Latest local result:** `env -u VIRTUAL_ENV uv run pytest -q` → `73 passed, 1 skipped`.
- **Planning doc:** `docs/plans/stage-3.5-proxy-normalisation.md`

### Job 3.5b — Low-bitrate remote proxy tier

- **Status:** done
- **Depends on:** 3.5
- **Spec stage:** 3.5b
- **Goal:** a smaller proxy tier for remote reviewers on poor WAN connections.
- **Build:** `POST /projects/{id}/proxy-low` and `/angles/{aid}/proxy-low`; same GOP/encoder, 360p/CRF 26, `proxy_low/`.
- **Required tests:** DB update, correct ffmpeg args (360p, CRF 26), idempotent, bulk + single routes.
- **Latest local result:** `env -u VIRTUAL_ENV uv run pytest -q` → `79 passed, 1 skipped`.
- **Planning doc:** none (trivial extension of 3.5)

### Job 3.6 — Range-request media streaming

- **Status:** done
- **Depends on:** 3.5, 7.0 (auth middleware)
- **Spec stage:** 3.6
- **Goal:** serve proxies and audio over HTTPS with seek support, behind auth.
- **Build:** `GET /projects/{id}/media/{kind}/{filename}` — Starlette FileResponse with Range support; confined to proxy/proxy_low/audio dirs and allowlisted to DB-known playback assets.
- **Required tests:** auth, full file, Range (fixed/open/suffix), audio/proxy_low, missing file, invalid kind, path traversal, source access denial, DB-known allowlist, playback MIME headers.
- **Latest local result:** internal review hardening full suite → `257 passed, 1 skipped`.
- **Planning doc:** none (straightforward Starlette FileResponse wrapper)

### Job 4.2 — Noise floor & threshold

- **Status:** done
- **Depends on:** 4.1
- **Spec stage:** 4.2
- **Goal:** compute noise floor and VAD threshold from loudness data.
- **Build:** `POST /projects/{id}/noise-floor` reads `loudness.json`, computes 10th percentile + 8dB margin, stores on `audio_channels`.
- **Required tests:** floor/percentile math, silence, custom margin, DB updates, auth/404/400.
- **Latest local result:** `env -u VIRTUAL_ENV uv run pytest -q` → `108 passed, 1 skipped`.

### Job DIARIZE — Speaker diarization

- **Status:** done
- **Depends on:** 3.4
- **Spec stage:** N/A (fits between 4.2 and 5.1)
- **Goal:** identify speakers from audio (stereo channel mapping or mono diarization).
- **Build:** `POST /projects/{id}/diarize` — stereo uses channel mapping; mono runs `mock_diarize()`; writes `audio/diarization.json`.
- **Required tests:** mock diarization segments, stereo channel mapping, mono diarization + audio_channels creation, auth/404/400.
- **Latest local result:** `env -u VIRTUAL_ENV uv run pytest -q` → `114 passed, 1 skipped`.
- **Production swap:** replace `mock_diarize()` with pyannote.audio or WhisperX.

### Job 4.3 — Interval construction

- **Status:** done
- **Depends on:** 4.2
- **Spec stage:** 4.3
- **Goal:** turn loudness + thresholds into clean speaking intervals.
- **Build:** `POST /projects/{id}/intervals` reads `loudness.json` + `vad_threshold_db`, writes `speaking_intervals`; `compute_speaking_intervals()` with hangover merge (300ms) and min-duration filtering (150ms).
- **Required tests:** 200ms gap at 300ms hangover does not split; short bursts dropped; hangover/merge; threshold silence; idempotent; mean/peak dB.
- **Latest local result:** `env -u VIRTUAL_ENV uv run pytest -q` → `129 passed, 1 skipped`.
- **Schema note:** `speaking_intervals.id` uses `Integer().with_variant(BigInteger(), "mysql")` for cross-DB autoincrement.

### Job 4.4 — Derived activity timeline

- **Status:** done
- **Depends on:** 4.3
- **Spec stage:** 4.4
- **Goal:** contiguous who-is-active timeline from speaking intervals.
- **Build:** `POST /projects/{id}/activity` reads `speaking_intervals`, builds contiguous `[{start_ms, end_ms, active}]`; `compute_activity_timeline()` with overlap detection and identical-segment merging; writes `audio/activity.json`.
- **Required tests:** silence=empty active; overlap region shows both speakers; timeline contiguous; total_duration_ms extends; identical segments merged; active sorted.
- **Latest local result:** `env -u VIRTUAL_ENV uv run pytest -q` → `141 passed, 1 skipped`.

### Job 4.6 — Program audio mixdown

- **Status:** done
- **Depends on:** 3.4
- **Spec stage:** 4.6
- **Goal:** browser-playable stereo `audio/program.m4a`.
- **Build:** `POST /projects/{id}/program-audio` mixes channel WAVs with timeline offsets via ffmpeg adelay/apad/amerge, AAC 192k +faststart.
- **Required tests:** ffmpeg args correct; sync offsets applied; single-channel mode; auth/404/400.
- **Latest local result:** `env -u VIRTUAL_ENV uv run pytest -q` → `152 passed, 1 skipped`.

### Job HARDEN-1 — Internal review hardening

- **Status:** done
- **Depends on:** review after Stage 6.3
- **Goal:** fix review blockers before continuing to player/public exposure work.
- **Build:** DB URL uses configured URL-encoded password; upload chunks have app and proxy-level hard size limits; generated media filenames use immutable IDs; channel remap invalidates dependent analysis rows; media endpoint serves only DB-known playback assets with player MIME types; wide angle is sync reference when present; diarization output is explicitly marked as placeholder/mock; ffmpeg wrappers fail clearly when executable is missing.
- **Required tests:** focused regressions in `tests/test_review_hardening.py` plus full suite.
- **Latest local result:** `env -u VIRTUAL_ENV uv run pytest -q` → `257 passed, 1 skipped`; `python -m compileall -q src tests` passes.

### Job 7.4 — Notes (multi-author)

- **Status:** in_progress — backend CRUD and UI are implemented and deployed in `c096e4e`; exact-deployed-commit independent Tester verdict is pending.
- **Depends on:** 7.0 (display name), 7.2 (timeline)
- **Spec stage:** 7.4
- **Goal:** timestamped review notes from named reviewers, renderable on timeline, seekable, XSS-safe.
- **Build:** `POST /projects/{id}/notes` creates notes with author from session; `GET /projects/{id}/notes` lists sorted by t_ms; `DELETE /projects/{id}/notes/{note_id}` removes; notes included in timeline-state; timeline 4th lane with coloured markers (blue=note, orange=cut_suggestion); click marker → seek; note list panel below angle controls; add-note form captures current playhead; body rendered via `textContent` (XSS-safe).
- **Required tests:** `tests/test_notes.py` (17 tests) — CRUD, auth, invalid kind, negative t_ms, oversized body, XSS preservation, timeline-state integration.
- **Latest automated result:** `env -u VIRTUAL_ENV uv run pytest -q` → `321 passed, 2 skipped`.
- **Acceptance evidence:** a strict local Chromium harness run against exact `c096e4e`, with candidate CSS and audio/LUT fixtures served, returned `STAGE_7_4_XSS_GATE_PASS` with zero console/page errors. It passed two-author rendering, XSS-safe text rendering, marker seek, and delete removal from both list and lane; the post-delete screenshot shows one remaining note and one Notes-lane marker. Tester card `t_1a379f2a` ran the same harness against old `master` at `87b9d47`, reproduced a stale delete-marker defect there, and returned `TEST_FAIL`; that verdict is not evidence for deployed `c096e4e`.
- **Remaining gate:** independent Tester rerun against exact worktree `/opt/data/workspace/AUTOEDIT/.worktrees/autoedit-integrated` / commit `c096e4e`, with normal CSS/audio/LUT fixture routes and zero unexpected console/network errors.

### Job 7.3 — LUT application

- **Status:** done — LUT upload/list/activate/deactivate/assign API, `.cube` parser (with BMD_TITLE support), WebGL2 3D LUT pipeline (`RGBA8` texture), canvas overlay, and toggle button all working. Real DaVinci Resolve `.cube` file tested and verified in browser.
- **Depends on:** 7.1
- **Spec stage:** 7.3
- **Goal:** preview a graded look over the flat proxy — parse `.cube` LUTs, apply via WebGL 3D texture, toggle on/off without frame drops.
- **Build:** `POST /projects/{id}/luts` uploads validated .cube files; `GET /projects/{id}/luts` lists them; `POST .../assign` binds LUT to angle; `POST .../unassign` clears; `POST .../activate`/`deactivate` manage default LUT; `POST /luts` + `GET /luts` global library; active LUT + per-angle map in player-state; `parseCubeLUT()` parser; `createLUTPipeline(canvas)` WebGL2; render loop binds per-angle LUT on angle switch; angle buttons show blue LUT-assigned dot.
- **Required tests:** `tests/test_luts.py` (16 tests) and `tests/test_angle_luts.py` (12 tests) — all pass.
- **Latest automated result:** `env -u VIRTUAL_ENV uv run pytest -q` → `438 passed, 2 skipped`.
- **LUT pipeline fixes applied in 2026-06-09 session:** BMD_TITLE alias for DaVinci .cube files; media endpoint maps `lut` kind to `luts/` directory; 3D texture uses `RGBA8/Uint8Array` (not `RGB32F`); canvas layered on top of video via z-index rather than hiding videos; boot auto-activation block removed; activate button finally-block resets text.
- **Manual gate:** ✅ passed — real Blackmagic `Gen 5 Film to Video` .cube applied, toggle ON/OFF works, grade visibly changes.

### Job 7.2 — Metadata timeline & navigation

- **Status:** done — timeline-state endpoint, stacked CDL/topic/waveform lanes, click-to-seek, and current-angle label are implemented and live-browser verified.
- **Depends on:** 7.1, 5.5, 6.1
- **Spec stage:** 7.2
- **Goal:** see and jump around the content — scrubber with stacked CDL angle/topic colour lanes, optional loudness waveform, click-to-seek, current angle label.
- **Build:** `GET /projects/{id}/timeline-state` returns summary topics + CDL clips + angle colour mapping + total_duration_ms + optional loudness. Timeline UI renders stacked lanes in the player HTML/CSS/JS with scrubber seek, lane-track click-to-seek, and real-time current-angle indicator.
- **Required tests:** `tests/test_timeline_state.py` (10 tests) covering contract, auth, missing summary/cut, happy path, deterministic colours, loudness inclusion, no data-root exposure; `tests/player_logic.test.mjs` extended with timeline helper tests.
- **Latest automated result:** `env -u VIRTUAL_ENV uv run pytest -q` → `438 passed, 2 skipped`; focused player+timeline+media set → `41 passed`.
- **Manual gates:** ✅ passed — timeline lanes render correctly from JSON in the live browser, clicking topic/angle blocks seeks correctly, and current angle label tracks the CDL during playback.
- **Planning doc:** `docs/plans/stage-7.2-metadata-timeline.md` (to be created)

### Job 7.1 — Player engine

- **Status:** done — player-state endpoint, authenticated static shell, JS helper harness, and live browser playback/sync gates are verified.
- **Depends on:** 3.5/3.5b/3.6, 4.6, 6.1, and completed Stage 7.0 NPM/auth deployment.
- **Spec stage:** 7.1
- **Goal:** audio-master browser review player with smooth automatic cuts, manual angle override, quality switching, and drift correction.
- **Build:** `GET /projects/{id}/player-state`, static player shell, program audio master clock, two-video ping-pong playback, manual override/back-to-auto, proxy/proxy_low quality selection, buffer-aware WAN behavior.
- **Required automated tests:** player-state contract/auth/media URL tests; static shell auth tests; pure JS/player logic tests for clip selection, video-time math, drift threshold, and quality fallback.
- **Latest automated result:** `env -u VIRTUAL_ENV uv run pytest tests/test_player_state.py tests/test_player_static.py tests/test_player_logic_js.py tests/test_media_streaming.py tests/test_review_hardening.py -q` → `31 passed, 1 skipped`; full suite `438 passed, 2 skipped`.
- **Manual gates:** ✅ passed — live rough cut plays without visible stutter, manual switch is ~1–2 frames with no audio glitch, forced angle stays in sync, seek chooses correct angle/time, and throttled/poor-network behavior degrades gracefully.
- **Planning doc:** `docs/plans/stage-7.1-player-engine.md`

### Job 6.1 — Core cut algorithm

- **Status:** done
- **Depends on:** 4.4, CDL contract (2.4)
- **Spec stage:** 6.1
- **Goal:** deterministic rough-cut CDL from the activity timeline.
- **Build:** `POST /projects/{id}/cut` reads `activity.json`, maps speakers→angles, finds wide angle, generates CDL with `generate_cdl()`. Writes `edit/cdl.json` and persists to `cuts` table (`kind='rough'`).
- **Algorithm:** direct baseline: single speaker→that speaker's cam immediately, overlap→wide, silence→wide, no lead/tail delay, tiny `min_shot_ms=250` anti-chatter guard; looser profiles may explicitly raise min-shot/lead/tail or hold silence. Frame-snapping to project FPS; src_in_ms = timeline_in_ms − sync_offset_ms.
- **Required tests:** determinism (byte-identical CDL); single-speaker mapping; overlap-to-wide; silence-hold/silence-wide; frame-snapping; src_in applies sync offset; anti-jitter merge; lead-in/tail; empty timeline; CDL contract structure; custom params.
- **Latest local result:** `env -u VIRTUAL_ENV uv run pytest tests/test_cut_engine.py tests/test_player_state.py -q` → `39 passed`; full suite `438 passed, 2 skipped`.

### Job 6.2 — Anti-jitter & relief wide

- **Status:** done
- **Depends on:** 6.1
- **Spec stage:** 6.2
- **Goal:** polish the cut feel with incoming-speaker-preference anti-jitter and optional relief-wide shots.
- **Build:** Enhanced `_enforce_min_shot_ms()` prefers extending into following clip (incoming speaker), with same-angle→merge and last-clip→preceding fallbacks. `_inject_periodic_wides()` is now treated as optional relief-wide insertion at `wide_interval_ms` cadence with jitter, skipping violations.
- **Required tests:** incoming-speaker preference; same-angle forward/backward merge; pathological rapid-fire respects min_shot_ms; optional relief wides appear when requested; deterministic w/o jitter; respects min_shot_ms; no wides when interval=0 or no wide angle; doesn't inject on existing wide.
- **Latest local result:** `env -u VIRTUAL_ENV uv run pytest tests/test_cut_engine.py tests/test_player_state.py -q` → `39 passed`; full suite `438 passed, 2 skipped`.

### Job 5.1 — Transcription

- **Status:** in_progress — deterministic baseline complete; AI-GPU-1 WhisperX service boundary implemented locally, live V100 gates pending.
- **Depends on:** 3.4
- **Spec stage:** 5.1
- **Goal:** per-speaker transcript segments with word-level timestamps on the master timeline.
- **Build:** `POST /projects/{id}/transcribe` selects explicit `mock` or `whisperx` backends. The WhisperX path calls a separate internal GPU service, normalizes segment/word seconds to integer master-timeline milliseconds, applies the channel sync offset exactly once, and fails visibly without fake fallback text. `services/whisperx_service/` and `docker-compose.gpu-ai.yml` provide an opt-in CUDA service with forced alignment and read-only path-confined media access.
- **Required tests:** mock contract and idempotency; WhisperX request/options; millisecond normalization; offset applied exactly once; unaligned words retain text without fabricated timestamps; explicit service errors; shared-path confinement.
- **Latest targeted result:** `env -u VIRTUAL_ENV uv run pytest tests/test_whisperx.py tests/test_transcribe.py -q` → `19 passed`.
- **Planning doc:** `docs/plans/gpu-ai-whisperx-llm-integration.md`.
- **Manual gates:** build image on Unraid; verify V100 in container; real-WAV aligned word timing within one frame; measure VRAM alongside Dots TTS with Ollama unloaded; only then enable `WHISPER_BACKEND=whisperx`.

### Job 5.2 — Topic segmentation

- **Status:** done
- **Depends on:** 5.1
- **Spec stage:** 5.2
- **Goal:** segment transcript into non-overlapping topic spans with conciseness scores.
- **Build:** `POST /projects/{id}/segment-topics` reads `transcript.json`, runs `mock_segment_topics()`, writes `transcript/topics.json` and persists to `topics` + `topic_spans` tables. Chunks into ~20-60s topics with unique labels and colours.
- **Required tests:** non-overlapping spans; >95% coverage; conciseness 1-5; empty input; required fields; auth/404/400; idempotent; JSON on disk.
- **Latest local result:** `env -u VIRTUAL_ENV uv run pytest -q` → `207 passed, 1 skipped`.
- **Production swap:** harden/replace topic segmentation with an LLM path via `OLLAMA_BASE_URL` / `LLM_MODEL` and avoid silent mock fallback in production.

### Job 5.3 — Conciseness grading

- **Status:** done
- **Depends on:** 5.2
- **Spec stage:** 5.3
- **Goal:** defensible 1-5 conciseness score per span with deterministic metrics.
- **Build:** `POST /projects/{id}/conciseness` reads `topic_spans` + `transcript.json`, computes `grade_conciseness()` per span. Updates `conciseness_score` and `summary` on `topic_spans`.
- **Deterministic signals:** filler-word density (>15% → −2, >8% → −1), duration ratio vs median (>2x → −1, <0.5x → +1), word rate (WPM). Score clamped to 1-5.
- **Required tests:** clean text no filler penalty; heavy fillers downgrade; reproducibility; score clamped 1-5; filler density/WPM/dur_ratio computed; auth/404/400; DB updated; all response fields present.
- **Latest local result:** `env -u VIRTUAL_ENV uv run pytest -q` → `221 passed, 1 skipped`.

### Job 5.5 — Report output

- **Status:** done
- **Depends on:** 5.3, 4.4
- **Spec stage:** 5.5
- **Goal:** single `summary.json` file the reporting UI and timeline lane read.
- **Build:** `POST /projects/{id}/summary` reads `topics` + `topic_spans` + `speaking_intervals` + `activity.json`, calls `build_summary()`, writes `transcript/summary.json`.
- **Output:** `{topics: [{label, colour, spans, speaker_time_ms}], totals: {speaker_time_ms, talk_overlap_ms, silence_ms}}`. Speaker times computed by intersecting `speaking_intervals` with topic span boundaries.
- **Required tests:** per-topic speaker time computed correctly; totals reconcile with sum of per-topic; overlap/silence from activity; empty inputs; structure; auth/404/400; JSON on disk.
- **Latest local result:** `env -u VIRTUAL_ENV uv run pytest -q` → `232 passed, 1 skipped`.

### Job 6.3 — Sub-edit generation

- **Status:** done
- **Depends on:** 6.1, 5.5
- **Spec stage:** 6.3
- **Goal:** themed/social/manual cut versions from topic spans.
- **Build:** `POST /projects/{id}/sub-edit` accepts `by_topics`, `minus_topics`, or `custom_ranges` modes. Selects topic ranges, extracts activity segments within them, re-bases to a new timeline, runs cut engine. Persists to `cuts` table and `edit/cdl_sub_<name>.json`.
- **Required tests:** minus topic excludes; by-topics selects correct ranges; custom ranges; rebasing; fill-to-duration; auth/404/400; CDL file written; DB row created.
- **Latest local result:** `env -u VIRTUAL_ENV uv run pytest -q` → `248 passed, 1 skipped`.

### Job 4.1 — Loudness envelope

- **Status:** done
- **Depends on:** 3.4
- **Spec stage:** 4.1
- **Goal:** a cheap per-channel energy envelope for detection and waveform display.
- **Build:** `POST /projects/{id}/loudness` writes `audio/loudness.json` with per-channel RMS-dB arrays at 20ms hop.
- **Required tests:** correct length, dBFS values, silence floor, hop_ms parameter, JSON shape on disk, auth/404/400.
- **Latest local result:** `env -u VIRTUAL_ENV uv run pytest -q` → `100 passed, 1 skipped`.

### Job 8.3 — OTIO fallback / secondary EDL export

- **Status:** in_progress — direct EDL writer is implemented, tested, and Resolve-verified; the source spec's optional OTIO-generated FCPXML/EDL fallback is not implemented.
- **Depends on:** 8.1, 8.2, 7.4 (notes)
- **Spec stage:** 8.3
- **Goal:** satisfy the source-spec 8.3 fallback contract while retaining the working direct CMX3600 EDL path with `* LOC:` locators.
- **Build:** `src/autoedit/edl_writer.py` — `write_edl()` generates CMX 3600 EDL with correct timecodes, reel names from angle labels, `* FROM CLIP NAME` comments, and `* LOC:` lines per note marker. Export endpoint supports `?format=edl` parameter.
- **Required tests:** `tests/test_edl.py` (8 tests) — timecode conversion, basic EDL structure, notes as LOC lines, empty clips, multiple notes per clip, timeline offsets.
- **Latest automated result:** `env -u VIRTUAL_ENV uv run pytest -q` → `388 passed, 2 skipped`.
- **Manual gate:** ✅ direct EDL imports into Resolve with clips on correct frames and markers visible as timeline locators. OTIO-generated FCPXML/EDL remains unimplemented and unverified.
- **Test file:** `test_export.edl` (6 clips, 6 LOC markers).

### Job 8.1 + 8.2 — CDL validator + FCPXML writer

- **Status:** done — validator and FCPXML writer are implemented/tested, and the populated Resolve import/cut-frame gate passed.
- **Depends on:** CDL contract (2.4), 6.1 (cut engine)
- **Spec stage:** 8.1, 8.2
- **Goal:** never emit a broken export file; valid CDLs produce valid FCPXML.
- **Build:** `src/autoedit/cdl_validator.py` — `validate_cdl()` checks required fields, integer types, positive values, frame-exact times, sort order, contiguity (gap/overlap), source file existence, source duration bounds. `src/autoedit/fcpxml_writer.py` — `write_fcpxml()` generates FCPXML 1.9 with rational frame durations, `file://` URLs, asset-clip spine. `POST /projects/{id}/export` validates then writes `edit/export.fcpxml`.
- **Required tests:** `tests/test_export.py` (24 tests) — frame math, rational formatting, validator (happy path, missing fields, non-integer, sub-frame, gap, overlap, out-of-order, negative, zero, missing src, duration exceeded), FCPXML (XML structure, file URLs, frame boundaries, empty clips).
- **Latest automated result:** `env -u VIRTUAL_ENV uv run pytest -q` → `345 passed, 2 skipped`.
- **Manual gate:** ✅ generated FCPXML opens populated in DaVinci Resolve; cuts land on the same frames as player preview and source files are found/relinkable.
- **Test file:** `/workspace/AUTOEDIT/test_export.fcpxml` (25fps, 3 angles, 6 clips, valid CDL).

### Job 3.2 — Chunked resumable upload

- **Status:** done
- **Depends on:** 3.1; protected by Stage 7.0 backend auth gate when auth is enabled
- **Spec stage:** 3.2
- **Goal:** get three large files onto the array without timeout failures.
- **Build:** upload sessions, chunk write/status, SHA-256 completion, atomic source move, `angles` row creation.
- **Required tests:** interrupted/resumed upload, wrong SHA cleanup, filename/upload-id traversal rejection, three uploads to one project.
- **Latest local result:** `env -u VIRTUAL_ENV uv run pytest -q` → `35 passed, 1 skipped`.
- **Planning doc:** `docs/plans/stage-3.2-chunked-resumable-upload.md`

### Job 3.1 — Project + DB bootstrap

- **Status:** done
- **Depends on:** none
- **Spec stage:** 3.1
- **Goal:** create the first backend foundation: database schema, project creation endpoint, manifest endpoint, project folder skeleton, and `project.json`.
- **Required tests:** migration idempotency, project creation, invalid FPS rejected, `project.json` matches DB.
- **Planning doc:** `docs/plans/stage-3.1-project-db-bootstrap.md`
- **Latest local test:** `env -u VIRTUAL_ENV uv run pytest -q` → `17 passed, 1 skipped`.
- **Latest canonical MySQL gate:** existing MySQL server `192.168.50.50:3306` with `DB_*` env vars → `18 passed`.
- **Historical temporary MySQL gate:** `./scripts/mysql-tunnel.sh` + `./scripts/test-mysql-unraid.sh` → `1 passed`; full suite with `AUTOEDIT_MYSQL_TEST_URL` → `18 passed`.

## Stage backlog

| Job | Stage | Status | Depends on | Output |
| --- | --- | --- | --- | --- |
| CONFIG-REVIEW | Central MySQL deployment + docs remediation | done | DB-0, 7.0 | explicit central-DB compose env, NPM deployment docs, truthful feature status, sync fail-fast |
| DB-0 | Existing MySQL wiring | done | 3.1 code | verified against Peter's existing MySQL server |
| 3.1 | Project + DB bootstrap | done | none | schema, `POST /projects`, `GET /projects/:id`, project skeleton; canonical MySQL gate passed |
| 7.0 | Auth gate + reverse proxy | done | 3.1, DB-0 | backend auth/session/rate limits/origin checks; live-verified behind NPM |
| PROGRESS | Pipeline progress | done | all pipeline stages | project status tracking, progress endpoint, process runner, processing UI, player blocking gate |
| 3.2 | Chunked resumable upload | done | 3.1 | resumable chunk upload + SHA verification + angles rows |
| 3.3 | Probe & channel mapping | done | 3.2 | ffprobe metadata, channel mapping; exceptional nudge controls are Advanced-only, never the normal sync path |
| 3.4 | Channel extraction + audio sync | done | 3.3 | channel WAV extraction, cross-correlation sync |
| 3.5 | Main proxy normalisation | done | 3.3 | silent 720p short-GOP proxies |
| 3.5b | Low-bitrate remote proxy tier | done | 3.5 | silent 360p low-bandwidth proxies |
| 3.6 | Range-request media streaming | done | 3.5, 7.0 | authenticated `206 Partial Content` media streaming |
| 4.1 | Loudness envelope | done | 3.4 | `audio/loudness.json` with RMS-dB arrays at 20ms hop |
| 4.2 | Noise floor & threshold | done | 4.1 | floor (10th percentile) + 8dB threshold on `audio_channels` |
| — | Speaker diarization baseline | done | 3.4 | `audio/diarization.json`; stereo channel mapping + mono mock baseline; real acceptance remains AI-GPU-1 `in_progress` |
| 4.3 | Interval construction | done | 4.2 | `speaking_intervals` with hangover merge + min-duration filter |
| 4.4 | Derived activity timeline | done | 4.3 | contiguous `activity.json` with overlap detection |
| 4.6 | Program audio mixdown | done | 3.4 | browser-playable `audio/program.m4a` with timing offsets |
| 6.1 | Core cut algorithm | done | 4.4, CDL contract | deterministic rough-cut CDL; writes `edit/cdl.json` + `cuts` table |
| 6.2 | Anti-jitter & periodic wide | done | 6.1 | incoming-speaker pref anti-jitter + periodic wide injection |
| 5.1 | Transcription | in_progress | 3.4 | mock baseline complete; opt-in WhisperX adapter/service implemented, live V100 gates pending |
| 5.2 | Topic segmentation | done | 5.1 | non-overlapping topic spans + `topics.json` |
| 5.3 | Conciseness grading | done | 5.2 | deterministic scores + rationale per span |
| 5.5 | Report output | done | 5.3, 4.4 | `transcript/summary.json` with speaker times + overlap/silence |
| 6.3 | Sub-edit generation | done | 6.1, 5.5 | themed/manual cut versions; `edit/cdl_sub_*.json` |
| 7.1 | Player engine | done | 3.5/3.5b/3.6, 4.6, 6.1 | player-state + static shell; browser playback/sync verified |
| 7.2 | Metadata timeline & navigation | done | 7.1, 5.5, 6.1 | timeline-state endpoint, stacked CDL/topic/waveform lanes, click-to-seek; browser verified |
| 7.3 | LUT application | done | 7.1 | per-angle .cube upload/parse/WebGL2 with BMD_TITLE + RGBA8; browser verified with real DaVinci .cube |
| 7.4 | Notes | in_progress | 7.0, 7.2 | deployed candidate passes local Chromium behavior harness; exact-commit independent Tester rerun pending |
| 8.1 | CDL validator | done | CDL contract, 6.1 | strict validator; FCPXML writer verified in Resolve |
| 8.2 | FCPXML writer | done | 8.1 | rational-frame FCPXML 1.9, asset spine; Resolve verified |
| 8.3 | OTIO fallback / EDL | in_progress | 8.1, 7.4 | direct CMX3600 EDL with LOC markers is Resolve-verified; OTIO fallback remains open |
| 9.1 | Natural-language sub-edit requests | done | 6.3 | NL intent parser (deterministic), fuzzy topic matching, API endpoint |
| 9.2 | YouTube title generator | in_progress | 5.5 | 4-category template baseline exists; specified LLM strategies/regeneration/defensive JSON path remains open |


## Remaining project/stage completion gates

- **Stage 7.4:** independent exact-`c096e4e` browser acceptance. Do not reuse the old-`master` failure as a deployed-candidate verdict.
- **Stage 8.3:** optional OTIO fallback remains open; direct EDL is already Resolve-verified.
- **Stage 9.2:** template baseline is not the specified LLM-backed grouped-strategy/regeneration implementation.
- **Golden media fixtures:** no real test media in repo; all tests use mocked ffprobe + numpy-generated audio.
- **LLM integration roadmap (Tier 1-4)** in `AI_HANDOFF.md` — real Whisper transcription, LLM topic segmentation, speaker diarization, conciseness grading not yet wired.

## Job template for future additions

```markdown
### Job X.Y — Name

- **Status:** pending
- **Depends on:** ...
- **Spec stage:** ...
- **Goal:** ...
- **Build:** ...
- **Required tests:** ...
- **Manual gates:** ...
- **Notes/blockers:** ...
```

## Rules for adding jobs

- Add new jobs here before implementing them.
- Keep each job tied to a spec stage or explicitly label it as supporting infrastructure.
- Include exact dependencies.
- Include tests or manual gates.
- Update status at the end of each session.
