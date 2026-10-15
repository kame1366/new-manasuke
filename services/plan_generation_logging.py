from __future__ import annotations

import logging
from pathlib import Path

LOGGER_NAME = "manasuke.plan_generation"
LOG_FILE_NAME = "plan_generation.log"


def get_plan_generation_logger(
    db_path: str | Path,
) -> logging.Logger:
    """Return the plan-generation logger configured for the database."""

    logger = logging.getLogger(LOGGER_NAME)
    logger.setLevel(logging.INFO)
    logger.propagate = False

    log_path = Path(db_path).resolve().parent / LOG_FILE_NAME

    for handler in logger.handlers:
        if (
            isinstance(handler, logging.FileHandler)
            and Path(handler.baseFilename).resolve()
            == log_path
        ):
            return logger

    log_path.parent.mkdir(parents=True, exist_ok=True)

    handler = logging.FileHandler(
        log_path,
        encoding="utf-8",
    )
    handler.setFormatter(
        logging.Formatter(
            "%(asctime)s %(levelname)s "
            "%(message)s"
        )
    )
    logger.addHandler(handler)

    return logger
