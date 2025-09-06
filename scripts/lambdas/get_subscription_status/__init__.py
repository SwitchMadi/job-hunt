import json
from user import User
from utilities.logging import get_logger
from utilities.sql import get_sql_query_output
from utilities.aws import send_lambda_response

logger = get_logger(name="get_subscription_status")


@send_lambda_response(logger)
def lambda_handler(event, context):
    """
    Lambda function to get user subscription status.
    Used by frontend to check if user can proceed with job application.
    """
    try:
        # Extract user email from JWT token
        email = event["requestContext"]["authorizer"].get("email")
        if not email:
            logger.exception(
                f"User email not found in authorizer lambda response - \n{event}"
            )
            return {
                "statusCode": 401,
                "body": json.dumps({"message": "User email not found", "error": True}),
            }

        # Get user object
        user = User(email=email)

        # Get subscription status
        subscription_status = {
            "user_email": email,
            "subscription_plan_code": user.subscription_plan_code,
            "subscription_status": user.subscription_status,
            "can_apply_for_jobs": user.can_apply_for_jobs,
            "applications_remaining": user.applications_remaining,
            "subscription_status_summary": user.subscription_status_summary,
        }

        # Get BASIC plan details only
        basic_plan = get_basic_plan_details()
        subscription_status["basic_plan"] = basic_plan

        logger.info(
            f"Retrieved subscription status for user {email}: {subscription_status}"
        )

        return {
            "statusCode": 200,
            "body": json.dumps(
                {"subscription_status": subscription_status, "success": True}
            ),
        }

    except Exception as e:
        logger.exception(f"Error getting subscription status: {e}")
        return {
            "statusCode": 500,
            "body": json.dumps(
                {
                    "message": f"Failed to get subscription status: {str(e)}",
                    "error": True,
                }
            ),
        }


def get_basic_plan_details():
    """
    Get BASIC plan details with active services and entitlements.
    """
    try:
        basic_plan_query = """
            SELECT 
                p.id,
                p.code,
                p.name,
                p.description,
                p.billing_period,
                p.price_amount,
                p.price_currency,
                p.is_active,
                json_agg(
                    json_build_object(
                        'service_code', s.code,
                        'service_name', s.name,
                        'service_description', s.description,
                        'limit_quantity', pe.limit_quantity
                    )
                ) as services
            FROM subscription.plans p
            LEFT JOIN subscription.plan_entitlements pe ON p.id = pe.plan_id AND pe.is_active = TRUE
            LEFT JOIN subscription.services s ON pe.service_id = s.id AND s.is_active = TRUE
            WHERE p.code = 'BASIC' AND p.is_active = TRUE
            GROUP BY p.id, p.code, p.name, p.description, p.billing_period, p.price_amount, p.price_currency, p.is_active
        """

        plan_result = get_sql_query_output(basic_plan_query)

        if not plan_result:
            logger.warning("BASIC plan not found or not active")
            return None

        plan_data = plan_result[0]

        # Filter out null services (where no entitlements exist)
        active_services = [
            service
            for service in plan_data["services"]
            if service["service_code"] is not None
        ]

        basic_plan = {
            "id": plan_data["id"],
            "code": plan_data["code"],
            "name": plan_data["name"],
            "description": plan_data["description"],
            "billing_period": plan_data["billing_period"],
            "price_amount": plan_data["price_amount"],
            "price_currency": plan_data["price_currency"],
            "services": active_services,
        }

        logger.info(f"Retrieved BASIC plan with {len(active_services)} active services")
        return basic_plan

    except Exception as e:
        logger.exception(f"Error getting BASIC plan details: {e}")
        return None
