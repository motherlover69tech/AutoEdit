# Stage 7.0 Auth Gate + Reverse Proxy Implementation Plan

> **For Hermes:** Use test-driven-development for backend auth behavior. Do not expose upload/media routes until this gate is complete.

**Goal:** Ensure nobody reaches the app or media endpoints without TLS and an authenticated session, while keeping `/health` and ACME challenge paths public.

**Architecture:** Add a FastAPI auth layer with signed httpOnly session cookies, shared operator-password login for the first deploy, reviewer display-name persistence in the session, brute-force login lockout, and explicit origin checks tied to `PUBLIC_DOMAIN`. Peter's active deployment uses Nginx Proxy Manager for TLS termination and HTTP→HTTPS redirect. Keep the temporary MySQL dev container non-canonical.

**Tech Stack:** Python 3.12, FastAPI middleware/dependencies, SQLAlchemy-backed API, stdlib HMAC session signing, pytest/TestClient, Nginx Proxy Manager.

---

## Current status

Backend auth/session/rate-limit/origin behavior is implemented and live-deployed. Nginx Proxy Manager terminates TLS for `ingest.peteflix.uk` and proxies to the host-networked app at `192.168.50.50:8010`. Public `/health` returns 200, protected routes return 401 without a session, login sets a secure httpOnly cookie, and `/data` is not exposed. Stage 7.0 is complete for the current Unraid deployment.

## Source requirements

From `docs/source/multicam_autoedit_spec.md`:

- Section 1.3: TLS everywhere, auth required for every route except health/ACME, rate limiting/brute-force protection, no unauthenticated media, CORS/origin locked to `PUBLIC_DOMAIN`, secrets via env only.
- Stage 7.0: proxy container terminates HTTPS for `PUBLIC_DOMAIN`; login endpoint; signed httpOnly cookies; rate-limit auth/upload; CORS locked to `PUBLIC_DOMAIN`.
- Definition of Done: all routes except health + ACME require session; TLS cert provisions/plain HTTP redirects; brute-force lockout after N failed logins; reviewer display name can be attached to later notes.

## Current non-goals / remaining boundary

- Backend auth, upload protection, authenticated media streaming, and the NPM/TLS deployment are complete for Peter's Unraid instance.
- No per-user database accounts yet; single shared operator password remains acceptable per spec minimum.
- Keep `SESSION_SECRET`, operator password, and DB password configured outside the repo.

## Task 1: Write backend auth gate tests

**Objective:** Lock the security contract before implementation.

**Files:**
- Create: `tests/test_auth_gate.py`
- Modify as needed: `tests/test_projects_api.py`

**Tests to add:**

1. `/health` is public with auth enabled.
2. `/.well-known/acme-challenge/<token>` is public enough to not fail auth, even if it returns 404 due no static challenge handler.
3. `POST /projects` returns `401` without a session when auth is enabled.
4. `POST /auth/login` with correct shared password and display name returns `204` and sets an httpOnly session cookie.
5. Authenticated `POST /projects` succeeds with the returned cookie.
6. `GET /auth/me` returns the reviewer display name from the session.
7. Repeated failed logins trigger `429` after the configured threshold.
8. Requests with an unexpected `Origin` header return `403`; allowed `https://PUBLIC_DOMAIN` passes.

**Run to verify RED:**

```bash
env -u VIRTUAL_ENV uv run pytest tests/test_auth_gate.py -q
```

Expected before implementation: failures/errors because auth endpoints/middleware do not exist yet.

## Task 2: Add auth settings

**Objective:** Document and load the env values required for public deployment.

**Files:**
- Modify: `src/autoedit/config.py`
- Modify: `.env.example`

**Settings:**

- `AUTH_ENABLED=true` by default for deployed `create_app()`.
- `SESSION_SECRET` — required for meaningful authenticated deployment; no default secret in repo.
- `OPERATOR_PASSWORD` — shared initial password; never committed.
- `SESSION_COOKIE_NAME=autoedit_session`.
- `SESSION_COOKIE_SECURE=true` for public deployments.
- `LOGIN_MAX_FAILURES=5`.
- `LOGIN_LOCKOUT_SECONDS=300`.
- `PUBLIC_DOMAIN` drives allowed origin `https://PUBLIC_DOMAIN`.

