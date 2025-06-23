# read job_id from sys arguments
import sys

job_id = sys.argv[1] if len(sys.argv) > 1 else None
# If job_id is not provided, exit the script
if not job_id:
    sys.exit(1)

import os

os.environ["LOG_GROUP_STREAM_SUFFIX"] = f"job_id-{job_id}"

from jobs import Job
from user import User

user = User(email="bhaskar2choudhary@gmail.com")
job = Job(job_id=job_id, user=user)

job.application_page.apply()
