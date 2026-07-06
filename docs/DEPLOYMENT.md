# AUTOEDIT Deployment Runbook

This is the canonical deployment path for Peter's AUTOEDIT instance.

## Canonical architecture

```text
Browser
  → Nginx Proxy Manager TLS at https://ingest.peteflix.uk
  → AUTOEDIT app on http://192.168.50.50:8010 using host networking
  → Peter's central MySQL server at 192.168.50.50:3306
  → media on /mnt/user/automulticam mounted as /data
```

Important decisions:

- **Nginx Proxy Manager is the TLS boundary.** Do not follow old Caddy instructions for this deployment unless the architecture is intentionally changed.
- **Central MySQL is canonical.** The app connects with `DB_HOST=192.168.50.50`, `DB_PORT=3306`, `DB_NAME=autoedit`, `DB_USER=autoedit`, and a password from the deployment secret store.
- **Do not start or add an `autoedit-mysql` service** for production. The old container is historical compatibility proof only.
- **Runtime env is explicit in `docker-compose.yml`.** Do not rely on `env_file` as the only source of production config.
- **Auto-cut default is Direct.** New rough cuts should start from `min_shot_ms=250`, no lead/tail delay, overlap→wide, and silence→wide. Existing projects keep their stored cut params until a rough cut is regenerated.
- **No secrets in git.** Use shell exports, Unraid template variables, or another secret store.

## Prerequisites

- Docker + Docker Compose on the Unraid host.
- Nginx Proxy Manager route:
  - public hostname: `ingest.peteflix.uk`
  - forward host/IP: `192.168.50.50`
  - forward port: `8010`
  - WebSockets enabled if available
  - force SSL / HTTP→HTTPS enabled
- MySQL 8 reachable at `192.168.50.50:3306` with the `autoedit` database/user already provisioned.
- Media path exists on Unraid: `/mnt/user/automulticam`.
- Secrets available outside the repo:
  - `SESSION_SECRET`
  - `OPERATOR_PASSWORD`
  - `DB_PASSWORD`

## Quick start

From the project checkout:

```bash
cd /workspace/AUTOEDIT

# Supply secrets from the deployment secret store. These examples are placeholders;
# do not paste real values into docs or commit them to git.
export SESSION_SECRET='<from secret store>'
export OPERATOR_PASSWORD='<from secret store>'
export DB_PASSWORD='<from secret store>'

# Optional overrides. Defaults in docker-compose.yml are suitable for the current
# deployment unless intentionally changed.
export OPERATOR_USERNAME=peter
export OPERATOR_DISPLAY_NAME=Peter
export LLM_MODEL=gemma4:12b-q4-68k
export PROXY_ENCODER=h264_vaapi

# Confirm what Compose will pass to the container before starting it.
docker compose config

# Build/restart the app.
docker compose up -d --build
```

Expected `docker compose config` shape:

- one service: `app`
- `network_mode: host`
- no `mysql` or `mariadb` service
- app environment includes:
  - `DB_HOST: 192.168.50.50`
  - `DB_PORT: "3306"`
  - `DB_NAME: autoedit`
  - `DB_USER: autoedit`
  - `OLLAMA_BASE_URL: http://192.168.50.50:11434`
  - `UPLOAD_MAX_CHUNK_BYTES: 67108864`
  - `CUT_MIN_SHOT_MS: "250"`

## Environment variables

| Variable | Required | Canonical value/default | Notes |
|---|---:|---|---|
| `PUBLIC_DOMAIN` | yes | `ingest.peteflix.uk` | Used for origin checks. |
| `ALLOWED_ORIGINS` | yes | `https://ingest.peteflix.uk,http://192.168.50.50:8010` | Comma-separated origins. |
| `AUTH_ENABLED` | yes | `true` | Keep enabled outside local tests. |
| `SESSION_SECRET` | yes | secret store | HMAC secret for sessions. |
| `OPERATOR_PASSWORD` | yes | secret store | Operator login password. |
| `OPERATOR_USERNAME` | no | `peter` | Seeded/updated operator user. |
| `OPERATOR_DISPLAY_NAME` | no | `Peter` | Display label in the UI. |
| `SESSION_COOKIE_SECURE` | yes | `true` | NPM terminates HTTPS, so browser cookies must be secure. |
| `DB_HOST` | yes | `192.168.50.50` | Central MySQL host. |
| `DB_PORT` | yes | `3306` | Central MySQL port. |
| `DB_NAME` | yes | `autoedit` | Application database. |
| `DB_USER` | yes | `autoedit` | Application DB user. |
| `DB_PASSWORD` | yes | secret store | Never commit. |
| `OLLAMA_BASE_URL` | no | `http://192.168.50.50:11434` | Current code reads this name. Do not use `LLM_BASE_URL`. |
| `LLM_MODEL` | no | `gemma4:12b-q4-68k` | Ollama model alias for LLM-backed paths. |
| `WHISPER_BACKEND` | no | `mock` | Real faster-whisper is not wired yet. |
| `DIARIZE_BACKEND` | no | `mock` | Real diarization backend is not wired yet. |
| `UPLOAD_MAX_CHUNK_BYTES` | no | `67108864` | Current code reads bytes. Do not use `UPLOAD_CHUNK_MB`. |
| `PROXY_ENCODER` | no | `h264_vaapi` | Verified Intel hardware encode path in the container. Use `libx264` for software fallback; do not use `h264_qsv` until QSV MFX initialization is fixed. |
| `CUT_MIN_SHOT_MS` | no | `250` | Direct-cut micro-guard only. Raise in a per-cut/project override if an edit is too twitchy. |

