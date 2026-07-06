# Stage 3.5 Proxy Normalisation (Main Tier) Implementation Plan

> **For Hermes:** Use test-driven-development. Keep routes behind Stage 7.0 auth middleware when auth is enabled. ffmpeg not installed in CI — mock subprocess.run in tests.

**Goal:** Produce silent 720p short-GOP playback proxies from uploaded source files.

**Depends on:** Stage 3.3 probe & channel mapping.

**Source spec:** `docs/source/multicam_autoedit_spec.md`, Stage 3.5.

**Architecture:** Create `src/autoedit/proxy.py` with `generate_proxy(source_path, output_path, ...)` that calls ffmpeg. Add `POST /projects/{id}/proxy` route to generate proxies for all angles, plus per-angle `POST /projects/{id}/angles/{aid}/proxy`. Config: `PROXY_ENCODER`, `PROXY_GOP`, `PROXY_HEIGHT` env vars with defaults. Tests mock subprocess.run.

---

## Required behavior

- ffmpeg command: `-vf scale=-2:{height} -c:v {encoder} -profile:v high -pix_fmt yuv420p -g {gop} -keyint_min {gop} -sc_threshold 0 -preset veryfast -crf 20 -movflags +faststart -an`
- Store `proxy_path` on the angles row.
- Proxies go to `{data_root}/{project_id}/proxy/{angle_label}.proxy.mp4`.
- Idempotent: running proxy generation again overwrites existing.

## API surface

- `POST /projects/{project_id}/proxy` — generates proxies for all angles in project
- `POST /projects/{project_id}/angles/{angle_id}/proxy` — generates proxy for a single angle

## Tests (tests/test_proxy.py)

1. Proxy routes require auth.
2. Missing project/angle returns 404.
3. Single-angle proxy generation updates `angles.proxy_path`.
4. All-angle proxy generation updates all angles.
5. Proxy generation uses correct ffmpeg args (capture subprocess call args).
6. Idempotent: re-running proxy overwrites existing (same path).
7. Missing source file returns 400.

## Implementation files

- **Create:** `src/autoedit/proxy.py`
- **Modify:** `src/autoedit/api.py` — add proxy routes
- **Create:** `tests/test_proxy.py`
- **Modify:** `src/autoedit/config.py` — add proxy env vars

## Verification

```bash
env -u VIRTUAL_ENV uv run pytest tests/test_proxy.py -v
env -u VIRTUAL_ENV uv run pytest -q
```

## Definition of done

- `angles.proxy_path` is set after proxy generation.
- Correct ffmpeg args (GOP, height, encoder, silent, faststart).
- Per-angle and bulk proxy routes work.
- Full suite passes.
- Update continuity docs.
