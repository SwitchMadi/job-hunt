"""
Process Slack interactivity for captcha human tasks: confirm modals, then update users.captcha_tasks.
Configure Slack Interactivity Request URL to this API Gateway path.

Block actions open a modal via Slack Web API (views.open); view_submission updates Postgres.
"""

import base64
import hashlib
import hmac
import json
import os
import time
from typing import Any, Dict, Optional, Tuple
from urllib.parse import parse_qs

import requests

from utilities import constants
from utilities.logging import get_logger
from utilities.sql import get_sql_connection

logger = get_logger(name="process_slack_captcha_actions")


class ProcessSlackCaptchaActionsHandler:
    """Verify Slack signatures, route block_actions / view_submission, update Postgres."""

    def __init__(self):
        self._signing_secret = (os.getenv("SLACK_SIGNING_SECRET") or "").strip()
        self._bot_token = (os.getenv("SLACK_BOT_TOKEN") or "").strip()

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
        if ptype == "view_submission":
            return self._on_view_submission(payload)

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

        if action_id == constants.SLACK_CAPTCHA_ACTION_MARK_SOLVED:
            self._open_confirm_modal_via_api(
                payload,
                raw_value,
                constants.SLACK_CAPTCHA_VIEW_SOLVED_CONFIRM,
                "Captcha solved?",
                "Mark this captcha task as *solved* and let automation continue?",
            )
            return {"statusCode": 200, "body": ""}
        if action_id == constants.SLACK_CAPTCHA_ACTION_MARK_FAILED:
            self._open_confirm_modal_via_api(
                payload,
                raw_value,
                constants.SLACK_CAPTCHA_VIEW_FAILED_CONFIRM,
                "Captcha failed?",
                "Mark this captcha task as *failed* (could not solve)?",
            )
            return {"statusCode": 200, "body": ""}

        return {"statusCode": 200, "body": ""}

    def _open_confirm_modal_via_api(
        self,
        payload: Dict[str, Any],
        task_id_str: str,
        callback_id: str,
        title: str,
        question_md: str,
    ) -> None:
        try:
            int(task_id_str)
        except ValueError:
            logger.warning("Invalid captcha task id: %s", task_id_str)
            return

        trigger_id = payload.get("trigger_id")
        if not trigger_id:
            logger.warning("Missing trigger_id for modal")
            return

        if not self._bot_token:
            logger.error("SLACK_BOT_TOKEN is not set; cannot open confirmation modal")
            return

        view = {
            "type": "modal",
            "callback_id": callback_id,
            "private_metadata": json.dumps({"task_id": task_id_str}),
            "title": {"type": "plain_text", "text": title[:24]},
            "submit": {"type": "plain_text", "text": "Confirm"},
            "close": {"type": "plain_text", "text": "Cancel"},
            "blocks": [
                {
                    "type": "section",
                    "text": {"type": "mrkdwn", "text": question_md},
                }
            ],
        }

        try:
            resp = requests.post(
                "https://slack.com/api/views.open",
                headers={
                    "Authorization": f"Bearer {self._bot_token}",
                    "Content-Type": "application/json; charset=utf-8",
                },
                json={"trigger_id": trigger_id, "view": view},
                timeout=10,
            )
            data = resp.json()
            if not data.get("ok"):
                logger.error("views.open failed: %s", data.get("error"))
        except requests.RequestException as e:
            logger.exception("views.open request failed: %s", e)

    def _on_view_submission(self, payload: Dict[str, Any]) -> Dict[str, Any]:
        view = payload.get("view") or {}
        callback_id = view.get("callback_id")
        if callback_id not in (
            constants.SLACK_CAPTCHA_VIEW_SOLVED_CONFIRM,
            constants.SLACK_CAPTCHA_VIEW_FAILED_CONFIRM,
        ):
            return {"statusCode": 200, "body": ""}

        meta_raw = view.get("private_metadata") or "{}"
        try:
            meta = json.loads(meta_raw)
        except json.JSONDecodeError:
            logger.warning("Invalid private_metadata")
            return self._clear_modal_response()

        task_id = meta.get("task_id")
        try:
            tid = int(task_id)
        except (TypeError, ValueError):
            return self._clear_modal_response()

        user = payload.get("user") or {}
        slack_user_id = user.get("id") or ""
        if not slack_user_id:
            return self._clear_modal_response()

        if callback_id == constants.SLACK_CAPTCHA_VIEW_SOLVED_CONFIRM:
            ok = self._finalize_task(
                tid, slack_user_id, "completed", "Confirmed solved via Slack"
            )
        else:
            ok = self._finalize_task(
                tid, slack_user_id, "failed", "Marked failed via Slack (could not solve)"
            )

        if ok:
            logger.info(
                "captcha_tasks id=%s set to %s by %s", tid, callback_id, slack_user_id
            )
        else:
            logger.info("captcha_tasks id=%s not updated (not pending or missing)", tid)

        return self._clear_modal_response()

    @staticmethod
    def _clear_modal_response() -> Dict[str, Any]:
        return {
            "statusCode": 200,
            "headers": {"Content-Type": "application/json"},
            "body": json.dumps({"response_action": "clear"}),
        }

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
