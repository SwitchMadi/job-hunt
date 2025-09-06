import json
import os
from payment import PaymentGatewayFactory
from utilities.logging import get_logger
from utilities.aws import send_lambda_response

logger = get_logger(name="create_order")


@send_lambda_response(logger)
def lambda_handler(event, context):
    """
    Lambda function to create PayPal orders server-side.
    """
    try:
        # Parse request body
        body = json.loads(event.get("body", "{}"))

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

        # Extract required parameters
        amount = body.get("amount")
        description = body.get("description", "Payment Service - SwitchMadi")
        currency = body.get("currency", "USD")

        # Validate required parameters
        if not amount:
            return {
                "statusCode": 400,
                "body": json.dumps(
                    {"error": "Missing required parameter: amount is required"}
                ),
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

        # Create order using the gateway
        result = gateway.create_order(
            amount=float(amount),
            currency=currency,
            user_email=user_email,
            description=description,
        )

        if result.status == "pending":
            logger.info(
                f"Successfully created order {result.order_id} for user {user_email}"
            )
            return {
                "statusCode": 201,
                "body": json.dumps(
                    {
                        "orderID": result.order_id,
                        "status": result.status,
                        "amount": result.amount,
                        "currency": result.currency,
                    }
                ),
            }
        else:
            logger.error(
                f"Failed to create order for user {user_email}: {result.error_message}"
            )
            return {
                "statusCode": 400,
                "body": json.dumps(
                    {"error": result.error_message or "Failed to create order"}
                ),
            }

    except json.JSONDecodeError:
        logger.error("Invalid JSON in request body")
        return {
            "statusCode": 400,
            "body": json.dumps({"error": "Invalid JSON in request body"}),
        }
    except Exception as e:
        logger.exception(f"Error creating order: {e}")
        return {
            "statusCode": 500,
            "body": json.dumps({"error": "Internal server error"}),
        }
