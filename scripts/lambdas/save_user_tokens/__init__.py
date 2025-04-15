import json
from google.oauth2.credentials import Credentials
from datetime import datetime
import os
import dotenv

from utilities.logging import get_logger
from utilities.google_services import get_user_info
from utilities import decrypt_string
from utilities.aws import send_lambda_response
from user import User


dotenv.load_dotenv()
logger = get_logger(name="save_user_tokens")


@send_lambda_response(logger)
def lambda_handler(event, context):
    body = json.loads(event.get("body", "{}"))
    encrypted_payload = body.get("data")

    if not encrypted_payload:
        return {
            "statusCode": 400,
            "headers": {"Content-Type": "application/json"},
            "body": json.dumps({"error": "Missing payload"}),
        }

    # AES decryption (default)
    decrypted_data = decrypt_string(encrypted_payload, mode="aes")

    # Parse JSON string to dict
    payload = json.loads(decrypted_data)

    email = event["requestContext"]["authorizer"].get("email")
    if not email:
        logger.exception(
            f"User email not found in authorizer lambda response - \n{event}"
        )
        raise

    access_token = payload.get("access_token")
    user_info = get_user_info(access_token)

    user = User(email=email, name=user_info["name"])

    refresh_token = payload.get("refresh_token")
    expiry = payload.get("expiry")
    expiry = datetime.fromtimestamp(expiry / 1000)
    scopes = payload.get("scopes").split()

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
