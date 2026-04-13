"""DCV browser URL and session token helpers (not job-application-specific)."""

import hashlib
import hmac
import os
import secrets
from typing import Tuple


def dcv_web_port() -> int:
    raw = os.getenv("DCV_WEB_PORT", "8445")
    try:
        return int(raw)
    except ValueError:
        return 8445


def dcv_token_ttl_seconds() -> int:
    raw = os.getenv("DCV_SESSION_TOKEN_TTL_SECONDS", "3600")
    try:
        return int(raw)
    except ValueError:
        return 3600


def create_dcv_session_token_pair() -> Tuple[str, str]:
    """
    Returns (token, hmac_sha256_hex) for URL query param and DynamoDB verification.
    """
    secret = (os.getenv("DCV_SESSION_HMAC_SECRET") or "").strip()
    if not secret:
        raise ValueError("DCV_SESSION_HMAC_SECRET is not set")

    token = secrets.token_urlsafe(32)
    sig = hmac.new(
        secret.encode("utf-8"),
        token.encode("utf-8"),
        hashlib.sha256,
    ).hexdigest()
    return token, sig


def build_dcv_browser_url(public_host: str, token: str) -> str:
    host = public_host.strip().rstrip("/")
    port = dcv_web_port()
    return f"https://{host}:{port}/?token={token}"
