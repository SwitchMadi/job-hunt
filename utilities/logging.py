import logging.config
import yaml
from datetime import datetime
import pytz
import os
import dotenv
import boto3

from utilities import str_to_bool


def get_logger(
    name,
    file_log_level="INFO",
    console_log_level="INFO",
    cloudwatch_log_level="INFO",
):
    dotenv.load_dotenv()
    config = yaml.safe_load(open("config.yml"))

    cloudwatch_log_group = config.get("cloudwatch_log_group")
    log_group_suffix = os.getenv("LOG_GROUP_STREAM_SUFFIX")

    today = datetime.now(pytz.timezone("Asia/Kolkata")).date()
    today = f"{today.year}{str(today.month).zfill(2)}{str(today.day).zfill(2)}"

    handlers = ["console"]

    # File handler configuration
    if os.path.exists(config["log_folder"]):
        file_handler = {
            "class": "logging.handlers.RotatingFileHandler",
            "level": file_log_level,
            "formatter": "standard",
            "filename": f"{config['log_folder']}/{cloudwatch_log_group}-{log_group_suffix if log_group_suffix else today}.log",
            "mode": "a",
            "maxBytes": 2 * 1024 * 1024,
            "backupCount": 50,
        }
        handlers.append("file")
    else:
        file_handler = None

    # CloudWatch handler configuration
    if str_to_bool(os.getenv("CLOUDWATCH_LOGS")):
        boto3_logs_client = boto3.client(
            "logs",
            aws_access_key_id=os.getenv("JH_AWS_ACCESS_KEY_ID"),
            aws_secret_access_key=os.getenv("JH_AWS_SECRET_ACCESS_KEY"),
            region_name=os.getenv("JH_AWS_AWS_REGION"),
        )

        # Pre-check/create log group to avoid Watchtower timeout on first log
        # This ensures the log group exists before Watchtower tries to send logs,
        # preventing the background thread from timing out while creating it
        try:
            log_groups = boto3_logs_client.describe_log_groups(
                logGroupNamePrefix=cloudwatch_log_group
            )
            log_group_exists = any(
                lg["logGroupName"] == cloudwatch_log_group
                for lg in log_groups.get("logGroups", [])
            )
            if not log_group_exists:
                try:
                    boto3_logs_client.create_log_group(
                        logGroupName=cloudwatch_log_group
                    )
                except Exception:
                    # Log group might have been created by another process, or we don't have permissions
                    pass
        except Exception:
            # If we can't check/create, let Watchtower handle it
            pass

        cloudwatch_handler = {
            "class": "watchtower.CloudWatchLogHandler",
            "level": cloudwatch_log_level,
            "formatter": "standard",
            "log_group": cloudwatch_log_group,
            "stream_name": f"{cloudwatch_log_group}-{log_group_suffix if log_group_suffix else today}",
            "boto3_client": boto3_logs_client,
            "send_interval": 2,
        }
        handlers.append("cloudwatch")
    else:
        cloudwatch_handler = None

    # Logging configuration
    log_config = {
        "version": 1,
        "disable_existing_loggers": False,
        "formatters": {
            "standard": {
                "format": "%(asctime)s - %(name)s - %(levelname)s - %(message)s"
            }
        },
        "handlers": {
            "console": {
                "class": "logging.StreamHandler",
                "level": console_log_level,
                "formatter": "standard",
                "stream": "ext://sys.stdout",
            },
        },
        "loggers": {"": {"handlers": handlers, "level": "DEBUG", "propagate": True}},
    }

    if file_handler:
        log_config["handlers"]["file"] = file_handler

    if cloudwatch_handler:
        log_config["handlers"]["cloudwatch"] = cloudwatch_handler

    logging.config.dictConfig(log_config)
    logger = logging.getLogger(name)

    return logger
