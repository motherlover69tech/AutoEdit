# AUTOEDIT MySQL dev DB

This compose file runs a MySQL 8 dev database for Stage 3.1+ integration testing.

## Current Unraid deployment

Remote path:

```text
/mnt/user/appdata/autoedit-mysql/compose.yaml
/mnt/user/appdata/autoedit-mysql/.env
/mnt/user/appdata/autoedit-mysql/data/
```

Container:

```text
autoedit-mysql
```

The compose port is bound to the Unraid host loopback only:

```yaml
127.0.0.1:3307:3306
```

That means MySQL is not exposed on the LAN. Use an SSH tunnel.

## Start tunnel

```bash
./scripts/mysql-tunnel.sh
```

Leave that process running in one terminal/session. It forwards local `127.0.0.1:33306` to Unraid's local MySQL port.

## Run MySQL integration test

```bash
./scripts/test-mysql.sh
```

Or manually:

```bash
AUTOEDIT_MYSQL_TEST_URL='mysql+pymysql://autoedit:autoedit_dev_password@127.0.0.1:33306/autoedit' \
  env -u VIRTUAL_ENV uv run pytest tests/test_mysql_integration.py -q
```

## Deploy/update on Unraid

```bash
scp -i /home/hermeswebui/.hermes/home/.ssh/id_ed25519 infra/mysql/compose.yaml \
  root@192.168.50.50:/mnt/user/appdata/autoedit-mysql/compose.yaml
ssh -i /home/hermeswebui/.hermes/home/.ssh/id_ed25519 root@192.168.50.50 \
  'cd /mnt/user/appdata/autoedit-mysql && docker compose up -d'
```

## Production note

This is a dev/test database. For production, replace all passwords, keep secrets in `.env`, and do not expose MySQL publicly.
