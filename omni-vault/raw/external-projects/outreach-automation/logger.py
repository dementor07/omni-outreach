import logging
import os
import sys
from logging.handlers import RotatingFileHandler
import rollbar
import rollbar.logger
from rollbar_init import init_rollbar

LOG_DIR = "logs"
os.makedirs(LOG_DIR, exist_ok=True)

LOG_FORMAT = (
    "%(asctime)s | %(levelname)s | %(name)s | %(message)s"
)


class StreamToLogger:
    def __init__(self, logger: logging.Logger, stream, level: int):
        self.logger = logger
        self.stream = stream
        self.level = level

    def write(self, message: str):
        if message:
            msg = message.rstrip()
            if msg:
                self.logger.log(self.level, msg)
            self.stream.write(message)

    def flush(self):
        self.stream.flush()


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

    # Optional Rollbar handler (only if token is set)
    if init_rollbar():
        rollbar_handler = rollbar.logger.RollbarHandler()
        rollbar_handler.setLevel(logging.ERROR)
        logger.addHandler(rollbar_handler)

    return logger


def setup_stdio_tee():
    """
    Mirror stdout/stderr to a rotating file while keeping systemd journal output.
    """
    rollbar_ready = init_rollbar()
    logger = logging.getLogger("stdout_tee")
    logger.setLevel(logging.INFO)
    logger.propagate = False

    if not logger.handlers:
        file_handler = RotatingFileHandler(
            f"{LOG_DIR}/app.log",
            maxBytes=5 * 1024 * 1024,
            backupCount=5,
        )
        file_handler.setFormatter(logging.Formatter(LOG_FORMAT))
        file_handler.setLevel(logging.INFO)
        logger.addHandler(file_handler)

        err_handler = RotatingFileHandler(
            f"{LOG_DIR}/error.log",
            maxBytes=5 * 1024 * 1024,
            backupCount=5,
        )
        err_handler.setFormatter(logging.Formatter(LOG_FORMAT))
        err_handler.setLevel(logging.ERROR)
        logger.addHandler(err_handler)

        # Forward ERROR-level stderr output (uncaught exceptions) to Rollbar
        if rollbar_ready:
            rollbar_handler = rollbar.logger.RollbarHandler()
            rollbar_handler.setLevel(logging.ERROR)
            logger.addHandler(rollbar_handler)

    sys.stdout = StreamToLogger(logger, sys.__stdout__, logging.INFO)
    sys.stderr = StreamToLogger(logger, sys.__stderr__, logging.ERROR)
