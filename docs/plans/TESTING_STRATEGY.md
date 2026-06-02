# AUTOEDIT Testing Strategy

This plan expands Appendix D of the source spec. Every implementation stage must add or update tests here as the project structure becomes concrete.

## Test categories

### 1. Unit tests

Use for pure or mostly-pure logic:

- FPS/time conversion helpers.
- ULID/id validation.
- Config loading and env defaults.
- CDL generation.
- CDL validation.
- Topic-span stitching/validation.
- FCPXML rational-time formatting.
- VAD interval merge/drop logic.

Expected command once code exists: record exact test command here, e.g. `pytest` or `npm test`.

### 2. Contract tests

These guard integration boundaries:

- Database schema columns/types/enums match spec Section 2.2.
- Project manifest `project.json` mirrors expected DB fields.
- CDL fixtures satisfy spec Section 2.4 and are accepted by player/exporter code.
- API response shapes match Appendix B.
- Media times are integer milliseconds only.

### 3. Golden-file media tests

Keep a tiny fixture set once available:

```text
tests/fixtures/golden_30s/
  source/
    angleA.mp4
    angleB.mp4
    angleC.mp4
  expected/
    probe.json
    sync_offsets.json
    cdl.json
    export.fcpxml
```

Fixture requirements:

- Around 30 seconds.
- Three camera angles.
- Clear clapper/transient near the start.
- Two isolated speaker channels if possible.
- Small enough to keep in repo, or documented external download if too large.

Golden tests should cover:

- ffprobe metadata extraction.
- Audio sync within ±1 frame.
- Proxy generation/keyframe cadence.
- Program audio alignment.
- Transcription offset math using known words if available.
- FCPXML generation against stable expected structure.

### 4. Integration smoke test

Once the backend exists, maintain a scripted smoke path:

1. Start test stack.
2. Run migrations.
3. Create project.
4. Upload or seed fixture angles.
5. Map channels.
6. Run process pipeline.
7. Assert project reaches `ready`.
8. Fetch CDL.
9. Validate CDL.
10. Export FCPXML.
11. Validate XML and expected references.

Expected command should eventually be documented here, e.g.:

```bash
./scripts/smoke-test.sh
```

### 5. Security tests

Required before public exposure:

- Auth required on all non-health/ACME routes.
- Brute-force lockout/rate limit triggers.
- Upload path traversal rejected.
- Note body XSS sanitized on render.
- Media endpoint returns `401`/redirect without session.
- Media endpoint honours `Range` with `206 Partial Content` when authenticated.
- CORS/origin checks reject unexpected origins.

### 6. Manual gates

Some gates are explicitly manual and must be recorded in stage notes:

- Review player has no visible stutter at switches.
- Forced angle stays within one frame of audio on clapper test.
- LUT visibly changes the image and does not drop frames on target hardware.
- FCPXML opens populated in DaVinci Resolve.
- Cuts in Resolve land on the same frames as player preview.

## Test command

Current local command:

```bash
env -u VIRTUAL_ENV uv run pytest -q
```

Latest local result without MySQL URL: `17 passed, 1 skipped`.

Latest local result after Stage 3.2 chunked upload: `35 passed, 1 skipped`.

Canonical existing-MySQL integration commands:

```bash
# Preferred: provide DB_* variables directly so special characters in DB_PASSWORD
# do not need URL encoding.
DB_HOST=192.168.50.50 \
DB_PORT=3306 \
DB_NAME=autoedit \
DB_USER=autoedit \
DB_PASSWORD='***' \
  env -u VIRTUAL_ENV uv run pytest tests/test_mysql_integration.py -q

DB_HOST=192.168.50.50 \
DB_PORT=3306 \
DB_NAME=autoedit \
DB_USER=autoedit \
DB_PASSWORD='***' \
  env -u VIRTUAL_ENV uv run pytest -q
```

Latest canonical existing-MySQL result after Stage 7.0 backend auth gate: `25 passed in 1.90s`.

Security tests added in `tests/test_auth_gate.py` cover:

- `/health` public while auth is enabled.
- ACME challenge path bypasses auth.
- Project routes require a session.
- Login sets an httpOnly session cookie.
- Authenticated project creation works.
- `GET /auth/me` returns reviewer display name from the session.
- Failed login lockout returns `429` after threshold.
- Unexpected `Origin` returns `403`; configured `PUBLIC_DOMAIN` origin passes.

Upload tests added in `tests/test_uploads_api.py` cover:

- Upload routes require auth when auth is enabled.
- Missing project returns `404`.
- Filename path traversal is rejected.
- Invalid upload ids / chunk indexes are rejected.
- Interrupted upload can resume from highest contiguous chunk.
- Complete validates byte count and SHA-256, writes exact source bytes, and inserts an `angles` row.
- Wrong SHA is rejected and temp upload files are cleaned up.
- Three uploads to one project complete and create three `angles` rows.

Latest temporary-dev-MySQL result: `1 passed in 1.58s`.

Latest full suite with temporary-dev-MySQL `AUTOEDIT_MYSQL_TEST_URL` set: `18 passed in 1.77s`.

The temporary Unraid `autoedit-mysql` container only proved MySQL compatibility and is not the canonical AUTOEDIT DB.

## Stage 3.1 initial test plan

Implemented tests for:

1. Migrations run on empty DB.
2. Migrations are idempotent when re-run.
3. `POST /projects` with valid `name`, `fps_num`, `fps_den` returns a 26-char ULID.
4. Project directory tree is created under configured `DATA_ROOT`:
   - `source/`
   - `proxy/`
   - `proxy_low/`
   - `audio/`
   - `transcript/`
   - `edit/`
   - `luts/`
5. `project.json` exists and matches the DB project row.
6. `GET /projects/:id` returns manifest data.
7. Invalid FPS values are rejected with HTTP 400:
   - `fps_num=0`
   - `fps_den=0`
   - non-integer values
   - missing values

Current coverage:

- `tests/test_migrations.py` verifies required tables are created, migration helper is idempotent, and media-time columns are integer-like.
- `tests/test_project_paths.py` verifies the spec directory tree and path-traversal/invalid-id rejection.
- `tests/test_projects_api.py` verifies `/health`, `POST /projects`, `GET /projects/:id`, manifest JSON, project skeleton creation, invalid FPS rejection, and missing-project 404.

Deployment DB gate:

- Complete: verified against Peter's existing MySQL server (`192.168.50.50:3306`, database `autoedit`, user `autoedit`, password not recorded). Full suite with DB enabled passed: `18 passed in 1.82s`.

## Rule for future AI sessions

Before marking any job done, update this file with the exact command(s) used and the observed result. If a test cannot yet be automated, document the manual gate and why.
