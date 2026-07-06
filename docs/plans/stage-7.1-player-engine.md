# Stage 7.1 Player Engine Implementation Plan

> **For Hermes:** Use test-driven-development for backend player-state endpoints and browser-state logic. Use the source spec Section 7.1 as the acceptance contract. Do not mark this stage done until the manual playback/sync gates are actually checked.

**Goal:** Build the first review-player frontend: audio-master multicam playback of an existing CDL using proxy media, with smooth automatic cuts, manual angle override, quality switching, and drift correction.

**Architecture:** Add a small static browser app served by FastAPI and a JSON `player-state` endpoint that bundles the already-generated project manifest, angle media URLs, program audio URL, rough CDL, and duration/FPS metadata. Keep program audio as the only master clock. Use two ping-pong `<video>` elements: one visible, one hidden/pre-seeked for the next clip. Videos follow `audio.currentTime`; audio never reloads during angle switches.

**Tech Stack:** Python 3.12, FastAPI `StaticFiles`/JSON routes, pytest/TestClient, plain HTML/CSS/JavaScript first. Avoid adding a frontend build pipeline unless this stage proves plain static assets are insufficient.

**Current checkpoint (2026-06-20):** Stage 7.1 is implemented and live-verified behind NPM. `GET /projects/{id}/player-state`, `GET /player/{project_id}`, `/web/index.html`, `/web/player.js`, `/web/styles.css`, `tests/test_player_state.py`, `tests/test_player_static.py`, `tests/test_player_logic_js.py`, and `tests/player_logic.test.mjs` exist. Browser playback, ping-pong switching, quality selection, manual angle override/back-to-auto, timeline labels, and LUT interaction have been verified on the live route. Current full local suite: `438 passed, 2 skipped`. Node is not installed in the current environment, so JS helper assertions skip here but will run where Node exists. Remaining Module 7 manual work is Stage 7.4 multi-author/XSS verification, not the core player engine.

---

## Current prerequisites already implemented

- Auth/session gate and origin checks are live behind NPM; Stage 7.0 is complete for the current Unraid deployment.
- Media streaming route exists: `GET /projects/{project_id}/media/{kind}/{filename}`.
- Media route is auth-protected when auth is enabled, supports Range via Starlette `FileResponse`, and serves only DB-known playback assets.
- Program audio generation exists: `POST /projects/{project_id}/program-audio` writes `audio/program.m4a`.
- Rough cut generation exists: `POST /projects/{project_id}/cut` writes `edit/cdl.json` and a `cuts.kind='rough'` row.
- Static player frontend and player-state read endpoint exist and are live-verified.

## Non-goals for Stage 7.1

- No LUT shader yet — Stage 7.3.
- No metadata/topic timeline lanes yet — Stage 7.2.
- No notes UI/API yet — Stage 7.4.
- No FCPXML export/Resolve validation — Module 8.
- No WebCodecs fallback unless the `<video>` ping-pong path measurably fails on target hardware.

## Completion gates

Automated gates:

- `env -u VIRTUAL_ENV uv run pytest -q` passes.
- New backend tests prove the player-state route returns only auth-checked, DB-known media URLs.
- New frontend logic tests or lightweight browser-state tests cover CDL clip selection, next-clip preloading decisions, drift-threshold math, and manual override state transitions.

Manual gates required before marking Stage 7.1 `done`:

- Load a project with generated `program.m4a`, proxies, and rough `cdl.json` in the browser.
- Full rough cut plays with no obvious stutter at automatic cut boundaries.
- Manual angle switch reflects within about 1–2 frames and audio does not glitch/reload.
- Forced angle matches program audio within 1 frame on a clapper/sync test.
- Seeking to arbitrary timeline positions selects the correct angle/time; local target is <200 ms where practical.
- Throttled/poor-network test degrades gracefully: either uses `proxy_low` or holds current angle instead of showing a stall.

If manual gates cannot be run in the current environment, leave Stage 7.1 `in_progress` and document exactly which gate remains.

---

## Task 1: Add player-state contract tests

**Objective:** Define the single JSON payload the browser needs without making the frontend scrape unrelated endpoints/files.

**Files:**
- Create: `tests/test_player_state.py`
- Modify later: `src/autoedit/api.py`

**Payload shape:**

```json
{
  "project": {"id": "...", "name": "...", "fps_num": 24000, "fps_den": 1001},
  "audio": {"program_url": "/projects/<id>/media/audio/program.m4a"},
  "angles": [
    {"id": "...", "label": "Presenter", "role": "cam_left", "proxy_url": "...", "proxy_low_url": "...", "sync_offset_ms": 0}
  ],
  "cut": {"id": "...", "name": "rough", "params": {"min_shot_ms": 250, "silence_behaviour": "wide"}, "clips": [...]},
  "quality_default": "proxy"
}
```

**Tests to add:**

1. Missing project returns `404`.
2. Auth enabled + no session returns `401`.
3. Project without rough cut returns `400` with clear detail.
4. Project without `audio/program.m4a` DB/file reference returns `400`.
5. Happy path returns project FPS, angle IDs/labels/roles, signed/auth-relative media URLs, and rough CDL clips.
6. URLs point through `/projects/{id}/media/...`, never raw `/data` paths.
7. Only angles with DB-known `proxy_path` are included; `proxy_low_url` is present only when `proxy_low_path` exists.

**Run to verify RED:**

```bash
env -u VIRTUAL_ENV uv run pytest tests/test_player_state.py -q
```

Expected before implementation: route missing / failures.

## Task 2: Implement `GET /projects/{project_id}/player-state`

**Objective:** Provide a frontend-ready, auth-protected bootstrap payload.

