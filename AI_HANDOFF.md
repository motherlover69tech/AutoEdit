# AUTOEDIT AI Handoff

This file exists so a future AI can start a new session and continue without asking Peter to re-explain the project.

## Project mission

Build AUTOEDIT: a self-hosted, internet-accessible multicam ingest, transcription, AI logging, review-player, and NLE export platform for three-angle interviews.

The system ingests three 1080p H.264 angles, syncs them by audio, creates smooth proxies, detects who is speaking from two speaker channels, transcribes and logs topics, generates a deterministic cut decision list, lets reviewers remotely review/annotate the cut, and exports FCPXML that imports populated into DaVinci Resolve.

## Source-of-truth documents

- Deployment runbook: `docs/DEPLOYMENT.md`
- Technical spec/build plan: `docs/source/multicam_autoedit_spec.md`
- UI style guide/flow: `docs/source/multicam_ui_style_guide.html`
- Job backlog: `jobs/BACKLOG.md`
- Testing strategy: `docs/plans/TESTING_STRATEGY.md`
- Player debugging skill: `~/.hermes/profiles/mastercoder/skills/autoedit-player-debugging/SKILL.md`

Read those before implementing.

## Next AI quickstart

1. Run from `/workspace/AUTOEDIT`.
2. Do **not** ask Peter to restate context; this file + `jobs/BACKLOG.md` + `docs/plans/TESTING_STRATEGY.md` are the handoff.
3. **Immediate engineering pickup:** continue Phase 4 speaker mapping/diarization from `docs/plans/ai-gpu-1-corrective-pickup.md` and the authoritative roadmap. The artifact corrective review is now `PASS`.
4. Preserve `WHISPER_BACKEND=mock` and `DIARIZE_BACKEND=mock`; queued ASR/alignment/diarization ran successfully, but frame-level timing, confirmed speaker identity, and speaker-aware cut acceptance remain open.
5. The unrelated Stage 7.4 gate is now narrower: the exact deployed candidate needs an independent Tester rerun for multi-author, XSS-safe rendering, marker seek, and delete-from-list-and-lane. A 2026-07-16 Tester run accidentally exercised `master` at `87b9d47`, not deployed `c096e4e`, so its delete-marker failure is not evidence about production.
6. For the broader real-AI phase order, also read `docs/plans/whisperx-speaker-aware-ai-roadmap.md`.

## AI-GPU-1 corrective checkpoint (updated 2026-07-16)

Substantial local speaker-aware AI work now exists. The corrective review passed, but the stage remains **in progress**, not production-ready:

- Strict/versioned AI contracts, atomic last-known-good artifacts, synchronized analysis-audio generation, and an isolated single-concurrency WhisperX job queue were added locally.
- Real-media technical baseline: `docs/ai/real-media-phase0-baseline.json`; private media/analysis stays ignored under `testmedia/`.
- Consent-cleared local analysis audio is 16 kHz mono; exact source/derivative measurements and fingerprints remain in the untracked local manifest.
- Authoritative sync convention: `source_ms = master_ms + sync_offset_ms`; convert results using `master_ms = source_ms - sync_offset_ms` and clip negative pre-roll.
- Current deterministic mock-isolated checkpoint: `OLLAMA_BASE_URL='' LLM_MODEL='' env -u VIRTUAL_ENV uv run pytest -q -rs` → `691 passed, 1 skipped`; the sole skip is the credential-gated central-MySQL integration test. The direct Node 22 player suite, Python compile, and `git diff --check` also pass. The delayed-review worker/artifact/transcript hardening checkpoint remains `142 passed`.
- Remote V100 `/ready` passed for `large-v3` FP16: compute capability 7.0, about 50 seconds cold load, maximum observed readiness VRAM 22,186 MiB.
- A consent-cleared queued ASR/alignment run completed in 20.93 seconds with 241 ordered/non-empty segments, approximately 1,422 words, and no structural timing defects. A wrong-hash request returned HTTP 400. Observed post-job GPU memory was 6,048 MiB, not a sampled peak.
- Independent artifact review now returns `PASS`; symlink confinement, strict integer timestamps, immutable failure records, and resolved-speaker integrity have direct regressions.
- Worker logs expose a TorchCodec/PyTorch/FFmpeg file-decoder warning, but the in-memory waveform path passed real pyannote diarization and does not use that decoder.
- Real constrained two-speaker diarization completed in 28.99 seconds: 241 aligned segments, 1,422 words, 322 turns, two anonymous speakers, and 8,024 MiB sampled peak VRAM. The reviewed worker image tag is `autoedit-whisperx:phase1-overlap-sweep`; its digest remains in the local manifest.
- Phase 4 deterministic speaker resolution now exists locally: multi-turn high-confidence voice evidence may suggest an identity, prior confirmations require current voice revalidation (so anonymous label swaps are safe), transcript/LLM context is audit-only, and conflicts remain unresolved/wide.
- Independent Phase 4 resolver and WhisperX diarization-import re-review returned `PASS`; all four requested direct regressions are present and no mandatory resolver/import regressions remain missing.
- The strict LLM context seam ran through AUTOEDIT against the consent-controlled transcript with local Qwen 3.6 27B. It extracted three anonymous explicit-address candidates at the 0.40 audit ceiling, made no voice-cluster assignments, used non-thinking structured output, and unloaded immediately afterward.
- Independent review then required fail-closed transcript grounding and stricter malformed-output handling. The seam now validates every quote and timestamp against the same source segment, rejects thinking traces and coercive/malformed input/output, and passed the consent-controlled Qwen rerun after hardening. Names, excerpts, exact evidence timestamps, job IDs, and media fingerprints are intentionally not committed.
- The temporary Unraid container `autoedit-whisperx-phase0` was stopped after the AI gate. That AI gate did not alter production. Production was later rebuilt for the frontend-only `c096e4e` release; `WHISPER_BACKEND=mock` and `DIARIZE_BACKEND=mock` remained pinned.

