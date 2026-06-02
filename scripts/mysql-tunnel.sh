#!/usr/bin/env bash
set -euo pipefail

SSH_KEY="${AUTOEDIT_UNRAID_SSH_KEY:-/home/hermeswebui/.hermes/home/.ssh/id_ed25519}"
UNRAID_HOST="${AUTOEDIT_UNRAID_HOST:-192.168.50.50}"
REMOTE_PORT="${AUTOEDIT_MYSQL_REMOTE_PORT:-3307}"
LOCAL_PORT="${AUTOEDIT_MYSQL_LOCAL_PORT:-33306}"

exec ssh \
  -i "$SSH_KEY" \
  -o BatchMode=yes \
  -o StrictHostKeyChecking=no \
  -N \
  -L "${LOCAL_PORT}:127.0.0.1:${REMOTE_PORT}" \
  "root@${UNRAID_HOST}"
