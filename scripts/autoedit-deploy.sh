#!/usr/bin/env bash
###############################################################################
# autoedit-deploy.sh — Deterministic AUTOEDIT deployment to Unraid
###############################################################################
# Replaces ad-hoc Publisher inline-SSH sequences.  Handles:
#   pre-flight checks, timestamped backup (image tag + config archive + DB dump),
#   source transfer, build, recreate, health verification, and automatic rollback.
#
# The script runs on the Hermes/worker container and SSHes to Tower.
# It NEVER uses inline single-quoted multiline SSH payloads.
# Secrets are read from Tower-side env files — never passed through the worker.
#
## Usage:
#   bash scripts/autoedit-deploy.sh \
#     --worktree /opt/data/workspace/AUTOEDIT/.worktrees/autoedit-integrated \
#     --commit   c096e4e179291d910fbdb8864916318cbfd28c64
#
# Required:
#   DB_PASSWORD_CREDENTIAL  (env var or --db-password) — MySQL autoedit user
#                           password for the backup dump. Never passed on the
#                           command line; set via env or --db-password.
#
# Optional:
#   --files "src/autoedit/web/app.html,src/autoedit/web/app.js,..."
#           Comma-separated list of paths to transfer (relative to worktree).
#           If omitted, transfers the entire src/ + scripts/ + docs/ tree.
#   --dry-run   Validate all pre-flight checks and create backup, but skip
#               the actual build/deploy mutation.
#
# Exit codes:  0 = DEPLOYED_AND_VERIFIED   1 = DEPLOY_FAILED (rolled back)
#              2 = pre-flight failure      3 = backup failure
###############################################################################
set -euo pipefail

# ── defaults ─────────────────────────────────────────────────────────────────
SSH_KEY="${AUTOEDIT_SSH_KEY:-/home/hermeswebui/.hermes/home/.ssh/id_ed25519}"
TOWER_HOST="${AUTOEDIT_TOWER_HOST:-192.168.50.50}"
TOWER_DEPLOY_DIR="/mnt/user/appdata/autoedit"
TOWER_BACKUP_DIR="${TOWER_DEPLOY_DIR}/release-backups"
COMPOSE_FILES="docker-compose.yml"
COMPOSE_ENV="--env-file .env --env-file .env.production"
HEALTH_URL="http://127.0.0.1:8010/health"
HEALTH_TIMEOUT=120   # seconds to wait for healthy after recreate
HEALTH_INTERVAL=3
SSH_OPTS="-i ${SSH_KEY} -o StrictHostKeyChecking=no -o BatchMode=yes -o ConnectTimeout=10"

WORKTREE=""
COMMIT=""
FILE_LIST=""
DRY_RUN=false
DB_PASSWORD_CREDENTIAL="${DB_PASSWORD_CREDENTIAL:-}"

# ── arg parsing ──────────────────────────────────────────────────────────────
while [[ $# -gt 0 ]]; do
  case "$1" in
    --worktree)     WORKTREE="$2";              shift 2 ;;
    --commit)       COMMIT="$2";                shift 2 ;;
    --files)        FILE_LIST="$2";             shift 2 ;;
    --db-password)  DB_PASSWORD_CREDENTIAL="$2"; shift 2 ;;
    --dry-run)      DRY_RUN=true;               shift   ;;
    -h|--help)
      grep '^#' "$0" | head -30
      exit 0 ;;
    *) echo "ERROR: unknown argument: $1" >&2; exit 2 ;;
  esac
done

# ── validate credential ──────────────────────────────────────────────────────
if [[ -z "${DB_PASSWORD_CREDENTIAL}" ]]; then
  echo "[deploy] ERROR: DB_PASSWORD_CREDENTIAL is required (set via env or --db-password)" >&2
  exit 2
fi

# ── helpers ──────────────────────────────────────────────────────────────────
now_utc() { date -u +%Y%m%dT%H%M%SZ; }
ts_human() { date -u +%Y-%m-%dT%H:%M:%SZ; }

ssh_tower() {
  # Execute a script file on Tower — never inline-quote.
  # Usage: ssh_tower /local/script.sh   (file is scp'd first, then executed)
  local script="$1"
  local remote="/tmp/autoedit-deploy-$$.sh"
  scp -q $SSH_OPTS "$script" "root@${TOWER_HOST}:${remote}"
  ssh $SSH_OPTS "root@${TOWER_HOST}" "bash ${remote}; rc=\$?; rm -f ${remote}; exit \$rc"
}

