import re

from utilities.logging import get_logger
from utilities.llm import create_llm_service

_llm_service = create_llm_service(provider="openai")

logger = get_logger(name="job_info_extraction")


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
            "key": "job_domain",
            "prompt": "Most matching just 1 job domain out of following? "
            "Frontend Development / Backend Development / Full-stack Development / Mobile App Development / "
            "Data Engineering / ML-AI / Solution Architecture / Machine Learning / "
            "Systems Analysis / Database Administration / Embedded Systems Development / "
            "Network Engineering / DevOps / Quality Assurance / Business Analysis / Data Analysis / Cyber Security",
            "prompt_group": 4,
        },
        "12": {
            "key": "visa_sponsorship",
            "prompt": "Is visa sponsorship available? Yes / No / Cannot Determine",
            "prompt_group": 5,
        },
        "13": {
            "key": "spoken_language_requirement",
            "prompt": "Spoken language requirement (comma separated)",
            "prompt_group": 5,
        },
        "14": {
            "key": "salary",
            "prompt": "Salary as mentioned",
            "prompt_group": 5,
        },
        "15": {
            "key": "description_language",
            "prompt": "What language is the description majorly written in? Mention just one language.",
            "prompt_group": 5,
        },
    }
    gpt_resp = ""
    group_questions_prompt = ""
    prompt_groups = set([val["prompt_group"] for key, val in question_map.items()])
    for cur_group in prompt_groups:
        for question_no, question_obj in question_map.items():
            if question_obj["prompt_group"] == cur_group:
                group_questions_prompt += f"{question_no}. {question_obj['prompt']}\n"

        user_prompt = f"""Job description -
        {job_description}
        
        For the following job description, extract following info - 
        {group_questions_prompt}
        Answer format should strictly be - "Question number: Answer"
        """

        gpt_resp += f"{_llm_service.chat(system_prompt, user_prompt)}\n"
        group_questions_prompt = ""

    job_info = {}
    try:
        gpt_resp_questions = gpt_resp.strip().split("\n\n")
        if len(gpt_resp_questions) == 1:
            gpt_resp_questions = gpt_resp.strip().split("\n")
        for question in gpt_resp_questions:
            answer = re.sub(r"^\d+\.", "", question)
            answer = (
                answer.split("?")[-1]
                .split(":")[-1]
                .split("\n")[-1]
                .strip("-")
                .strip()
                .strip("'")
                .strip('"')
            )
            if "cannot determine" in answer.lower():
                continue

            match = re.search(r"(\d+)", question)
            if match:
                question_no = match.group(1)
                if question_map.get(question_no):
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
    except Exception as e:
        logger.exception(
            f"An unexpected error occurred while extracting job info - {e}\nJob description -\n{job_description}"
        )

    return job_info
