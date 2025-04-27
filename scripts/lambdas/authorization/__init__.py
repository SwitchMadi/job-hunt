import jwt
import os
import dotenv

from utilities.logging import get_logger


dotenv.load_dotenv()
SECRET = os.getenv("JWT_SECRET_KEY")

logger = get_logger(name="lambda_authorizer")


def lambda_handler(event, context):
    # Handle WebSocket protocol auth
    if "headers" in event and "Sec-WebSocket-Protocol" in event["headers"]:
        token = event["headers"]["Sec-WebSocket-Protocol"]
    # Handle REST API auth
    elif "authorizationToken" in event:
        token = event["authorizationToken"].replace("Bearer ", "")
    else:
        logger.error("No authorization token found")
        raise Exception("Unauthorized")

    method_arn = event["methodArn"]

    try:
        decoded = jwt.decode(token, SECRET, algorithms=["HS256"])
        user_id = decoded["sub"]

        return {
            "principalId": user_id,
            "policyDocument": {
                "Version": "2012-10-17",
                "Statement": [
                    {
                        "Action": "execute-api:Invoke",
                        "Effect": "Allow",
                        "Resource": method_arn,
                    }
                ],
            },
            "context": {"email": decoded["email"]},
        }
    except Exception as e:
        logger.exception(f"Exception during lambda authorization - {e}")
        return {
            "principalId": "unknown",
            "policyDocument": {
                "Version": "2012-10-17",
                "Statement": [
                    {
                        "Action": "execute-api:Invoke",
                        "Effect": "Deny",
                        "Resource": method_arn,
                    }
                ],
            },
        }
