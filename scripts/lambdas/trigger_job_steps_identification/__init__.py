import json
from utilities.logging import get_logger
from utilities.aws.ec2 import EC2
from utilities.aws.dynamo import OperationLocksTable

logger = get_logger(name="trigger_job_steps_identification")


def lambda_handler(event, context):
    """
    Lambda function to trigger job steps identification process.
    Checks for existing lock before launching EC2 instance.
    """
    try:
        # Check if job steps identification is already running
        lock_table = OperationLocksTable()
        operation_name = "job_steps_identification"

        if lock_table.is_locked(operation_name):
            logger.info(
                "Job steps identification is already running. Skipping trigger."
            )
            return {
                "statusCode": 200,
                "body": json.dumps(
                    {
                        "message": "Job steps identification already in progress",
                        "skipped": True,
                    }
                ),
            }

        logger.info(
            "No existing lock found. Triggering job steps identification process."
        )

        # TODO: Update script to update env variable for cloudwatch group (for other scripts/lambdas as well)
        script = r"""<script>
                echo Current date and time >> C:\Users\JobHunt\Desktop\startup.log
                echo %DATE% %TIME% >> C:\Users\JobHunt\Desktop\startup.log
                del "C:\Users\JobHunt\AppData\Roaming\Microsoft\Windows\Start Menu\Programs\Startup\startup_script.bat"
                echo call C:\Users\JobHunt\Desktop\venv\Scripts\activate.bat >> "C:\Users\JobHunt\AppData\Roaming\Microsoft\Windows\Start Menu\Programs\Startup\startup_script.bat"
                echo cd C:\Users\JobHunt\Desktop\job-hunt >> "C:\Users\JobHunt\AppData\Roaming\Microsoft\Windows\Start Menu\Programs\Startup\startup_script.bat"
                echo git pull origin main >> "C:\Users\JobHunt\AppData\Roaming\Microsoft\Windows\Start Menu\Programs\Startup\startup_script.bat"
                echo powershell -Command "(Get-Content 'C:\Users\JobHunt\Desktop\job-hunt\config.yml') -replace '^user_email:.*','user_email: bhaskar2choudhary@gmail.com' | Set-Content 'C:\Users\JobHunt\Desktop\job-hunt\config.yml'" >> "C:\Users\JobHunt\AppData\Roaming\Microsoft\Windows\Start Menu\Programs\Startup\startup_script.bat"
                echo powershell -Command "(Get-Content 'C:\Users\JobHunt\Desktop\job-hunt\config.yml') -replace '^cloudwatch_log_group:.*','cloudwatch_log_group: jobs-steps-identification' | Set-Content 'C:\Users\JobHunt\Desktop\job-hunt\config.yml'" >> "C:\Users\JobHunt\AppData\Roaming\Microsoft\Windows\Start Menu\Programs\Startup\startup_script.bat"
                echo python -m scripts.jobs_steps_identification.run >> "C:\Users\JobHunt\AppData\Roaming\Microsoft\Windows\Start Menu\Programs\Startup\startup_script.bat"
                echo python -m scripts.windows.terminate_windows_machine >> "C:\Users\JobHunt\AppData\Roaming\Microsoft\Windows\Start Menu\Programs\Startup\startup_script.bat"
            </script>
            <persist>true</persist>"""

        # Launch EC2 instance to run job steps identification
        EC2(
            instance_pricing_model="on_demand",
            ami_id="ami-08b28ae49511d344b",
            instance_type="t3a.2xlarge",
            key_name="job-hunt",
            security_group="sg-011a3786d569e6382",
            user_data_script=script,
            instance_name="job-steps-identification",
        )

        logger.info("Successfully triggered job steps identification EC2 instance.")

        return {
            "statusCode": 200,
            "body": json.dumps(
                {
                    "message": "Job steps identification process triggered successfully",
                    "triggered": True,
                }
            ),
        }

    except Exception as e:
        logger.exception(f"Error triggering job steps identification: {e}")
        return {
            "statusCode": 500,
            "body": json.dumps(
                {
                    "message": f"Failed to trigger job steps identification: {str(e)}",
                    "error": True,
                }
            ),
        }
