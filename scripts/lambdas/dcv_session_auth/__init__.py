"""
DCV external session authentication (Windows DCV server -> API Gateway -> Lambda).

Expects ``application/x-www-form-urlencoded`` body with ``authenticationToken`` and
optionally ``sessionId`` (logged only). Validates HMAC against DynamoDB and allows
each token only once (sets ``consumedAt`` on success).

Configure DCV ``auth-token-verifier`` URL to this API path, e.g.:
``https://webhook.api.switchmadi.com/prod/dcv/session-auth``
"""

import base64
import os
import urllib.parse
from typing import Any, Dict, Tuple

import yaml

from utilities.aws.dynamo.dcv_session_tokens import DcvSessionTokensTable
from utilities.logging import get_logger

logger = get_logger(name="dcv_session_auth")

# Same pattern as jobs/__init__.py and other modules (cwd = Lambda task root).
config = yaml.safe_load(open("config.yml"))

_XML_YES_TEMPLATE = '<auth result="yes"><username>{username}</username></auth>'
_XML_NO = '<auth result="no"><message>Invalid or expired token</message></auth>'


def _xml_response(status: int, body: str) -> Dict[str, Any]:
    return {
        "statusCode": status,
        "headers": {"Content-Type": "application/xml"},
        "body": body,
    }


def _parse_form_body(event: Dict[str, Any]) -> Tuple[str, str]:
    raw = event.get("body") or ""
    if event.get("isBase64Encoded"):
        raw = base64.b64decode(raw).decode("utf-8")
    form = urllib.parse.parse_qs(raw, keep_blank_values=True)
    token = (form.get("authenticationToken") or [""])[0].strip()
    session_id = (form.get("sessionId") or [""])[0].strip()
    return token, session_id


def lambda_handler(event, context):
    del context

    token, session_id = _parse_form_body(event)
    if session_id:
        logger.info("DCV session auth request sessionId=%s", session_id[:64])

    if not token:
        logger.warning("DCV session auth missing authenticationToken")
        return _xml_response(200, _XML_NO)

    secret = (os.getenv("DCV_SESSION_HMAC_SECRET") or "").strip()
    if not secret:
        logger.error("DCV_SESSION_HMAC_SECRET is not set")
        return _xml_response(500, _XML_NO)

    table_name = ((config.get("aws") or {}).get("dcv_session_tokens_table") or "").strip()
    try:
        table = DcvSessionTokensTable(table_name)
    except ValueError as e:
        logger.error("%s", e)
        return _xml_response(500, _XML_NO)

    outcome = table.consume_token_once(token, hmac_secret=secret)
    if outcome != "consumed":
        logger.info(
            "DCV session auth denied token=%s... outcome=%s",
            token[:8],
            outcome,
        )
        return _xml_response(200, _XML_NO)

    dcv_cfg = config.get("dcv") or {}
    username = (dcv_cfg.get("auth_windows_username") or "JobHunt").strip() or "JobHunt"
    xml = _XML_YES_TEMPLATE.format(username=_escape_xml(username))
    logger.info("DCV session auth granted for sessionId prefix=%s", (session_id or "")[:32])
    return _xml_response(200, xml)


def _escape_xml(text: str) -> str:
    return (
        text.replace("&", "&amp;")
        .replace("<", "&lt;")
        .replace(">", "&gt;")
        .replace('"', "&quot;")
        .replace("'", "&apos;")
    )
