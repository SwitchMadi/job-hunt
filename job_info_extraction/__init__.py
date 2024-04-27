import re

from utilities.logging import get_logger
from utilities.gpt import get_gpt_response

logger = get_logger(name="job_info_extraction", file_name="job-hunt")


def extract_job_info(job_description, source):
    if source == "linkedin":
        system_prompt = (
            "You are an assistant which reads given job description, sourced from LinkedIn, and help "
            "users extract meaningful information. You always answer crisp and short. If you are not sure, then"
            "your standard answer is - Cannot Determine"
        )
    else:
        system_prompt = (
            "You are an assistant which reads given job description and help users extract meaningful "
            "information. You always answer crisp and short. If you are not sure, then"
            "your standard answer is - Cannot Determine"
        )

    user_prompt = f"""For the following job description on this page, extract following info - 
1. Company name
2. Job Title
3. Job location
4. Job location requirement (onsite / remote / hybrid)
5. Job type (Full-time / Contract)
6. Years of experience required
7. Software technical skills required (comma separated)
8. Other skills required (comma separated)
9. How many employees?

Answer format should be - "Question number: Answer"

Job description -
{job_description}"""

    logger.info(f"Extracting job info for following job -\n{job_description[:50]}...")
    gpt_resp = get_gpt_response(system_prompt, user_prompt)

    job_info = {}
    question_map = {
        "1": "company",
        "2": "title",
        "3": "location",
        "4": "location_requirement",
        "5": "employment_type",
        "6": "experience_requirement",
        "7": "technical_skills",
        "8": "other_skills",
        "9": "employees_count",
    }
    for question in gpt_resp.split("\n"):
        answer = question.split(":")[-1]
        question_no = question[0]
        job_info[question_map[question_no]] = answer.strip()

    if job_info.get("experience_requirement"):
        years = re.findall(r"\d+", job_info["experience_requirement"])
        years = [int(x.split(".")[0]) for x in years]
        min_years = min(years) if years else None
        max_years = max(years) if years else None
        job_info["experience_requirement_min_years"] = min_years
        job_info["experience_requirement_max_years"] = max_years
        del job_info["experience_requirement"]

    if job_info.get("employees_count"):
        employees_count = re.findall(
            r"\d+", job_info["employees_count"].replace(",", "")
        )
        employees_count = [int(x) for x in employees_count]
        employees_count = min(employees_count) if employees_count else None
        job_info["employees_count"] = employees_count

    return job_info
