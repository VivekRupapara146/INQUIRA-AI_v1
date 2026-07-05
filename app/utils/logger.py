import logging
import sys

from app.config import get_settings


def get_logger(name: str) -> logging.Logger:
    settings = get_settings()
    logger = logging.getLogger(name)

    if not logger.handlers:  # avoid duplicate handlers on reimport
        handler = logging.StreamHandler(sys.stdout)
        formatter = logging.Formatter(
            "%(asctime)s | %(levelname)-8s | %(name)s | %(message)s",
            datefmt="%H:%M:%S",
        )
        handler.setFormatter(formatter)
        logger.addHandler(handler)
        logger.setLevel(settings.log_level)

    return logger
