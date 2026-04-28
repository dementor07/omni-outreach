import logging
import os
from logging.handlers import RotatingFileHandler

LOG_DIR = "logs"
os.makedirs(LOG_DIR, exist_ok=True)

LOG_FORMAT = (
    "%(asctime)s | %(levelname)s | %(name)s | %(message)s"
)

def get_logger(name: str) -> logging.Logger:
    logger = logging.getLogger(name)
    logger.setLevel(logging.INFO)

    if logger.handlers:
        return logger  # prevent duplicate handlers

    # INFO logs
    info_handler = RotatingFileHandler(
        f"{LOG_DIR}/app.log",
        maxBytes=5 * 1024 * 1024,  # 5MB
        backupCount=5,
    )
    info_handler.setFormatter(logging.Formatter(LOG_FORMAT))
    info_handler.setLevel(logging.INFO)

    # ERROR logs
    error_handler = RotatingFileHandler(
        f"{LOG_DIR}/error.log",
        maxBytes=5 * 1024 * 1024,
        backupCount=5,
    )
    error_handler.setFormatter(logging.Formatter(LOG_FORMAT))
    error_handler.setLevel(logging.ERROR)

    logger.addHandler(info_handler)
    logger.addHandler(error_handler)

    return logger
