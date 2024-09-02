import logging.config
import yaml
from datetime import datetime
import pytz
import os


def get_logger(
    name,
    file_name,
    file_log_level="INFO",
    console_log_level="INFO",
):
    config = yaml.safe_load(open("config.yml"))

    handlers = ["console"]
    if os.path.exists(config["log_folder"]):
        today = datetime.now(pytz.timezone("Asia/Kolkata")).date()
        today = f"{today.year}{str(today.month).zfill(2)}{str(today.day).zfill(2)}"

        file_handler = {
            "class": "logging.handlers.RotatingFileHandler",
            "level": file_log_level,
            "formatter": "standard",
            "filename": f"{config['log_folder']}/{file_name}-{today}.log",
            "mode": "a",
            "maxBytes": 2 * 1024 * 1024,
            "backupCount": 50,
        }

        handlers.append("file")
    else:
        file_handler = None

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

    logging.config.dictConfig(log_config)
    logger = logging.getLogger(name)

    return logger