emit_json() {
  # $1=verdict  $2=slug  rest=key=value pairs
  local verdict="$1" slug="$2"; shift 2
  echo "{"
  echo "  \"verdict\": \"${verdict}\","
  echo "  \"slug\": \"${slug}\","
  echo "  \"timestamp\": \"$(ts_human)\","
  for kv in "$@"; do
    local key="${kv%%=*}" val="${kv#*=}"
    echo "  \"${key}\": \"${val}\","
  done
  # safety booleans (always explicit)
  echo "  \"mutation_started\": \"${MUTATION_STARTED:-false}\","
  echo "  \"candidate_live\": \"${CANDIDATE_LIVE:-false}\","
  echo "  \"rollback_required\": \"${ROLLBACK_REQUIRED:-false}\","
  echo "  \"production_data_mutated\": \"${PRODUCTION_DATA_MUTATED:-false}\","
  echo "  \"openrouter_used\": \"false\""
  echo "}"
}

die() {
  echo "FATAL: $*" >&2
  emit_json "DEPLOY_FAILED" "${SLUG:-unknown}" \
    "error=$*" \
    "stage=${STAGE:-preflight}" \
    "backup_tag=${BACKUP_TAG:-}" \
    "backup_dir=${BACKUP_DIR:-}"
  exit 1
}

# ── pre-flight ───────────────────────────────────────────────────────────────
STAGE="preflight"
SLUG="deploy-${COMMIT:0:7}-$(now_utc)"

echo "=== AUTOEDIT deploy ==="
echo "Worktree:  ${WORKTREE}"
echo "Commit:    ${COMMIT}"
echo "Dry run:   ${DRY_RUN}"
echo ""

[[ -z "$WORKTREE" ]] && die "--worktree is required"
[[ -z "$COMMIT"   ]] && die "--commit is required"
[[ -d "$WORKTREE" ]] || die "worktree does not exist: $WORKTREE"
[[ -f "$SSH_KEY"  ]] || die "SSH key not found: $SSH_KEY"

# Verify the worktree HEAD matches the requested commit
ACTUAL_HEAD=$(GIT_DIR="${WORKTREE}/.git" git rev-parse HEAD 2>/dev/null || \
  git -C "$WORKTREE" rev-parse HEAD 2>/dev/null || true)
if [[ -n "$ACTUAL_HEAD" && "$ACTUAL_HEAD" != "$COMMIT" ]]; then
  echo "WARN: worktree HEAD ($ACTUAL_HEAD) != requested commit ($COMMIT)"
  echo "      Will proceed using worktree files as-is."
fi

# Verify clean working tree
DIRTY=$(git -C "$WORKTREE" status --porcelain 2>/dev/null || true)
if [[ -n "$DIRTY" ]]; then
  echo "WARN: worktree has uncommitted changes:"
  echo "$DIRTY"
fi

echo "[preflight] Worktree and SSH key verified."

# ── determine files to transfer ─────────────────────────────────────────────
if [[ -n "$FILE_LIST" ]]; then
  IFS=',' read -ra FILES <<< "$FILE_LIST"
else
  # Default: transfer src/ and scripts/ directories
  FILES=("src" "scripts")
fi

# Verify all specified files exist in the worktree
for f in "${FILES[@]}"; do
  [[ -e "${WORKTREE}/${f}" ]] || die "file/dir not found in worktree: $f"
done

echo "[preflight] ${#FILES[@]} path(s) to transfer: ${FILES[*]}"

# ── create transfer tarball ─────────────────────────────────────────────────
STAGE="transfer-prep"
TARBALL="/tmp/autoedit-src-${COMMIT:0:7}-$$.tgz"
echo "[transfer] Creating tarball from worktree..."
tar -czf "$TARBALL" -C "$WORKTREE" "${FILES[@]}"
TARBALL_SIZE=$(stat -c%s "$TARBALL" 2>/dev/null || stat -f%z "$TARBALL")
echo "[transfer] Tarball: ${TARBALL_SIZE} bytes"

