# Stage 3.1 — Project + DB Bootstrap Implementation Plan

> **For Hermes:** Use subagent-driven-development skill to implement this plan task-by-task once the backend stack choice is confirmed or selected.

**Goal:** Build the first runnable backend foundation: schema migrations, project creation, project manifest retrieval, project directory skeleton, and initial tests.

**Architecture:** Use a Docker-friendly backend with a small API service, a migration layer, and a filesystem abstraction rooted at `DATA_ROOT`. The project record is stored in MySQL and mirrored to `/data/<project_id>/project.json` for portability.

**Tech Stack:** Not chosen yet. Candidate stacks: Python/FastAPI + SQLAlchemy/Alembic + pytest, or Node/Fastify + Knex/Prisma + Vitest. Record the choice in `AI_HANDOFF.md` before coding.

---

## Acceptance criteria from spec

- Migrations run clean on an empty DB and are idempotent.
- `POST /projects` creates a ULID project row and `/data/<id>/` skeleton dirs.
- `GET /projects/:id` returns the manifest.
- Invalid FPS is rejected with HTTP 400.
- `project.json` on disk matches the DB row.

## Implementation tasks

### Task 1: Choose backend stack and scaffold project

**Objective:** Create a minimal runnable API skeleton and document the decision.

**Files:**
- Create: backend source tree after stack choice.
- Modify: `AI_HANDOFF.md`
- Create: `.env.example`

**Steps:**
1. Choose Python/FastAPI or Node/Fastify based on simplicity and long-term fit.
2. Create minimal API app with `/health`.
3. Add dependency files.
4. Add `.env.example` with at least `DATA_ROOT`, `DB_HOST`, `DB_PORT`, `DB_NAME`, `DB_USER`, `DB_PASSWORD`.
5. Run the app locally and hit `/health`.
6. Update `AI_HANDOFF.md` with the stack choice.

### Task 2: Add database migration for Section 2.2 schema

**Objective:** Create all required tables from the spec.

**Files:**
- Create migration files according to chosen stack.
- Create schema/model definitions if applicable.

**Steps:**
1. Encode all Section 2.2 tables.
2. Preserve enum values exactly.
3. Use `CHAR(26)` for ULID ids where specified.
4. Use `BIGINT` integer milliseconds for media times.
5. Run migration against an empty test DB.
6. Re-run migration to prove idempotency or migration no-op behavior.

### Task 3: Implement filesystem project skeleton helper

**Objective:** Create the exact `/data/<project_id>/` tree from spec Section 2.1.

**Files:**
- Create helper module for project paths.
- Test helper module.

**Required directories:**
- `source/`
- `proxy/`
- `proxy_low/`
- `audio/`
- `transcript/`
- `edit/`
- `luts/`

**Tests:**
- Given a project id and temp `DATA_ROOT`, all directories are created.
- Path helper rejects traversal-like project ids.

### Task 4: Implement project validation and manifest model

**Objective:** Validate project create inputs and define `project.json` shape.

**Rules:**
- `name` required and non-empty.
- `fps_num` and `fps_den` required positive integers.
- Defaults: `status='created'`, `timeline_origin_ms=0`, `config_json={}`.

**Tests:**
- Valid input accepted.
- `fps_num=0`, `fps_den=0`, missing, and non-integer FPS rejected.

### Task 5: Implement `POST /projects`

**Objective:** Create project DB row, filesystem skeleton, and `project.json` atomically enough for stage 3.1.

**API:**

```http
POST /projects
Content-Type: application/json

{ "name": "Interview", "fps_num": 24000, "fps_den": 1001 }
```

**Expected:**

```json
{
  "id": "01...26 chars...",
  "name": "Interview",
  "status": "created",
  "fps_num": 24000,
  "fps_den": 1001,
  "timeline_origin_ms": 0,
  "config_json": {}
}
```

**Tests:**
- Response includes valid ULID.
- DB row exists.
- Directory tree exists.
- `project.json` exists and matches DB row.

### Task 6: Implement `GET /projects/:id`

**Objective:** Return the project manifest.

**Tests:**
- Existing project returns expected manifest.
- Missing project returns 404.
- Invalid id shape returns 400 or 404 consistently, as documented.

### Task 7: Add integration test and update docs

**Objective:** Verify the whole Stage 3.1 flow and leave handoff current.

**Steps:**
1. Run all tests.
2. Record exact command and result in `docs/plans/TESTING_STRATEGY.md`.
3. If passing, update `jobs/BACKLOG.md` status for 3.1 to `done`.
4. Update `AI_HANDOFF.md` current state and immediate next job.
5. Commit if git is initialized.

## Do not proceed to Stage 7.0 or 3.2 until this plan's acceptance criteria pass.