**Canonical pickup instructions, exact gates, paths, and safe rerun order:** `docs/plans/ai-gpu-1-corrective-pickup.md`.

## Current implementation state

- Backend stack: Python 3.12 + FastAPI + SQLAlchemy Core + pytest, managed with `uv`.
- Final deterministic local checkpoint (2026-07-16): `691 passed, 1 skipped` with Ollama/model variables explicitly cleared; the only skip is the central-MySQL integration test when DB credentials are absent.
- Compilation, lock/dependency validation, and `git diff --check` are part of the final commit gate.
- Deployed on Unraid: exact non-`master` integration commit `c096e4e179291d910fbdb8864916318cbfd28c64`, image `sha256:3ac84cf4f23fa287fe40fc33a3121aae1680636ea6971d5aa23d408e11108d52`, under `/mnt/user/appdata/autoedit`, `network_mode: host`, port 8010 behind NPM at `ingest.peteflix.uk`. Publisher card `t_26cf76c6` recorded zero restarts, a preserved DB backup/rollback tag, and no media/data mutation. Fresh public read-only checks on 2026-07-16 returned `/health` 200 and unauthenticated `/projects` 401.
- Branch topology matters: deployed `c096e4e` lives on `autoedit-integrated` and is **not** an ancestor of local `master`; `master` and the deployed branch share base `426c26b`. Never test or publish `master` while claiming evidence for `c096e4e`.
- The deployed UI simplification makes project/ingest actions status-driven, uses progressive disclosure, keeps automatic energy-envelope cross-correlation as the normal sync path, and moves any exceptional nudge controls under Advanced.
- Central MySQL at `192.168.50.50:3306`, database `autoedit`, user `autoedit`. Password in deployment secrets only.
- VAAPI hardware proxy encoding active (`PROXY_ENCODER=h264_vaapi`, `/dev/dri` mounted).
- Quality default is now `proxy` (720p), not `proxy_low`. All three places updated: API, HTML, JS.
- Auto-cut editorial default is now **Direct** and live-deployed: `min_shot_ms=250`, `lead_in_ms=0`, `tail_ms=0`, `silence_behaviour='wide'`, `overlap_to_wide=true`. Existing projects keep stored `cuts.params_json` until regenerated; live project `sm test` was regenerated as `Direct rough cut`. Loosen only deliberately via higher min-shot/tail/lead or relief wides.
- Shot-reason audit metadata is implemented and live-deployed: each newly generated CDL reason segment carries `reason_code`, `reason_label`, and `reason_detail`, and the player shows the active reason during playback. Same-camera reason boundaries are retained without causing a visual camera switch, including segments below the 250 ms visual anti-jitter threshold. Existing CDLs fall back to their legacy `reason` strings and therefore do not require regeneration merely to show a basic reason. Regenerate only when the richer same-camera reason boundaries are wanted.
- Final independent shot-reason re-review returned `PASS`: sub-minimum same-camera boundaries, visual anti-jitter, frame snapping, source-fallback reconstruction, and API/disk/database/player-state persistence were all accepted with no further findings.
- New processing stage: `level_normalization` runs after `noise_floor`, writes `audio/level_normalization.json`, and applies analysis-only gain offsets to activity `levels` so cut dominance compares normalized channel levels instead of raw uneven mic dBFS. It does not change source WAVs or `program.m4a`.
- Ingest/channel mapping UI clarification: Camera A/B/Wide are now neutral source labels, probe results are persisted in `metadata/probes/*.json` and exposed via `/assets`, and the audio mapping table starts blank unless mappings are already saved. Operators must explicitly pick source channel + speaker heard.