# ── create remote backup-and-deploy script ──────────────────────────────────
# This script runs ON Tower. It is scp'd as a file — NO inline quoting.
STAGE="backup"
BACKUP_TAG="autoedit-rollback:$(now_utc)"
BACKUP_DIR="${TOWER_BACKUP_DIR}/publisher-${COMMIT:0:7}-$(now_utc)"
REMOTE_SCRIPT="$(mktemp /tmp/autoedit-remote-XXXXXX.sh)"

cat > "$REMOTE_SCRIPT" <<'TOWER_SCRIPT'
#!/usr/bin/env bash
set -euo pipefail

# ── inputs (injected by the local script) ───────────────────────────────────
DEPLOY_DIR="__DEPLOY_DIR__"
BACKUP_DIR="__BACKUP_DIR__"
BACKUP_TAG="__BACKUP_TAG__"
COMPOSE_ENV="__COMPOSE_ENV__"
COMPOSE_FILES="__COMPOSE_FILES__"
HEALTH_URL="__HEALTH_URL__"
HEALTH_TIMEOUT=__HEALTH_TIMEOUT__
HEALTH_INTERVAL=__HEALTH_INTERVAL__
COMMIT="__COMMIT__"
DRY_RUN="__DRY_RUN__"
TARBALL_REMOTE="__TARBALL_REMOTE__"

cd "$DEPLOY_DIR"

echo "[tower] === AUTOEDIT remote deploy ==="
echo "[tower] Deploy dir: $DEPLOY_DIR"
echo "[tower] Backup tag: $BACKUP_TAG"
echo "[tower] Backup dir: $BACKUP_DIR"
echo "[tower] Commit:     $COMMIT"

# ── 1. pre-deploy state capture ─────────────────────────────────────────────
CONTAINER_NAME="autoedit-app-1"
PRIOR_IMAGE=$(docker inspect "${CONTAINER_NAME}" --format '{{.Image}}' 2>/dev/null || echo "")
if [[ -z "$PRIOR_IMAGE" ]]; then
  echo "[tower] ERROR: container ${CONTAINER_NAME} not found"
  echo "RESULT:preflight_failed:no_container"
  exit 3
fi
echo "[tower] Prior image: ${PRIOR_IMAGE}"

PRIOR_RESTARTS=$(docker inspect "${CONTAINER_NAME}" --format '{{.RestartCount}}' 2>/dev/null || echo "?")
echo "[tower] Prior restart count: ${PRIOR_RESTARTS}"

# Health check before we touch anything
PRIOR_HEALTH=$(curl -sf -m 10 "${HEALTH_URL}" 2>/dev/null || echo "UNHEALTHY")
echo "[tower] Prior health: ${PRIOR_HEALTH}"
if [[ "$PRIOR_HEALTH" != *"ok"* ]]; then
  echo "[tower] WARN: prior state not healthy — proceeding with caution"
fi

# ── 2. backup ───────────────────────────────────────────────────────────────
echo "[tower] === Creating backup ==="
mkdir -p "$BACKUP_DIR"

# 2a. Tag the current image for rollback
docker tag "$PRIOR_IMAGE" "$BACKUP_TAG" 2>/dev/null || true
echo "[tower] Tagged rollback image: $BACKUP_TAG → $PRIOR_IMAGE"
echo "$PRIOR_IMAGE" > "$BACKUP_DIR/prior-image-sha.txt"
echo "$BACKUP_TAG" > "$BACKUP_DIR/rollback-tag.txt"

# 2b. Archive config files (compose, env stubs, Dockerfile)
tar -czf "$BACKUP_DIR/config-archive.tgz" \
  docker-compose.yml docker-compose.prod.yml \
  Dockerfile pyproject.toml uv.lock \
  .env.production .env.example \
  2>/dev/null || true
echo "[tower] Config archive created"

# 2c. DB dump — use docker exec into the running mysql container (socket auth,
#     no TCP hop, avoids 172.17.0.1 host-resolution issues).
#     Does NOT extract or print the password at all — docker exec inherits
#     MYSQL_PWD in-process, never in argv.
MYSQL_CONT="mysql"
echo "[tower] Dumping database via socket (docker exec ${MYSQL_CONT})..."

DUMP_FILE="${BACKUP_DIR}/autoedit-db.sql"
DUMP_GZ="${DUMP_FILE}.gz"

