import pandas as pd
import numpy as np
from sqlalchemy.types import Integer, Boolean
from datetime import datetime
import yaml
import time

from jobs.sourcing.linkedin import extract_linkedin_jobs
from jobs.sourcing import extract_job_info
from utilities import generate_hash, unzip_directory
from utilities.sql import get_sql_connection, get_sql_query_output, execute_sql_query
from utilities.logging import get_logger
from utilities.aws.s3 import S3Bucket

logger = get_logger(name="scrape_jobs", file_name="job-hunt")
config = yaml.safe_load(open("config.yml"))

try:
    user_email = None
    while user_email is None:
        time.sleep(1)
        logger.info("Checking if user email has been set in startup config...")
        startup_config = yaml.safe_load(open(config["startup_input"])) or {}
        user_email = startup_config.get("user_email")

        if user_email:
            logger.info(f"Writing user email {user_email} to main config...")
            config["user_email"] = user_email
            with open("config.yml", "w") as file:
                yaml.safe_dump(config, file)

    s3_bucket = S3Bucket(bucket_name=config["s3_bucket"])
    chrome_profile_fetched = s3_bucket.fetch_data(
        file_s3_path=f"chrome_profiles/{config['user_email']}.zip",
        file_local_path=f"{config['chrome_profile_path']}/{config['user_email']}.zip",
    )
    if chrome_profile_fetched:
        logger.info("Unzipping user chrome profile...")
        unzip_directory(
            zip_file_path=f"{config['chrome_profile_path']}/{config['user_email']}.zip",
            extract_dir=f"{config['chrome_profile_path']}/{config['user_email']}",
        )

    for jobs_url in config["scraping"]["linkedin"]["jobs_urls"]:
        logger.info(f"Scraping url - {jobs_url}")
        jobs = extract_linkedin_jobs(jobs_url)
        if not jobs:
            continue

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
        logger.info(
            f"Jobs remaining after removing already scraped - {df_jobs.shape[0]}"
        )
        if df_jobs.empty:
            continue

        df_jobs["job_info"] = df_jobs.apply(
            lambda row: extract_job_info(row["job_description"], source=row["source"]),
            axis=1,
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
except Exception as e:
    logger.exception(f"Unexpected error occurred - {e}")
