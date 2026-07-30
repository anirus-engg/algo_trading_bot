"""
Centralized logging for the stock trading agent.
Logs to both console and a rotating daily log file.
"""
import logging
import os
from datetime import datetime
from logging.handlers import TimedRotatingFileHandler

LOG_DIR = os.path.expanduser("~/.local/share/stockagent")
try:
    os.makedirs(LOG_DIR, exist_ok=True)
except OSError:
    LOG_DIR = os.path.join(os.path.dirname(os.path.abspath(__file__)), "logs")
    os.makedirs(LOG_DIR, exist_ok=True)


def get_logger(name: str) -> logging.Logger:
    """Get a named logger with console + file output."""
    logger = logging.getLogger(name)

    if logger.handlers:
        return logger  # already configured

    logger.setLevel(logging.DEBUG)

    formatter = logging.Formatter(
        fmt="%(asctime)s [%(name)-20s] %(levelname)-8s %(message)s",
        datefmt="%Y-%m-%d %H:%M:%S"
    )

    # Console handler
    console = logging.StreamHandler()
    console.setLevel(logging.INFO)
    console.setFormatter(formatter)
    logger.addHandler(console)

    # File handler — rotates daily, keeps 30 days
    log_file = os.path.join(LOG_DIR, "stockagent.log")
    file_handler = TimedRotatingFileHandler(
        log_file, when="midnight", interval=1, backupCount=30
    )
    file_handler.setLevel(logging.DEBUG)
    file_handler.setFormatter(formatter)
    logger.addHandler(file_handler)

    return logger
