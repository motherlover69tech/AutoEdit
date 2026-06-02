# AUTOEDIT AI Handoff

This file exists so a future AI can start a new session and continue without asking Peter to re-explain the project.

## Project mission

Build AUTOEDIT: a self-hosted, internet-accessible multicam ingest, transcription, AI logging, review-player, and NLE export platform for three-angle interviews.

The system ingests three 1080p H.264 angles, syncs them by audio, creates smooth proxies, detects who is speaking from two speaker channels, transcribes and logs topics, generates a deterministic cut decision list, lets reviewers remotely review/annotate the cut, and exports FCPXML that imports populated into DaVinci Resolve.

## Source-of-truth documents

- Technical spec/build plan: `docs/source/multicam_autoedit_spec.md`
- UI style guide/flow: `docs/source/multicam_ui_style_guide.html`
- Reviewed summary: `docs/review/source-docs-review.md`
- Job backlog: `jobs/BACKLOG.md`
- Testing strategy: `docs/plans/TESTING_STRATEGY.md`

Read those before implementing.

## Current implementation state

- Backend stack chosen: Python 3.12 + FastAPI + SQLAlchemy Core + pytest, managed with `uv`.
- Stage 3.1 code is implemented and deployment-DB verified.
  - DB schema tables for spec Section 2.2.
  - Idempotent `run_migrations(engine)` helper using SQLAlchemy metadata.
  - `POST /projects` and `GET /projects/:id`.
  - `DATA_ROOT` project skeleton creation.
  - Atomic `project.json` manifest write.
  - Strict invalid-FPS validation returning HTTP 400.
  - Local SQLite-backed tests pass.
  - MySQL compatibility was first proven against a temporary Unraid dev container.
  - Peter's existing MySQL server at `192.168.50.50:3306`, database `autoedit`, user `autoedit`, has now passed the canonical deployment DB gate. Password is intentionally not recorded.
- **Canonical DB decision:** use Peter's existing MySQL server, not the temporary `autoedit-mysql` container.
  - Required creds/details are documented in `docs/plans/EXISTING_MYSQL_REQUIREMENTS.md`.
  - Existing MySQL verification command used direct `DB_*` env vars to avoid URL-encoding issues with special-character passwords.
  - Latest canonical DB result: `DB_HOST=192.168.50.50 DB_PORT=3306 DB_NAME=autoedit DB_USER=autoedit DB_PASSWORD=*** env -u VIRTUAL_ENV uv run pytest -q` → `18 passed in 1.82s`.
  - Temporary dev DB: `/mnt/user/appdata/autoedit-mysql/compose.yaml`, container `autoedit-mysql`, bound to Unraid `127.0.0.1:3307` only. It is currently stopped and should not be used as the canonical DB.
- Stage 7.0 backend auth gate is implemented and tested locally:
  - Signed httpOnly session cookie login at `POST /auth/login`.
  - `GET /auth/me` returns reviewer display name from the session.
  - All non-public routes require a session when auth is enabled.
  - Public exceptions: `/health`, `POST /auth/login`, and `/.well-known/acme-challenge/...`.
  - Brute-force login lockout and `PUBLIC_DOMAIN` origin checks are covered by tests.
  - Caddy reverse-proxy template exists in `infra/proxy/`.
  - Remaining Stage 7.0 gate: deploy/verify TLS cert provisioning + HTTP→HTTPS redirect on the real public domain.
- No frontend exists yet.

## Immediate next job

Finish **Stage 7.0 — Auth gate + reverse proxy** by deploying/verifying the proxy/TLS manual gate on the real public domain. Do not start upload/media exposure until this is done.

If TLS/public-domain details are not available, the next code job is Stage 3.2 chunked resumable upload, but keep all upload/media routes behind the auth middleware added in Stage 7.0.

## Key architecture constraints

- Backend may be Node or Python; choose deliberately before first code and record decision here.
- All services must be Docker-friendly for Unraid.
- Data paths are under `DATA_ROOT`, default `/mnt/user/automulticam`, mounted as `/data` in containers.
- Never expose `/data` directly as static files.
- No secrets in repo. Create `.env.example`, never `.env` with real values.
- Use ULIDs for project/user/angle/cut ids where the schema expects `CHAR(26)`.
- Store media times as `BIGINT` integer milliseconds, never floats.
- The CDL contract in spec Section 2.4 is the shared boundary. Do not change it without stopping and flagging the issue.

## Highest-risk areas to preserve

Attempt 1 failed on:

1. Choppy playback.
2. Angles drifting/out of sync.
3. Blank FCPXML import in Resolve.
4. LUT not working.

Mitigations that must survive implementation:

- Silent short-GOP proxies; source is never played in the browser.
- Program audio is the review-player master clock.
- Browser video follows audio and corrects drift if beyond one frame.
- Audio sync via cross-correlation, integer-ms offsets, same offsets used in player and exporter.
- CDL validator before every export.
- FCPXML times as exact rational seconds matching project FPS.
- LUT preview via WebGL over flat proxy; do not bake LUT into proxies or exports.

## Required ongoing maintenance

After each session/stage:

1. Mark completed/pending work in `jobs/BACKLOG.md`.
2. Add or update implementation/test plans in `docs/plans/`.
3. Update this handoff with:
   - current state
   - next exact job
   - test status
   - blockers or decisions
4. If code exists, leave the workspace in a runnable/testable state.
5. Do not mark a stage done unless the stage Definition of Done passes.
