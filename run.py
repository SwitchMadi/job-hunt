from jobs_sourcing.linkedin import extract_linkedin_jobs
from job_info_extraction import extract_job_info

job_description = extract_linkedin_jobs()
job_info = extract_job_info(job_description, source="linkedin")
print(job_info)
