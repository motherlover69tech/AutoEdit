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

MySQL integration commands:

```bash
# terminal 1: open tunnel to Unraid-local MySQL
./scripts/mysql-tunnel.sh

# terminal 2: run MySQL gate using remote .env credentials
./scripts/test-mysql-unraid.sh
```

Latest temporary-dev-MySQL result: `1 passed in 1.58s`.

Latest full suite with temporary-dev-MySQL `AUTOEDIT_MYSQL_TEST_URL` set: `18 passed in 1.77s`.

Canonical deployment DB target is Peter's existing MySQL server. When credentials are available, re-run the MySQL integration gate against the existing server and record the result here.

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

Remaining deployment DB gate:

- Pending: verify against Peter's existing MySQL server. The temporary Unraid `autoedit-mysql` container only proved MySQL compatibility and is not the canonical AUTOEDIT DB.

## Rule for future AI sessions

Before marking any job done, update this file with the exact command(s) used and the observed result. If a test cannot yet be automated, document the manual gate and why.
