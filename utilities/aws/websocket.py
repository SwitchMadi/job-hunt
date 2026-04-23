import json
import yaml
from utilities.aws import get_aws_client
from utilities.aws.dynamo import WebSocketConnectionsTable
from utilities.logging import get_logger

logger = get_logger(name="websocket")


class WebSocketClient:
    def __init__(self, endpoint_url=None):
        # Read endpoint from config if not provided
        if endpoint_url is None:
            try:
                with open("config.yml", "r") as file:
                    config = yaml.safe_load(file)
                    endpoint_url = config.get("websocket", {}).get(
                        "endpoint_url", "https://ws.api.switchmadi.com"
                    )
            except Exception as e:
                logger.warning(
                    f"Failed to read config.yml, using default endpoint: {e}"
                )
                endpoint_url = "https://ws.api.switchmadi.com"

        self.client = get_aws_client(
            "apigatewaymanagementapi", endpoint_url=endpoint_url
        )
        self.connections_table = WebSocketConnectionsTable()

    def send_message(self, connection_id, message_type, data=None, user_email=None):
        """Send message to WebSocket client with connection recovery"""
        try:
            message = {"type": message_type}
            if data is not None:
                message["data"] = data

            # First attempt: Send to the provided connection ID
            success = self._send_to_connection(connection_id, message)

            if success:
                return True

            # If failed and we have user_email, try to find new connection
            if user_email:
                logger.info(
                    f"Connection {connection_id} failed for user {user_email}, checking for new connection"
                )
                return self._send_with_connection_recovery(user_email, message)

            return False

        except Exception as e:
            logger.exception(f"Failed to send message to client {connection_id}: {e}")
            return False

    def _send_to_connection(self, connection_id, message):
        """Send message to a specific connection ID"""
        try:
            self.client.post_to_connection(
                ConnectionId=connection_id, Data=json.dumps(message)
            )
            return True
        except Exception as e:
            logger.warning(f"Failed to send to connection {connection_id}: {e}")
            return False

    def _send_with_connection_recovery(self, user_email, message):
        """Try to send message using connection recovery logic"""
        try:
            # Get user's latest connection from DynamoDB
            connection = self.connections_table.get_connections_by_user(user_email)

            if not connection:
                logger.warning(f"No active connection found for user {user_email}")
                return False

            new_connection_id = connection.get("connectionId", {}).get("S")

            if not new_connection_id:
                logger.warning(f"No valid connection ID found for user {user_email}")
                return False

            # Try sending to the new connection
            success = self._send_to_connection(new_connection_id, message)

            if success:
                logger.info(
                    f"Successfully sent message to user {user_email} via new connection {new_connection_id}"
                )
            else:
                logger.warning(
                    f"Failed to send message to user {user_email} via new connection {new_connection_id}"
                )

            return success

        except Exception as e:
            logger.exception(f"Error in connection recovery for user {user_email}: {e}")
            return False
