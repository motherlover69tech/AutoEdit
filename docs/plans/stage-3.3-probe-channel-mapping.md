# Stage 3.3 Probe & Channel Mapping Implementation Plan

> **For Hermes:** Use test-driven-development. Keep all project/source routes behind the Stage 7.0 auth middleware when auth is enabled.

**Goal:** Probe uploaded source angle files with `ffprobe`, persist media metadata on `angles`, and let the operator map speaker channels for later extraction/sync.

**Depends on:** Stage 3.2 chunked upload.

**Source spec:** `docs/source/multicam_autoedit_spec.md`, Stage 3.3.

## Required behavior

- Run `ffprobe -show_streams -show_format -of json` per uploaded source file.
- Fill existing `angles` metadata fields:
  - width
  - height
  - src_fps_num
  - src_fps_den
  - duration_ms
  - vcodec
- Soft-warn if input is not 1080p H.264. The warning should not block when a future force/override path is present.
- Add channel mapping endpoint for the operator:
  - source angle id
  - channel index
  - speaker label
  - speaker role
  - optional manual sync nudge in integer milliseconds per angle
- Mapping should create exactly the two intended `audio_channels` rows for the speaker channels.
- Store all times as integer milliseconds.

## Suggested API shape

Keep this flexible if implementation discovers a cleaner contract, but preserve tests around behavior:

- `POST /projects/{project_id}/angles/{angle_id}/probe`
  - probes the uploaded source file for that angle
  - updates the `angles` row
  - returns metadata + warnings
- `POST /projects/{project_id}/channels`
  - body contains channel mappings for one or more angles
  - creates/updates `audio_channels` rows
  - records manual sync nudge either on `angles.sync_offset_ms` or a clearly documented field/structure if a separate nudge concept is needed

## Tests first

Create `tests/test_probe_channel_mapping.py` covering:

1. Probe route requires auth when auth is enabled.
2. Missing project/angle returns `404`.
3. Probe rejects angle source paths outside `source/` / outside `DATA_ROOT`.
4. `ffprobe` JSON fixture updates the `angles` row with correct codec/dimensions/duration/fps.
5. Non-1080p or non-H.264 fixture returns a warning but still records metadata.
6. Channel mapping creates exactly two `audio_channels` rows with correct `source_angle_id`, `channel_index`, `speaker_label`, and `role`.
7. Manual sync nudge is stored as integer milliseconds.
8. Invalid channel mapping payloads are rejected with `400`.

## Fixture strategy

Prefer one of these in order:

1. Tiny generated media fixtures in a test temp dir using `ffmpeg` if available.
2. Static `ffprobe` JSON fixtures under `tests/fixtures/ffprobe/` with the probe runner mocked.
3. A documented external fixture path if real media is too large.

Do not commit large source footage.

## Implementation files likely needed

- Create: `src/autoedit/probe.py`
- Modify: `src/autoedit/api.py`
- Possibly add small helpers in `src/autoedit/uploads.py` or `src/autoedit/project_paths.py` for source-path confinement.
- Create tests: `tests/test_probe_channel_mapping.py`
- Add fixtures: `tests/fixtures/ffprobe/*.json` if mocking `ffprobe`.

## Verification commands

```bash
env -u VIRTUAL_ENV uv run pytest tests/test_probe_channel_mapping.py -q
env -u VIRTUAL_ENV uv run pytest -q
```

If real `ffmpeg`/`ffprobe` is used, also document the installed versions:

```bash
ffprobe -version | head -1
ffmpeg -version | head -1
```

## Definition of done

- `angles` rows have correct fps/codec/dimensions/duration for test clips or fixtures.
- Channel mapping creates the two `audio_channels` rows with correct angle/channel/speaker data.
- Non-1080p input produces a warning but proceeds when allowed.
- Local full suite passes.
- Update `AI_HANDOFF.md`, `jobs/BACKLOG.md`, and `docs/plans/TESTING_STRATEGY.md` before committing.
