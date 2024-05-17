import pandas as pd
import numpy as np
from sqlalchemy.types import Integer, Boolean
from datetime import datetime

from jobs.sourcing.linkedin import extract_linkedin_jobs
from jobs.sourcing import extract_job_info
from utilities import generate_hash
from utilities.sql import get_sql_connection, get_sql_query_output, execute_sql_query
from utilities.logging import get_logger


logger = get_logger(name="scrape_jobs", file_name="job-hunt")

jobs = extract_linkedin_jobs()
df_jobs = pd.DataFrame(jobs)

df_jobs["source"] = "linkedin"
df_jobs["job_hash_id"] = df_jobs["job_url"].apply(generate_hash)
df_jobs.drop_duplicates("job_hash_id", inplace=True)
logger.info(f"Jobs scraped from linkedin - {df_jobs.shape[0]}")

scraped_jobs_query = f"""
select job_hash_id
from jobs.jobs
where job_posted_at >= {datetime.now().timestamp() - 7*24*60*60}
"""
df_scraped_jobs = get_sql_query_output(
    query=scraped_jobs_query, output_as_dataframe=True
)
scraped_jobs = set(df_scraped_jobs["job_hash_id"])
df_jobs = df_jobs[~df_jobs["job_hash_id"].isin(scraped_jobs)]
df_jobs.reset_index(drop=True, inplace=True)
logger.info(f"Jobs remaining after removing already scraped - {df_jobs.shape[0]}")


df_jobs["job_info"] = df_jobs.apply(
    lambda row: extract_job_info(row["job_description"], source=row["source"]), axis=1
)

df_dict = pd.json_normalize(df_jobs["job_info"])
df_jobs = pd.concat([df_jobs, df_dict], axis=1).drop("job_info", axis=1)
df_jobs = df_jobs.replace({np.nan: None})

con = get_sql_connection(con_type="sqlalchemy")
df_jobs.to_sql(
    name="jobs_staging",
    con=con,
    schema="jobs",
    if_exists="replace",
    index=False,
    chunksize=1000,
    method="multi",
    dtype={
        "employees_count": Integer(),
        "experience_requirement_min_years": Integer(),
        "experience_requirement_max_years": Integer(),
        "job_posted_at": Integer(),
        "is_reposted_job": Boolean(),
        "linkedin_easy_apply": Boolean(),
    },
)
main_table_query = """INSERT INTO jobs.jobs
(job_hash_id, job_url, is_reposted_job, repost_url, job_posted_at, 
"source", job_description, company, title, "location", location_requirement, employment_type, technical_skills, 
other_skills, employees_count, software_domain, experience_level, experience_requirement_min_years, 
experience_requirement_max_years, linkedin_easy_apply)
SELECT job_hash_id, job_url, is_reposted_job, repost_url, job_posted_at, "source", 
job_description, company, title, "location", location_requirement, employment_type, technical_skills, other_skills, 
employees_count, software_domain, experience_level, experience_requirement_min_years, experience_requirement_max_years, 
linkedin_easy_apply
FROM jobs.jobs_staging
WHERE job_hash_id NOT IN (
                            SELECT DISTINCT job_hash_id
                            FROM jobs.jobs
                        );

drop table jobs.jobs_staging;
"""
execute_sql_query(main_table_query)
