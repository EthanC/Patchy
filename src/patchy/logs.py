"""Configure Loguru sinks for the console and, optionally, Discord."""

import logging
import sys

from loguru import logger
from loguru_discord import DiscordSink

lazy from patchy.config import LogSettings

# Loggers that warn about every retry. Patchy reports a request only once its
# retries are used up, so these are demoted to debug. niquests' urllib3-future is
# importable as urllib3_future when the original urllib3 is also installed.
RETRY_LOGGERS: tuple[str, ...] = tuple(
    f"{package}.{module}"
    for package in ("urllib3", "urllib3_future")
    for module in ("connectionpool", "_async.connectionpool")
)


def _demote_retry_warning(record: logging.LogRecord) -> bool:
    """Log urllib3's per-attempt retry warnings at debug level."""
    if record.levelno == logging.WARNING and str(record.msg).startswith("Retrying ("):
        record.levelno = logging.DEBUG
        record.levelname = logging.getLevelName(logging.DEBUG)

    return True


def configure_logging(settings: LogSettings) -> None:
    """Replace Loguru's default sink with Patchy's configured sinks.

    Standard-library logging (used by SQLAlchemy and niquests) is routed through
    Loguru so every record shares one format and one set of destinations. Warnings
    about individual retries are demoted to debug, because transient failures that
    succeed on retry (such as a brief DNS outage) are not worth reporting.

    Args:
        settings: Logging settings.
    """
    for name in RETRY_LOGGERS:
        retry_logger: logging.Logger = logging.getLogger(name)

        if _demote_retry_warning not in retry_logger.filters:
            retry_logger.addFilter(_demote_retry_warning)

    logger.remove()
    logger.add(sys.stderr, level=settings.level, backtrace=False, diagnose=False)

    if settings.discord_webhook_url is None:
        logger.debug("Log forwarding to Discord is disabled")

        return

    logger.add(
        DiscordSink(str(settings.discord_webhook_url), intercept=True),
        level=settings.discord_level,
        backtrace=False,
        diagnose=False,
        enqueue=True,
    )

    logger.debug(f"Forwarding {settings.discord_level} and above logs to Discord")
