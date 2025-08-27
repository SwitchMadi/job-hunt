import subprocess
import sys
import yaml

from jobs import ApplicationPage
from user import User
from utilities import take_screenshot
from utilities.logging import get_logger
from utilities.selenium import kill_selenium_chrome
from utilities.aws.dynamo import OperationLocksTable
from utilities.aws.s3 import S3Bucket


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

    # Apply subscription-based limits
    if user.is_trial_user:
        remaining_applications = user.trial_applications_remaining
        logger.info(f"Trial user - limiting to {remaining_applications} applications")
        jobs = jobs[:remaining_applications]
    elif user.is_basic_user:
        remaining_applications = user.basic_applications_remaining_this_period
        logger.info(
            f"Basic user - limiting to {remaining_applications} applications for current period"
        )
        jobs = jobs[:remaining_applications]

    kill_selenium_chrome()

    if not jobs:
        logger.warning("No jobs found for application.")
    else:
        logger.info(f"Applying for {len(jobs)} jobs.")

        # Extract job IDs from the job details
        job_ids = [job["job_id"] for job in jobs]
        for curr_job_id in job_ids:
            logger.info(f"Applying job for job ID: {curr_job_id}")

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
