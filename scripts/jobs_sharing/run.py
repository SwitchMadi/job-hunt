import sys
from utilities.sql import get_sql_query_output
from utilities.logging import get_logger
from utilities.aws.dynamo import OperationLocksTable
from user import User


logger = get_logger(name="share_jobs")

# Initialize lock manager
lock_table = OperationLocksTable()
operation_name = "share_jobs"
lock_id = None

try:
    # Attempt to acquire lock
    lock_id = lock_table.acquire_lock(operation_name)

    if not lock_id:
        logger.info("Another share jobs process is already running. Exiting.")
        sys.exit(0)

    logger.info(f"Lock acquired for share jobs. Lock ID: {lock_id}")

    # TODO: Remove share_jobs flag from users table
    user_emails_to_share_jobs_query = """
        select email
        from users.users
        where share_jobs is true;
    """
    emails = get_sql_query_output(user_emails_to_share_jobs_query)
    logger.info(f"Total users to share jobs with - {len(emails)}")

    for email in emails:
        user = User(email=email["email"])

        # Check if user can share jobs based on subscription
        if not user.can_share_jobs:
            logger.warning(
                f"User {user.email} cannot share jobs due to subscription limits. "
                f"Subscription status: {user.subscription_status_summary}"
            )
            continue

        user.share_jobs()

finally:
    # Always release the lock, even if an error occurred
    if lock_id:
        try:
            lock_table.release_lock(operation_name, lock_id)
            logger.info(f"Lock released for share jobs. Lock ID: {lock_id}")
        except Exception as e:
            logger.exception(f"Error releasing lock: {e}")
