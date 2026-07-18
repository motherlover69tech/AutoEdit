# AUTOEDIT Deployment Runbook

This is the canonical deployment path for Peter's AUTOEDIT instance.

## Canonical architecture

```text
Browser
  → Nginx Proxy Manager TLS at https://ingest.peteflix.uk
  → AUTOEDIT app on http://192.168.50.50:8010 using host networking
  → Peter's central MySQL server at 192.168.50.50:3306
  → Ollama at http://192.168.50.50:11434
  → optional internal WhisperX GPU service on http://127.0.0.1:8011
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
| `LLM_MODEL` | no | `hf.co/unsloth/Qwen3.5-9B-GGUF:Q4_K_M` | Current Ollama-only client model and planned local fallback. DeepSeek-primary provider chaining is not implemented yet. |
| `WHISPER_BACKEND` | no | `mock` | Use `whisperx` only after the opt-in GPU service passes the live gates below. Unknown/unavailable backends fail explicitly. |
| `WHISPER_MODEL` | no | `large-v3` | WhisperX ASR model name. |
| `WHISPERX_BASE_URL` | no | `http://127.0.0.1:8011` | Internal service URL; do not expose through NPM. |
| `WHISPERX_TIMEOUT_SECONDS` | no | `3600` | Long request timeout for model loading/transcription. |
| `WHISPER_LANGUAGE` | no | `en` | App and worker must use the same fixed language; the current Compose profile defaults to English. |
| `WHISPER_BATCH_SIZE` | no | `4` | Conservative V100 default; raise only after VRAM measurement. |
| `WHISPER_COMPUTE_TYPE` | no | `float16` | Isolated V100 FP16/model smokes passed; rerun Compose-managed readiness/timing/VRAM acceptance before enablement. |
| `WHISPER_ALIGN` | no | `true` | Forced alignment supplies word timestamps. |
| `DIARIZE_BACKEND` | no | `mock` | Real diarization is not enabled; isolated mapped speaker channels are transcribed separately. |
| `UPLOAD_MAX_CHUNK_BYTES` | no | `67108864` | Current code reads bytes. Do not use `UPLOAD_CHUNK_MB`. |
| `PROXY_ENCODER` | no | `h264_vaapi` | Verified Intel hardware encode path in the container. Use `libx264` for software fallback; do not use `h264_qsv` until QSV MFX initialization is fixed. |
| `CUT_MIN_SHOT_MS` | no | `250` | Direct-cut micro-guard only. Raise in a per-cut/project override if an edit is too twitchy. |

## Opt-in WhisperX GPU service

`docker-compose.gpu-ai.yml` adds a separate CUDA/WhisperX service instead of putting
PyTorch and CUDA into the VAAPI-enabled AUTOEDIT web image. The service shares
`/mnt/user/automulticam` as read-only `/data`; requests are path-confined to that
mount. It is internal host-network traffic only and must not be added to NPM.

The current target is the NVIDIA Tesla V100 32 GB. The application-facing adapter
still uses isolated mapped speaker WAVs for WhisperX ASR/alignment transport. Local
versioned-artifact, synchronized-analysis-audio, queued-diarization, overlap, and
speaker-mapping components exist, but the application does **not** yet import those
resolved turns as authoritative transcript/camera evidence. Production therefore
remains mock-backed.

Build and inspect without enabling real transcription:

```bash
export SESSION_SECRET='<from secret store>'
export OPERATOR_PASSWORD='<from secret store>'
export DB_PASSWORD='<from secret store>'
export WHISPER_BACKEND=mock

docker compose -f docker-compose.yml -f docker-compose.gpu-ai.yml \
  --profile gpu-ai config
docker compose -f docker-compose.yml -f docker-compose.gpu-ai.yml \
  --profile gpu-ai up -d --build whisperx
curl --fail http://127.0.0.1:8011/health
curl --fail http://127.0.0.1:8011/ready
```

Production enablement gates (the isolated historical smokes do not replace this
Compose-managed acceptance run):

1. Confirm `nvidia-smi` sees the V100 inside the service container.
2. Submit a short real WAV under `/mnt/user/automulticam` directly to
   `POST http://127.0.0.1:8011/v1/transcribe`; verify non-empty aligned words.
3. Check three audible word boundaries against AUTOEDIT's player/master timeline;
   each must be within one project frame after the stored channel sync offset.
4. Measure peak VRAM with Dots TTS resident and Ollama unloaded. Start with batch
   size 4; do not raise it without headroom.
5. Only then set `WHISPER_BACKEND=whisperx` in deployment secrets and recreate the
   app service. A service failure then returns a visible 502 and marks processing
   errored; it never emits mock transcript text.

