from googleapiclient.discovery import build
import base64

from utilities.logging import get_logger
from utilities.google_services import get_google_credentials
from user import User

logger = get_logger(name="gmail", file_name="job-hunt")


class Email:
    def __init__(self, service, message_id):
        self.service = service
        self.message_id = message_id
        self.title = None
        self.time = None
        self.sender = None
        self.body = None
        self._populate_email_details()

    def _populate_email_details(self):
        """
        Fetch the email details using the message ID and populate the object's attributes.
        """
        try:
            msg = (
                self.service.users()
                .messages()
                .get(
                    userId="me",
                    id=self.message_id,
                    fields="id,internalDate,payload/headers,payload/parts",
                )
                .execute()
            )

            self.title = self._extract_subject(msg)
            self.time = self._extract_time(msg)
            self.sender = self._extract_sender(msg)
            self.body = self._extract_body(msg)

        except Exception as e:
            logger.exception(f"Failed to populate email details: {e}")

    @staticmethod
    def _extract_subject(msg):
        """Extract the subject from the email headers."""
        headers = msg["payload"]["headers"]
        subject = next(
            (header["value"] for header in headers if header["name"] == "Subject"),
            "No Subject",
        )
        return subject

    @staticmethod
    def _extract_sender(msg):
        """Extract the sender's email address from the email headers."""
        headers = msg["payload"]["headers"]
        sender = next(
            (header["value"] for header in headers if header["name"] == "From"),
            "No Sender",
        )
        return sender

    @staticmethod
    def _extract_time(msg):
        """Extract and return the time as an epoch timestamp."""
        timestamp = int(msg["internalDate"]) / 1000
        return int(timestamp)  # Return as integer

    @staticmethod
    def _extract_body(msg):
        """Extract the body text from the email."""
        if "parts" in msg["payload"]:
            for part in msg["payload"]["parts"]:
                if part["mimeType"] == "text/plain":
                    body_data = part["body"]["data"]
                    body = base64.urlsafe_b64decode(body_data).decode("utf-8")
                    return body
        else:
            body_data = msg["payload"]["body"]["data"]
            body = base64.urlsafe_b64decode(body_data).decode("utf-8")
            return body
        return "No body text"

    def mark_as_read(self):
        """
        Mark this email as read.
        """
        try:
            self.service.users().messages().modify(
                userId="me", id=self.message_id, body={"removeLabelIds": ["UNREAD"]}
            ).execute()
            logger.info(f"Email '{self.title}' marked as read.")
        except Exception as e:
            logger.exception(f"Failed to mark email as read: {e}")


class Gmail:
    def __init__(self, user: User):
        credentials = get_google_credentials(scopes=["gmail"], user=user)
        self.client = build("gmail", "v1", credentials=credentials)

    def get_emails(self, query=None, max_results=10):
        """
        Get emails based on the provided query.
        :param query: Gmail search query string.
        :param max_results: Maximum number of emails to return.
        :return: List of Email objects matching the criteria.
        """
        try:
            results = (
                self.client.users()
                .messages()
                .list(
                    userId="me", q=query, maxResults=max_results, fields="messages/id"
                )
                .execute()
            )

            messages = results.get("messages", [])
            emails = [
                Email(service=self.client, message_id=msg["id"]) for msg in messages
            ]

            return emails
        except Exception as e:
            logger.exception(f"An error occurred while retrieving emails: {str(e)}")
            return []
