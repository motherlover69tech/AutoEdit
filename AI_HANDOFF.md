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
- **Stage 3.1 — Project + DB bootstrap is done.**
  - DB schema tables for spec Section 2.2.
  - Idempotent `run_migrations(engine)` helper using SQLAlchemy metadata.
  - `POST /projects` and `GET /projects/:id`.
  - `DATA_ROOT` project skeleton creation.
  - Atomic `project.json` manifest write.
  - Strict invalid-FPS validation returning HTTP 400.
  - Local SQLite-backed tests pass.
  - Real MySQL 8 integration test passes through the Unraid dev DB.
- Dev MySQL is deployed on Unraid:
  - Compose path: `/mnt/user/appdata/autoedit-mysql/compose.yaml`
  - Container: `autoedit-mysql`
  - Host binding: `127.0.0.1:3307:3306` on Unraid only.
  - Use `./scripts/mysql-tunnel.sh`, then `./scripts/test-mysql-unraid.sh`.
- No frontend exists yet.

## Immediate next job

Proceed to **Stage 7.0 — Auth gate + reverse proxy** before upload/media exposure:

- Plan and implement session auth, password hashing/shared-password minimum, reviewer display name, protected routes, rate limiting, and CORS/origin checks.
- Keep `/health` public; all other routes should require auth once 7.0 is active.
- Add tests proving unauthenticated access is blocked and login/session works.

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
