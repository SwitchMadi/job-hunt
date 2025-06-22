from utilities import timeout, TimeoutException
from utilities.logging import get_logger


@timeout(10)
def identify_job_application_steps(job_id):
    from jobs import Job
    from user import User

    user = User(email="bhaskar2choudhary@gmail.com")
    job = Job(
        url=f"https://example.com/job-application-url-{job_id}",
        title="Data Analyst, Staff",
        user=user,
        company="Qualcomm",
    )

    job.application_page.apply()


for curr_job_id in range(2):
    logger = get_logger("jobs_steps_identification")
    try:
        identify_job_application_steps(curr_job_id)
    except TimeoutException as e:
        logger.warn(e)

        from utilities.selenium import kill_selenium_chrome

        kill_selenium_chrome()
        logger.info("Selenium Chrome process killed.")

        from jobs import ApplicationPage

        ApplicationPage.update_steps_identification_status(
            job_id=curr_job_id,
            is_application_feasible=False,
            remarks="Steps identification timed out",
        )
    finally:
        from utilities.selenium import kill_selenium_chrome

        kill_selenium_chrome()
        logger.info("Selenium Chrome process killed.")
