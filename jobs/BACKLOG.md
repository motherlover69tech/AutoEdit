# AUTOEDIT Job Backlog

Statuses: `pending`, `in_progress`, `blocked`, `done`.

Do not mark a stage `done` unless its Definition of Done from `docs/source/multicam_autoedit_spec.md` has passed.

## Current next job

### Job 7.0 — Auth gate + reverse proxy

- **Status:** pending
- **Depends on:** 3.1
- **Spec stage:** 7.0
- **Goal:** require TLS/session auth before any public exposure; protect routes, add login/session handling, rate limit auth/upload, lock CORS to `PUBLIC_DOMAIN`.
- **Required tests:** `/health` public; protected API routes blocked without session; login creates httpOnly session; brute-force/rate-limit behavior covered; reviewer display name persisted for later notes.
- **Planning doc:** create before implementation: `docs/plans/stage-7.0-auth-gate-reverse-proxy.md`

### Job 3.1 — Project + DB bootstrap

- **Status:** done
- **Depends on:** none
- **Spec stage:** 3.1
- **Goal:** create the first backend foundation: database schema, project creation endpoint, manifest endpoint, project folder skeleton, and `project.json`.
- **Required tests:** migration idempotency, project creation, invalid FPS rejected, `project.json` matches DB.
- **Planning doc:** `docs/plans/stage-3.1-project-db-bootstrap.md`
- **Latest local test:** `env -u VIRTUAL_ENV uv run pytest -q` → `17 passed, 1 skipped`.
- **Latest MySQL gate:** `./scripts/mysql-tunnel.sh` + `./scripts/test-mysql-unraid.sh` → `1 passed`; full suite with `AUTOEDIT_MYSQL_TEST_URL` → `18 passed`.

## Stage backlog

| Job | Stage | Status | Depends on | Output |
| --- | --- | --- | --- | --- |
| 3.1 | Project + DB bootstrap | done | none | schema, `POST /projects`, `GET /projects/:id`, project skeleton; MySQL gate passed |
| 7.0 | Auth gate + reverse proxy | pending | 3.1 | TLS proxy, auth/session, rate limits, CORS |
| 3.2 | Chunked resumable upload | pending | 3.1 | resumable chunk upload + SHA verification |
| 3.3 | Probe & channel mapping | pending | 3.2 | ffprobe metadata, angle rows, speaker channel mapping |
| 3.4 | Channel extraction + audio sync | pending | 3.3 | speaker WAVs, cross-correlation sync offsets |
| 3.5 | Main proxy normalisation | pending | 3.3 | silent 720p short-GOP proxies |
| 3.5b | Low-bitrate remote proxy tier | pending | 3.5 | silent 360p / low-bandwidth proxies |
| 3.6 | Range-request media streaming | pending | 3.5, 7.0 | authenticated `206 Partial Content` media streaming |
| 4.1 | Loudness envelope | pending | 3.4 | `audio/loudness.json` |
| 4.2 | Noise floor & threshold | pending | 4.1 | floor/threshold values, override support |
| 4.3 | Interval construction | pending | 4.2 | `speaking_intervals` |
| 4.4 | Derived activity timeline | pending | 4.3 | contiguous who-is-active timeline |
| 4.6 | Program audio mixdown | pending | 3.4 | browser-playable `audio/program.m4a` |
| 6.1 | Core cut algorithm | pending | 4.4, CDL contract | deterministic rough-cut CDL |
| 6.2 | Anti-jitter & periodic wide | pending | 6.1 | polished cut rules |
| 5.1 | Transcription | pending | 3.4 | per-speaker transcript segments |
| 5.2 | Topic segmentation | pending | 5.1 | non-overlapping topic spans |
| 5.3 | Conciseness grading | pending | 5.2 | reproducible scores + metrics |
| 5.5 | Report output | pending | 5.3, 4.4 | `transcript/summary.json` |
| 7.1 | Player engine | pending | 3.5/3.5b/3.6, 4.6, 6.1 | audio-master multicam playback |
| 7.2 | Metadata timeline & navigation | pending | 7.1, 5.5, 6.1 | timeline lanes, topic/note seek |
| 7.3 | LUT application | pending | 7.1 | WebGL `.cube` LUT preview |
| 7.4 | Notes | pending | 7.0, 7.2 | multi-author timestamped notes |
| 8.1 | CDL validator | pending | CDL contract, 6.1 | strict validator with precise errors |
| 8.2 | FCPXML writer | pending | 8.1 | Resolve-populated FCPXML export |
| 6.3 | Sub-edit generation | pending | 6.1, 5.5 | themed/social/manual cut versions |
| 9.1 | Natural-language sub-edit requests | pending | 6.3 | LLM intent parser + generated cuts |
| 9.2 | YouTube title generator | pending | 5.5 | grouped JSON title suggestions |
| 8.3 | OTIO fallback | pending | 8.1 | optional fallback export path |

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
