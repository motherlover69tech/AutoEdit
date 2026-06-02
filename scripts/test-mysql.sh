#!/usr/bin/env bash
set -euo pipefail

if [[ -z "${AUTOEDIT_MYSQL_TEST_URL:-}" ]]; then
  cat >&2 <<'EOF'
AUTOEDIT_MYSQL_TEST_URL is required.

Start the tunnel first:
  ./scripts/mysql-tunnel.sh

Then run with the URL from the remote dev DB .env, for example:
  AUTOEDIT_MYSQL_TEST_URL='mysql+pymysql://autoedit:<password>@127.0.0.1:33306/autoedit' ./scripts/test-mysql.sh
EOF
  exit 2
fi

export AUTOEDIT_MYSQL_TEST_URL
env -u VIRTUAL_ENV uv run pytest tests/test_mysql_integration.py -q
