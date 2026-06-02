# AUTOEDIT

Self-hosted multicam auto-edit platform for three-angle interview footage.

## Start here for every new AI session

1. Read `AI_HANDOFF.md` first — it is the current handoff/source-of-truth for session state.
2. Check `jobs/BACKLOG.md` for stage status and the next stage-gated job.
3. Check `docs/plans/TESTING_STRATEGY.md` before changing code or marking work done.
4. Read the imported source documents only when needed for details:
   - `docs/source/multicam_autoedit_spec.md`
   - `docs/source/multicam_ui_style_guide.html`
5. Keep the continuity docs updated after any meaningful work:
   - `AI_HANDOFF.md`
   - `jobs/BACKLOG.md`
   - `docs/plans/TESTING_STRATEGY.md`
   - relevant `docs/plans/*.md`

## Current status snapshot

- Backend stack: Python 3.12 + FastAPI + SQLAlchemy Core + pytest, managed with `uv`.
- Stage 3.1 — Project + DB bootstrap: **done**.
- DB-0 — Existing MySQL wiring: **done** against Peter's existing MySQL server (`192.168.50.50:3306`, database/user `autoedit`; password not recorded).
- Stage 7.0 — Auth gate + reverse proxy: **in progress**.
  - Backend auth/session/rate-limit/origin checks are implemented and tested.
  - Remaining gate is real public-domain reverse proxy/TLS verification.
- Stage 3.2 — Chunked resumable upload: **done locally**, protected by auth middleware when auth is enabled.
- No frontend exists yet.

## Immediate next work

1. Preferred before public exposure: finish Stage 7.0 manual deployment gate:
   - configure real `PUBLIC_DOMAIN`
   - verify TLS certificate provisioning
   - verify HTTP → HTTPS redirect
   - verify protected routes return `401` without session
   - verify `/data` is not exposed directly
2. If public-domain/TLS details are not available, continue code work with **Stage 3.3 — Probe & channel mapping**.

## Test commands

```bash
# Local/default suite; MySQL integration skips unless DB env vars are set.
env -u VIRTUAL_ENV uv run pytest -q

# Existing MySQL gate; provide the real password only in process env, never in files/docs.
DB_HOST=192.168.50.50 \
DB_PORT=3306 \
DB_NAME=autoedit \
DB_USER=autoedit \
DB_PASSWORD='***' \
  env -u VIRTUAL_ENV uv run pytest -q
```

Latest local result after Stage 3.2: `35 passed, 1 skipped`.

## Non-negotiable project rules

- Stage-gated build: do not start a stage until its dependencies are marked done.
- Do not mark a stage `done` unless its Definition of Done or documented manual gate has passed.
- Honour the shared contracts in spec Section 2 exactly, especially:
  - storage layout
  - MySQL schema
  - env/config parameters
  - Cut Decision List / CDL contract
- All media times are integer milliseconds on the synced master timeline.
- Operator-tunable values must be env vars or per-project config, never hardcoded.
- Remote/public exposure requires TLS, auth, rate limiting, CORS/origin checks, and authenticated Range-aware media streaming.
- Never expose `/data` directly as static files.
- Player performance and sync are core risks: proxy playback only, program audio as master clock, drift correction.
- Export is not done until FCPXML opens populated in DaVinci Resolve.
- No secrets in repo. Never commit `.env` or real credentials.

## Expected deployment target

- Host: Unraid + Docker.
- Data root default from spec: `/mnt/user/automulticam`, mounted into containers as `/data`.
- Canonical DB: Peter's existing MySQL server, configured via `DB_*` environment variables.
- Temporary `autoedit-mysql` dev container exists only as historical compatibility proof and should not be treated as canonical.
