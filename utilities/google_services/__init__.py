from google.oauth2.service_account import Credentials
import os
import dotenv

dotenv.load_dotenv()


def get_google_credentials(scopes: list):
    _scopes = []

    if "drive" in scopes:
        _scopes.append("https://www.googleapis.com/auth/drive")

    if "sheet" in scopes:
        _scopes.append("https://www.googleapis.com/auth/spreadsheets")

    credentials = Credentials.from_service_account_file(
        os.getenv("GOOGLE_SERVICE_ACCOUNT_KEY"), scopes=_scopes
    )
    return credentials
