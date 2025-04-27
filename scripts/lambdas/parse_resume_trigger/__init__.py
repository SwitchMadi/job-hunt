import json
from utilities.logging import get_logger
from utilities.aws import send_lambda_response, get_aws_client
from utilities.aws.dynamo import DynamoTable
from user import User

logger = get_logger(name="parse_resume_trigger")
lambda_client = get_aws_client("lambda")


@send_lambda_response(logger)
def lambda_handler(event, context):
    # Get user email from authorizer
    email = event["requestContext"]["authorizer"].get("email")
    if not email:
        logger.exception(
            f"User email not found in authorizer lambda response - \\n{event}"
        )
        raise

    try:
        # Get user's latest WebSocket connection
        dynamo = DynamoTable("websocket-connections")
        connection = dynamo.get_connections_by_user(email)

        if not connection:
            return {
                "statusCode": 400,
                "body": json.dumps(
                    {
                        "message": "No active WebSocket connection found. Please ensure WebSocket is connected."
                    }
                ),
            }

        connection_id = connection["connectionId"]["S"]

        # Verify resume exists
        user = User(email=email)
        if not user.resume:
            return {
                "statusCode": 400,
                "body": json.dumps(
                    {
                        "message": "No resume found for user. Please upload a resume first."
                    }
                ),
            }

        # Invoke background parsing Lambda
        payload = {"email": email, "connection_id": connection_id}
        lambda_client.invoke(
            FunctionName="ParseResume",
            InvocationType="Event",  # Async invocation
            Payload=json.dumps(payload),
        )

        return {
            "statusCode": 202,
            "body": json.dumps({"message": "Resume parsing started"}),
        }

    except Exception as e:
        logger.exception(f"Error initiating resume parse: {e}")
        raise