### Stage status table

| Module | Stages | Status |
|--------|--------|--------|
| 3 — Ingest & normalisation | 3.1–3.6, 3.5b | ✅ Complete |
| 4 — Audio analysis & VAD | 4.1–4.6 | ✅ Complete |
| — Speaker diarization | diarize | ✅ Mock placeholder; needs pyannote/WhisperX |
| 5 — Transcription & AI | 5.1–5.5 | 🔄 Mock/deterministic; needs real Whisper/LLM |
| 6 — Auto-cut engine | 6.1–6.3 | ✅ Complete |
| — Pipeline progress | progress | ✅ Progress tracking + processing UI |
| HARDEN-1 — Review fixes | review | ✅ Complete |
| 7.0 — Auth gate | 7.0 | ✅ Live-verified: TLS, login, session cookies |
| 7.1 — Player engine | 7.1 | ✅ Live-verified: playback, ping-pong switching |
| 7.2 — Timeline & nav | 7.2 | ✅ Live-verified: lanes, click-to-seek, labels |
| 7.3 — LUT application | 7.3 | ✅ Live-verified: upload, activate, toggle with real DaVinci .cube |
| 7.4 — Multi-author notes | 7.4 | 🔄 Deployed-candidate behavior passes a local Chromium harness; exact-commit independent Tester rerun pending |
| 8 — Export | 8.1–8.2 | ✅ Validator + FCPXML verified in Resolve |
| 8.3 — OTIO fallback | 8.3 | 🔄 Direct CMX3600 EDL exists and was Resolve-verified; spec's OTIO fallback is not implemented |
| 9 — Generative features | 9.1–9.2 | 🔄 Deterministic NL intent baseline done; title output is template-based, not the specified LLM/regeneration flow |

### Player.js bugs fixed (2026-06-09 session)

The player had pervasive scope bugs where `doc` (a function parameter) was used at module level and in helper functions that don't have a `doc` parameter. All fixed:

- **`doc.getElementById()` → `document.getElementById()`** in: module-level LUT upload code, `loadCutParams`, `renderLutList`, `updateDefaultLutSelect`, `renderDefaultLut`, `renderAngleLutAssignments`, and the sync nudge controls.
- **Missing function parameters**: `loadLuts`, `renderDefaultLut`, `renderAngleLutAssignments` were missing `projectId`, `statePayload`, `currentAngleId`. Added to all signatures and callers.
- **LUT upload handler** was at module level using `projectId` (undefined). Moved into `bootPlayer()`.
- **Boot auto-activation block** hid videos and showed canvas before LUT data was loaded. Removed.
- **Stuck "Activating…" button**: `finally` block wasn't resetting button text. Fixed.

### LUT pipeline fixes

- **BMD_TITLE support**: DaVinci Resolve `.cube` files use `BMD_TITLE` instead of `TITLE`. Added to both backend (`lut_io.py`) and frontend (`parseCubeLUT`).
- **Media directory mismatch**: LUT files stored in `luts/` but endpoint expected `lut/`. Fixed in `stream_media()` with `kind_dir = kind if kind != "lut" else "luts"`.
- **3D texture format**: `gl.RGB32F` unsupported on many GPUs. Switched to `gl.RGBA8` with `Uint8Array` (0-255) — universally supported.
- **`texImage2D: no video`**: Render loop was capturing video frames before video decoded. Added guard: `if (!videoEl || !videoEl.videoWidth || !videoEl.videoHeight) return;`
- **Hidden videos don't decode**: Setting `opacity:0` on `<video>` can stop frame decoding. Changed to keep videos visible and layer WebGL canvas on top via `z-index`.

