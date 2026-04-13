"""
Notify humans on Slack when an open captcha blocks job application, with a DCV URL.
Persists a row in Postgres (users.slack_interactive_requests) and a record in DynamoDB for Lambda auth.
"""

from __future__ import annotations

import hashlib
import hmac
import os
import secrets
import time
from typing import TYPE_CHECKING, Any, Dict, List, Optional, Tuple

import yaml
from psycopg2 import errors as pg_errors

from utilities.aws.dynamo.dcv_session_tokens import DcvSessionTokensTable
from utilities.aws.ec2 import resolve_public_host_for_dcv
from utilities.logging import get_logger
from utilities.messaging import MessagingClientFactory
from utilities.sql import get_sql_connection

if TYPE_CHECKING:
    from jobs.page_components.captcha import Captcha

logger = get_logger(name="captcha_human_escalation")

_CAPTCHA_SLACK_TEXT = (
    "Captcha found on the job application page — please solve it in the remote session "
    "and mark complete in Slack when done."
)


def _load_config() -> dict:
    with open("config.yml", encoding="utf-8") as f:
        return yaml.safe_load(f)


def _dcv_port() -> int:
    raw = os.getenv("DCV_WEB_PORT", "8445")
    try:
        return int(raw)
    except ValueError:
        return 8443


def _dcv_token_ttl_seconds() -> int:
    raw = os.getenv("DCV_SESSION_TOKEN_TTL_SECONDS", "3600")
    try:
        return int(raw)
    except ValueError:
        return 3600


