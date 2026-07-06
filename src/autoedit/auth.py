from __future__ import annotations

import base64
import hashlib
import hmac
import json
import secrets
import time
from dataclasses import dataclass, field
from typing import Any


SESSION_TTL_SECONDS = 60 * 60 * 24 * 7
PASSWORD_HASH_ITERATIONS = 260_000


def _b64encode(data: bytes) -> str:
    return base64.urlsafe_b64encode(data).decode("ascii").rstrip("=")


def _b64decode(data: str) -> bytes:
    padding = "=" * (-len(data) % 4)
    return base64.urlsafe_b64decode(f"{data}{padding}".encode("ascii"))


def create_session_token(
    *,
    display_name: str,
    secret: str,
    username: str | None = None,
    role: str | None = None,
    user_id: str | None = None,
    ttl_seconds: int = SESSION_TTL_SECONDS,
    now: float | None = None,
) -> str:
    issued_at = int(now if now is not None else time.time())
    payload = {
        "display_name": display_name,
        "exp": issued_at + ttl_seconds,
    }
    if username:
        payload["username"] = username
    if role:
        payload["role"] = role
    if user_id:
        payload["user_id"] = user_id
    payload_bytes = json.dumps(payload, separators=(",", ":"), sort_keys=True).encode("utf-8")
    payload_b64 = _b64encode(payload_bytes)
    signature = hmac.new(secret.encode("utf-8"), payload_b64.encode("ascii"), hashlib.sha256)
    return f"{payload_b64}.{_b64encode(signature.digest())}"


def parse_session_token(token: str | None, *, secret: str, now: float | None = None) -> dict[str, Any] | None:
    if not token or "." not in token:
        return None
    payload_b64, signature_b64 = token.split(".", 1)
    expected = hmac.new(secret.encode("utf-8"), payload_b64.encode("ascii"), hashlib.sha256)
    if not hmac.compare_digest(_b64encode(expected.digest()), signature_b64):
        return None

    try:
        payload = json.loads(_b64decode(payload_b64))
    except (ValueError, json.JSONDecodeError):
        return None

    expires_at = payload.get("exp")
    if not isinstance(expires_at, int):
        return None
    current_time = int(now if now is not None else time.time())
    if expires_at < current_time:
        return None

    display_name = payload.get("display_name")
    if not isinstance(display_name, str) or not display_name.strip():
        return None

    parsed: dict[str, Any] = {"display_name": display_name}
    for key in ("username", "role", "user_id"):
        value = payload.get(key)
        if isinstance(value, str) and value.strip():
            parsed[key] = value
    return parsed


def hash_password(password: str, *, salt: str | None = None, iterations: int = PASSWORD_HASH_ITERATIONS) -> str:
    if not password:
        raise ValueError("password is required")
    salt_value = salt or secrets.token_urlsafe(18)
    digest = hashlib.pbkdf2_hmac(
        "sha256",
        password.encode("utf-8"),
        salt_value.encode("utf-8"),
        iterations,
    )
    return f"pbkdf2_sha256${iterations}${salt_value}${_b64encode(digest)}"


def verify_password(password: str, stored_hash: str | None) -> bool:
    if not password or not stored_hash:
        return False
    try:
        scheme, iter_str, salt, digest = stored_hash.split("$", 3)
        if scheme != "pbkdf2_sha256":
            return False
        iterations = int(iter_str)
    except (ValueError, TypeError):
        return False
    candidate = hash_password(password, salt=salt, iterations=iterations)
    return hmac.compare_digest(candidate, stored_hash)


@dataclass
class LoginRateLimiter:
    max_failures: int
    lockout_seconds: int
    failures: dict[str, tuple[int, float]] = field(default_factory=dict)

    def is_allowed(self, key: str, now: float | None = None) -> bool:
        count, first_failure_at = self.failures.get(key, (0, 0.0))
        if count < self.max_failures:
            return True
        current_time = now if now is not None else time.time()
        if current_time - first_failure_at >= self.lockout_seconds:
            self.failures.pop(key, None)
            return True
        return False

    def record_failure(self, key: str, now: float | None = None) -> None:
        current_time = now if now is not None else time.time()
        count, first_failure_at = self.failures.get(key, (0, current_time))
        if current_time - first_failure_at >= self.lockout_seconds:
            count = 0
            first_failure_at = current_time
        self.failures[key] = (count + 1, first_failure_at)

    def record_success(self, key: str) -> None:
        self.failures.pop(key, None)
