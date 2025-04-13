import json
from google.oauth2.credentials import Credentials
from datetime import datetime
import os
import dotenv

from utilities.logging import get_logger
from utilities.google_services import get_user_info
from user import User


dotenv.load_dotenv()
logger = get_logger(name="save_user_tokens")


def lambda_handler(event, context):
    body = json.loads(event.get("body", "{}"))

    logger.info(f"Body received - {body}")

    email = event["requestContext"]["authorizer"].get("email")
    if not email:
        logger.exception(
            f"User email not found in authorizer lambda response - \n{event}"
        )
        raise

    access_token = body.get("access_token")
    user_info = get_user_info(access_token)

    user = User(email=email, name=user_info["name"])

    refresh_token = body.get("refresh_token")
    expiry = body.get("expiry")  # ISO 8601 string (optional)
    expiry = datetime.fromisoformat(expiry.replace("Z", "+00:00")).timestamp()
    scopes = body.get("scopes")

    credentials = Credentials(
        token=access_token,
        refresh_token=refresh_token,
        expiry=expiry,
        token_uri="https://oauth2.googleapis.com/token",
        client_id=os.getenv("GOOGLE_CLIENT_ID"),
        client_secret=os.getenv("GOOGLE_CLIENT_SECRET"),
        scopes=scopes,
    )

    user.google_oauth_credentials = credentials

    return
