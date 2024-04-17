import logging.config
import yaml
from datetime import datetime
import pytz

config = yaml.safe_load(open("config.yml"))


def get_logger(
    name,
    file_name,
    level="INFO",
):
    today = datetime.now(pytz.timezone("Asia/Kolkata")).date()
    today = f"{today.year}{str(today.month).zfill(2)}{str(today.day).zfill(2)}"
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
                "level": "DEBUG",
                "formatter": "standard",
                "stream": "ext://sys.stdout",
            },
            "file": {
                "class": "logging.handlers.RotatingFileHandler",
                "level": level,
                "formatter": "standard",
                "filename": f"{config['log_folder']}/{file_name}-{today}.log",
                "mode": "a",
                "maxBytes": 2 * 1024 * 1024,
                "backupCount": 50,
            },
        },
        "loggers": {
            "": {"handlers": ["console", "file"], "level": "DEBUG", "propagate": True}
        },
    }

    logging.config.dictConfig(log_config)
    logger = logging.getLogger(name)

    return logger