Rollback the integration by setting `WHISPER_BACKEND=mock`, recreating `app`, and
stopping `whisperx`. **Do not run `/transcribe` while mock is selected on a project
whose real transcript must be retained:** mock intentionally generates fake test
text and a successful mock run replaces the prior transcript. Backend, validation,
or persistence failures preserve the previous transcript artifact and DB rows.

The detailed staged plan is
`docs/plans/gpu-ai-whisperx-llm-integration.md`.

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

- Real WhisperX transcription now has an opt-in service/client path, but production remains `WHISPER_BACKEND=mock` until the V100 image, real-WAV timing, and VRAM gates pass.
- Diarization currently uses `mock_diarize()` / explicit channel mapping; WhisperX diarization is intentionally not enabled for isolated speaker WAVs.
- Topic segmentation can use Ollama but still has mock fallback behavior.
- YouTube title generation is deterministic/template-based.
- Pipeline processing is an in-process background thread, not Redis/worker infrastructure.
- Hardware proxy encoding currently uses VAAPI (`h264_vaapi`). QSV should be called deployed only after a real container encode verifies `h264_qsv`.
- Audio sync now fails on low-confidence matches instead of silently using zero offset.

## Automated deployment via `autoedit-deploy.sh` (Kanban Publisher)

The canonical mechanism for the Publisher agent to deploy to live Unraid is the
deterministic script at `scripts/autoedit-deploy.sh`. It replaces ad-hoc inline
SSH sequences that were fragile (shell-quoting of apostrophes, hardcoded node
paths, inline DB dumps, cross-container git admin paths).

### What the script handles

1. **Pre-flight**: verifies worktree exists, SSH key is present, commit matches HEAD.
2. **Backup**: tags the prior image for rollback, archives config files, and dumps
   the central MySQL database (table-by-table if `--single-transaction` is denied).
3. **Transfer**: creates a tarball of specified paths and scp's it to Tower.
4. **Build + deploy**: validates `docker compose config`, then `up -d --build`.
5. **Health verification**: polls `/health` for up to 120s after recreate.
6. **Automatic rollback**: if health check fails, restores the prior image tag and recreates.
7. **Post-deploy checks**: auth gate (401 without cookie), NPM TLS health.
8. **Structured JSON output**: `DEPLOYED_AND_VERIFIED` / `DRY_RUN_COMPLETE` / `DEPLOY_FAILED`
   with safety booleans (`mutation_started`, `candidate_live`, `rollback_required`,
   `production_data_mutated`, `openrouter_used`).

### Usage

```bash
# Dry run (backup + pre-flight only, no production mutation):
bash scripts/autoedit-deploy.sh \
  --worktree /opt/data/workspace/AUTOEDIT/.worktrees/autoedit-integrated \
  --commit   <FULL_SHA> \
  --dry-run

# Full deploy:
bash scripts/autoedit-deploy.sh \
  --worktree /opt/data/workspace/AUTOEDIT/.worktrees/autoedit-integrated \
  --commit   <FULL_SHA> \
  --files    "src/autoedit/web/app.html,src/autoedit/web/app.js"
```

### Key design decisions

- **No inline single-quoted SSH payloads**: the remote script is scp'd as a file.
- **DB dump via `docker run --network host mysql:latest mysqldump`**: the autoedit
  MySQL user connects from 192.168.50.50 (host network), avoiding bridge-network
  ACL issues. Falls back to table-by-table dump if the user lacks RELOAD privilege.
- **Secrets stay on Tower**: DB password is extracted from the running container's
  env inside the remote script — never passed through the worker.
- **Node path discovery**: uses `command -v node`, never hardcodes `/usr/bin/node`.
- **Rollback is automatic**: on health-check failure, the script restores the
  prior image and recreates. The Publisher should NOT retry after a DEPLOY_FAILED.

The Publisher template at `docs/status/templates/publish-card-template.md` is the
board-card body that tells the Publisher to call this script and report its JSON
output. The Publisher must not run manual docker/ssh/scp/mysqldump commands.

## Troubleshooting

**`docker compose config` fails with missing secret errors:** export `SESSION_SECRET`, `OPERATOR_PASSWORD`, and `DB_PASSWORD` from the deployment secret store, then rerun.

**App cannot reach MySQL:** verify the central server is reachable from the Docker host at `192.168.50.50:3306`; do not use `localhost` from inside deployment config.

**NPM returns 502:** confirm the app container is running with host networking and listening on `192.168.50.50:8010` / port `8010`.

**Login cookie does not stick:** confirm public access is HTTPS and `SESSION_COOKIE_SECURE=true`.

**Uploads or generated media fail:** confirm `/mnt/user/automulticam` exists and is writable by the container process.
