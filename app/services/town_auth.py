"""Signed session cookies and CSRF tokens for the town dashboard (stdlib only).

Session token: "<issued_at>.<nonce>.<signature>", where signature is HMAC-SHA256 over
"session|<issued_at>|<nonce>" with SESSION_SECRET. The cookie holds no user data. Tokens expire
SESSION_MAX_AGE seconds after they're issued. Signing out records the nonce in the app DB's
revoked_sessions table (the nonce is random, not personal data) so a copied cookie stops working.

CSRF token: HMAC-SHA256 over "csrf|<nonce>", so it's tied to one session and can't be forged
without the secret.

The dashboard password is only ever compared with hmac.compare_digest; it's never stored,
logged, or put in a token.
"""
import hashlib
import hmac
import secrets
import time
from contextlib import closing
from pathlib import Path

from app.config import Settings
from app.db import connect

SESSION_COOKIE = "tw_town_session"
SESSION_MAX_AGE = 8 * 60 * 60  # 8 hours
MIN_SECRET_CHARS = 32
CLOCK_SKEW_SECONDS = 60


def is_configured(settings: Settings) -> bool:
    return bool(
        settings.dashboard_password
        and settings.session_secret
        and len(settings.session_secret) >= MIN_SECRET_CHARS
    )


def check_password(settings: Settings, supplied: str) -> bool:
    expected = (settings.dashboard_password or "").encode("utf-8")
    # Compare fixed-length digests so timing doesn't reveal the password's length.
    # An empty expected password never matches.
    supplied_digest = hashlib.sha256(supplied.encode("utf-8")).digest()
    expected_digest = hashlib.sha256(expected).digest()
    return bool(expected) and hmac.compare_digest(supplied_digest, expected_digest)


def _sign(secret: str, message: str) -> str:
    return hmac.new(secret.encode("utf-8"), message.encode("utf-8"), hashlib.sha256).hexdigest()


def issue_session(secret: str, now: float | None = None) -> str:
    issued = int(now if now is not None else time.time())
    nonce = secrets.token_urlsafe(24)
    return f"{issued}.{nonce}.{_sign(secret, f'session|{issued}|{nonce}')}"


def session_info(secret: str, token: str | None, now: float | None = None) -> tuple[str, int] | None:
    """(nonce, issued_at) when the token is genuine and unexpired, else None."""
    if not token or len(token) > 256 or not token.isascii():
        return None
    parts = token.split(".")
    if len(parts) != 3:
        return None
    issued_text, nonce, sig = parts
    if not issued_text.isdigit() or not nonce:
        return None
    expected = _sign(secret, f"session|{issued_text}|{nonce}")
    if not hmac.compare_digest(sig.encode("ascii"), expected.encode("ascii")):
        return None
    now = now if now is not None else time.time()
    issued = int(issued_text)
    if issued > now + CLOCK_SKEW_SECONDS or now - issued >= SESSION_MAX_AGE:
        return None
    return nonce, issued


def verify_session(secret: str, token: str | None, now: float | None = None) -> str | None:
    """The session nonce when the token is genuine and unexpired, else None."""
    info = session_info(secret, token, now)
    return info[0] if info else None


def csrf_token(secret: str, nonce: str) -> str:
    return _sign(secret, f"csrf|{nonce}")


def check_csrf(secret: str, nonce: str, supplied: str | None) -> bool:
    if not supplied or not supplied.isascii():
        return False
    return hmac.compare_digest(supplied.encode("ascii"), csrf_token(secret, nonce).encode("ascii"))


# --- Revocation -----------------------------------------------------------------------------


def revoke_session(app_db: Path, nonce: str, issued_at: int, now: float | None = None) -> None:
    """Record a signed-out session until it would have expired anyway, and prune old rows."""
    now = int(now if now is not None else time.time())
    with closing(connect(app_db)) as con, con:
        con.execute("DELETE FROM revoked_sessions WHERE expires_at <= ?", (now,))
        con.execute(
            "INSERT OR REPLACE INTO revoked_sessions (nonce, expires_at) VALUES (?, ?)",
            (nonce, issued_at + SESSION_MAX_AGE),
        )


def is_revoked(app_db: Path, nonce: str) -> bool:
    with closing(connect(app_db)) as con:
        return con.execute("SELECT 1 FROM revoked_sessions WHERE nonce = ?", (nonce,)).fetchone() is not None
