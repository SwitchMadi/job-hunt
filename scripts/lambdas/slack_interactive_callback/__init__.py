"""
Slack interactivity URL: block_actions for captcha completion → users.slack_interactive_requests.
"""

import json
import os
from typing import Optional

from utilities.logging import get_logger
from utilities.slack_interactive_request import (
    SLACK_ACTION_CAPTCHA_COMPLETED,
    get_header,
    parse_interactive_payload,
    verify_slack_signature,
)
from utilities.sql import get_sql_connection

logger = get_logger(name="slack_interactive_callback")

def _update_request_completed(
    request_id: int,
    slack_user_id: str,
    resolution_notes: Optional[str] = None,
) -> bool:
    notes = resolution_notes or "Marked completed via Slack"
    con = get_sql_connection()
    try:
        cur = con.cursor()
        cur.execute(
            """
            UPDATE users.slack_interactive_requests
            SET status = 'completed',
                completed_by_slack_user_id = %s,
                completed_at = NOW(),
                resolution_notes = %s,
                updated_at = NOW()
            WHERE id = %s
              AND status = 'pending';
            """,
            (slack_user_id, notes, request_id),
        )
        updated = cur.rowcount > 0
        con.commit()
        return updated
    except Exception:
        con.rollback()
        raise
    finally:
        con.close()


def _process_block_actions(payload: dict) -> dict:
    actions = payload.get("actions") or []
    if not actions:
        return {"ok": True, "ignored": True}

    user = payload.get("user") or {}
    slack_user_id = user.get("id") or ""

    for action in actions:
        action_id = action.get("action_id")
        if action_id != SLACK_ACTION_CAPTCHA_COMPLETED:
            continue
        raw_value = action.get("value") or ""
        try:
            request_id = int(raw_value.strip())
        except ValueError:
            logger.warning("Invalid captcha action value: %s", raw_value)
            return {"ok": False, "error": "invalid_value"}

        if not slack_user_id:
            logger.warning("Missing Slack user on captcha completion action")
            return {"ok": False, "error": "missing_user"}

        updated = _update_request_completed(request_id, slack_user_id)
        if updated:
            logger.info(
                "slack_interactive_requests id=%s marked completed by %s",
                request_id,
                slack_user_id,
            )
        else:
            logger.info(
                "No pending row updated for id=%s (already completed or missing)",
                request_id,
            )
        return {"ok": True, "updated": updated}

    return {"ok": True, "ignored": True}


def lambda_handler(event, context):
    del context

    signing_secret = (os.getenv("SLACK_SIGNING_SECRET") or "").strip()
    if not signing_secret:
        logger.error("SLACK_SIGNING_SECRET is not set")
        return {"statusCode": 500, "body": json.dumps({"error": "server_misconfigured"})}

    headers = event.get("headers") or {}
    raw_body = event.get("body") or ""
    if event.get("isBase64Encoded"):
        import base64

        raw_body = base64.b64decode(raw_body).decode("utf-8")

    sig = get_header(headers, "X-Slack-Signature")
    ts = get_header(headers, "X-Slack-Request-Timestamp")
    if not verify_slack_signature(
        signing_secret=signing_secret,
        request_timestamp=ts,
        raw_body=raw_body,
        slack_signature=sig,
    ):
        logger.warning("Slack signature verification failed")
        return {"statusCode": 401, "body": ""}

    payload, err = parse_interactive_payload(raw_body)
    if err:
        logger.warning("Bad interactive payload: %s", err)
        return {"statusCode": 400, "body": ""}

    ptype = payload.get("type")
    if ptype == "block_actions":
        _process_block_actions(payload)
    else:
        logger.info("Ignoring Slack interactive type: %s", ptype)

    return {"statusCode": 200, "body": ""}
