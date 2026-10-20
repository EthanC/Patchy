"""Configure Loguru sinks for the console and, optionally, Discord."""

import sys

from loguru import logger
from loguru_discord import DiscordSink

lazy from patchy.config import LogSettings


def configure_logging(settings: LogSettings, *, username: str) -> None:
    """Replace Loguru's default sink with Patchy's configured sinks.

    Standard-library logging (used by SQLAlchemy and niquests) is routed through
    Loguru so every record shares one format and one set of destinations.

    Args:
        settings: Logging settings.
        username: Name the Discord log forwarder posts as.
    """
    logger.remove()
    logger.add(sys.stderr, level=settings.level, backtrace=False, diagnose=False)

    if settings.discord_webhook_url is None:
        logger.debug("Log forwarding to Discord is disabled")

        return

    logger.add(
        DiscordSink(
            str(settings.discord_webhook_url),
            username=username,
            rich=True,
            intercept=True,
        ),
        level=settings.discord_level,
        backtrace=False,
        diagnose=False,
        enqueue=True,
    )

    logger.debug(f"Forwarding {settings.discord_level} and above logs to Discord")
