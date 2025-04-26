import json
import base64
import os
import tempfile

from utilities.logging import get_logger
from utilities.aws import send_lambda_response
from user import User

logger = get_logger(name="upload_resume")


@send_lambda_response(logger)
def lambda_handler(event, context):
    # Get user email from authorizer
    email = event["requestContext"]["authorizer"].get("email")
    if not email:
        logger.exception(
            f"User email not found in authorizer lambda response - \n{event}"
        )
        raise

    # Parse request body
    body = json.loads(event.get("body", "{}"))
    file_content = body.get("file")  # Base64 encoded file content
    file_name = body.get("fileName")

    if not all([file_content, file_name]):
        logger.error("Missing required fields: file, fileName")
        raise ValueError("Missing required fields: file, fileName")

    # Create temporary file to store the resume
    file_extension = os.path.splitext(file_name)[1]
    with tempfile.NamedTemporaryFile(suffix=file_extension, delete=False) as temp_file:
        # Decode and write file content
        file_data = base64.b64decode(file_content)
        temp_file.write(file_data)
        temp_file_path = temp_file.name

    try:
        # Get or create user and save resume
        user = User(email=email)
        success = user.save_resume(file_local_path=temp_file_path)

        if not success:
            raise Exception("Failed to save resume")

        return {"message": "Resume uploaded successfully"}

    finally:
        # Clean up temporary file
        if os.path.exists(temp_file_path):
            os.remove(temp_file_path)
