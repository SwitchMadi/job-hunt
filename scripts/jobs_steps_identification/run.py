import os
import subprocess
import sys

from jobs import ApplicationPage
from utilities.logging import get_logger
from utilities.sql import get_sql_query_output
from utilities.selenium import kill_selenium_chrome


os.environ["LOG_GROUP_STREAM_SUFFIX"] = "overall"
logger = get_logger("jobs_steps_identification")

steps_unidentified_jobs_query = """
    select distinct t1.id job_id
    from jobs.jobs t1
    join jobs.application_steps t2
    on t1.id = t2.job_id
    where t1.is_active;
"""
jobs = get_sql_query_output(steps_unidentified_jobs_query)
kill_selenium_chrome()

if not jobs:
    logger.warn("No jobs found for steps identification.")
else:
    logger.info(f"Identifying steps for {len(jobs)} jobs.")

    # jobs = [job["job_id"] for job in jobs]
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
            proc.wait(timeout=15)
        except subprocess.TimeoutExpired:
            proc.kill()
            logger.warn(
                f"Steps identification for job_id {curr_job_id} timed out and killed."
            )

            kill_selenium_chrome()
            logger.info("Selenium Chrome process killed.")

            ApplicationPage.update_steps_identification_status(
                job_id=curr_job_id,
                is_application_feasible=False,
                remarks="Steps identification timed out",
            )
        finally:
            kill_selenium_chrome()
            logger.info("Selenium Chrome process killed.")
