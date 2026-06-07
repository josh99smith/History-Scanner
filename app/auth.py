"""Minimal password gate for public deployments.

When ``ACCESS_PASSWORD`` is set, the app requires a login. We avoid extra
dependencies by signing a session cookie with an HMAC derived from the password
itself (so there is no separate secret to manage). When no password is
configured, every check is a no-op and the app is fully open.
"""

from __future__ import annotations

import hmac
from hashlib import sha256

from .config import settings

COOKIE_NAME = "hs_session"
# ~30 days
COOKIE_MAX_AGE = 30 * 24 * 3600


def _expected_token() -> str:
    pw = (settings.access_password or "").encode()
    return hmac.new(pw, b"history-scanner-auth-v1", sha256).hexdigest()


def check_password(candidate: str | None) -> bool:
    """Constant-time comparison of a submitted password."""
    if not settings.auth_enabled:
        return True
    return hmac.compare_digest(candidate or "", settings.access_password or "")


def issue_cookie_value() -> str:
    return _expected_token()


def cookie_is_valid(value: str | None) -> bool:
    if not settings.auth_enabled:
        return True
    if not value:
        return False
    return hmac.compare_digest(value, _expected_token())
