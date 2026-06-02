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

- Source docs copied into this workspace.
- Handoff/project planning docs created.
- No app code, Docker setup, DB schema, migrations, API, or frontend exists yet.

## Immediate next job

Implement **Stage 3.1 — Project + DB bootstrap** from the spec.

Required outputs for 3.1:

- Migrations for all tables in spec Section 2.2.
- `POST /projects` accepting `name`, `fps_num`, `fps_den`.
- `GET /projects/:id` returning the manifest.
- On project creation: create DB row, `/data/<id>/` skeleton, and `project.json` mirroring DB.
- Invalid FPS rejected with HTTP 400.
- Migrations idempotent.
- Tests proving all of the above.

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
