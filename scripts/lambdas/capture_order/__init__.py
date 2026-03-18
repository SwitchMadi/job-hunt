import json
import os

# import for lambda requirements.txt
import requests

from payment import PaymentGatewayFactory
from utilities.logging import get_logger
from utilities.aws import send_lambda_response

logger = get_logger(name="capture_order")


@send_lambda_response(logger)
def lambda_handler(event, context):
    """
    Lambda function to capture PayPal orders.
    """
    try:
        # Extract order ID from path parameters
        order_id = event.get("pathParameters", {}).get("orderId")
        if not order_id:
            return {
                "statusCode": 400,
                "body": json.dumps({"error": "Order ID is required"}),
            }

        # Extract user email from authorizer (already handled by LambdaTokenAuthorizer)
        user_email = event["requestContext"]["authorizer"].get("email")
        if not user_email:
            logger.exception(
                f"User email not found in authorizer lambda response - \n{event}"
            )
            return {
                "statusCode": 401,
                "body": json.dumps({"error": "User email not found in authentication"}),
            }

        # Get payment gateway (default to PayPal)
        gateway_type = os.getenv("PAYMENT_GATEWAY", "paypal")
        gateway = PaymentGatewayFactory.create_gateway(gateway_type)

        if not gateway:
            logger.error(f"Failed to create payment gateway: {gateway_type}")
            return {
                "statusCode": 500,
                "body": json.dumps({"error": "Payment gateway not available"}),
            }

        # Capture order first (this will cache order details)
        result = gateway.capture_order(order_id)

        # Verify order ownership using cached data
        if not gateway.verify_order_ownership(order_id, user_email):
            logger.warning(f"Order {order_id} does not belong to user {user_email}")
            return {
                "statusCode": 403,
                "body": json.dumps(
                    {"error": "Order does not belong to authenticated user"}
                ),
            }

        if result.status == "completed":
            logger.info(f"Successfully captured order {order_id} for user {user_email}")
            return {
                "statusCode": 200,
                "body": json.dumps(
                    {
                        "id": result.payment_id,
                        "status": result.status,
                        "amount": result.amount,
                        "currency": result.currency,
                        "purchase_units": [
                            {
                                "payments": {
                                    "captures": [
                                        {
                                            "id": result.payment_id,
                                            "status": result.status,
                                            "amount": {
                                                "currency_code": result.currency,
                                                "value": str(result.amount),
                                            },
                                        }
                                    ]
                                }
                            }
                        ],
                    }
                ),
            }
        else:
            logger.error(f"Failed to capture order {order_id}: {result.error_message}")
            return {
                "statusCode": 400,
                "body": json.dumps(
                    {
                        "error": "Failed to capture order",
                        "details": [
                            {
                                "issue": "CAPTURE_FAILED",
                                "description": "Order capture failed",
                            }
                        ],
                    }
                ),
            }

    except Exception as e:
        logger.exception(f"Error capturing order: {e}")
        return {
            "statusCode": 500,
            "body": json.dumps({"error": "Internal server error"}),
        }
