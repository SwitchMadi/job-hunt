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

    question_map = {
        "1": {"key": "company", "prompt": "Company name", "prompt_group": 1},
        "2": {"key": "title", "prompt": "Job title", "prompt_group": 1},
        "3": {
            "key": "employees_count",
            "prompt": "Employees count",
            "prompt_group": 1,
        },
        "4": {"key": "location", "prompt": "Job location", "prompt_group": 2},
        "5": {
            "key": "location_requirement",
            "prompt": "Workplace type (onsite / remote / hybrid)",
            "prompt_group": 2,
        },
        "6": {
            "key": "employment_type",
            "prompt": "Job type (Full-time / Contract)",
            "prompt_group": 2,
        },
        "7": {
            "key": "experience_requirement",
            "prompt": "Years of experience required",
            "prompt_group": 3,
        },
        "8": {
            "key": "experience_level",
            "prompt": "Most suitable experience level required for the job? - "
            "Entry level / Associate / Mid-Senior level / Director / Executive",
            "prompt_group": 3,
        },
        "9": {
            "key": "technical_skills",
            "prompt": "Software technical skills required (comma separated)",
            "prompt_group": 4,
        },
        "10": {
            "key": "other_skills",
            "prompt": "Non technical skills required (comma separated)",
            "prompt_group": 4,
        },
        "11": {
            "key": "software_domain",
            "prompt": "Most matching just 1 software domain out of following? "
            "Frontend Development / Backend Development / Full-stack Development / Mobile App Development / "
            "Data Engineering / Data Science / Solution Architecture / Machine Learning / "
            "Systems Analysis / Database Administration / Embedded Systems Development / "
            "Network Engineering / DevOps / Quality Assurance / Business Analysis / "
            "Cyber Security",
            "prompt_group": 4,
        },
    }
    gpt_resp = ""
    group_questions_prompt = ""
    prompt_groups = set([val["prompt_group"] for key, val in question_map.items()])
    for cur_group in prompt_groups:
        for question_no, question_obj in question_map.items():
            if question_obj["prompt_group"] == cur_group:
                group_questions_prompt += f"{question_no}. {question_obj['prompt']}\n"

        user_prompt = f"""For the following job description on this page, extract following info - 
        {group_questions_prompt}
        Answer format should strictly be - "Question number: Answer"

        Job description -
        {job_description}"""

        gpt_resp += f"{get_gpt_response(system_prompt, user_prompt)}\n"
        group_questions_prompt = ""

    job_info = {}
    for question in gpt_resp.strip().split("\n"):
        answer = re.sub(r"^\d+\.", "", question)
        answer = (
            answer.split("?")[-1]
            .split(":")[-1]
            .split(" - ")[-1]
            .split("\n")[-1]
            .strip()
            .strip("'")
            .strip('"')
        )
        if "cannot determine" in answer.lower():
            continue

        match = re.search(r"(\d+)", question)
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