### Deployment pitfalls learned

- **Docker Compose auto-loads `.env`**: The file at `/mnt/user/appdata/autoedit/.env` had stale `DB_HOST=autoedit-mysql` and placeholder passwords. When shell env vars aren't present, `.env` takes over and breaks deployments. Always verify with `docker compose config` before deploying.
- **`cat > file` over SSH produces 0-byte files**: Piping content through SSH to `cat` is unreliable. Always use `scp` for file transfers.
- **Static web files hot-inject**: JS/HTML/CSS can be copied into running container without rebuild: `docker cp src/autoedit/web/player.js autoedit-app-1:/app/src/autoedit/web/player.js`. Python changes still need rebuild.
- **Narrow deploys from a dirty feature workspace must account for dependency drift**: the workspace `api.py` can import other uncommitted AI modules that production does not yet have. For the shot-reason deploy, copying workspace `api.py` alone caused a restart loop (`transcribe_with_backend` missing). Production was immediately rebuilt from its backed-up API with only `_with_shot_reason` imported/applied, while the reviewed cut engine/player files were deployed unchanged. Always run an in-container API import before accepting a narrow deploy.
- **Deployed commit can differ from `master`**: the current release is exact `c096e4e` on `autoedit-integrated`; local `master` does not contain it. Every regression card must name and verify the exact commit/worktree before producing a verdict.

### Feature-status caveats

- Transcription uses `mock_transcribe()`.
- Diarization uses `mock_diarize()` / simple channel mapping.
- Topic segmentation has mock fallback.
- YouTube title generation is template-based.
- Pipeline processing is in-process background thread, not Redis/worker.
- Hardware proxy uses VAAPI; QSV is broken (`MFX session: -9`).

## Test commands

```bash
# Deterministic local SQLite-backed suite (prevents accidental live Ollama calls)
OLLAMA_BASE_URL='' LLM_MODEL='' env -u VIRTUAL_ENV uv run pytest -q -rs

# Compile sanity
python -m compileall -q src tests

# Central MySQL integration (passwords from deployment secrets)
DB_HOST=192.168.50.50 DB_PORT=3306 DB_NAME=autoedit DB_USER=autoedit DB_PASSWORD='***' \
  env -u VIRTUAL_ENV uv run pytest -q
```

## Known blockers / manual gates

- Stage 7.4: obtain an independent Tester verdict against exact deployed `c096e4e`. The candidate-local Chromium harness passed XSS safety, two-author rendering, marker seek, and delete synchronization; the prior `TEST_FAIL` targeted old `master` and must not be treated as production evidence.
- Stage 8.3: the optional OTIO fallback from the source spec is not implemented. The existing direct CMX3600 EDL path is separately Resolve-verified.
- No golden media fixtures yet (mocked ffprobe + numpy-generated audio used in tests).
- Real transcription/diarization have opt-in local components but are not production-authoritative; topic/title paths still retain deterministic/mock/template behavior.
- QSV hardware encoding broken; VAAPI is the active path.

## Highest-risk areas to preserve

- Silent short-GOP proxies; source is never played in the browser.
- Program audio is the review-player master clock.
- Browser video follows audio and corrects drift if beyond one frame.
- Audio sync via cross-correlation, integer-ms offsets, same offsets used in player and exporter.
- CDL validator before every export.
- Direct auto-cut should remain the baseline: single active speaker cuts to that speaker immediately; overlap and silence go wide. Do not reintroduce the old conservative 1200ms/hold-last defaults unless Peter explicitly asks for a looser profile.
- FCPXML times as exact rational seconds matching project FPS.
- LUT preview via WebGL over flat proxy; do not bake LUT into proxies or exports.
- WebGL LUT texture uses `RGBA8` unsigned byte — changing back to float formats will break on some GPUs.

## Required ongoing maintenance

After each session/stage:

1. Mark completed/pending work in `jobs/BACKLOG.md`.
2. Add or update implementation/test plans in `docs/plans/`.
3. Update this handoff with current state, next job, test status, blockers/decisions.
4. If code exists, leave the workspace in a runnable/testable state.
5. Do not mark a stage done unless the stage Definition of Done passes.
