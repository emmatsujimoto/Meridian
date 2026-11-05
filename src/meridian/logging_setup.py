"""Logging for the command line: readable text by default, JSON lines on request.

Log records go to standard error so they never mix with command output on standard
output. With JSON lines, each record is one JSON object on its own line, which log
collectors can ingest without parsing free text.
"""

import json
import logging
import sys
import time as time
from datetime import datetime, timezone

LOGGER_NAME = "meridian"
LEVELS = ("DEBUG", "INFO", "WARNING", "ERROR")
_RESERVED = set(vars(logging.makeLogRecord({}))) | {"message", "asctime", "taskName"}


class JsonLinesFormatter(logging.Formatter):
    """One JSON object per record: time, level, logger, message and any extra fields."""

    def format(self, record: logging.LogRecord) -> str:
        entry = {
            "time": datetime.fromtimestamp(record.created, timezone.utc).isoformat(),
            "level": record.levelname,
            "logger": record.name,
            "message": record.getMessage(),
        }
        entry.update({k: v for k, v in vars(record).items() if k not in _RESERVED})
        if record.exc_info:
            entry["exception"] = self.formatException(record.exc_info)
        return json.dumps(entry, default=str)


def configure_logging(
    level: str = "WARNING", json_lines: bool = False, log_file: bool = False
) -> logging.Logger:
    if level not in LEVELS:
        raise ValueError(f"level must be one of {', '.join(LEVELS)}")
    logger = logging.getLogger(LOGGER_NAME)
    for handler in list(logger.handlers):
        logger.removeHandler(handler)
        handler.close()
    logger.setLevel(level)
    logger.propagate = False
    console = logging.StreamHandler(sys.stderr)
    if json_lines:
        console.setFormatter(JsonLinesFormatter())
    else:
        console.setFormatter(logging.Formatter("%(levelname)s %(name)s: %(message)s"))
    console.setLevel(level)
    logger.addHandler(console)
    if log_file:
        handler = logging.FileHandler("meridian.log", encoding="utf-8")
        if json_lines:
            handler.setFormatter(JsonLinesFormatter())
        else:
            handler.setFormatter(logging.Formatter("%(levelname)s %(name)s: %(message)s"))
        handler.setLevel(level)
        logger.addHandler(handler)
    return logger
