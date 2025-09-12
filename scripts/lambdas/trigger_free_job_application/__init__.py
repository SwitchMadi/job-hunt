import json

from user import User
from utilities.logging import get_logger
from utilities.aws.ec2 import EC2
from utilities.aws.dynamo import OperationLocksTable, WebSocketConnectionsTable
from utilities.aws.websocket import WebSocketClient

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
        if user.subscription_plan_code != "TRIAL":
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

        # Extract job information before launching EC2 instance
        jobs = user.fetch_job_ids_to_apply()

        # Apply trial plan limits using generic service methods
        remaining_applications = user.applications_remaining
        logger.info(f"Trial user - limiting to {remaining_applications} applications")
        jobs = jobs[:remaining_applications]

        # Jobs now contain all the details we need
        job_details = jobs if jobs else []
        logger.info(f"Found {len(job_details)} job details for websocket message")

        # If no jobs are available, return 204 No Content
        if not job_details:
            return {
                "statusCode": 204,
                "body": json.dumps(
                    {
                        "message": "No suitable jobs found for application",
                        "no_jobs": True,
                    }
                ),
            }

        # Send job information via websocket to improve user experience
        try:
            websocket_table = WebSocketConnectionsTable()
            connection = websocket_table.get_connections_by_user(email)

            if connection:
                connection_id = connection["connectionId"]["S"]
                websocket_client = WebSocketClient()

                # Send job list message when jobs are found
                # Remove job_id from websocket data, only send hash_id and other details
                websocket_jobs = []
                for job in job_details:
                    websocket_jobs.append(
                        {
                            "job_hash_id": job["job_hash_id"],
                            "job_url": job["job_url"],
                            "title": job["title"],
                            "company": job["company"],
                            "location": job["location"],
                        }
                    )

                websocket_data = {
                    "total_jobs": len(job_details),
                    "jobs": websocket_jobs,
                }

                success = websocket_client.send_message(
                    connection_id,
                    "JOB_APPLICATION_JOBS_FOUND",
                    websocket_data,
                    user_email=email,
                )

                if success:
                    logger.info(
                        f"Successfully sent job list to user {email} via websocket"
                    )
                else:
                    logger.warning(
                        f"Failed to send job list to user {email} via websocket"
                    )
            else:
                logger.warning(f"No websocket connection found for user {email}")
        except Exception as e:
            logger.exception(f"Error sending websocket message: {e}")

        script = rf"""<script>
        echo Current date and time >> C:\Users\JobHunt\Desktop\startup.log
        echo %DATE% %TIME% >> C:\Users\JobHunt\Desktop\startup.log
        echo user_email: '{email}' >> C:\Users\JobHunt\Desktop\startup_input.yml
        del "C:\Users\JobHunt\AppData\Roaming\Microsoft\Windows\Start Menu\Programs\Startup\startup_script.bat"
        echo call C:\Users\JobHunt\Desktop\venv\Scripts\activate.bat >> "C:\Users\JobHunt\AppData\Roaming\Microsoft\Windows\Start Menu\Programs\Startup\startup_script.bat"
        echo cd C:\Users\JobHunt\Desktop\job-hunt >> "C:\Users\JobHunt\AppData\Roaming\Microsoft\Windows\Start Menu\Programs\Startup\startup_script.bat"
        echo git pull origin main >> "C:\Users\JobHunt\AppData\Roaming\Microsoft\Windows\Start Menu\Programs\Startup\startup_script.bat"
        echo powershell -Command "(Get-Content 'C:\Users\JobHunt\Desktop\job-hunt\config.yml') -replace '^cloudwatch_log_group:.*','cloudwatch_log_group: jobs-application' | Set-Content 'C:\Users\JobHunt\Desktop\job-hunt\config.yml'" >> "C:\Users\JobHunt\AppData\Roaming\Microsoft\Windows\Start Menu\Programs\Startup\startup_script.bat"
        echo python -m scripts.job_application.run >> "C:\Users\JobHunt\AppData\Roaming\Microsoft\Windows\Start Menu\Programs\Startup\startup_script.bat"
        echo python -m scripts.windows.terminate_windows_machine >> "C:\Users\JobHunt\AppData\Roaming\Microsoft\Windows\Start Menu\Programs\Startup\startup_script.bat"
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

        # Send engaging message about the process starting
        try:
            if connection:
                websocket_data = {
                    "message": "🚀 Your job applications are being prepared! Our AI is analyzing each position and customizing your applications. This usually takes a few minutes - hang tight while we work our magic! ✨",
                    "status": "processing",
                }

                success = websocket_client.send_message(
                    connection_id,
                    "JOB_APPLICATION_PROCESSING_STARTED",
                    websocket_data,
                    user_email=email,
                )

                if success:
                    logger.info(
                        f"Successfully sent processing message to user {email} via websocket"
                    )
                else:
                    logger.warning(
                        f"Failed to send processing message to user {email} via websocket"
                    )
        except Exception as e:
            logger.exception(f"Error sending processing message: {e}")

        return {
            "statusCode": 200,
            "body": json.dumps(
                {
                    "message": "Job application process triggered successfully",
                    "triggered": True,
                    "jobs_found": len(job_details),
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
