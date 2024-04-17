from utilities.logging import get_logger
from utilities.gpt import get_gpt_response

logger = get_logger(name="job_info_extraction", file_name="job-hunt")


def extract_job_info(job_description, source):
    if source == "linkedin":
        system_prompt = (
            "You are an assistant which reads given job description, sourced from LinkedIn, and help "
            "users extract meaningful information. You always answer crisp and short."
        )
    else:
        system_prompt = (
            "You are an assistant which reads given job description and help users extract meaningful "
            "information. You always answer crisp and short."
        )

    user_prompt = f"""For the following job description on this page, extract following info - 
1. Company name
2. Job location requirement and type (onsite / remote / hybrid)
3. Years of experience required
4. Skills required (comma separated)

Job description -
{job_description}"""

    logger.info(f"Extracting job info for following job -\n{job_description[:20]}...")
    job_info = get_gpt_response(system_prompt, user_prompt)

    return job_info