## Auto-cut deployment behavior

The deployed editorial baseline is **Direct**:

```json
{
  "min_shot_ms": 250,
  "overlap_to_wide": true,
  "lead_in_ms": 0,
  "tail_ms": 0,
  "silence_behaviour": "wide",
  "wide_interval_ms": 0,
  "wide_interval_jitter": 0.3
}
```

This means AUTOEDIT should cut to the active single speaker as soon as the activity timeline changes, cut to wide when both speakers overlap, and cut to wide during silence. Loosening is explicit: use the player **Looser preset** or manually raise `min_shot_ms`, `tail_ms`, `lead_in_ms`, or enable a relief-wide interval.

Important: `cuts.params_json` is stored with each generated cut. Deploying new code does **not** mutate old cuts. For an existing project, regenerate the rough cut from the player controls or `POST /projects/{id}/cut` with the Direct params above. The live `sm test` project was regenerated after deployment as `Direct rough cut` with these params.

## Central MySQL verification

Run the integration gate with real secrets supplied through env only:

```bash
DB_HOST=192.168.50.50 \
DB_PORT=3306 \
DB_NAME=autoedit \
DB_USER=autoedit \
DB_PASSWORD='<from secret store>' \
  env -u VIRTUAL_ENV uv run pytest tests/test_mysql_integration.py -q
```

If it is safe to run the full suite against the target DB for the current task, run:

```bash
DB_HOST=192.168.50.50 \
DB_PORT=3306 \
DB_NAME=autoedit \
DB_USER=autoedit \
DB_PASSWORD='<from secret store>' \
  env -u VIRTUAL_ENV uv run pytest -q
```

For normal local/offline verification, use SQLite-backed tests:

```bash
env -u VIRTUAL_ENV uv run pytest -q
python -m compileall -q src tests
```

## NPM/live app verification

After `docker compose up -d --build` and NPM routing are in place:

| Check | Command | Expected |
|---|---|---|
| Health is public | `curl -i https://ingest.peteflix.uk/health` | `200` with `{"status":"ok"}` |
| Protected routes require auth | `curl -i https://ingest.peteflix.uk/projects` | `401` without cookie |
| Login works | `curl -i -X POST https://ingest.peteflix.uk/auth/login -H 'Content-Type: application/json' -d '{"username":"peter","password":"<secret>","display_name":"Peter"}'` | `204` and `Set-Cookie` |
| Session works | `curl -i https://ingest.peteflix.uk/auth/me -b 'autoedit_session=<cookie>'` | `200` with Peter's user info |
| `/data` not exposed | `curl -i https://ingest.peteflix.uk/data/` | `404` or equivalent no-route response |
| Media requires auth | `curl -i https://ingest.peteflix.uk/projects/<id>/media/proxy/<file>` | `401` without cookie |
| HTTP redirects | `curl -I http://ingest.peteflix.uk` | HTTP→HTTPS redirect from NPM |

## Feature-status caveats for deployment

Do not advertise these as production-complete until implemented and verified:

- Transcription currently uses `mock_transcribe()`.
- Diarization currently uses `mock_diarize()` / simple channel mapping.
- Topic segmentation can use Ollama but still has mock fallback behavior.
- YouTube title generation is deterministic/template-based.
- Pipeline processing is an in-process background thread, not Redis/worker infrastructure.
- Hardware proxy encoding currently uses VAAPI (`h264_vaapi`). QSV should be called deployed only after a real container encode verifies `h264_qsv`.
- Audio sync now fails on low-confidence matches instead of silently using zero offset.

## Troubleshooting

**`docker compose config` fails with missing secret errors:** export `SESSION_SECRET`, `OPERATOR_PASSWORD`, and `DB_PASSWORD` from the deployment secret store, then rerun.

**App cannot reach MySQL:** verify the central server is reachable from the Docker host at `192.168.50.50:3306`; do not use `localhost` from inside deployment config.

**NPM returns 502:** confirm the app container is running with host networking and listening on `192.168.50.50:8010` / port `8010`.

**Login cookie does not stick:** confirm public access is HTTPS and `SESSION_COOKIE_SECURE=true`.

**Uploads or generated media fail:** confirm `/mnt/user/automulticam` exists and is writable by the container process.
