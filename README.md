# AUTOEDIT

Self-hosted multicam auto-edit platform for three-angle interview footage.

## Start here for every new AI session

1. Read `AI_HANDOFF.md` first — it is the current session handoff and should tell you what to do next without needing chat history.
2. Read `jobs/BACKLOG.md` for stage status, dependencies, and completion gates.
3. Read `docs/plans/TESTING_STRATEGY.md` before changing code or marking anything done.
4. **Current engineering pickup:** continue the unresolved Phase 4/acceptance gates in `docs/plans/ai-gpu-1-corrective-pickup.md`: frame-level timing, operator-confirmed speaker identity, speaker-turn cut generation, and the consent-cleared benchmark. Keep production AI backends on mock until acceptance.
5. Read source docs only when you need deeper spec details:
   - `docs/source/multicam_autoedit_spec.md`
   - `docs/source/multicam_ui_style_guide.html`

## Current status snapshot

- Backend: Python 3.12 + FastAPI + SQLAlchemy Core + pytest, managed with `uv`.
- Frontend: Stage 7.4 notes (multi-author markers + list panel + add-note form) + Stage 7.3 per-angle LUT + Stage 7.2 timeline lanes + Stage 7.1 player shell via static web shell.
- Final reconciliation verification: `env -u VIRTUAL_ENV uv run pytest -q` → **685 passed, 2 skipped**.
- The final commit gate also runs compilation, lock/dependency checks, and `git diff --check` after all reconciliation edits.
- Auto-cut Direct defaults are live-deployed on Unraid: `min_shot_ms=250`, no lead/tail delay, overlap→wide, silence→wide. Existing cuts keep stored params until regenerated; `sm test` was regenerated as `Direct rough cut`.
- Processing now includes an analysis-only `level_normalization` stage after noise-floor. It writes `audio/level_normalization.json` and normalizes activity `levels` for dominance/cross-bleed decisions without altering source WAVs or program audio.
- Ingest/channel mapping UI now separates camera sources from speaker channels: upload labels are Camera A/B/Wide, probe metadata persists into `/assets`, and audio-channel rows no longer auto-select presenter/interviewee defaults.
- Stage 7.0 backend auth is implemented and deployed behind NPM. CONFIG-REVIEW is complete: active Unraid deploy uses central MySQL, explicit compose env vars, and NPM.
- Module 7 (player) code exists; Module 8 export has been verified in Resolve. Some AI/worker features are mock/template/in-process and must not be documented as production-complete until remediated.
- Export test files: `test_export.fcpxml` (multi-track), `test_export.edl` (with markers).

| Module | Stages | Status |
|--------|--------|--------|
| 3 — Ingest & normalisation | 3.1–3.6, 3.5b | ✅ Complete locally |
| 4 — Audio analysis & VAD | 4.1, 4.2, 4.3, 4.4, 4.6 | ✅ Complete locally |
| — Speaker diarization | diarize | ✅ Placeholder/mock complete locally |
| 5 — Transcription & AI | 5.1, 5.2, 5.3, 5.5 | 🔄 Mock/deterministic + local Ollama option; authoritative Whisper import and planned DeepSeek→Qwen provider chain pending |
| 6 — Auto-cut engine | 6.1, 6.2, 6.3 | ✅ Complete locally |
| — Pipeline progress | progress | ✅ Progress tracking + process runner + processing UI |
| HARDEN-1 — Internal review fixes | review hardening | ✅ Complete locally |
| 7 — Auth & reverse proxy | 7.0 | ✅ Complete — NPM/TLS/auth live-verified |
| 7 — Review player | 7.1–7.4 | 🔄 7.1–7.3 live-verified; 7.4 multi-author/XSS gates pending |
| 8 — Export | 8.1–8.3 | ✅ Complete — clips + markers verified in Resolve |
| 9 — Generative features | 9.1 | ✅ NL sub-edit intent parser + endpoint done |
| 9 — Generative features | 9.2 | 🔄 Template-based YouTube title generator; LLM-backed generation pending if desired |

## Immediate next action

1. Continue the remaining real-AI acceptance gates: consent-cleared labels/metrics, frame-level word-timing review, operator-confirmed speaker identity, and speaker-turn cut generation.
2. Implement the provider-neutral `deepseek-v4-flash` → local Qwen3.5 9B chain only after the authoritative transcript path is accepted; remove randomized mock degradation and record provider/fallback provenance.
3. Keep `WHISPER_BACKEND=mock` and `DIARIZE_BACKEND=mock` until acceptance. The Stage 7.4 browser/XSS gate remains a separate parallel manual task.

## Test commands

```bash
# Local/default suite; MySQL integration skips unless DB env vars are set.
env -u VIRTUAL_ENV uv run pytest -q

# Compile/import sanity check.
python -m compileall -q src tests

# Existing MySQL gate; provide the real password only in process env, never in files/docs.
DB_HOST=192.168.50.50 \
DB_PORT=3306 \
DB_NAME=autoedit \
DB_USER=autoedit \
DB_PASSWORD='***' \
  env -u VIRTUAL_ENV uv run pytest -q
```

## Non-negotiable project rules

- Stage-gated build: do not start a stage until its dependencies are marked done.
- Do not mark a stage `done` unless its automated tests and documented manual gates pass.
- Honour the shared contracts in spec Section 2 exactly.
- All media times are integer milliseconds on the synced master timeline.
- Operator-tunable values must be env vars or per-project config, never hardcoded.
- Remote/public exposure requires TLS, auth, upload/body limits, CORS/origin checks, and authenticated Range-aware media streaming.
- Never expose `/data` directly as static files.
- Player performance and sync are core risks: proxy playback only, program audio as master clock, drift correction.
- Export is not done until FCPXML opens populated in DaVinci Resolve.
- No secrets in repo. Never commit `.env` or real credentials.

## Expected deployment target

- Host: Unraid + Docker.
- TLS boundary: Nginx Proxy Manager at `ingest.peteflix.uk`.
- Data root default from spec: `/mnt/user/automulticam`, mounted into containers as `/data`.
- Canonical DB: Peter's existing MySQL server, configured via explicit `DB_*` environment variables.
- Temporary `autoedit-mysql` dev container exists only as historical compatibility proof and should not be treated as canonical.

## Continuity docs to update after meaningful work

- `AI_HANDOFF.md` — current implementation state, next job, blockers/manual gates, latest test result.
- `jobs/BACKLOG.md` — statuses, dependencies, outputs, required tests/manual gates.
- `docs/plans/TESTING_STRATEGY.md` — exact commands/results and new required tests.
- Any relevant `docs/plans/stage-*.md` plan.
