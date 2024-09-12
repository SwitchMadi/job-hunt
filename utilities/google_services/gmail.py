from googleapiclient.discovery import build
import base64
from bs4 import BeautifulSoup

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
                    fields="id,internalDate,payload/*",
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
        """Extract the text content from the email, handling different content types."""

        def decode_body(data):
            """Helper function to decode base64 body data."""
            return base64.urlsafe_b64decode(data).decode("utf-8")

        def get_text_from_html(html):
            """Helper function to extract text from HTML."""
            soup = BeautifulSoup(html, "html.parser")
            return soup.get_text(separator="\n", strip=True)

        def get_body_from_parts(parts):
            """Recursively extract body content from parts."""
            for part in parts:
                mime_type = part.get("mimeType")
                body_data = part.get("body", {}).get("data")

                if mime_type == "text/plain" and body_data:
                    return decode_body(body_data)
                elif mime_type == "text/html" and body_data:
                    html_content = decode_body(body_data)
                    return get_text_from_html(html_content)
                elif (
                    mime_type
                    in ["multipart/alternative", "multipart/mixed", "multipart/related"]
                    and "parts" in part
                ):
                    nested_body = get_body_from_parts(part["parts"])
                    if nested_body:
                        return nested_body

            return None

        if "body" in msg["payload"] and "data" in msg["payload"]["body"]:
            body_data = decode_body(msg["payload"]["body"]["data"])
            if msg["payload"]["mimeType"] == "text/html":
                return get_text_from_html(body_data)
            return body_data

        if "parts" in msg["payload"]:
            return get_body_from_parts(msg["payload"]["parts"])

        return None

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

    def get_emails(self, query=None, max_results=100):
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