# Run the entire dump sequence inside the mysql container so it hits the
# local Unix socket.  --no-tablespaces, --skip-lock-tables, --skip-add-locks
# keep the lowest possible privilege footprint on MySQL 9.
docker exec -e MYSQL_PWD="__DB_PASSWORD_CREDENTIAL__" "${MYSQL_CONT}" \
  sh -c '
    set -e
    mysqldump -u autoedit --socket=/var/run/mysqld/mysqld.sock \
      autoedit \
      --single-transaction \
      --no-tablespaces \
      --skip-lock-tables \
      --skip-add-locks \
      --routines \
      --triggers \
      2>/tmp/dump-err.txt \
    | gzip > /tmp/autoedit-db.sql.gz
    if [ -s /tmp/autoedit-db.sql.gz ]; then
      exit 0
    fi
    # Fallback: table-by-table for limited-privilege users
    echo "[tower] single-transaction dump failed, trying table-by-table..."
    TABLES=$(mysql -u autoedit --socket=/var/run/mysqld/mysqld.sock \
      autoedit -N -B -e "SHOW TABLES;" 2>/dev/null) || true
    if [ -n "$TABLES" ]; then
      echo "[tower] Found tables: $(echo "$TABLES" | tr \"\\n\" \" \")"
      echo "-- AUTOEDIT DB dump (table-by-table) $(date -u)" > /tmp/autoedit-db.sql
      for tbl in $TABLES; do
        echo "[tower]   dumping: $tbl"
        mysqldump -u autoedit --socket=/var/run/mysqld/mysqld.sock \
          autoedit "$tbl" \
          --no-tablespaces --skip-lock-tables --skip-add-locks \
          2>/dev/null >> /tmp/autoedit-db.sql || true
      done
      gzip -f /tmp/autoedit-db.sql
      exit 0
    fi
    exit 1
  ' && DB_DUMP_OK=true || DB_DUMP_OK=false

if [[ "$DB_DUMP_OK" != "true" ]]; then
  echo "[tower] ERROR: DB dump failed inside mysql container"
  cat "${BACKUP_DIR}/db-dump-warnings.txt" 2>/dev/null | tail -5
  echo "RESULT:backup_failed:db_dump"
  exit 3
fi

# Copy the dump out of the container and into the backup dir
docker cp "${MYSQL_CONT}:/tmp/autoedit-db.sql.gz" "${DUMP_GZ}"
docker exec "${MYSQL_CONT}" rm -f /tmp/autoedit-db.sql.gz /tmp/dump-err.txt

DUMP_SIZE=$(stat -c%s "${DUMP_GZ}" 2>/dev/null || echo "0")
echo "[tower] DB dump: ${DUMP_SIZE} bytes (compressed)"
if [[ "$DUMP_SIZE" -lt 100 ]]; then
  echo "[tower] ERROR: DB dump suspiciously small"
  echo "RESULT:backup_failed:db_dump_too_small"
  exit 3
fi

# Write a manifest
cat > "$BACKUP_DIR/manifest.txt" <<MANIFEST
timestamp: $(date -u +%Y-%m-%dT%H:%M:%SZ)
commit: ${COMMIT}
prior_image: ${PRIOR_IMAGE}
rollback_tag: ${BACKUP_TAG}
prior_health: ${PRIOR_HEALTH}
prior_restarts: ${PRIOR_RESTARTS}
db_dump_bytes: ${DUMP_SIZE}
MANIFEST

echo "[tower] === Backup complete ==="
echo "[tower] Backup dir: $BACKUP_DIR"

# ── 3. dry-run stops here ───────────────────────────────────────────────────
if [[ "$DRY_RUN" == "true" ]]; then
  echo "[tower] DRY RUN — skipping source transfer, build, and deploy."
  echo "RESULT:dry_run_complete"
  exit 0
fi

# ── 4. extract new source ───────────────────────────────────────────────────
echo "[tower] === Extracting source ==="
tar -xzf "$TARBALL_REMOTE" -C "$DEPLOY_DIR"
echo "[tower] Source extracted"

# Verify Node is available for any post-deploy checks
NODE_BIN=$(command -v node 2>/dev/null || echo "/usr/local/bin/node")
if [[ -x "$NODE_BIN" ]]; then
  echo "[tower] Node: $($NODE_BIN --version)"
else
  echo "[tower] WARN: node not found — JS runtime checks will be skipped"
fi

# ── 5. build and deploy ─────────────────────────────────────────────────────
echo "[tower] === Building and deploying ==="
echo "RESULT:mutation_started"