def create_dcv_session_token_pair() -> Tuple[str, str]:
    """
    Returns (token, hmac_hex) for URL query param and DynamoDB verification.
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
    port = _dcv_port()
    return f"https://{host}:{port}/?token={token}"


def _slack_channel_from_config(cfg: dict) -> str:
    slack_cfg = cfg.get("slack") or {}
    channel = (slack_cfg.get("captcha_alerts_channel") or "").strip()
    if not channel:
        raise ValueError("config.yml slack.captcha_alerts_channel is not set")
    return channel


def _pending_captcha_request_exists(job_application_id: Optional[int]) -> bool:
    if job_application_id is None:
        return False
    con = get_sql_connection()
    try:
        cur = con.cursor()
        cur.execute(
            """
            SELECT 1
            FROM users.slack_interactive_requests
            WHERE job_application_id = %s
              AND request_kind = 'captcha_dcv'
              AND status = 'pending'
            LIMIT 1;
            """,
            (job_application_id,),
        )
        return cur.fetchone() is not None
    finally:
        con.close()


def _insert_slack_interactive_request(
    *,
    job_application_id: Optional[int],
    job_id: Optional[int],
    user_id: Optional[int],
    dcv_token: str,
    dcv_url: str,
) -> Optional[int]:
    con = get_sql_connection()
    try:
        cur = con.cursor()
        cur.execute(
            """
            INSERT INTO users.slack_interactive_requests (
                request_kind,
                status,
                job_application_id,
                job_id,
                user_id,
                dcv_session_token,
                dcv_public_url
            )
            VALUES ('captcha_dcv', 'pending', %s, %s, %s, %s, %s)
            RETURNING id;
            """,
            (job_application_id, job_id, user_id, dcv_token, dcv_url),
        )
        row = cur.fetchone()
        con.commit()
        return int(row[0]) if row else None
    except pg_errors.UniqueViolation:
        con.rollback()
        return None
    except Exception:
        con.rollback()
        raise
    finally:
        con.close()


def _update_slack_message_metadata(
    request_id: int, slack_channel_id: str, slack_message_ts: str
) -> None:
    con = get_sql_connection()
    try:
        cur = con.cursor()
        cur.execute(
            """
            UPDATE users.slack_interactive_requests
            SET slack_channel_id = %s,
                slack_message_ts = %s,
                updated_at = NOW()
            WHERE id = %s;
            """,
            (slack_channel_id, slack_message_ts, request_id),
        )
        con.commit()
    finally:
        con.close()


def _captcha_slack_blocks(dcv_url: str, job_title: str, application_url: str) -> List[Dict[str, Any]]:
    return [
        {
            "type": "section",
            "text": {
                "type": "mrkdwn",
                "text": (
                    f"*{_CAPTCHA_SLACK_TEXT}*\n"
                    f"*Job:* {job_title}\n"
                    f"*Application page:* {application_url}"
                ),
            },
        },
        {
            "type": "actions",
            "elements": [
                {
                    "type": "button",
                    "text": {"type": "plain_text", "text": "Open DCV session"},
                    "url": dcv_url,
                    "action_id": "open_dcv_session",
                }
            ],
        },
    ]


def escalate_open_captcha_to_slack(
    parent_application_page: Any,
    captcha_component: "Captcha",
) -> bool:
    """
    Post Slack alert with DCV link, Dynamo token row, and Postgres tracking row.
    Returns True if a pending request already exists or notification was sent (or best-effort completed).
    """
    cfg = _load_config()
    job = parent_application_page.parent_job
    job_title = getattr(job, "title", "") or "Unknown job"
    application_url = getattr(parent_application_page, "url", "") or ""
    job_application_id = getattr(parent_application_page, "application_id", None)
    job_id = getattr(job, "id", None)
    user_id = getattr(getattr(job, "user", None), "id", None)

    if _pending_captcha_request_exists(job_application_id):
        logger.info(
            "Skipping duplicate captcha Slack alert; pending request exists for application_id=%s",
            job_application_id,
        )
        return True

    public_host = resolve_public_host_for_dcv()
    if not public_host:
        logger.error("Cannot resolve public host for DCV URL (metadata / DCV_PUBLIC_HOST)")
        return False

    try:
        token, sig = create_dcv_session_token_pair()
    except ValueError as e:
        logger.error("%s", e)
        return False

    dcv_url = build_dcv_browser_url(public_host, token)

    row_id = _insert_slack_interactive_request(
        job_application_id=job_application_id,
        job_id=job_id,
        user_id=user_id,
        dcv_token=token,
        dcv_url=dcv_url,
    )
    if row_id is None:
        logger.info(
            "No new slack_interactive_requests row (unique pending captcha per application); skipping Slack."
        )
        return True

    ttl = int(time.time()) + _dcv_token_ttl_seconds()
    dcv_table = DcvSessionTokensTable()
    dynamo_ok = dcv_table.put_token(
        token,
        sig,
        job_id=str(job_id) if job_id is not None else None,
        user_id=str(user_id) if user_id is not None else None,
        job_application_id=str(job_application_id)
        if job_application_id is not None
        else None,
        slack_request_id=str(row_id),
        ttl_epoch_seconds=ttl,
    )
    if not dynamo_ok:
        logger.error("Failed to store DCV token in DynamoDB for slack_request_id=%s", row_id)

    try:
        channel = _slack_channel_from_config(cfg)
    except ValueError as e:
        logger.error("%s", e)
        return False

    client = MessagingClientFactory.create_client("slack")
    if not client:
        return False

    evidence = getattr(captcha_component, "evidence", None) or ""
    text = f"{_CAPTCHA_SLACK_TEXT} Job: {job_title}. {application_url}"
    if evidence:
        text = f"{text} Evidence: {evidence[:500]}"

    blocks = _captcha_slack_blocks(dcv_url, job_title, application_url)
    result = client.post_message(channel, text, blocks=blocks)

    if result.ok and result.channel and result.message_ts:
        _update_slack_message_metadata(row_id, result.channel, result.message_ts)
        return True

    logger.error(
        "Slack captcha alert failed: %s",
        result.error_message if result else "no client",
    )
    return False


def notify_if_open_captcha(parent_application_page: Any) -> bool:
    """
    Run Captcha.proceed(); if an open captcha is present, notify Slack and return True.
    If no captcha, return False.
    """
    from jobs.page_components.captcha import Captcha

    captcha = Captcha(parent_application_page)
    if not captcha.proceed():
        return False

    escalate_open_captcha_to_slack(parent_application_page, captcha)
    return True
