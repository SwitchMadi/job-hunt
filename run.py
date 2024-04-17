import pandas as pd
import yaml
from datetime import datetime
import pytz

from jobs_sourcing.linkedin import extract_linkedin_jobs
from job_info_extraction import extract_job_info
from utilities.google_services.sheet import (
    create_sheet,
    add_new_tab_to_sheet,
    delete_tab_from_sheet,
    write_dataframe_to_sheet,
)
from utilities.google_services.drive import (
    create_drive_folder,
    share_resource,
    list_folder_resources,
)

config = yaml.safe_load(open("config.yml"))

jobs = extract_linkedin_jobs()
df_jobs = pd.DataFrame(jobs)
df_jobs["source"] = "linkedin"
df_jobs["job_info"] = df_jobs.apply(
    lambda row: extract_job_info(row["job_description"], source=row["source"]), axis=1
)

user_folder_id = None
for resource in list_folder_resources():
    if (resource["mimeType"] == "application/vnd.google-apps.folder") and (
        resource["name"] == config["user_email"]
    ):
        user_folder_id = resource["id"]
if user_folder_id is None:
    user_folder_id = create_drive_folder(config["user_email"])
    share_resource(resource_id=user_folder_id, email=config["user_email"])

today = datetime.now(pytz.timezone("Asia/Kolkata")).date()
today = f"{today.year}{str(today.month).zfill(2)}{str(today.day).zfill(2)}"
cur_month = today[:-2]

jobs_sheet_id = None
for resource in list_folder_resources(folder_id=user_folder_id):
    if (resource["mimeType"] == "application/vnd.google-apps.spreadsheet") and (
        resource["name"] == cur_month
    ):
        jobs_sheet_id = resource["id"]
if jobs_sheet_id is None:
    jobs_sheet_id = create_sheet(sheet_title=cur_month, folder_id=user_folder_id)

add_new_tab_to_sheet(sheet_id=jobs_sheet_id, tab_name=today)
delete_tab_from_sheet(sheet_id=jobs_sheet_id, tab_name="Sheet1")

write_dataframe_to_sheet(
    df=df_jobs, sheet_id=jobs_sheet_id, tab_name=today, mode="append"
)
