import json
import os

# import for lambda requirements.txt
import requests

from user import User
from payment import PaymentGatewayFactory
from utilities.logging import get_logger

logger = get_logger(name="paypal_webhook")


def lambda_handler(event, context):
    """
    Lambda function to handle payment webhook notifications.
    Uses the payment gateway interface for processing.
    """
    try:
        logger.info("PayPal webhook received - starting processing")

        # Parse webhook payload
        webhook_data = json.loads(event.get("body", "{}"))
        headers = event.get("headers", {})

        # Log webhook data
        logger.info(f"Webhook payload: {webhook_data}")
        logger.info(f"Webhook headers: {headers}")

        # Extract and log user email for easy CloudWatch Insights queries
        resource = webhook_data.get("resource", {})
        user_email = resource.get("custom_id", "")
        payment_id = resource.get("id", "")

        logger.info(f"PayPal webhook - User: {user_email}, Payment: {payment_id}")

        # Get payment gateway (default to PayPal for now)
        gateway_type = os.getenv("PAYMENT_GATEWAY", "paypal")
        gateway = PaymentGatewayFactory.create_gateway(gateway_type)

        if not gateway:
            logger.error(f"Failed to create payment gateway: {gateway_type}")
            return {
                "statusCode": 500,
                "body": json.dumps({"message": "Payment gateway not available"}),
            }

        # Handle webhook using the gateway interface
        result = gateway.handle_webhook(webhook_data, headers)

        if result.status == "completed":
            # Update user subscription
            user = User(email=result.user_email)
            if user:
                success = user.update_subscription_status(
                    "BASIC", "ACTIVE", result.payment_id, result.amount
                )
                if success:
                    logger.info(
                        f"Successfully updated subscription for user {result.user_email}"
                    )
                else:
                    logger.error(
                        f"Failed to update subscription for user {result.user_email}"
                    )
            else:
                logger.error(f"User not found for email: {result.user_email}")

        elif result.status == "failed":
            logger.warning(
                f"Payment failed for user {result.user_email}: {result.error_message}"
            )

        # Always return 200 to acknowledge receipt
        return {
            "statusCode": 200,
            "body": json.dumps({"message": "Webhook processed successfully"}),
        }

    except Exception as e:
        logger.exception(f"Error processing webhook: {e}")
        return {
            "statusCode": 500,
            "body": json.dumps({"message": "Internal server error"}),
        }
