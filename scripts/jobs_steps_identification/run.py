import subprocess
import sys
import yaml

from jobs import ApplicationPage
from user import User
from utilities import take_screenshot
from utilities.logging import get_logger
from utilities.sql import get_sql_query_output
from utilities.selenium import kill_selenium_chrome
from utilities.aws.dynamo import OperationLocksTable
from utilities.aws.s3 import S3Bucket


config = yaml.safe_load(open("config.yml"))

logger = get_logger("jobs_steps_identification")

# Initialize lock manager
lock_table = OperationLocksTable()
operation_name = "job_steps_identification"
lock_id = None

try:
    # Attempt to acquire lock
    lock_id = lock_table.acquire_lock(operation_name)

    if not lock_id:
        logger.info(
            "Another job steps identification process is already running. Exiting."
        )
        kill_selenium_chrome()
        sys.exit(0)

    logger.info(f"Lock acquired for job steps identification. Lock ID: {lock_id}")

    # Get user and their job filters to build preference filters
    user = User(email=config["user_email"])
    user_job_filters = user.job_filters

    # Build preference filters for all active job filters
    preference_filters = []
    if user_job_filters:
        for job_filter in user_job_filters:
            filter_conditions = user._preferred_jobs_query_filters(job_filter["id"])
            if filter_conditions:
                preference_filters.append(f"({filter_conditions})")

    # Combine all filters with OR logic (job matching any filter is eligible)
    user_preference_filter_clause = ""
    if preference_filters:
        user_preference_filter_clause = f"and ({' or '.join(preference_filters)})"
    else:
        logger.warning(
            f"No active job filters found for user {config['user_email']}. All jobs will be considered."
        )

    steps_unidentified_jobs_query = f"""
        select distinct t1.id job_id
        from jobs.jobs t1
        left join (
            select id, job_id 
            from jobs.application_steps
        ) t2
        on t1.id = t2.job_id
        where t1.is_active
        and t2.id is null
        and not t1.linkedin_easy_apply
        and t1.employment_type not ilike '%intern%'
        and t1.job_posted_at >= EXTRACT(EPOCH FROM (CURRENT_DATE - INTERVAL '7 days'))
        {user_preference_filter_clause};
    """
    jobs = get_sql_query_output(steps_unidentified_jobs_query)
    kill_selenium_chrome()

    if not jobs:
        logger.warning("No jobs found for steps identification.")
    else:
        logger.info(f"Identifying steps for {len(jobs)} jobs.")

        jobs = [job["job_id"] for job in jobs]
        for curr_job_id in jobs:
            logger.info(f"Identifying steps for job ID: {curr_job_id}")

            # Uploading screenshot before starting the identification process
            user = User(email=config["user_email"])

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
                proc.wait(timeout=90 * 60)  # Wait for 90 minutes
            except Exception as e:
                if isinstance(e, subprocess.TimeoutExpired):
                    proc.kill()
                    logger.warn(
                        f"Steps identification for job_id {curr_job_id} timed out and killed."
                    )
                    remark = "Steps identification timed out"
                else:
                    remark = str(e)
                    logger.exception(
                        f"Error occurred while identifying steps for job_id {curr_job_id}: {e}"
                    )

                try:
                    user = User(email=config["user_email"])

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
            logger.info(
                f"Lock released for job steps identification. Lock ID: {lock_id}"
            )
        except Exception as e:
            logger.exception(f"Error releasing lock: {e}")
