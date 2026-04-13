import os
from typing import Any, Dict, List, Optional

import requests

from utilities.logging import get_logger

from . import MessagingClientInterface, MessagingResult

logger = get_logger(name="slack_messaging")

_SLACK_API_BASE = "https://slack.com/api"


class SlackMessagingClient(MessagingClientInterface):
    """
    Slack Web API implementation of MessagingClientInterface.
    """

    def __init__(self, bot_token: Optional[str] = None):
        self._token = (bot_token or os.getenv("SLACK_BOT_TOKEN") or "").strip()
        if not self._token:
            logger.error("Slack messaging client initialized without SLACK_BOT_TOKEN")

    def _headers(self) -> Dict[str, str]:
        return {
            "Authorization": f"Bearer {self._token}",
            "Content-Type": "application/json; charset=utf-8",
        }

    def _call_api(self, method: str, payload: Dict[str, Any]) -> MessagingResult:
        if not self._token:
            return MessagingResult(
                ok=False,
                provider="slack",
                error_message="Missing SLACK_BOT_TOKEN",
            )

        url = f"{_SLACK_API_BASE}/{method}"
        try:
            response = requests.post(
                url,
                headers=self._headers(),
                json=payload,
                timeout=30,
            )
            response.raise_for_status()
            data = response.json()
        except requests.RequestException as e:
            logger.exception("Slack API request failed for %s: %s", method, e)
            return MessagingResult(
                ok=False,
                provider="slack",
                error_message=str(e),
            )
        except ValueError as e:
            logger.exception("Slack API returned invalid JSON for %s: %s", method, e)
            return MessagingResult(
                ok=False,
                provider="slack",
                error_message="Invalid JSON response from Slack",
            )

        if not data.get("ok"):
            err = data.get("error", "unknown_error")
            logger.error(
                "Slack API error for %s: %s (channel=%s)",
                method,
                err,
                payload.get("channel"),
            )
            return MessagingResult(
                ok=False,
                provider="slack",
                channel=data.get("channel"),
                error_message=str(err),
                raw_response=data,
            )

        return MessagingResult(
            ok=True,
            provider="slack",
            channel=data.get("channel"),
            message_ts=data.get("ts") or data.get("message", {}).get("ts"),
            raw_response=data,
        )

    def post_message(
        self,
        channel: str,
        text: str,
        *,
        thread_ts: Optional[str] = None,
        blocks: Optional[List[Dict[str, Any]]] = None,
    ) -> MessagingResult:
        body: Dict[str, Any] = {"channel": channel, "text": text}
        if thread_ts:
            body["thread_ts"] = thread_ts
        if blocks is not None:
            body["blocks"] = blocks

        result = self._call_api("chat.postMessage", body)
        if result.ok:
            logger.info(
                "Slack message posted channel=%s ts=%s",
                result.channel,
                result.message_ts,
            )
        return result

    def update_message(
        self,
        channel: str,
        message_ts: str,
        *,
        text: Optional[str] = None,
        blocks: Optional[List[Dict[str, Any]]] = None,
    ) -> MessagingResult:
        body: Dict[str, Any] = {"channel": channel, "ts": message_ts}
        if text is not None:
            body["text"] = text
        if blocks is not None:
            body["blocks"] = blocks

        result = self._call_api("chat.update", body)
        if result.ok:
            logger.info(
                "Slack message updated channel=%s ts=%s",
                result.channel,
                message_ts,
            )
        return result
