"""
DynamoDB Package
Provides table-specific implementations for DynamoDB operations.
"""

from utilities.aws import get_aws_client
from utilities.logging import get_logger

logger = get_logger(name="dynamo_base")


class BaseDynamoTable:
    """Generic DynamoDB table operations base class"""

    def __init__(self, table_name):
        self.client = get_aws_client("dynamodb")
        self.table_name = table_name

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

    def put_item(self, item_dict):
        """Put an item into the table"""
        try:
            formatted_item = {}
            for key, value in item_dict.items():
                if isinstance(value, str):
                    formatted_item[key] = {"S": value}
                elif isinstance(value, (int, float)):
                    formatted_item[key] = {"N": str(value)}
                else:
                    formatted_item[key] = {"S": str(value)}

            self.client.put_item(TableName=self.table_name, Item=formatted_item)
            return True
        except Exception as e:
            logger.exception(f"Error putting item {item_dict}: {e}")
            return False

    def delete_item(self, key_dict):
        """Delete an item from the table"""
        try:
            formatted_key = {}
            for key, value in key_dict.items():
                formatted_key[key] = {"S": value}

            self.client.delete_item(TableName=self.table_name, Key=formatted_key)
            return True
        except Exception as e:
            logger.exception(f"Error deleting item with key {key_dict}: {e}")
            return False

    def conditional_put_item(
        self, item_dict, condition_expression, expression_attribute_values=None
    ):
        """Put an item with conditional expression (for atomic operations)"""
        try:
            formatted_item = {}
            for key, value in item_dict.items():
                if isinstance(value, str):
                    formatted_item[key] = {"S": value}
                elif isinstance(value, (int, float)):
                    formatted_item[key] = {"N": str(value)}
                else:
                    formatted_item[key] = {"S": str(value)}

            params = {
                "TableName": self.table_name,
                "Item": formatted_item,
                "ConditionExpression": condition_expression,
            }

            if expression_attribute_values:
                params["ExpressionAttributeValues"] = expression_attribute_values

            self.client.put_item(**params)
            return True
        except self.client.exceptions.ConditionalCheckFailedException:
            return False
        except Exception as e:
            logger.exception(f"Error with conditional put: {e}")
            return False


# Import table-specific implementations
from .websocket_connections import WebSocketConnectionsTable
from .operation_locks import OperationLocksTable

# Backward compatibility - will be deprecated
DynamoTable = WebSocketConnectionsTable

__all__ = [
    "BaseDynamoTable",
    "WebSocketConnectionsTable",
    "OperationLocksTable",
    "DynamoTable",  # Deprecated
]