**Verification:** config unit/behavior tests in `tests/test_auth_gate.py` should use explicit injected settings or `create_app` keyword overrides so normal offline tests remain deterministic.

## Task 3: Implement signed session utilities

**Objective:** Create minimal stdlib session signing without introducing secrets into files.

**Files:**
- Create: `src/autoedit/auth.py`

**Behavior:**

- Encode a JSON payload containing reviewer display name and expiry.
- Sign with HMAC-SHA256 using `SESSION_SECRET`.
- Base64url encode token parts.
- Reject tampered, malformed, or expired tokens.
- Do not log token contents.

**Run:**

```bash
env -u VIRTUAL_ENV uv run pytest tests/test_auth_gate.py -q
```

Expected after this task: session utility tests/indirect login tests may still fail until middleware/endpoints exist.

## Task 4: Implement login/session endpoints and route protection

**Objective:** Enforce auth on all non-public routes.

**Files:**
- Modify: `src/autoedit/api.py`
- Use: `src/autoedit/auth.py`

**Routes:**

- Public: `GET /health`.
- Public auth endpoint: `POST /auth/login` because users must be able to obtain a session.
- Protected: `GET /auth/me`, `POST /auth/logout`, all existing `/projects...` routes.
- Public ACME prefix: `/.well-known/acme-challenge/` should bypass auth; returning 404 is acceptable until proxy/static challenge handling exists.

**Login payload:**

```json
{ "password": "...", "display_name": "Peter" }
```

**Session cookie:** signed, httpOnly, SameSite=Lax, Secure controlled by config.

**Run:**

```bash
env -u VIRTUAL_ENV uv run pytest tests/test_auth_gate.py -q
env -u VIRTUAL_ENV uv run pytest -q
```

## Task 5: Add brute-force lockout and origin checks

**Objective:** Complete backend security behavior required before public exposure.

**Files:**
- Modify: `src/autoedit/auth.py`
- Modify: `src/autoedit/api.py`

**Behavior:**

- Track failed login attempts by client host in memory.
- Return `429` once `LOGIN_MAX_FAILURES` is reached inside the lockout window.
- Reset failure count on successful login.
- If `PUBLIC_DOMAIN` is configured and request has `Origin`, allow only `https://PUBLIC_DOMAIN`; return `403` otherwise.
- Keep requests with no `Origin` valid for server-side clients and same-origin non-browser calls.

**Run:**

```bash
env -u VIRTUAL_ENV uv run pytest tests/test_auth_gate.py -q
env -u VIRTUAL_ENV uv run pytest -q
```

## Task 6: Configure Nginx Proxy Manager route

**Objective:** Document and verify the TLS boundary without serving `/data` directly.

**Files:**
- Modify: `docs/DEPLOYMENT.md`
- Keep: `infra/proxy/` as historical/non-canonical reference only unless Peter explicitly revives Caddy.

**NPM behavior:**

- `http://ingest.peteflix.uk` redirects to HTTPS.
- `https://ingest.peteflix.uk` terminates TLS and proxies to `192.168.50.50:8010`.
- Preserve `X-Forwarded-*` headers.
- Do not serve `/data` statically.
- Optional proxy-level rate limits can be added later; backend lockout remains required.

**Manual gate:** TLS cert provisioning can only be marked done when the NPM route is live and `/health`, protected-route `401`, login cookie, HTTP→HTTPS redirect, and no direct `/data` exposure have been verified.

## Task 7: Update continuity docs and commit

**Objective:** Leave the project resumable.

**Files:**
- Modify: `AI_HANDOFF.md`
- Modify: `jobs/BACKLOG.md`
- Modify: `docs/plans/TESTING_STRATEGY.md`

**Status rules:**

- Mark Stage 7.0 `done` for Peter's current Unraid/NPM deployment. If a future deployment target changes, re-run the same health/auth/login/redirect/no-`/data` manual gate before marking that new target complete.

**Final verification commands:**

```bash
env -u VIRTUAL_ENV uv run pytest -q
DB_HOST=192.168.50.50 DB_PORT=3306 DB_NAME=autoedit DB_USER=autoedit DB_PASSWORD='***' env -u VIRTUAL_ENV uv run pytest -q
```

**Commit:**

```bash
git add .
git commit -m "feat: add stage 7 auth gate"
```
