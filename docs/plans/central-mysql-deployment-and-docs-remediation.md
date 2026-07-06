# Central MySQL Deployment and Documentation Remediation Plan

> **For Hermes:** Use stage-gated-development and test-driven-development. This is a corrective/supporting infrastructure job, not a new product feature. Keep secrets out of repo. Do not reintroduce a local AUTOEDIT MySQL service.

**Job name:** `CONFIG-REVIEW`

**Goal:** Make AUTOEDIT's deployment/docs match reality: Peter's central MySQL is canonical, Nginx Proxy Manager is the TLS boundary, env handling is explicit, and planned/mock features are not documented as production-complete.

**Architecture:** Keep the app as a single FastAPI container behind NPM on Unraid, using `DB_*` variables to connect to Peter's existing MySQL server at `192.168.50.50:3306`. Remove ambiguity around the historical `autoedit-mysql` dev container. Separate implemented behavior from placeholders/future work in README, handoff, backlog, deployment docs, and tests.

**Tech Stack:** Python 3.12, FastAPI, SQLAlchemy Core, Docker Compose on Unraid, Nginx Proxy Manager, MySQL 8, Ollama.

---

## Non-negotiable decisions

- **Canonical DB:** Peter's existing central MySQL server via `DB_HOST=192.168.50.50`, `DB_PORT=3306`, `DB_NAME=autoedit`, `DB_USER=autoedit`, `DB_PASSWORD=<secret>`.
- **Do not use:** the historical `autoedit-mysql` container except as a documented old compatibility proof.
- **Deployment proxy:** Nginx Proxy Manager terminates TLS for `ingest.peteflix.uk`; do not document Caddy as the active path unless the deployment is intentionally changed.
- **Env handling:** active compose must pass required environment variables explicitly. Do not rely on `env_file` as the only source; this deployment has previously failed that way.
- **Sync:** never silently zero a low-confidence sync result and call it done. Fail the sync stage with a useful quality/error report.
- **Truth in docs:** distinguish production behavior from mocks/templates/in-process placeholders.

---

## Execution status from local remediation pass

CONFIG-REVIEW is complete locally and on the Unraid deployment host.

Completed locally:

1. `docker-compose.yml` now defines a single host-networked `app` service behind NPM and explicitly passes central MySQL `DB_*` variables; it no longer relies on `env_file` and does not define a MySQL/MariaDB service.
2. `.env.example` documents secret/operator overrides without real credentials and uses live config names.
3. `docker-compose.prod.yml` is labelled deprecated/non-canonical for Peter's Unraid deployment.
4. `docs/DEPLOYMENT.md` is rewritten around NPM (`ingest.peteflix.uk` → `192.168.50.50:8010`) and central MySQL.
5. Docs/source references were standardized on `OLLAMA_BASE_URL` and `UPLOAD_MAX_CHUNK_BYTES`.
6. Mock/template/in-process areas are labelled accurately: transcription, diarization, topic fallback, YouTube titles, and pipeline worker model.
7. Low-confidence automatic audio sync now raises a diagnostic error instead of silently zeroing offsets; the API returns `422`, marks the project `error`, and records a pipeline error.
8. Local source-level Compose sanity passed: exactly one `app` service, `network_mode: host`, no MySQL/MariaDB service, no `env_file`, explicit central `DB_*`, `OLLAMA_BASE_URL`, `UPLOAD_MAX_CHUNK_BYTES`, and secure cookies.

Verification completed locally:

- `env -u VIRTUAL_ENV uv run pytest tests/test_audio_sync.py -q` → `18 passed`.
- `env -u VIRTUAL_ENV uv run pytest -q` → `436 passed, 2 skipped`.
- `env -u VIRTUAL_ENV uv run python -m compileall -q src tests` → passed.
- `git diff --check` → passed.

Deployment-host verification completed:

- Remote active compose directory: `/mnt/user/appdata/autoedit`.
- Remote backup before deploy: `/mnt/user/appdata/autoedit-backups/config-review-20260609_221906`.
- `docker compose config` on Unraid rendered one `app` service, no MySQL/MariaDB service, `network_mode: host`, explicit central `DB_*`, `SESSION_COOKIE_SECURE=true`, `WHISPER_BACKEND=mock`, and `DIARIZE_BACKEND=mock`.
- Central MySQL `autoedit` user password was rotated without printing the new value; login to `192.168.50.50:3306` as `autoedit` tested successfully.
- App recreated with the central DB env and started successfully.
- Public NPM checks passed: `/health` → 200, `/projects` without session → 401, `/auth/login` → 204 with `HttpOnly; SameSite=lax; Secure`, `/data/` → 401, HTTP → HTTPS redirect → 301.
- Historical `autoedit-mysql` container was stopped, not deleted; app health remained 200 afterward.

Original review findings preserved for context:

1. `README.md`, `AI_HANDOFF.md`, and `docs/plans/EXISTING_MYSQL_REQUIREMENTS.md` correctly say central MySQL is canonical.
2. Transcription is currently `mock_transcribe()` only.
3. Diarization is currently `mock_diarize()` only.
4. Topic segmentation can call Ollama, but falls back silently to mock on LLM failure.
5. YouTube title generation is template-based, not LLM-generated.
6. Pipeline processing runs in an in-process Python thread, not Redis/worker queue.

