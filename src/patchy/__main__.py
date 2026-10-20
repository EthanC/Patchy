"""Command-line entry point: ``patchy`` or ``python -m patchy``."""

import argparse
import signal
import sys
import threading
from contextlib import contextmanager
from pathlib import Path
from typing import Any
lazy from collections.abc import Generator
lazy from types import FrameType

from loguru import logger

from patchy import PROJECT_URL
from patchy.client import HttpClient
from patchy.config import EnvironmentSettings, FileSettings, LogSettings
from patchy.database import Database
from patchy.errors import ConfigError, PatchyError
from patchy.logs import configure_logging
from patchy.platforms import Platform, registry
from patchy.runner import Runner, build_platforms

EXIT_OK: int = 0
EXIT_FAILURE: int = 1

_stop: threading.Event = threading.Event()


def parse_args(argv: list[str] | None = None) -> argparse.Namespace:
    """Parse command-line arguments."""
    parser = argparse.ArgumentParser(
        prog="patchy",
        description=(
            "Monitor games on Steam, Battle.net, and PlayStation and notify about "
            "updates via Discord."
        ),
    )
    parser.add_argument(
        "-c",
        "--config",
        type=Path,
        default=None,
        help="path to config.toml (default: $PATCHY_CONFIG or ./config.toml)",
    )

    parser.set_defaults(command="run", once=False, dry_run=False)

    commands = parser.add_subparsers(dest="command")

    run = commands.add_parser("run", help="check titles for updates (default)")
    run.add_argument(
        "--once",
        action="store_true",
        help="check once and exit, ignoring the configured interval",
    )
    run.add_argument(
        "--dry-run",
        action="store_true",
        help="check titles without saving versions or sending notifications",
    )

    commands.add_parser("platforms", help="list available platforms")

    return parser.parse_args(argv)


def main(argv: list[str] | None = None) -> int:
    """Run Patchy and return a process exit code."""
    args: argparse.Namespace = parse_args(argv)

    if args.command == "platforms":
        for key, cls in registry().items():
            print(f"{key:<16}{cls.name}")  # noqa: T201

        return EXIT_OK

    try:
        environment: EnvironmentSettings = EnvironmentSettings.load()
    except PatchyError as e:
        configure_logging(LogSettings())
        logger.critical(str(e))

        return EXIT_FAILURE

    configure_logging(environment.log)

    try:
        _run(
            environment,
            FileSettings.load(args.config or environment.config),
            once=args.once,
            dry_run=args.dry_run or environment.dry_run,
        )
    except ConfigError as e:
        logger.critical(str(e))

        return EXIT_FAILURE
    except PatchyError as e:
        logger.opt(exception=e).critical(str(e))

        return EXIT_FAILURE
    finally:
        logger.complete()

    return EXIT_OK


@contextmanager
def _open_database(environment: EnvironmentSettings) -> Generator[Database]:
    """Open the database for the duration of a ``with`` block."""
    database: Database = Database(environment.database.path)

    try:
        yield database
    finally:
        database.close()


def _run(
    environment: EnvironmentSettings,
    settings: FileSettings,
    *,
    once: bool,
    dry_run: bool,
) -> None:
    """Check titles once, or repeatedly when an interval is configured."""
    logger.info("Patchy")
    logger.info(PROJECT_URL)

    if dry_run:
        logger.warning("Dry run, versions will not be saved and nothing will be sent")

    interval: int = 0 if once else settings.interval

    for signum in (signal.SIGINT, signal.SIGTERM):
        signal.signal(signum, _request_stop)

    with (
        HttpClient(
            timeout=environment.http.timeout, retries=environment.http.retries
        ) as client,
        _open_database(environment) as database,
    ):
        platforms: list[Platform[Any]] = build_platforms(settings.platforms, client)

        if not platforms:
            logger.warning("No titles are configured, nothing to check")

            return

        runner: Runner = Runner(platforms, database, dry_run=dry_run)

        while not _stop.is_set():
            logger.success(f"Finished checking titles: {runner.run()}")

            if interval == 0:
                break

            logger.info(f"Next check in {interval} minutes")

            _stop.wait(interval * 60)


def _request_stop(signum: int, _frame: FrameType | None) -> None:
    """Finish the current check, then exit."""
    logger.info(f"Received {signal.Signals(signum).name}, stopping")

    _stop.set()


if __name__ == "__main__":
    sys.exit(main())