**Files:**
- Modify: `src/autoedit/api.py`
- Test: `tests/test_player_state.py`

**Implementation notes:**

- Use existing DB tables: `projects`, `angles`, `cuts`.
- Use `project_root()` to verify `audio/program.m4a` exists before returning the program URL.
- Select the latest rough cut (`cuts.kind == 'rough'`) or the canonical rough cut row used by existing `/cut` route.
- Do not expose source media URLs.
- Build relative URLs to the existing media endpoint so auth/range/allowlist behavior stays centralized.

**Run:**

```bash
env -u VIRTUAL_ENV uv run pytest tests/test_player_state.py -q
env -u VIRTUAL_ENV uv run pytest tests/test_media_streaming.py tests/test_review_hardening.py -q
```

## Task 3: Serve a minimal static player shell

**Objective:** Create a browser entrypoint without adding a build toolchain.

**Files:**
- Create: `src/autoedit/web/index.html`
- Create: `src/autoedit/web/player.js`
- Create: `src/autoedit/web/styles.css`
- Modify: `src/autoedit/api.py`
- Test: `tests/test_player_static.py`

**Behavior:**

- `GET /player/{project_id}` serves the static shell or redirects to `/web/index.html?project_id=...`.
- Static assets are auth-protected by existing middleware when `AUTH_ENABLED=true`.
- Shell contains:
  - one `<audio id="programAudio" controls>` element,
  - two `<video>` elements for ping-pong playback,
  - angle buttons,
  - quality toggle (`proxy_low` / `proxy`),
  - status text for buffering/manual/auto mode.

**Tests:**

- Auth enabled + no session cannot fetch the player shell.
- Authenticated shell fetch succeeds.
- Shell references `player.js` and `styles.css`.

## Task 4: Implement pure player state helpers in JavaScript

**Objective:** Keep timing logic testable without a browser media stack.

**Files:**
- Modify: `src/autoedit/web/player.js`
- Create: `tests/player_logic.test.mjs` or a Python test that runs Node when available and skips cleanly otherwise.

**Functions to expose for tests:**

- `findClipAtTime(clips, tMs)` → current CDL clip.
- `findNextClip(clips, tMs)` → next CDL clip boundary.
- `timelineMsFromAudio(audioCurrentTime)` → integer ms.
- `videoTimeForClip(clip, timelineMs)` → `(timelineMs - clip.timeline_in_ms + clip.src_in_ms) / 1000`.
- `needsDriftCorrection(videoTime, desiredTime, frameDurationSeconds)`.
- `chooseMediaUrl(angle, quality)`.

**Tests:**

- Boundaries pick the expected clip.
- Frame threshold is derived from project FPS.
- Sync offset math uses CDL `src_in_ms`, not angle labels or wall-clock time.
- Quality toggle falls back from missing `proxy_low_url` to `proxy_url`.

## Task 5: Implement audio-master playback loop

**Objective:** Make video follow program audio and preload next clip.

**Files:**
- Modify: `src/autoedit/web/player.js`
- Modify: `src/autoedit/web/styles.css`

**Behavior:**

- Fetch `/projects/{project_id}/player-state` on load.
- Set audio source to `program_url`.
- Maintain `visibleVideo` and `hiddenVideo` elements.
- On play/tick:
  - find current clip from `audio.currentTime`,
  - ensure visible video source/seek match current angle/time,
  - preload hidden video with the next clip's angle/time,
  - at cut boundary swap visible/hidden elements when ready,
  - if hidden is not ready, keep current angle briefly and display buffering state.
- Apply drift correction when `abs(video.currentTime - desiredVideoTime) > oneFrameSeconds`.

**Manual browser check:** open a project that has program audio/proxies/CDL and verify automatic cuts visually switch.

## Task 6: Implement manual angle override and back-to-auto

**Objective:** Let reviewer force an angle without interrupting audio.

**Files:**
- Modify: `src/autoedit/web/player.js`
- Modify: `src/autoedit/web/index.html`

**Behavior:**

- Angle buttons set `manualAngleId`.
- Hidden video seeks selected angle at current master time, waits for `seeked`/`canplay`, then swaps.
- Audio element continues uninterrupted.
- `Back to auto` clears override and resumes CDL-driven angle selection.
- Override state is visible in the UI.

**Manual gate:** switch angles repeatedly while audio plays; audio must not restart or glitch.

## Task 7: Add quality switching and WAN tolerance

**Objective:** Make remote review usable on poor connections.

**Files:**
- Modify: `src/autoedit/web/player.js`
- Modify: `src/autoedit/web/index.html`

**Behavior:**

- Default to `proxy_low` when available for remote/WAN safety.
- Let user switch to full proxy.
- If the next segment is not buffered/ready at a cut boundary, hold current visible video and show `Buffering next angle...` rather than black/stalled playback.
- Keep audio master running unless severe buffering makes the entire player unusable; if pausing is needed, show explicit status.

**Manual gate:** use browser throttling if available and confirm player degrades gracefully.

## Task 8: Update continuity docs and stage status

**Objective:** Make completion state unambiguous for the next AI.

**Files:**
- Modify: `AI_HANDOFF.md`
- Modify: `jobs/BACKLOG.md`
- Modify: `docs/plans/TESTING_STRATEGY.md`
- Modify: `README.md` if the snapshot changes

**Status rule:**

- Mark Stage 7.1 `done` only after automated tests pass and the manual playback/sync gates above are recorded.
- If code/tests pass but no browser/manual test was possible, mark Stage 7.1 `in_progress — automated checks pass; manual playback gate pending`.

**Final verification commands:**

```bash
env -u VIRTUAL_ENV uv run pytest -q
python -m compileall -q src tests
git diff --check
```
