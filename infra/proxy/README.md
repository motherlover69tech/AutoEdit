# AUTOEDIT reverse proxy reference (non-canonical)

Peter's active AUTOEDIT deployment uses **Nginx Proxy Manager** as the public TLS boundary:

```text
https://ingest.peteflix.uk → http://192.168.50.50:8010
```

Use `docs/DEPLOYMENT.md` for the canonical deployment runbook.

The files in this directory are historical/reference material for a possible Caddy deployment. Do **not** treat them as the live Unraid deployment path unless Peter explicitly decides to replace NPM with Caddy.

## Files

- `Caddyfile` — historical Caddy TLS + reverse-proxy template.

## Historical Caddy env

```env
PUBLIC_DOMAIN=autoedit.example.com
APP_UPSTREAM=http://app:8000
ACME_EMAIL=you@example.com
```

## Security rules that still apply to any proxy

- Only the proxy should be internet-facing.
- Do **not** mount or serve `/data`/`DATA_ROOT` from the proxy.
- App routes remain protected by signed httpOnly session cookies.
- Backend origin checks should use the same public domain value.

## Manual Stage 7.0 proxy gate

Stage 7.0 cannot be marked fully done until the active NPM deployment verifies:

1. `https://ingest.peteflix.uk/health` returns `{"status":"ok"}`.
2. `http://ingest.peteflix.uk/...` redirects to `https://ingest.peteflix.uk/...`.
3. `https://ingest.peteflix.uk/projects` or other protected routes return `401` without a session.
4. TLS certificate is valid in a browser.
5. No `/data` path is served directly by the proxy.