---

## Task 1: Canonicalize active Docker Compose deployment

**Objective:** Ensure the active compose file connects to central MySQL and does not depend on the historical DB container or fragile `env_file` behavior.

**Files:**
- Modify: `docker-compose.yml`
- Possibly remove/deprecate: `docker-compose.prod.yml`
- Modify: `.env.example`

**Steps:**

1. Update `docker-compose.yml` to pass all runtime-critical env vars explicitly under `services.app.environment`:
   - `DATA_ROOT=/data`
   - `PORT=8010`
   - `PUBLIC_DOMAIN=ingest.peteflix.uk`
   - `ALLOWED_ORIGINS=https://ingest.peteflix.uk,http://192.168.50.50:8010`
   - `AUTH_ENABLED=true`
   - `SESSION_SECRET=${SESSION_SECRET}`
   - `OPERATOR_PASSWORD=${OPERATOR_PASSWORD}`
   - `OPERATOR_USERNAME=${OPERATOR_USERNAME:-peter}`
   - `OPERATOR_DISPLAY_NAME=${OPERATOR_DISPLAY_NAME:-Peter}`
   - `SESSION_COOKIE_SECURE=true`
   - `DB_HOST=192.168.50.50`
   - `DB_PORT=3306`
   - `DB_NAME=autoedit`
   - `DB_USER=autoedit`
   - `DB_PASSWORD=${DB_PASSWORD}`
   - `OLLAMA_BASE_URL=http://192.168.50.50:11434`
   - `LLM_MODEL=<chosen deployed Ollama alias>`
   - `WHISPER_BACKEND=mock` until real faster-whisper is implemented, or implement faster-whisper first and set `faster-whisper` only after tests pass.
   - `UPLOAD_MAX_CHUNK_BYTES=67108864`
   - `PROXY_ENCODER=h264_qsv` only if QSV is verified in the rebuilt container; otherwise keep `libx264` with a clear comment.
2. Keep `/dev/dri:/dev/dri` device mapping for QSV.
3. Do **not** add a `mysql:` service.
4. Decide whether `docker-compose.prod.yml` is still needed. If kept, add a top comment saying it is deprecated/non-canonical and should not be used for Peter's Unraid deployment.
5. Update `.env.example` to document only secret/operator-overridable values and the canonical non-secret defaults.

**Verification:**

```bash
docker compose config
```

Expected:
- Exactly one service: `app`.
- No MySQL/MariaDB service.
- `DB_HOST: 192.168.50.50` visible in rendered config.
- `DB_PASSWORD` is sourced from environment and not committed with a real value.

---

## Task 2: Rewrite deployment docs for NPM + central MySQL

**Objective:** Make the deployment runbook match the actual target.

**Files:**
- Modify: `docs/DEPLOYMENT.md`
- Modify: `README.md`
- Modify: `AI_HANDOFF.md`

**Steps:**

1. Replace Caddy architecture with Nginx Proxy Manager:
   - Browser → NPM TLS at `ingest.peteflix.uk` → app on `192.168.50.50:8010` / host network.
2. State clearly that MySQL is external/central and reached at `192.168.50.50:3306` using `DB_*`.
3. Remove “copy `.env.example` and rely on env_file” language. Prefer:
   - export required secrets in the shell or Unraid template;
   - run `docker compose up -d --build`;
   - verify rendered compose/config before starting.
4. Add a warning box:
   - The old `autoedit-mysql` container is historical only.
   - Do not start it for production.
5. Update latest local test count to `434 passed, 2 skipped` if still true when this task is run.

**Verification:**

```bash
env -u VIRTUAL_ENV uv run pytest -q
python -m compileall -q src tests
```

Expected: full suite and compile check pass.

---

## Task 3: Standardize env variable names

**Objective:** Remove ignored config names from docs/examples, or add backward-compatible aliases with tests.

**Files:**
- Modify: `src/autoedit/config.py` if adding aliases
- Modify: `.env.example`
- Modify: `docs/source/multicam_autoedit_spec.md` only if intentionally updating the source contract
- Modify: `docs/DEPLOYMENT.md`, `README.md`, `AI_HANDOFF.md`, `jobs/BACKLOG.md`
- Test: existing config tests or add `tests/test_config.py`

**Current code names:**

- `OLLAMA_BASE_URL`
- `UPLOAD_MAX_CHUNK_BYTES`

**Conflicting docs/example names:**

- `LLM_BASE_URL`
- `UPLOAD_CHUNK_MB`

**Preferred fix:**

- Use `OLLAMA_BASE_URL` and `UPLOAD_MAX_CHUNK_BYTES` everywhere in deployment docs/examples.
- If backward compatibility is desired, add aliases in `Settings` and tests proving both names work, with the canonical name taking precedence.

**Verification:**

```bash
env -u VIRTUAL_ENV uv run pytest tests/test_review_hardening.py -q
env -u VIRTUAL_ENV uv run pytest -q
```

---

