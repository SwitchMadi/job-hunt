from utilities.logging import get_logger
from utilities.aws.websocket import WebSocketClient
from user import User

API_ENDPOINT = "https://ws.api.switchmadi.com"
logger = get_logger(name="parse_resume")


def lambda_handler(event, context):
    try:
        email = event["email"]
        connection_id = event["connection_id"]

        websocket = WebSocketClient(API_ENDPOINT)
        user = User(email=email)

        # Notify parsing started
        websocket.send_message(connection_id, "PARSING_STARTED")

        success = user.parse_resume()

        if not success:
            websocket.send_message(connection_id, "ERROR", "Failed to parse resume")
            return {"statusCode": 500, "message": "Failed to parse resume"}

        # Send parsed data
        websocket.send_message(connection_id, "PARSING_COMPLETED", user.parsed_resume)
        return {"statusCode": 200, "message": "Resume parsed successfully"}

    except Exception as e:
        logger.exception(f"Error in resume parsing: {e}")
        if "connection_id" in locals():
            websocket.send_message(connection_id, "ERROR", str(e))
        return {"statusCode": 500, "message": str(e)}
