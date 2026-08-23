from __future__ import annotations

import logging
import re


SECRET_PATTERN = re.compile(r"(?i)(api[_-]?key|authorization|bearer|token)([=: ]+)([^, ]+)")


class SecretFilter(logging.Filter):
    def filter(self, record: logging.LogRecord) -> bool:
        record.msg = SECRET_PATTERN.sub(r"\1\2***REDACTED***", str(record.msg))
        if record.args:
            record.args = tuple(SECRET_PATTERN.sub(r"\1\2***REDACTED***", str(arg)) for arg in record.args)
        return True


def configure_logging(debug: bool = False) -> logging.Logger:
    logger = logging.getLogger("ai_daily")
    logger.setLevel(logging.DEBUG if debug else logging.INFO)
    if not logger.handlers:
        handler = logging.StreamHandler()
        handler.setFormatter(logging.Formatter("%(asctime)s %(levelname)s [%(name)s] %(message)s"))
        handler.addFilter(SecretFilter())
        logger.addHandler(handler)
    return logger

