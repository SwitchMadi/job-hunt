from utilities.sql import get_sql_query_output
from utilities.logging import get_logger
from user import User

# imports for lambda requirements.txt
import pandas as pd
from utilities.google_services.sheet import Sheet


logger = get_logger(name="share_jobs")


def lambda_handler(event, context):
    user_emails_to_share_jobs_query = """
        select email
        from users.users
        where share_jobs is true;
    """
    emails = get_sql_query_output(user_emails_to_share_jobs_query)
    logger.info(f"Total users to share jobs with - {len(emails)}")

    for email in emails:
        user = User(email=email["email"])
        user.share_jobs()

    return
