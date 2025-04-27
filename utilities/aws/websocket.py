import json
from utilities.aws import get_aws_client
from utilities.logging import get_logger


logger = get_logger(name="websocket")


class WebSocketClient:
    def __init__(self, endpoint_url):
        self.client = get_aws_client(
            "apigatewaymanagementapi", endpoint_url=endpoint_url
        )

    def send_message(self, connection_id, message_type, data=None):
        """Send message to WebSocket client"""
        try:
            message = {"type": message_type}
            if data is not None:
                message["data"] = data

            self.client.post_to_connection(
                ConnectionId=connection_id, Data=json.dumps(message)
            )
            return True
        except Exception as e:
            logger.exception(f"Failed to send message to client {connection_id}: {e}")
            return False
