# Existing MySQL Database Requirements

Peter wants AUTOEDIT to use the existing MySQL server, not a separate AUTOEDIT database container.

## Required connection details

Provide these via `.env` or deployment secrets, never committed to git:

```env
DB_HOST=...
DB_PORT=3306
DB_NAME=autoedit
DB_USER=autoedit
DB_PASSWORD=...
```

## Recommended database/user setup

Run on the existing MySQL server as an admin user. Adjust host restrictions if the app container will connect from a specific Docker network/IP.

```sql
CREATE DATABASE IF NOT EXISTS autoedit
  CHARACTER SET utf8mb4
  COLLATE utf8mb4_0900_ai_ci;

CREATE USER IF NOT EXISTS 'autoedit'@'%'
  IDENTIFIED BY '<strong unique password>';

GRANT SELECT, INSERT, UPDATE, DELETE, CREATE, ALTER, INDEX
  ON autoedit.* TO 'autoedit'@'%';

FLUSH PRIVILEGES;
```

Least-privilege note from the spec: app runtime should ideally only need `SELECT/INSERT/UPDATE/DELETE`; migrations need `CREATE/ALTER/INDEX`. For early development, one account with migration privileges is acceptable. Later, split into migration/runtime users if needed.

## Verification command

Once creds are available, run:

```bash
AUTOEDIT_MYSQL_TEST_URL='mysql+pymysql://USER:PASSWORD@HOST:PORT/DB_NAME' \
  env -u VIRTUAL_ENV uv run pytest tests/test_mysql_integration.py -q
```

Then run full suite:

```bash
AUTOEDIT_MYSQL_TEST_URL='mysql+pymysql://USER:PASSWORD@HOST:PORT/DB_NAME' \
  env -u VIRTUAL_ENV uv run pytest -q
```

## Temporary dev DB status

A temporary MySQL 8 container named `autoedit-mysql` was created on Unraid to prove the code works against MySQL. It is **not canonical** and should not be used as the real AUTOEDIT database once Peter provides existing-server credentials.

Current state: the temporary container has been stopped. Its volume was not deleted.
