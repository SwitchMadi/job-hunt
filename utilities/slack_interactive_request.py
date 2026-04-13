"""
Verify and parse Slack interactivity (HTTP) requests — URL-encoded payload + signing secret.
"""

# Must match Block Kit ``action_id`` on the job-application captcha message and the interactivity Lambda.
SLACK_ACTION_CAPTCHA_COMPLETED = "captcha_mark_completed"

import hashlib
import hmac
import json
import time
from typing import Any, Dict, Optional, Tuple
from urllib.parse import parse_qs


def verify_slack_signature(
    *,
    signing_secret: str,
    request_timestamp: str,
    raw_body: str,
    slack_signature: str,
    max_age_seconds: int = 300,
) -> bool:
    """
    Slack signing: base string ``v0:{timestamp}:{body}``, compare to ``X-Slack-Signature``.
    """
    if not signing_secret or not slack_signature or not request_timestamp:
        return False
    try:
        ts = int(request_timestamp)
    except (TypeError, ValueError):
        return False
    if abs(int(time.time()) - ts) > max_age_seconds:
        return False
    basestring = f"v0:{request_timestamp}:{raw_body}".encode("utf-8")
    digest = hmac.new(
        signing_secret.encode("utf-8"),
        basestring,
        hashlib.sha256,
    ).hexdigest()
    expected = f"v0={digest}"
    return hmac.compare_digest(expected, slack_signature)


def parse_interactive_payload(form_body: str) -> Tuple[Optional[Dict[str, Any]], Optional[str]]:
    """
    Parse ``application/x-www-form-urlencoded`` body; return (payload_dict, error_reason).
    """
    if not form_body:
        return None, "empty_body"
    parsed = parse_qs(form_body, keep_blank_values=True)
    payload_list = parsed.get("payload")
    if not payload_list:
        return None, "missing_payload"
    try:
        return json.loads(payload_list[0]), None
    except json.JSONDecodeError:
        return None, "invalid_json"


def get_header(headers: Dict[str, str], name: str) -> str:
    if not headers:
        return ""
    lower = {k.lower(): v for k, v in headers.items()}
    val = lower.get(name.lower(), "")
    return val if isinstance(val, str) else str(val)
