import subprocess
import sys
import yaml
import os

from jobs import ApplicationPage
from user import User
from utilities import take_screenshot
from utilities.logging import get_logger
from utilities.selenium import kill_selenium_chrome
from utilities.aws.dynamo import OperationLocksTable, WebSocketConnectionsTable
from utilities.aws.s3 import S3Bucket
from utilities.aws.websocket import WebSocketClient
from utilities.sql import get_sql_query_output


logger = get_logger("jobs_application")

config = yaml.safe_load(open("config.yml"))
startup_config = yaml.safe_load(open(config["startup_input"])) or {}

user_email = startup_config.get("user_email")
if not user_email:
    message = "No user email found in startup config."
    logger.exception(message)
    raise Exception(message)

user = User(email=user_email)
logger = get_logger(f"jobs_application-{user.id}")

# set user id in environment variable for logging stream suffix at later stage
os.environ["USER_ID"] = f"{user.id}"

logger.info(f"Writing user email {user_email} to main config...")
config["user_email"] = user_email
with open("config.yml", "w") as file:
    yaml.safe_dump(config, file)

# Initialize lock manager
lock_table = OperationLocksTable()
operation_name = f"job_application-{user.id}"
lock_id = None

try:
    # Attempt to acquire lock
    lock_id = lock_table.acquire_lock(operation_name)

    if not lock_id:
        logger.info(
            f"Another job application process for the user {user.id} is already running. Exiting."
        )
        kill_selenium_chrome()
        sys.exit(0)

    logger.info(f"Lock acquired for job application. Lock ID: {lock_id}")

    # Check subscription status before proceeding
    if not user.can_apply_for_jobs:
        subscription_status = user.subscription_status_summary
        logger.error(
            f"User {user.id} cannot apply for jobs. Subscription status: {subscription_status}"
        )
        raise Exception(
            f"Job application not allowed due to subscription limits: {subscription_status}"
        )

    jobs = user.fetch_job_ids_to_apply()

    # Apply subscription-based limits using generic service methods
    remaining_applications = user.applications_remaining
    if remaining_applications > 0:
        logger.info(f"User plan - limiting to {remaining_applications} applications")
        jobs = jobs[:remaining_applications]
    else:
        logger.info("No applications remaining for user")
        jobs = []

    kill_selenium_chrome()

    if not jobs:
        logger.warning("No jobs found for application.")
    else:
        logger.info(f"Applying for {len(jobs)} jobs.")

        # Extract job IDs from the job details
        job_ids = [job["job_id"] for job in jobs]
        for curr_job_id in job_ids:
            logger.info(f"Applying job for job ID: {curr_job_id}")

            # TODO: Remove uploading screenshot before starting the identification process from all places
            # Uploading screenshot before starting the identification process
            screenshot_filename = f"jobId-{curr_job_id}--userId-{user.id}--start.png"
            take_screenshot(filename=screenshot_filename)

            s3 = S3Bucket(bucket_name=config["s3_bucket"])
            file_s3_path = f"user_data/applications/screenshots/{screenshot_filename}"
            s3.upload_data(
                file_local_path=screenshot_filename, file_s3_path=file_s3_path
            )

            python_executable = sys.executable
            proc = subprocess.Popen(
                [
                    python_executable,
                    "-m",
                    "scripts.job_application.apply_job",
                    str(curr_job_id),
                ]
            )
            try:
                proc.wait(timeout=10 * 60)  # Wait for 10 minutes
            except Exception as e:
                if isinstance(e, subprocess.TimeoutExpired):
                    proc.kill()
                    logger.warn(
                        f"Job application for job_id {curr_job_id} timed out and killed."
                    )
                    remark = "Job application timed out"
                else:
                    remark = str(e)
                    logger.exception(
                        f"Error occurred while applying job for job_id {curr_job_id}: {e}"
                    )

                try:
                    screenshot_filename = f"jobId-{curr_job_id}--userId-{user.id}.png"
                    take_screenshot(filename=screenshot_filename)

                    s3 = S3Bucket(bucket_name=config["s3_bucket"])
                    file_s3_path = (
                        f"user_data/applications/screenshots/{screenshot_filename}"
                    )
                    s3.upload_data(
                        file_local_path=screenshot_filename, file_s3_path=file_s3_path
                    )
                except Exception as e:
                    logger.warn(
                        f"Failed to take / upload screenshot for job {curr_job_id} - "
                        f"Error - {e}"
                    )

                kill_selenium_chrome()
                logger.info("Selenium Chrome process killed.")

                ApplicationPage.update_steps_identification_status(
                    job_id=curr_job_id,
                    is_application_feasible=False,
                    remarks=remark,
                )
            finally:
                kill_selenium_chrome()
                logger.info("Selenium Chrome process killed.")

finally:
    # Always release the lock, even if an error occurred
    if lock_id:
        try:
            lock_table.release_lock(operation_name, lock_id)
            logger.info(f"Lock released for job application. Lock ID: {lock_id}")
        except Exception as e:
            logger.exception(f"Error releasing lock: {e}")

    # Send final completion message if streaming is enabled
    if user.should_stream_applications:
        try:
            websocket_table = WebSocketConnectionsTable()
            connection = websocket_table.get_connections_by_user(user.email)

            if connection:
                connection_id = connection["connectionId"]["S"]
                websocket_client = WebSocketClient()

                # Use the jobs list that was extracted at the start
                total_apps = len(jobs) if jobs else 0
                successful_apps = 0
                failed_apps = 0

                # Get application statistics from the jobs we processed
                if jobs:
                    job_ids = [job["job_id"] for job in jobs]
                    job_ids_str = ",".join(map(str, job_ids))

                    stats_query = f"""
                        SELECT 
                            COUNT(*) as total_applications,
                            SUM(CASE WHEN application_status = 'submitted' THEN 1 ELSE 0 END) as successful_applications,
                            SUM(CASE WHEN application_status = 'failed' THEN 1 ELSE 0 END) as failed_applications
                        FROM users.job_applications 
                        WHERE user_id = {user.id} 
                        AND job_id IN ({job_ids_str})
                        AND created_at >= EXTRACT(EPOCH FROM NOW() - INTERVAL '1 hour')
                    """
                    stats = get_sql_query_output(stats_query)

                    if stats:
                        stats = stats[0]
                        successful_apps = stats["successful_applications"] or 0
                        failed_apps = stats["failed_applications"] or 0

                responses_url = "https://switchmadi.com/job-applications"

                completion_data = {
                    "total_applications": total_apps,
                    "successful_applications": successful_apps,
                    "failed_applications": failed_apps,
                    "responsesUrl": responses_url,
                    "message": f"🎉 Job application process completed successfully!",
                }

                websocket_client.send_message(
                    connection_id,
                    "JOB_APPLICATION_COMPLETED",
                    completion_data,
                    user_email=user.email,
                )

                logger.info(f"Sent final completion message for user {user.email}")

        except Exception as e:
            logger.exception(f"Error sending final completion message: {e}")
