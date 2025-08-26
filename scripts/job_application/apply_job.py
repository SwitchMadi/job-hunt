# read job_id from sys arguments
import sys

job_id = sys.argv[1] if len(sys.argv) > 1 else None
# If job_id is not provided, exit the script
if not job_id:
    sys.exit(1)

import os
import yaml

os.environ["LOG_GROUP_STREAM_SUFFIX"] = f"job_id-{job_id}"
config = yaml.safe_load(open("config.yml"))

from jobs import Job
from user import User

user = User(email=config["user_email"])

# Check subscription status before applying
if not user.can_apply_for_jobs:
    subscription_status = user.subscription_status_summary
    raise Exception(
        f"Job application not allowed due to subscription limits: {subscription_status}"
    )

job = Job(job_id=job_id, user=user)

job.application_page.apply()