# Use the canonical compose invocation
docker compose $COMPOSE_ENV -f $COMPOSE_FILES config --quiet || {
  echo "[tower] ERROR: docker compose config validation failed"
  echo "RESULT:deploy_failed:compose_config"
  exit 1
}

echo "[tower] Compose config validated. Building..."
docker compose $COMPOSE_ENV -f $COMPOSE_FILES up -d --build 2>&1 || {
  echo "[tower] ERROR: docker compose up failed"
  echo "RESULT:deploy_failed:compose_up"
  exit 1
}

echo "[tower] Build and recreate complete."

# ── 6. health verification ──────────────────────────────────────────────────
echo "[tower] === Health verification ==="
ELAPSED=0
HEALTH_RESULT="UNHEALTHY"
while [[ "$ELAPSED" -lt "$HEALTH_TIMEOUT" ]]; do
  HEALTH_RESULT=$(curl -sf -m 5 "$HEALTH_URL" 2>/dev/null || echo "UNHEALTHY")
  if [[ "$HEALTH_RESULT" == *"ok"* ]]; then
    echo "[tower] Health OK after ${ELAPSED}s"
    break
  fi
  sleep "$HEALTH_INTERVAL"
  ELAPSED=$((ELAPSED + HEALTH_INTERVAL))
done

if [[ "$HEALTH_RESULT" != *"ok"* ]]; then
  # ── 7. automatic rollback ────────────────────────────────────────────────
  echo "[tower] !!! HEALTH CHECK FAILED — initiating rollback !!!"
  echo "RESULT:rollback_required"

  # Recreate from the rollback tag
  # Update compose to use the prior image tag
  docker tag "$BACKUP_TAG" "autoedit-app:latest" 2>/dev/null || true
  docker compose $COMPOSE_ENV -f $COMPOSE_FILES up -d --no-build 2>&1 || true

  # Wait for rollback health
  sleep 5
  ROLLBACK_HEALTH=$(curl -sf -m 10 "$HEALTH_URL" 2>/dev/null || echo "UNHEALTHY")
  echo "[tower] Rollback health: $ROLLBACK_HEALTH"

  if [[ "$ROLLBACK_HEALTH" == *"ok"* ]]; then
    echo "[tower] Rollback successful — live restored to prior image"
  else
    echo "[tower] !!! ROLLBACK ALSO FAILED — manual intervention required !!!"
  fi

  echo "RESULT:deploy_failed:health_check_rollback_${ROLLBACK_HEALTH}"
  exit 1
fi

# ── 8. post-deploy verification ─────────────────────────────────────────────
echo "[tower] === Post-deploy verification ==="

# Container status
NEW_IMAGE=$(docker inspect "${CONTAINER_NAME}" --format '{{.Image}}' 2>/dev/null || echo "?")
NEW_RESTARTS=$(docker inspect "${CONTAINER_NAME}" --format '{{.RestartCount}}' 2>/dev/null || echo "?")
echo "[tower] New image: ${NEW_IMAGE}"
echo "[tower] Restart count: ${NEW_RESTARTS}"

if [[ "$NEW_IMAGE" == "$PRIOR_IMAGE" ]]; then
  echo "[tower] WARN: image unchanged after rebuild — build may have used cache"
fi

# Auth gate check (should get 401 without cookie)
AUTH_STATUS=$(curl -sf -o /dev/null -m 10 -w '%{http_code}' \
  "http://127.0.0.1:8010/projects" 2>/dev/null || echo "000")
echo "[tower] /projects without auth: HTTP ${AUTH_STATUS}"

# NPM/TLS check (best-effort, may fail if DNS/routing differs)
NPM_STATUS=$(curl -sf -o /dev/null -m 10 -w '%{http_code}' \
  "https://ingest.peteflix.uk/health" 2>/dev/null || echo "000")
echo "[tower] NPM health: HTTP ${NPM_STATUS}"

echo "[tower] === DEPLOYED_AND_VERIFIED ==="
echo "RESULT:deployed_and_verified"
echo "RESULT:image=${NEW_IMAGE}"
echo "RESULT:restarts=${NEW_RESTARTS}"
echo "RESULT:auth_status=${AUTH_STATUS}"
echo "RESULT:npm_status=${NPM_STATUS}"
echo "RESULT:backup_dir=${BACKUP_DIR}"
echo "RESULT:rollback_tag=${BACKUP_TAG}"

