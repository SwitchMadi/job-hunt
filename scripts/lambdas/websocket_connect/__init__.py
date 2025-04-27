import json
from utilities.logging import get_logger
from utilities.aws.dynamo import DynamoTable
from utilities.aws import send_lambda_response, get_aws_client

logger = get_logger(name="websocket_connect")


@send_lambda_response(logger)
def lambda_handler(event, context):
    """
    Handle WebSocket connect events
    """
    try:
        connection_id = event["requestContext"]["connectionId"]
        email = event["requestContext"]["authorizer"].get("email")

        if not email:
            logger.error("Email not found in authorizer context")
            return {"statusCode": 401, "body": "Unauthorized"}

        # Store connection mapping using DynamoTable
        dynamo = DynamoTable("websocket-connections")
        success = dynamo.put_connection(connection_id, email)

        if not success:
            raise Exception("Failed to store connection")

        # Get the protocol from request
        protocol = event.get("headers", {}).get("Sec-WebSocket-Protocol", "")

        # Return success for connection upgrade
        return {"statusCode": 200, "headers": {"Sec-WebSocket-Protocol": protocol}}

    except Exception as e:
        logger.exception("Error handling WebSocket connect")
        return {"statusCode": 500, "body": f"Failed to connect: {str(e)}"}
