import pandas as pd
import numpy as np
from sqlalchemy.types import Integer, Boolean
from datetime import datetime
import yaml
import time
import sys
from concurrent.futures import ThreadPoolExecutor

from jobs.sourcing.linkedin import extract_linkedin_jobs
from jobs.sourcing import extract_job_info
from utilities import generate_hash, unzip_directory
from utilities.sql import get_sql_connection, get_sql_query_output, execute_sql_query
from utilities.logging import get_logger
from utilities.aws.s3 import S3Bucket
from utilities.aws.dynamo import OperationLocksTable
from utilities.selenium import (
    get_selenium_driver,
    close_selenium_driver,
    kill_selenium_chrome,
)

logger = get_logger(name="scrape_jobs")
config = yaml.safe_load(open("config.yml"))

# Initialize lock manager
lock_table = OperationLocksTable()
operation_name = "job_scrape"
lock_id = None

try:
    # Attempt to acquire lock
    lock_id = lock_table.acquire_lock(operation_name)

    if not lock_id:
        logger.info("Another job scraping process is already running. Exiting.")
        sys.exit(0)

    logger.info(f"Lock acquired for job scraping. Lock ID: {lock_id}")

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

        linkedin_job_ids_query = """
            select split_part(coalesce(repost_url, job_url), '/', 6) linkedin_job_id
            from jobs.jobs j
            where coalesce(repost_url, job_url) is not null
            order by job_posted_at desc
            limit 20000
        """
        df_linkedin_jobs_ids = get_sql_query_output(
            query=linkedin_job_ids_query, output_as_dataframe=True
        )
        scraped_linkedin_job_ids = set(df_linkedin_jobs_ids["linkedin_job_id"])

        jobs = extract_linkedin_jobs(jobs_url, scraped_linkedin_job_ids)
        if not jobs:
            logger.warn(
                f"No jobs found on {jobs_url} or all jobs have already been scraped."
            )
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

        # Clean up WebDriver after processing this URL to ensure fresh ChromeDriver for next URL
        try:
            close_selenium_driver()
            # Also kill any remaining Chrome processes to ensure clean cleanup
            kill_selenium_chrome()
            logger.info(
                "WebDriver and Chrome processes cleaned up after processing URL"
            )
        except Exception as e:
            logger.warning(f"Failed to cleanup WebDriver: {e}")

        def extract_job_info_concurrently(func, df, max_workers=25):
            with ThreadPoolExecutor(max_workers=max_workers) as executor:
                results = list(
                    executor.map(
                        lambda row: func(row["job_description"], row["source"]),
                        df.to_dict("records"),
                    )
                )
            return results

        # Only process job info for automatable jobs
        df_automatable_jobs = df_jobs[~df_jobs["is_non_automatable"]].copy()
        if not df_automatable_jobs.empty:
            df_automatable_jobs["job_info"] = extract_job_info_concurrently(
                extract_job_info, df_automatable_jobs
            )
            # Update the original dataframe with processed info
            df_jobs.loc[~df_jobs["is_non_automatable"], "job_info"] = (
                df_automatable_jobs["job_info"]
            )
        # Set empty job info for non-automatable jobs
        df_jobs.loc[df_jobs["is_non_automatable"], "job_info"] = [{}] * sum(
            df_jobs["is_non_automatable"]
        )

        df_dict = pd.json_normalize(df_jobs["job_info"])
        df_jobs = pd.concat([df_jobs, df_dict], axis=1).drop("job_info", axis=1)
        df_jobs = df_jobs.replace({np.nan: None})

        keep_columns = [
            "company",
            "title",
            "location",
            "location_requirement",
            "employment_type",
            "technical_skills",
            "other_skills",
            "employees_count",
            "job_domain",
            "experience_level",
            "experience_requirement_min_years",
            "experience_requirement_max_years",
            "visa_sponsorship",
            "spoken_language_requirement",
            "salary",
            "description_language",
        ]
        for col in keep_columns:
            if col not in df_jobs.columns:
                df_jobs[col] = None

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
                "is_non_automatable": Boolean(),
            },
        )
        main_table_query = """INSERT INTO jobs.jobs
        (job_hash_id, job_url, is_reposted_job, repost_url, job_posted_at,
        "source", job_description, company, title, "location", location_requirement, employment_type, technical_skills,
        other_skills, employees_count, job_domain, experience_level, experience_requirement_min_years,
        experience_requirement_max_years, linkedin_easy_apply, visa_sponsorship, spoken_language_requirement, salary,
        description_language, is_non_automatable)
        SELECT job_hash_id, job_url, is_reposted_job, repost_url, job_posted_at, "source",
        job_description, company, title, "location", location_requirement, employment_type, technical_skills,
        other_skills, employees_count, job_domain, experience_level, experience_requirement_min_years,
        experience_requirement_max_years, linkedin_easy_apply, visa_sponsorship, spoken_language_requirement, salary,
        description_language, is_non_automatable
        FROM jobs.jobs_staging
        WHERE job_hash_id NOT IN (
                                    SELECT DISTINCT job_hash_id
                                    FROM jobs.jobs
                                );
        
        drop table jobs.jobs_staging;
        """
        execute_sql_query(main_table_query)

    driver = get_selenium_driver()
    driver.quit()
except Exception as e:
    logger.exception(f"Unexpected error occurred - {e}")

finally:
    # Always release the lock, even if an error occurred
    if lock_id:
        try:
            lock_table.release_lock(operation_name, lock_id)
            logger.info(f"Lock released for job scraping. Lock ID: {lock_id}")
        except Exception as e:
            logger.exception(f"Error releasing lock: {e}")
