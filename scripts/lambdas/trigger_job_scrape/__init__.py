import json
from utilities.logging import get_logger
from utilities.aws.ec2 import EC2
from utilities.aws.dynamo import OperationLocksTable

logger = get_logger(name="trigger_job_scrape")


def lambda_handler(event, context):
    """
    Lambda function to trigger job scraping process.
    Checks for existing lock before launching EC2 instance.
    Event-driven: AMI ID, branch name, and other configs come from EventBridge payload.
    """
    try:
        # Extract configuration from EventBridge event
        ami_id = event.get("ami_id")
        branch_name = event.get("branch_name", "main")  # Default to main branch

        if not ami_id:
            raise ValueError("ami_id is required in the event payload")

        logger.info(f"Event received: AMI={ami_id}, Branch={branch_name}")

        # Check if job scraping is already running
        lock_table = OperationLocksTable()
        # Sanitize branch name for lock name (replace slashes with underscores)
        sanitized_branch_name = branch_name.replace("/", "_")
        operation_name = f"job_scrape_{sanitized_branch_name}"

        if lock_table.is_locked(operation_name):
            logger.info(
                f"Job scraping for branch {branch_name} is already running. Skipping trigger."
            )
            return {
                "statusCode": 200,
                "body": json.dumps(
                    {
                        "message": f"Job scraping for branch {branch_name} already in progress",
                        "skipped": True,
                    }
                ),
            }

        logger.info(
            f"No existing lock found. Triggering job scraping process with AMI: {ami_id}, Branch: {branch_name}"
        )

        # Create user data script with dynamic branch checkout and operation name
        script = rf"""<script>
            echo Current date and time >> C:\Users\JobHunt\Desktop\startup.log
            echo %DATE% %TIME% >> C:\Users\JobHunt\Desktop\startup.log
            echo user_email: 'bhaskar2choudhary@gmail.com' >> C:\Users\JobHunt\Desktop\startup_input.yml
            del "C:\Users\JobHunt\AppData\Roaming\Microsoft\Windows\Start Menu\Programs\Startup\startup_script.bat"
            echo call C:\Users\JobHunt\Desktop\venv\Scripts\activate.bat >> "C:\Users\JobHunt\AppData\Roaming\Microsoft\Windows\Start Menu\Programs\Startup\startup_script.bat"
            echo cd C:\Users\JobHunt\Desktop\job-hunt >> "C:\Users\JobHunt\AppData\Roaming\Microsoft\Windows\Start Menu\Programs\Startup\startup_script.bat"
            echo git pull origin main >> "C:\Users\JobHunt\AppData\Roaming\Microsoft\Windows\Start Menu\Programs\Startup\startup_script.bat"
            echo git fetch origin >> "C:\Users\JobHunt\AppData\Roaming\Microsoft\Windows\Start Menu\Programs\Startup\startup_script.bat"
            echo git checkout {branch_name} >> "C:\Users\JobHunt\AppData\Roaming\Microsoft\Windows\Start Menu\Programs\Startup\startup_script.bat"
            echo git pull origin {branch_name} >> "C:\Users\JobHunt\AppData\Roaming\Microsoft\Windows\Start Menu\Programs\Startup\startup_script.bat"
            echo powershell -Command "(Get-Content 'C:\Users\JobHunt\Desktop\job-hunt\config.yml') -replace '^user_email:.*','user_email: bhaskar2choudhary@gmail.com' | Set-Content 'C:\Users\JobHunt\Desktop\job-hunt\config.yml'" >> "C:\Users\JobHunt\AppData\Roaming\Microsoft\Windows\Start Menu\Programs\Startup\startup_script.bat"
            echo python scrape_jobs.py --operation-name {operation_name} >> "C:\Users\JobHunt\AppData\Roaming\Microsoft\Windows\Start Menu\Programs\Startup\startup_script.bat"
            echo python -m scripts.windows.terminate_windows_machine >> "C:\Users\JobHunt\AppData\Roaming\Microsoft\Windows\Start Menu\Programs\Startup\startup_script.bat"
        </script>
        <persist>true</persist>"""

        # Launch EC2 instance to run job scraping
        EC2(
            instance_pricing_model="on_demand",
            ami_id=ami_id,
            instance_type="t3a.2xlarge",
            key_name="job-hunt",
            security_group="sg-011a3786d569e6382",
            user_data_script=script,
            instance_name="jobs-scraping",
        )

        logger.info(
            f"Successfully triggered job scraping EC2 instance with AMI: {ami_id}, Branch: {branch_name}"
        )

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
