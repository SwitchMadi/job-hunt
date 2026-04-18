"""
Process Slack interactivity for captcha human tasks: update users.captcha_tasks.
Configure Slack Interactivity Request URL to this API Gateway path.

Buttons use Block Kit ``confirm`` so Slack shows the confirmation UI; this Lambda runs only
after the user confirms (Slack then sends ``block_actions``).
"""

import base64
import hashlib
import hmac
import json
import os
import time
from typing import Any, Dict, Optional, Tuple
from urllib.parse import parse_qs

from utilities import constants
from utilities.logging import get_logger
from utilities.sql import get_sql_connection

logger = get_logger(name="process_slack_captcha_actions")


class ProcessSlackCaptchaActionsHandler:
    """Verify Slack signatures, handle block_actions after user-confirmed clicks, update Postgres."""

    def __init__(self):
        self._signing_secret = (os.getenv("SLACK_SIGNING_SECRET") or "").strip()

    def handle(self, event: Dict[str, Any], context: Any) -> Dict[str, Any]:
        del context
        if not self._signing_secret:
            logger.error("SLACK_SIGNING_SECRET is not set")
            return self._json_response(500, {"error": "server_misconfigured"})

        headers = event.get("headers") or {}
        raw_body = self._raw_body_from_event(event)
        if not self._verify_slack_signature(headers, raw_body):
            logger.warning("Slack signature verification failed")
            return {"statusCode": 401, "body": ""}

        payload, err = self._parse_interactive_payload(raw_body)
        if err:
            logger.warning("Bad interactive payload: %s", err)
            return {"statusCode": 400, "body": ""}

        ptype = payload.get("type")
        if ptype == "block_actions":
            return self._on_block_actions(payload)

        logger.info("Ignoring Slack interactive type: %s", ptype)
        return {"statusCode": 200, "body": ""}

    @staticmethod
    def _raw_body_from_event(event: Dict[str, Any]) -> str:
        body = event.get("body") or ""
        if event.get("isBase64Encoded"):
            body = base64.b64decode(body).decode("utf-8")
        return body

    def _verify_slack_signature(self, headers: Dict[str, str], raw_body: str) -> bool:
        sig = self._header(headers, "X-Slack-Signature")
        ts = self._header(headers, "X-Slack-Request-Timestamp")
        if not sig or not ts:
            return False
        try:
            age = abs(int(time.time()) - int(ts))
        except (TypeError, ValueError):
            return False
        if age > 300:
            return False
        basestring = f"v0:{ts}:{raw_body}".encode("utf-8")
        digest = hmac.new(
            self._signing_secret.encode("utf-8"),
            basestring,
            hashlib.sha256,
        ).hexdigest()
        expected = f"v0={digest}"
        return hmac.compare_digest(expected, sig)

    @staticmethod
    def _header(headers: Dict[str, str], name: str) -> str:
        lower = {k.lower(): v for k, v in (headers or {}).items()}
        val = lower.get(name.lower(), "")
        return val if isinstance(val, str) else str(val)

    @staticmethod
    def _parse_interactive_payload(form_body: str) -> Tuple[Optional[Dict], Optional[str]]:
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

    def _on_block_actions(self, payload: Dict[str, Any]) -> Dict[str, Any]:
        actions = payload.get("actions") or []
        if not actions:
            return {"statusCode": 200, "body": ""}

        action = actions[0]
        action_id = action.get("action_id")
        raw_value = (action.get("value") or "").strip()

        try:
            tid = int(raw_value)
        except ValueError:
            logger.warning("Invalid captcha task id: %s", raw_value)
            return {"statusCode": 200, "body": ""}

        user = payload.get("user") or {}
        slack_user_id = user.get("id") or ""
        if not slack_user_id:
            return {"statusCode": 200, "body": ""}

        if action_id == constants.SLACK_CAPTCHA_ACTION_MARK_SOLVED:
            ok = self._finalize_task(
                tid, slack_user_id, "completed", "Confirmed solved via Slack"
            )
        elif action_id == constants.SLACK_CAPTCHA_ACTION_MARK_FAILED:
            ok = self._finalize_task(
                tid, slack_user_id, "failed", "Marked failed via Slack (could not solve)"
            )
        else:
            return {"statusCode": 200, "body": ""}

        if ok:
            logger.info(
                "captcha_tasks id=%s finalized (%s) by %s",
                tid,
                action_id,
                slack_user_id,
            )
        else:
            logger.info("captcha_tasks id=%s not updated (not pending or missing)", tid)

        return {"statusCode": 200, "body": ""}

    def _finalize_task(
        self,
        task_id: int,
        slack_user_id: str,
        status: str,
        notes: str,
    ) -> bool:
        con = get_sql_connection()
        try:
            cur = con.cursor()
            cur.execute(
                """
                UPDATE users.captcha_tasks
                SET status = %s,
                    completed_by_slack_user_id = %s,
                    completed_at = NOW(),
                    resolution_notes = %s,
                    updated_at = NOW()
                WHERE id = %s
                  AND status = 'pending';
                """,
                (status, slack_user_id, notes, task_id),
            )
            updated = cur.rowcount > 0
            con.commit()
            return updated
        except Exception:
            con.rollback()
            raise
        finally:
            con.close()

    @staticmethod
    def _json_response(code: int, obj: Dict[str, Any]) -> Dict[str, Any]:
        return {
            "statusCode": code,
            "headers": {"Content-Type": "application/json"},
            "body": json.dumps(obj),
        }


def lambda_handler(event, context):
    return ProcessSlackCaptchaActionsHandler().handle(event, context)
