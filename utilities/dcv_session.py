"""DCV browser session URL and token signing (configuration from config.yml; secret from env)."""

import hashlib
import hmac
import os
import secrets
from typing import Any, Dict, Tuple


class DcvSession:
    """Builds DCV web client URLs and HMAC token pairs for DynamoDB-backed validation."""

    def __init__(self, app_config: Dict[str, Any]):
        self._dcv = app_config.get("dcv") or {}

    def web_port(self) -> int:
        raw = self._dcv.get("web_port", 8445)
        try:
            return int(raw)
        except (TypeError, ValueError):
            return 8445

    def token_ttl_seconds(self) -> int:
        raw = self._dcv.get("session_token_ttl_seconds", 3600)
        try:
            return int(raw)
        except (TypeError, ValueError):
            return 3600

    def create_token_pair(self) -> Tuple[str, str]:
        """Returns (token, hmac_sha256_hex) for query string and DynamoDB."""
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

    def build_browser_url(self, public_host: str, token: str) -> str:
        host = public_host.strip().rstrip("/")
        port = self.web_port()
        return f"https://{host}:{port}/?token={token}"