## Task 4: Fix sync low-confidence behavior

**Objective:** Low-confidence automatic sync must fail loudly instead of using a silent zero offset.

**Files:**
- Modify: `src/autoedit/audio.py`
- Modify: `src/autoedit/api.py` sync endpoint handling if needed
- Test: `tests/test_audio_sync.py`
- Update docs: `README.md`, `AI_HANDOFF.md`, `jobs/BACKLOG.md`, `docs/plans/stage-3.4-channel-extraction-audio-sync.md`

**Required behavior:**

- `find_sync_offset()` keeps returning `(offset_ms, quality)`.
- `compute_sync_offsets()` must not replace low-quality offsets with `0`.
- If quality is below threshold, raise a domain-specific error such as `SyncQualityError(angle_id, quality, threshold)`.
- The API/pipeline should mark the sync stage/project as `error` and expose a useful message in `pipeline.errors.json` / logs.
- Manual sync nudges must not be documented as the normal solution.

**Tests to add/update:**

1. Low-quality correlation raises instead of returning zero.
2. API `/projects/{id}/sync` returns a clear error for low-confidence sync.
3. Existing known-lag and transient/clap tests still pass.
4. No test should assert that quality failure becomes offset `0`.

**Verification:**

```bash
env -u VIRTUAL_ENV uv run pytest tests/test_audio_sync.py -q
env -u VIRTUAL_ENV uv run pytest -q
```

---

## Task 5: Correct feature status claims

**Objective:** Stop marking mock/template/future systems as production-complete.

**Files:**
- Modify: `README.md`
- Modify: `AI_HANDOFF.md`
- Modify: `jobs/BACKLOG.md`
- Modify: `docs/plans/TESTING_STRATEGY.md`
- Possibly add future plans under `docs/plans/`

**Status corrections:**

- Transcription: currently mock-only. Mark production `faster-whisper` as pending unless implemented.
- Diarization: currently mock-only and optional for normal stereo channel-mapped interviews.
- Topic segmentation: Ollama path exists but silently falls back to mock; document as degraded/fallback behavior.
- YouTube titles: template-based, not LLM generation.
- Pipeline runner: in-process background thread, not Redis/worker queue.
- QSV: mark as deployed only after real-container encode verification; otherwise say QSV code path exists and `/dev/dri` is passed through.

**Verification:**

- Docs make it clear what is implemented, mocked, manually verified, and future.
- `jobs/BACKLOG.md` includes follow-up jobs for real transcription/LLM/worker work if Peter still wants them.

---

## Task 6: Add deployment verification checklist for central MySQL

**Objective:** Make central-DB verification repeatable without storing secrets.

**Files:**
- Modify: `docs/plans/EXISTING_MYSQL_REQUIREMENTS.md`
- Modify: `docs/DEPLOYMENT.md`
- Modify: `docs/plans/TESTING_STRATEGY.md`

**Checklist:**

```bash
DB_HOST=192.168.50.50 \
DB_PORT=3306 \
DB_NAME=autoedit \
DB_USER=autoedit \
DB_PASSWORD='<from secret store>' \
  env -u VIRTUAL_ENV uv run pytest tests/test_mysql_integration.py -q
```

Then, if safe against the target DB:

```bash
DB_HOST=192.168.50.50 \
DB_PORT=3306 \
DB_NAME=autoedit \
DB_USER=autoedit \
DB_PASSWORD='<from secret store>' \
  env -u VIRTUAL_ENV uv run pytest -q
```

Live app checks:

```bash
curl -i https://ingest.peteflix.uk/health
curl -i https://ingest.peteflix.uk/projects
curl -i -X POST https://ingest.peteflix.uk/auth/login \
  -H 'Content-Type: application/json' \
  -d '{"username":"peter","password":"<secret>","display_name":"Peter"}'
```

Expected:
- `/health` is public and returns `200`.
- `/projects` returns `401` without a cookie.
- Login returns `204` and `Set-Cookie`.
- App logs show successful MySQL connection to central server, not a local DB container.

---

## Task 7: Final handoff update

**Objective:** Leave future sessions with a truthful next step and no stale counts.

**Files:**
- Modify: `README.md`
- Modify: `AI_HANDOFF.md`
- Modify: `jobs/BACKLOG.md`
- Modify: `docs/plans/TESTING_STRATEGY.md`

**Steps:**

1. Record exact final test result.
2. Record whether central MySQL live gate passed.
3. Record whether compose was deployed to Unraid.
4. Keep this remediation job `in_progress` until all docs/config/sync behavior are corrected and verified.
5. Mark as `done` only after:
   - compose uses explicit central-DB env vars;
   - deployment docs are NPM-based;
   - env var names are consistent;
   - sync low-confidence zero fallback is removed;
   - feature status claims are truthful;
   - local full suite passes.

**Verification:**

```bash
git diff -- README.md AI_HANDOFF.md jobs/BACKLOG.md docs/DEPLOYMENT.md docs/plans/TESTING_STRATEGY.md docs/plans/central-mysql-deployment-and-docs-remediation.md
```

Expected: diff clearly documents the corrective job and does not include real credentials.
