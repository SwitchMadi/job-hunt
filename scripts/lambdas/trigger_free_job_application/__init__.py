import json

from user import User
from utilities.logging import get_logger
from utilities.aws.ec2 import EC2
from utilities.aws.dynamo import OperationLocksTable

logger = get_logger(name="trigger_job_application")


def lambda_handler(event, context):
    """
    Lambda function to trigger job free job application.
    Checks for existing lock before launching EC2 instance.
    """
    try:
        email = event["requestContext"]["authorizer"].get("email")
        if not email:
            logger.exception(
                f"User email not found in authorizer lambda response - \n{event}"
            )
            raise

        user = User(email=email)

        # Check if user is on trial plan (free job application is only for trial users)
        if not user.is_trial_user:
            subscription_status = user.subscription_status_summary
            logger.warning(
                f"User {user.id} is not on trial plan. Free job application is only for trial users. Subscription status: {subscription_status}"
            )
            return {
                "statusCode": 403,
                "body": json.dumps(
                    {
                        "message": "Free job application is only available for trial users",
                        "subscription_status": subscription_status,
                        "error": True,
                    }
                ),
            }

        # Check subscription status before allowing job application
        if not user.can_apply_for_jobs:
            subscription_status = user.subscription_status_summary
            logger.warning(
                f"User {user.id} cannot apply for jobs. Subscription status: {subscription_status}"
            )
            return {
                "statusCode": 403,
                "body": json.dumps(
                    {
                        "message": "Job application not allowed due to subscription limits",
                        "subscription_status": subscription_status,
                        "error": True,
                    }
                ),
            }

        # Check if job scraping is already running
        lock_table = OperationLocksTable()
        operation_name = f"job_application-{user.id}"

        if lock_table.is_locked(operation_name):
            logger.info(
                f"Job application is already running for user {user.id}. Skipping trigger."
            )
            return {
                "statusCode": 200,
                "body": json.dumps(
                    {
                        "message": "Job application already in progress",
                        "skipped": True,
                    }
                ),
            }

        logger.info("No existing lock found. Triggering job application process.")

        script = rf"""<script>
        echo Current date and time >> C:\Users\JobHunt\Desktop\startup.log
        echo %DATE% %TIME% >> C:\Users\JobHunt\Desktop\startup.log
        echo user_email: '{email}' >> C:\Users\JobHunt\Desktop\startup_input.yml
        </script>
        <persist>true</persist>"""

        # Launch EC2 instance to run job scraping
        EC2(
            instance_pricing_model="on_demand",
            ami_id="ami-0728222dafaad95d8",
            instance_type="t3a.2xlarge",
            key_name="job-hunt",
            security_group="sg-011a3786d569e6382",
            user_data_script=script,
            instance_name=f"jobs-application-{user.id}",
        )

        logger.info("Successfully triggered job application EC2 instance.")

        return {
            "statusCode": 200,
            "body": json.dumps(
                {
                    "message": "Job application process triggered successfully",
                    "triggered": True,
                }
            ),
        }

    except Exception as e:
        logger.exception(f"Error triggering job application: {e}")
        return {
            "statusCode": 500,
            "body": json.dumps(
                {
                    "message": f"Failed to trigger job application: {str(e)}",
                    "error": True,
                }
            ),
        }
