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
3. **Player is live-verified:** playback, timeline, LUT upload/activate/toggle (real Blackmagic .cube tested), angle switching, and notes UI all render in the browser behind NPM. Remaining manual gates are XSS-safe note rendering and multi-author verification.
4. Stages/features that are mock/template/in-process must not be documented as production-complete.

## Current implementation state

- Backend stack: Python 3.12 + FastAPI + SQLAlchemy Core + pytest, managed with `uv`.
- Latest local verification: `env -u VIRTUAL_ENV uv run pytest -q` → **438 passed, 2 skipped**.
- Compile check: `python -m compileall -q src tests` passes.
- Deployed on Unraid: `/mnt/user/appdata/autoedit`, `network_mode: host`, port 8010 behind NPM at `ingest.peteflix.uk`.
- Central MySQL at `192.168.50.50:3306`, database `autoedit`, user `autoedit`. Password in deployment secrets only.
- VAAPI hardware proxy encoding active (`PROXY_ENCODER=h264_vaapi`, `/dev/dri` mounted).
- Quality default is now `proxy` (720p), not `proxy_low`. All three places updated: API, HTML, JS.
- Auto-cut editorial default is now **Direct** and live-deployed: `min_shot_ms=250`, `lead_in_ms=0`, `tail_ms=0`, `silence_behaviour='wide'`, `overlap_to_wide=true`. Existing projects keep stored `cuts.params_json` until regenerated; live project `sm test` was regenerated as `Direct rough cut`. Loosen only deliberately via higher min-shot/tail/lead or relief wides.

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
| 7.4 — Multi-author notes | 7.4 | 🔄 UI renders; XSS gate + multi-author pending |
| 8 — Export | 8.1–8.3 | ✅ FCPXML + EDL verified in Resolve |
| 9 — Generative features | 9.1–9.2 | 🔄 NL intent done; YT titles template-based |

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

### Feature-status caveats

- Transcription uses `mock_transcribe()`.
- Diarization uses `mock_diarize()` / simple channel mapping.
- Topic segmentation has mock fallback.
- YouTube title generation is template-based.
- Pipeline processing is in-process background thread, not Redis/worker.
- Hardware proxy uses VAAPI; QSV is broken (`MFX session: -9`).

## Test commands

```bash
# Local SQLite-backed suite
env -u VIRTUAL_ENV uv run pytest -q

# Compile sanity
python -m compileall -q src tests

# Central MySQL integration (passwords from deployment secrets)
DB_HOST=192.168.50.50 DB_PORT=3306 DB_NAME=autoedit DB_USER=autoedit DB_PASSWORD='***' \
  env -u VIRTUAL_ENV uv run pytest -q
```

## Known blockers / manual gates

- Stage 7.4: notes XSS-safe rendering + multi-author verification in browser.
- No golden media fixtures yet (mocked ffprobe + numpy-generated audio used in tests).
- Real transcription (Whisper), diarization, and LLM topic segmentation not yet wired.
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
