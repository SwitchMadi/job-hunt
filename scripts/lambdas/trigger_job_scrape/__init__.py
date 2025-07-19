import json
from utilities.logging import get_logger
from utilities.aws.ec2 import EC2
from utilities.aws.dynamo import OperationLocksTable

logger = get_logger(name="trigger_job_scrape")


def lambda_handler(event, context):
    """
    Lambda function to trigger job scraping process.
    Checks for existing lock before launching EC2 instance.
    """
    try:
        # Check if job scraping is already running
        lock_table = OperationLocksTable()
        operation_name = "job_scrape"

        if lock_table.is_locked(operation_name):
            logger.info("Job scraping is already running. Skipping trigger.")
            return {
                "statusCode": 200,
                "body": json.dumps(
                    {
                        "message": "Job scraping already in progress",
                        "skipped": True,
                    }
                ),
            }

        logger.info("No existing lock found. Triggering job scraping process.")

        script = r"""<script>
        echo Current date and time >> C:\Users\JobHunt\Desktop\startup.log
        echo %DATE% %TIME% >> C:\Users\JobHunt\Desktop\startup.log
        echo user_email: 'bhaskar2choudhary@gmail.com' >> C:\Users\JobHunt\Desktop\startup_input.yml
        </script>
        <persist>true</persist>"""

        # Launch EC2 instance to run job scraping
        EC2(
            instance_pricing_model="on_demand",
            ami_id="ami-034638e94ea8e378c",
            instance_type="t3a.2xlarge",
            key_name="job-hunt",
            security_group="sg-011a3786d569e6382",
            user_data_script=script,
            instance_name="jobs-scraping",
        )

        logger.info("Successfully triggered job scraping EC2 instance.")

        return {
            "statusCode": 200,
            "body": json.dumps(
                {
                    "message": "Job scraping process triggered successfully",
                    "triggered": True,
                }
            ),
        }

    except Exception as e:
        logger.exception(f"Error triggering job scraping: {e}")
        return {
            "statusCode": 500,
            "body": json.dumps(
                {
                    "message": f"Failed to trigger job scraping: {str(e)}",
                    "error": True,
                }
            ),
        }
