from utilities.logging import get_logger
from utilities.aws.dynamo import DynamoTable
from utilities.aws import send_lambda_response

logger = get_logger(name="websocket_disconnect")


@send_lambda_response(logger)
def lambda_handler(event, context):
    """
    Handle WebSocket disconnect events
    """
    try:
        connection_id = event["requestContext"]["connectionId"]

        # Remove connection mapping using DynamoTable
        dynamo = DynamoTable("websocket-connections")
        success = dynamo.delete_connection(connection_id)

        if not success:
            raise Exception("Failed to delete connection")

        return {"statusCode": 200, "body": "Disconnected"}

    except Exception as e:
        logger.exception("Error handling WebSocket disconnect")
        return {"statusCode": 500, "body": f"Failed to disconnect: {str(e)}"}
