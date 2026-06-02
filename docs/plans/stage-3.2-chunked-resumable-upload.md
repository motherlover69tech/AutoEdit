# Stage 3.2 Chunked Resumable Upload Implementation Plan

> **For Hermes:** Use test-driven-development. Upload/media routes must remain behind the Stage 7.0 auth middleware.

**Goal:** Upload large camera files to `source/` without timeout failures, with resume support, SHA-256 verification, and path confinement.

**Architecture:** Add a small upload service that creates an upload session per source angle. Session metadata and chunk part files live under `/data/<project_id>/.uploads/<upload_id>/`. Chunks are written as indexed part files so interrupted/out-of-order uploads can resume by asking for the highest contiguous chunk. Completion assembles to a temporary file, validates byte count and SHA-256, atomically moves to `source/<filename>`, removes the upload temp dir, and creates an `angles` row. The upload endpoints are ordinary protected API routes; tests explicitly log in before using them.

**API shape:**

- `POST /projects/{project_id}/uploads`
  - Body: `{filename, label, role, total_bytes, total_chunks}`
  - Returns: `{upload_id, project_id, filename, highest_contiguous_chunk}`
- `POST /upload/{upload_id}/chunk/{index}`
  - Raw request body bytes for the chunk.
  - Returns current `{highest_contiguous_chunk}`.
- `GET /upload/{upload_id}`
  - Returns session status + `{highest_contiguous_chunk}` for resume.
- `POST /upload/{upload_id}/complete`
  - Body: `{sha256, total_bytes}`
  - On success: moves to `source/`, inserts `angles` row, returns angle metadata.

## Tests first

Create `tests/test_uploads_api.py` covering:

1. Upload routes require auth when auth is enabled.
2. Start upload rejects missing project.
3. Start upload rejects filename path traversal (`../evil.mp4`, nested paths, empty names).
4. Chunk upload rejects invalid/traversal `upload_id` and negative/out-of-range chunk index.
5. Interrupted upload can resume: upload chunk 0 and 2, status reports highest contiguous `0`; upload chunk 1, status reports `2`; complete validates SHA and writes exact source file bytes.
6. Completing with wrong SHA rejects and removes the temp upload dir.
7. Three uploads to one project complete and create three `angles` rows.

## Implementation files

- Create: `src/autoedit/uploads.py`
- Modify: `src/autoedit/api.py`
- Modify: `src/autoedit/project_paths.py` if shared path validation helpers are useful.
- Add docs/results to `AI_HANDOFF.md`, `jobs/BACKLOG.md`, and `docs/plans/TESTING_STRATEGY.md` before final commit.

## Verification commands

```bash
env -u VIRTUAL_ENV uv run pytest tests/test_uploads_api.py -q
env -u VIRTUAL_ENV uv run pytest -q
```

If time permits, also re-run the existing MySQL-enabled suite with `DB_*` env vars.

## Stage status rule

Mark Stage 3.2 `done` only after automated tests pass and the wrong-SHA cleanup/path traversal/concurrent-three-file requirements are covered. The resilience test is simulated by skipping a chunk and resuming via status rather than killing a real TCP connection.
