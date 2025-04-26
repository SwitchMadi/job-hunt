import json

from utilities.logging import get_logger
from utilities.aws import send_lambda_response
from user import User

logger = get_logger(name="parse_resume")


@send_lambda_response(logger)
def lambda_handler(event, context):
    # Get user email from authorizer
    email = event["requestContext"]["authorizer"].get("email")
    if not email:
        logger.exception(
            f"User email not found in authorizer lambda response - \n{event}"
        )
        raise

    # Get user and parse resume
    user = User(email=email)

    if not user.resume:
        return {
            "statusCode": 400,
            "message": "No resume found for user. Please upload a resume first.",
        }

    success = user.parse_resume()

    if not success:
        raise Exception("Failed to parse resume")

    return {"message": "Resume parsed successfully", "data": user.parsed_resume}
