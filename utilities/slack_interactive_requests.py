"""Postgres helpers for users.slack_interactive_requests (no job-domain logic)."""

from typing import Optional

from psycopg2 import errors as pg_errors

from utilities.logging import get_logger
from utilities.sql import get_sql_connection

logger = get_logger(name="slack_interactive_requests")


def pending_captcha_request_exists(job_application_id: Optional[int]) -> bool:
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


def insert_pending_captcha_request(
    *,
    job_application_id: Optional[int],
    job_id: Optional[int],
    user_id: Optional[int],
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
                user_id
            )
            VALUES ('captcha_dcv', 'pending', %s, %s, %s)
            RETURNING id;
            """,
            (job_application_id, job_id, user_id),
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


def update_slack_delivery_metadata(
    request_id: int,
    *,
    slack_channel_id: str,
    slack_message_ts_epoch_ms: int,
    slack_message_id: Optional[str] = None,
) -> None:
    con = get_sql_connection()
    try:
        cur = con.cursor()
        cur.execute(
            """
            UPDATE users.slack_interactive_requests
            SET slack_channel_id = %s,
                slack_message_ts_epoch_ms = %s,
                slack_message_id = %s,
                updated_at = NOW()
            WHERE id = %s;
            """,
            (
                slack_channel_id,
                slack_message_ts_epoch_ms,
                slack_message_id,
                request_id,
            ),
        )
        con.commit()
    finally:
        con.close()
