import json
from utilities.logging import get_logger
from utilities.aws.ec2 import EC2
from utilities.aws.dynamo import OperationLocksTable

logger = get_logger(name="trigger_share_jobs")


def lambda_handler(event, context):
    """
    Lambda function to trigger share jobs process.
    Checks for existing lock before launching EC2 instance.
    """
    try:
        # Check if share jobs is already running
        lock_table = OperationLocksTable()
        operation_name = "share_jobs"

        if lock_table.is_locked(operation_name):
            logger.info("Share jobs is already running. Skipping trigger.")
            return {
                "statusCode": 200,
                "body": json.dumps(
                    {
                        "message": "Share jobs already in progress",
                        "skipped": True,
                    }
                ),
            }

        logger.info("No existing lock found. Triggering share jobs process.")

        script = r"""<script>
                echo Current date and time >> C:\Users\JobHunt\Desktop\startup.log
                echo %DATE% %TIME% >> C:\Users\JobHunt\Desktop\startup.log
                del "C:\Users\JobHunt\AppData\Roaming\Microsoft\Windows\Start Menu\Programs\Startup\startup_script.bat"
                echo call C:\Users\JobHunt\Desktop\venv\Scripts\activate.bat >> "C:\Users\JobHunt\AppData\Roaming\Microsoft\Windows\Start Menu\Programs\Startup\startup_script.bat"
                echo cd C:\Users\JobHunt\Desktop\job-hunt >> "C:\Users\JobHunt\AppData\Roaming\Microsoft\Windows\Start Menu\Programs\Startup\startup_script.bat"
                echo git pull origin main >> "C:\Users\JobHunt\AppData\Roaming\Microsoft\Windows\Start Menu\Programs\Startup\startup_script.bat"
                echo powershell -Command "(Get-Content 'C:\Users\JobHunt\Desktop\job-hunt\config.yml') -replace '^cloudwatch_log_group:.*','cloudwatch_log_group: jobs-sharing' | Set-Content 'C:\Users\JobHunt\Desktop\job-hunt\config.yml'" >> "C:\Users\JobHunt\AppData\Roaming\Microsoft\Windows\Start Menu\Programs\Startup\startup_script.bat"
                echo python -m scripts.jobs_sharing.run >> "C:\Users\JobHunt\AppData\Roaming\Microsoft\Windows\Start Menu\Programs\Startup\startup_script.bat"
                echo python -m scripts.windows.terminate_windows_machine >> "C:\Users\JobHunt\AppData\Roaming\Microsoft\Windows\Start Menu\Programs\Startup\startup_script.bat"
            </script>
            <persist>true</persist>"""

        # TODO: Update ami_id which has google service account creds
        # Launch EC2 instance to run share jobs
        EC2(
            instance_pricing_model="on_demand",
            ami_id="ami-08b28ae49511d344b",
            instance_type="t3a.2xlarge",
            key_name="job-hunt",
            security_group="sg-011a3786d569e6382",
            user_data_script=script,
            instance_name="share-jobs",
        )

        logger.info("Successfully triggered share jobs EC2 instance.")

        return {
            "statusCode": 200,
            "body": json.dumps(
                {
                    "message": "Share jobs process triggered successfully",
                    "triggered": True,
                }
            ),
        }

    except Exception as e:
        logger.exception(f"Error triggering share jobs: {e}")
        return {
            "statusCode": 500,
            "body": json.dumps(
                {
                    "message": f"Failed to trigger share jobs: {str(e)}",
                    "error": True,
                }
            ),
        }