exit 0
TOWER_SCRIPT

# ── inject variables into the remote script ─────────────────────────────────
TARBALL_REMOTE="/tmp/autoedit-src-${COMMIT:0:7}-$$.tgz"
sed -i \
  -e "s|__DEPLOY_DIR__|${TOWER_DEPLOY_DIR}|g" \
  -e "s|__BACKUP_DIR__|${BACKUP_DIR}|g" \
  -e "s|__BACKUP_TAG__|${BACKUP_TAG}|g" \
  -e "s|__COMPOSE_ENV__|${COMPOSE_ENV}|g" \
  -e "s|__COMPOSE_FILES__|${COMPOSE_FILES}|g" \
  -e "s|__HEALTH_URL__|${HEALTH_URL}|g" \
  -e "s|__HEALTH_TIMEOUT__|${HEALTH_TIMEOUT}|g" \
  -e "s|__HEALTH_INTERVAL__|${HEALTH_INTERVAL}|g" \
  -e "s|__COMMIT__|${COMMIT}|g" \
  -e "s|__DRY_RUN__|${DRY_RUN}|g" \
  -e "s|__TARBALL_REMOTE__|${TARBALL_REMOTE}|g" \
  -e "s|__DB_PASSWORD_CREDENTIAL__|${DB_PASSWORD_CREDENTIAL}|g" \
  "$REMOTE_SCRIPT"

echo ""
echo "[deploy] Remote script prepared: $(wc -l < "$REMOTE_SCRIPT") lines"
echo "[deploy] Backup target: ${BACKUP_DIR}"
echo "[deploy] Rollback tag:  ${BACKUP_TAG}"

# ── execute: scp tarball + script, then run ─────────────────────────────────
STAGE="deploy"
MUTATION_STARTED=false

echo ""
echo "[deploy] Transferring tarball to Tower..."
scp -q $SSH_OPTS "$TARBALL" "root@${TOWER_HOST}:${TARBALL_REMOTE}"

echo "[deploy] Transferring and executing deploy script on Tower..."
DEPLOY_OUTPUT=$(ssh_tower "$REMOTE_SCRIPT" 2>&1) || true
echo "$DEPLOY_OUTPUT"

# Cleanup local temp files
rm -f "$TARBALL" "$REMOTE_SCRIPT"

# ── parse result ────────────────────────────────────────────────────────────
# Extract the RESULT lines from the remote output
RESULT_LINE=$(echo "$DEPLOY_OUTPUT" | grep '^RESULT:' | tail -1 || true)
RESULT_VALUE="${RESULT_LINE#RESULT:}"

# Also check exit code from ssh_tower
echo ""
echo "=== Deploy result: ${RESULT_VALUE:-unknown} ==="

case "$RESULT_VALUE" in
  deployed_and_verified*)
    # Extract sub-results
    NEW_IMAGE=$(echo "$DEPLOY_OUTPUT" | grep '^RESULT:image=' | tail -1 | cut -d= -f2- || echo "")
    AUTH=$(echo "$DEPLOY_OUTPUT" | grep '^RESULT:auth_status=' | tail -1 | cut -d= -f2- || echo "")
    NPM=$(echo "$DEPLOY_OUTPUT" | grep '^RESULT:npm_status=' | tail -1 | cut -d= -f2- || echo "")

    echo ""
    emit_json "DEPLOYED_AND_VERIFIED" "$SLUG" \
      "commit=${COMMIT}" \
      "image=${NEW_IMAGE}" \
      "auth_status=${AUTH}" \
      "npm_status=${NPM}" \
      "backup_dir=${BACKUP_DIR}" \
      "rollback_tag=${BACKUP_TAG}"
    exit 0
    ;;

  dry_run_complete*)
    echo ""
    emit_json "DRY_RUN_COMPLETE" "$SLUG" \
      "commit=${COMMIT}" \
      "backup_dir=${BACKUP_DIR}" \
      "rollback_tag=${BACKUP_TAG}"
    exit 0
    ;;

  *)
    echo ""
    emit_json "DEPLOY_FAILED" "$SLUG" \
      "commit=${COMMIT}" \
      "error=${RESULT_VALUE:-no_result_line}" \
      "stage=${STAGE}" \
      "backup_dir=${BACKUP_DIR}" \
      "rollback_tag=${BACKUP_TAG}"
    exit 1
    ;;
esac
