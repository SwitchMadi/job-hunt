from google.oauth2.service_account import Credentials
from google.oauth2.credentials import Credentials as GmailCredentials
from google_auth_oauthlib.flow import InstalledAppFlow
from googleapiclient.discovery import build
import os
import dotenv
from datetime import datetime

from utilities.logging import get_logger


dotenv.load_dotenv()
logger = get_logger(name="google")


class InvalidGoogleOAuthCredentials(Exception):
    def __init__(self, message="Invalid Google OAuth Credentials"):
        self.message = message
        super().__init__(self.message)

    pass


def get_google_credentials(scopes: list, user=None):
    _scopes = []

    if "drive" in scopes or "sheet" in scopes:
        if "drive" in scopes:
            _scopes.append("https://www.googleapis.com/auth/drive")

        if "sheet" in scopes:
            _scopes.append("https://www.googleapis.com/auth/spreadsheets")

        # Use the service account credentials for Drive and Sheets
        credentials = Credentials.from_service_account_file(
            os.getenv("GOOGLE_SERVICE_ACCOUNT_KEY"), scopes=_scopes
        )
        return credentials

    if "gmail" in scopes:
        credentials = user.google_oauth_credentials

        # If no valid credentials, or if the credentials are invalid, request new ones
        if not credentials or not credentials.valid:
            _scopes.append("openid")
            _scopes.append("https://www.googleapis.com/auth/gmail.readonly")
            _scopes.append("https://www.googleapis.com/auth/userinfo.email")

            flow = InstalledAppFlow.from_client_secrets_file(
                os.getenv("GOOGLE_CLIENT_SECRET_KEY"), _scopes
            )
            try:
                credentials = flow.run_local_server(port=0)
            except Warning as w:
                logger.critical(f"{w}\nUser email - {user.email}")
                token_data = w.token
                credentials = GmailCredentials(
                    token=token_data["access_token"],
                    refresh_token=token_data["refresh_token"],
                    expiry=datetime.fromtimestamp(token_data["expires_at"]),
                    token_uri="https://oauth2.googleapis.com/token",
                    client_id=os.getenv("GOOGLE_CLIENT_ID"),
                    client_secret=os.getenv("GOOGLE_CLIENT_SECRET"),
                    scopes=token_data["scope"],
                )

            service = build("oauth2", "v2", credentials=credentials)
            user_info = service.userinfo().get().execute()

            if user.email == user_info["email"]:
                user.google_oauth_credentials = credentials
            else:
                raise InvalidGoogleOAuthCredentials(
                    message=f"Google oauth credentials are of different email id.\n"
                    f"User email - {user.email} | Oauth email - {user_info['email']}"
                )

        return credentials
