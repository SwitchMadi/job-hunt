from utilities.aws import get_aws_client
from utilities.logging import get_logger


logger = get_logger(name="dynamo")


class DynamoTable:
    def __init__(self, table_name):
        self.client = get_aws_client("dynamodb")
        self.table_name = table_name

    def put_connection(self, connection_id, user_id):
        """Store WebSocket connection mapping with timestamp"""
        try:
            import time

            timestamp = int(time.time() * 1000)  # Current time in milliseconds

            self.client.put_item(
                TableName=self.table_name,
                Item={
                    "connectionId": {"S": connection_id},
                    "userId": {"S": user_id},
                    "timestamp": {"N": str(timestamp)},
                },
            )
            return True
        except Exception as e:
            logger.exception(f"Error storing connection in DynamoDB: {e}")
            return False

    def delete_connection(self, connection_id):
        """Remove WebSocket connection mapping"""
        try:
            # Query to get full connection details
            response = self.client.query(
                TableName=self.table_name,
                KeyConditionExpression="connectionId = :connectionId",
                ExpressionAttributeValues={":connectionId": {"S": connection_id}},
            )

            items = response.get("Items", [])
            if not items:
                logger.warning(f"Connection {connection_id} not found for deletion")
                return True

            # Get userId from the connection record
            user_id = items[0]["userId"]["S"]

            # Delete with both hash and range keys
            self.client.delete_item(
                TableName=self.table_name,
                Key={"connectionId": {"S": connection_id}, "userId": {"S": user_id}},
            )
            return True
        except Exception as e:
            logger.exception(f"Error deleting connection from DynamoDB: {e}")
            return False

    def get_connections_by_user(self, user_id):
        """Get latest connection for a user"""
        try:
            response = self.client.query(
                TableName=self.table_name,
                IndexName="UserIdTimeStampIndex",
                KeyConditionExpression="userId = :userId",
                ExpressionAttributeValues={":userId": {"S": user_id}},
                ScanIndexForward=False,  # Sort in descending order (newest first)
                Limit=1,  # Get only the latest connection
            )
            items = response.get("Items", [])
            return items[0] if items else None
        except Exception as e:
            logger.exception(f"Error querying connections for user {user_id}: {e}")
            return []

    def verify_connection(self, connection_id, user_id):
        """Verify a connection belongs to a user"""
        try:
            response = self.client.get_item(
                TableName=self.table_name,
                Key={"connectionId": {"S": connection_id}},
                ConsistentRead=True,
            )

            item = response.get("Item")
            if not item:
                return False

            # Verify user owns this connection
            return item.get("userId", {}).get("S") == user_id

        except Exception as e:
            logger.exception(
                f"Error verifying connection {connection_id} for user {user_id}: {e}"
            )
            return False

    def get_item(self, key_dict):
        """Get a specific item by keys"""
        try:
            formatted_key = {}
            for key, value in key_dict.items():
                formatted_key[key] = {"S": value}

            response = self.client.get_item(
                TableName=self.table_name, Key=formatted_key
            )
            return response.get("Item")
        except Exception as e:
            logger.exception(f"Error getting item with key {key_dict}: {e}")
            return None
