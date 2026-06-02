# AUTOEDIT reverse proxy

Stage 7.0 requires the public edge to terminate TLS and proxy only to the app container. The app itself enforces session auth on all non-public routes.

## Files

- `Caddyfile` — template for Caddy TLS + reverse proxy.

## Required deployment env

```env
PUBLIC_DOMAIN=autoedit.example.com
APP_UPSTREAM=http://app:8000
ACME_EMAIL=you@example.com
```

## Security rules

- Only the proxy should be internet-facing.
- Do **not** mount or serve `/data`/`DATA_ROOT` from Caddy.
- App routes remain protected by signed httpOnly session cookies.
- Caddy owns ACME challenge handling and redirects HTTP to HTTPS.
- Backend origin checks should use the same `PUBLIC_DOMAIN` value.

## Manual Stage 7.0 proxy gate

Stage 7.0 cannot be marked fully done until deployment verifies:

1. `https://PUBLIC_DOMAIN/health` returns `{"status":"ok"}`.
2. `http://PUBLIC_DOMAIN/...` redirects to `https://PUBLIC_DOMAIN/...`.
3. `https://PUBLIC_DOMAIN/projects` or other protected routes return `401` without a session.
4. TLS certificate is valid in a browser.
5. No `/data` path is served directly by the proxy.
