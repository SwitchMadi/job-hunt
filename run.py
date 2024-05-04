import pandas as pd
import yaml
from datetime import datetime
import pytz
import numpy as np

from jobs_sourcing.linkedin import extract_linkedin_jobs
from jobs_sourcing import extract_job_info
from utilities.google_services.sheet import Sheet
from utilities.google_services.drive import DriveResource

config = yaml.safe_load(open("config.yml"))

jobs = extract_linkedin_jobs()
df_jobs = pd.DataFrame(jobs)
df_jobs["source"] = "linkedin"
df_jobs["job_info"] = df_jobs.apply(
    lambda row: extract_job_info(row["job_description"], source=row["source"]), axis=1
)
df_dict = pd.json_normalize(df_jobs["job_info"])
df_jobs = pd.concat([df_jobs, df_dict], axis=1).drop("job_info", axis=1)
df_jobs = df_jobs.replace({np.nan: None})

user_folder_id = None
root_folder = DriveResource(resource_id="root")
for resource in root_folder.get_folder_resources():
    if (resource["mimeType"] == "application/vnd.google-apps.folder") and (
        resource["name"] == config["user_email"]
    ):
        user_folder_id = resource["id"]

if user_folder_id:
    user_folder = DriveResource(resource_id=user_folder_id)
else:
    user_folder = DriveResource(
        name=config["user_email"],
        resource_type="folder",
        parent_folder_id=root_folder.id,
    )
    user_folder.share(email=config["user_email"])

today = datetime.now(pytz.timezone("Asia/Kolkata")).date()
today = f"{today.year}{str(today.month).zfill(2)}{str(today.day).zfill(2)}"
cur_month = today[:-2]

jobs_sheet = None
for resource in user_folder.get_folder_resources():
    if (resource["mimeType"] == "application/vnd.google-apps.spreadsheet") and (
        resource["name"] == cur_month
    ):
        jobs_sheet = Sheet(sheet_id=resource["id"])

if jobs_sheet is None:
    jobs_sheet = Sheet(title=cur_month, folder_id=user_folder.id)

jobs_sheet.add_new_tab(tab_name=today)
jobs_sheet.delete_tab(tab_name="Sheet1")

jobs_sheet.write_dataframe_to_tab(df=df_jobs, tab_name=today, mode="append")
jobs_sheet.reset_tab_row_heights(tab_name=today)
