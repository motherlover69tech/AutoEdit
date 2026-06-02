# AUTOEDIT

Self-hosted multicam auto-edit platform for three-angle interview footage.

## Start here for every new AI session

1. Read `AI_HANDOFF.md`.
2. Read the source documents:
   - `docs/source/multicam_autoedit_spec.md`
   - `docs/source/multicam_ui_style_guide.html`
3. Check `jobs/BACKLOG.md` for the next stage-gated job.
4. Check `docs/plans/TESTING_STRATEGY.md` before implementing or changing code.
5. After any meaningful work, update `AI_HANDOFF.md`, `jobs/BACKLOG.md`, and any relevant test plan so the next session can resume.

## Non-negotiable project rules

- Stage-gated build: do not start a stage until its dependencies are marked done.
- Honour the shared contracts in spec Section 2 exactly, especially:
  - storage layout
  - MySQL schema
  - env/config parameters
  - Cut Decision List / CDL contract
- All media times are integer milliseconds on the synced master timeline.
- Every stage ends with passing tests or an explicitly documented manual gate.
- Operator-tunable values must be env vars or per-project config, never hardcoded.
- Remote/public exposure requires TLS, auth, rate limiting, CORS/origin checks, and authenticated Range-aware media streaming.
- Player performance and sync are core risks: proxy playback only, program audio as master clock, drift correction.
- Export is not done until FCPXML opens populated in DaVinci Resolve.

## Current status

- Source spec and UI guide imported into `docs/source/`.
- No application code has been created yet.
- Next implementation stage: **Stage 3.1 — Project + DB bootstrap**.

## Expected deployment target

- Host: Unraid + Docker.
- Data root default from spec: `/mnt/user/automulticam` mounted into containers as `/data`.
- Existing external dependencies may include MySQL and local LLM/Ollama; all connection details must remain configurable via env.
