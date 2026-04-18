from abc import ABC, abstractmethod
from dataclasses import dataclass, field
from typing import Any, Dict, List, Optional


@dataclass
class MessagingResult:
    """
    Outcome of a messaging provider operation.
    """

    ok: bool
    provider: str
    channel: Optional[str] = None
    message_ts: Optional[str] = None
    error_message: Optional[str] = None
    raw_response: Optional[Dict[str, Any]] = field(default=None, repr=False)


class MessagingClientInterface(ABC):
    """
    Abstract interface for outbound messaging (Slack, etc.).
    """

    @abstractmethod
    def post_message(
        self,
        channel: str,
        text: str,
        *,
        thread_ts: Optional[str] = None,
        blocks: Optional[List[Dict[str, Any]]] = None,
    ) -> MessagingResult:
        """
        Post a message to a channel (optionally in a thread).

        Args:
            channel: Channel ID (e.g. C...) or name where supported by the API.
            text: Fallback plain text for notifications and accessibility.
            thread_ts: If set, reply in that thread.
            blocks: Optional Block Kit blocks (Slack-specific structure).
        """
        pass

    @abstractmethod
    def update_message(
        self,
        channel: str,
        message_ts: str,
        *,
        text: Optional[str] = None,
        blocks: Optional[List[Dict[str, Any]]] = None,
    ) -> MessagingResult:
        """
        Update an existing message.

        Args:
            channel: Channel ID or name.
            message_ts: Timestamp of the message to update.
            text: Updated fallback text (if provided).
            blocks: Updated blocks (if provided). Provider may require text and/or blocks.
        """
        pass


class MessagingClientFactory:
    """
    Factory for messaging client implementations.
    """

    @staticmethod
    def create_client(client_type: str) -> Optional[MessagingClientInterface]:
        """
        Create a messaging client for the given type.

        Args:
            client_type: e.g. "slack"

        Returns:
            MessagingClientInterface instance or None if creation fails.
        """
        try:
            normalized = client_type.lower().strip()
            if normalized == "slack":
                from .slack_gateway import SlackMessagingClient

                return SlackMessagingClient()
            raise ValueError(f"Unsupported messaging client: {client_type}")
        except Exception as e:
            from utilities.logging import get_logger

            logger = get_logger(name="messaging_factory")
            logger.exception(
                f"Failed to create messaging client '{client_type}': {e}"
            )
            return None

    @staticmethod
    def get_available_clients() -> List[str]:
        return ["slack"]
