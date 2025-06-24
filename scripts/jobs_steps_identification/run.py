import os
import subprocess
import sys

from jobs import ApplicationPage
from utilities.logging import get_logger
from utilities.sql import get_sql_query_output
from utilities.selenium import kill_selenium_chrome
from utilities.aws.dynamo import OperationLocksTable


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

    steps_unidentified_jobs_query = """
        select distinct t1.id job_id
        from jobs.jobs t1
        left join jobs.application_steps t2
        on t1.id = t2.job_id
        where t1.is_active
        and t1.job_posted_at >= EXTRACT(EPOCH FROM (CURRENT_DATE - INTERVAL '7 days'));
    """
    jobs = get_sql_query_output(steps_unidentified_jobs_query)
    kill_selenium_chrome()

    if not jobs:
        logger.warn("No jobs found for steps identification.")
    else:
        logger.info(f"Identifying steps for {len(jobs)} jobs.")

        jobs = [job["job_id"] for job in jobs]
        for curr_job_id in jobs:
            logger.info(f"Identifying steps for job ID: {curr_job_id}")

            python_executable = sys.executable
            proc = subprocess.Popen(
                [
                    python_executable,
                    "-m",
                    "scripts.jobs_steps_identification.identify_job_steps",
                    str(curr_job_id),
                ]
            )
            try:
                proc.wait(timeout=10 * 60)  # Wait for 10 minutes
            except Exception as e:
                if e is subprocess.TimeoutExpired:
                    proc.kill()
                    logger.warn(
                        f"Steps identification for job_id {curr_job_id} timed out and killed."
                    )
                    remark = "Steps identification timed out"
                else:
                    remark = f"Unknown exception"
                    logger.exception(
                        f"Error occurred while identifying steps for job_id {curr_job_id}: {e}"
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
