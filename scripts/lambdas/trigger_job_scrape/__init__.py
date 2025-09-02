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
            del "C:\Users\JobHunt\AppData\Roaming\Microsoft\Windows\Start Menu\Programs\Startup\startup_script.bat"
            echo call C:\Users\JobHunt\Desktop\venv\Scripts\activate.bat >> "C:\Users\JobHunt\AppData\Roaming\Microsoft\Windows\Start Menu\Programs\Startup\startup_script.bat"
            echo cd C:\Users\JobHunt\Desktop\job-hunt >> "C:\Users\JobHunt\AppData\Roaming\Microsoft\Windows\Start Menu\Programs\Startup\startup_script.bat"
            echo git pull origin main >> "C:\Users\JobHunt\AppData\Roaming\Microsoft\Windows\Start Menu\Programs\Startup\startup_script.bat"
            echo powershell -Command "(Get-Content 'C:\Users\JobHunt\Desktop\job-hunt\config.yml') -replace '^user_email:.*','user_email: bhaskar2choudhary@gmail.com' | Set-Content 'C:\Users\JobHunt\Desktop\job-hunt\config.yml'" >> "C:\Users\JobHunt\AppData\Roaming\Microsoft\Windows\Start Menu\Programs\Startup\startup_script.bat"
            echo python scrape_jobs.py >> C:\Users\JobHunt\Desktop\scrape_jobs.log 2>&1 >> "C:\Users\JobHunt\AppData\Roaming\Microsoft\Windows\Start Menu\Programs\Startup\startup_script.bat"
            echo python -m scripts.windows.terminate_windows_machine >> C:\Users\JobHunt\Desktop\terminate_windows_machine.log 2>&1 >> "C:\Users\JobHunt\AppData\Roaming\Microsoft\Windows\Start Menu\Programs\Startup\startup_script.bat"
        </script>
        <persist>true</persist>"""

        # Launch EC2 instance to run job scraping
        EC2(
            instance_pricing_model="on_demand",
            ami_id="ami-0728222dafaad95d8",
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
