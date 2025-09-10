import os
import sys

sys.path.append(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from utilities.sql import get_sql_query_output
from utilities.logging import get_logger

logger = get_logger(name="plan")


class Plan:
    """
    Plan class for handling subscription plan operations.
    """

    @staticmethod
    def get_plan_billing_period_days(plan_id):
        """
        Get billing period in days for a given plan ID.

        Args:
            plan_id (int): The plan ID to get billing period for

        Returns:
            int: Number of days for the billing period
        """
        try:
            period_query = f"""
                SELECT billing_period 
                FROM subscription.plans 
                WHERE id = {plan_id} AND is_active = TRUE
            """
            result = get_sql_query_output(period_query)

            if not result:
                logger.warning(f"Plan with ID {plan_id} not found or not active")
                return 30  # Default fallback

            billing_period = result[0]["billing_period"]

            # Convert billing period to days
            if billing_period == "MONTH":
                return 30
            elif billing_period == "YEAR":
                return 365
            elif billing_period == "WEEK":
                return 7
            elif billing_period == "DAY":
                return 1
            elif billing_period == "LIFETIME":
                return 36500  # 100 years for lifetime
            else:
                logger.warning(
                    f"Unknown billing period: {billing_period}, defaulting to 30 days"
                )
                return 30

        except Exception as e:
            logger.exception(f"Error getting billing period for plan {plan_id}: {e}")
            return 30  # Default fallback
