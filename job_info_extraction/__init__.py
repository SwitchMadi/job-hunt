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

    logger.info(f"Extracting job info for following job -\n{job_description[:50]}...")

    job_info = {}
    question_map = {
        "1": {"key": "company", "prompt": "Company name"},
        "2": {"key": "title", "prompt": "Job title"},
        "3": {"key": "location", "prompt": "Job location"},
        "4": {
            "key": "location_requirement",
            "prompt": "Job location requirement (onsite / remote / hybrid)",
        },
        "5": {"key": "employment_type", "prompt": "Job type (Full-time / Contract)"},
        "6": {
            "key": "experience_requirement",
            "prompt": "Years of experience required",
        },
        "7": {
            "key": "technical_skills",
            "prompt": "Software technical skills required (comma separated)",
        },
        "8": {
            "key": "other_skills",
            "prompt": "Non technical skills required (comma separated)",
        },
        "9": {
            "key": "employees_count",
            "prompt": "How many employees?",
        },
        "10": {
            "key": "software_domain",
            "prompt": "Software domain? (Backend / Web frontend / App frontend / Data engineering / DevOps / ML-AI)",
        },
    }
    gpt_resp = ""
    question_prompts_group = ""
    i = 0
    for question_no, question_obj in question_map.items():
        i += 1
        question_prompts_group += f"{question_no}. {question_obj['prompt']}\n"

        if (i % 4 == 0) or (i == len(question_map)):
            user_prompt = f"""For the following job description on this page, extract following info - 
            {question_prompts_group}
            Answer format should strictly be - "Question number: Answer"

            Job description -
            {job_description}"""

            gpt_resp += f"{get_gpt_response(system_prompt, user_prompt)}\n"
            question_prompts_group = ""

    for question in gpt_resp.strip().split("\n"):
        answer = (
            question.split(".")[-1]
            .split("?")[-1]
            .split(":")[-1]
            .split("\n")[-1]
            .strip()
            .strip("'")
            .strip('"')
        )
        if "cannot determine" in answer.lower():
            continue

        match = re.match(r"^(\d+)", question)
        if match:
            question_no = match.group(1)
            job_info[question_map[question_no]["key"]] = answer

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
