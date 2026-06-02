#!/usr/bin/env bash
set -euo pipefail

SSH_KEY="${AUTOEDIT_UNRAID_SSH_KEY:-/home/hermeswebui/.hermes/home/.ssh/id_ed25519}"
UNRAID_HOST="${AUTOEDIT_UNRAID_HOST:-192.168.50.50}"
LOCAL_PORT="${AUTOEDIT_MYSQL_LOCAL_PORT:-33306}"
REMOTE_ENV="${AUTOEDIT_MYSQL_REMOTE_ENV:-/mnt/user/appdata/autoedit-mysql/.env}"

MYSQL_PASSWORD=$(ssh \
  -i "$SSH_KEY" \
  -o BatchMode=yes \
  -o StrictHostKeyChecking=no \
  "root@${UNRAID_HOST}" \
  "awk -F= '/^MYSQL_PASSWORD=/{print \$2}' '${REMOTE_ENV}'")

if [[ -z "$MYSQL_PASSWORD" ]]; then
  echo "Could not read MYSQL_PASSWORD from ${UNRAID_HOST}:${REMOTE_ENV}" >&2
  exit 2
fi

export AUTOEDIT_MYSQL_TEST_URL="mysql+pymysql://autoedit:${MYSQL_PASSWORD}@127.0.0.1:${LOCAL_PORT}/autoedit"
env -u VIRTUAL_ENV uv run pytest tests/test_mysql_integration.py -q
