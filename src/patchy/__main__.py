"""Command-line entry point: ``patchy`` or ``python -m patchy``."""

import argparse
import os
import signal
import sys
import threading
from contextlib import contextmanager
from pathlib import Path
from typing import Any
lazy from collections.abc import Generator
lazy from types import FrameType

from loguru import logger

from patchy.client import HttpClient
from patchy.config import DEFAULT_CONFIG_PATH, LogSettings, Settings
from patchy.database import Database
from patchy.errors import PatchyError
from patchy.logs import configure_logging
from patchy.migrate import import_renovate_history
from patchy.notifier import DiscordNotifier, Notifier
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
        default=Path(os.environ.get("PATCHY_CONFIG", DEFAULT_CONFIG_PATH)),
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

    history = commands.add_parser(
        "import-history", help="import versions from a Renovate history.json file"
    )
    history.add_argument("path", type=Path, help="path to history.json")

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
        settings: Settings = Settings.load(args.config)
    except PatchyError as e:
        configure_logging(LogSettings(), username="Patchy")
        logger.critical(str(e))

        return EXIT_FAILURE

    configure_logging(settings.log, username=settings.discord.username)

    try:
        match args.command:
            case "import-history":
                with _open_database(settings) as database:
                    import_renovate_history(args.path, database)
            case _:
                _run(
                    settings,
                    once=args.once,
                    dry_run=args.dry_run or settings.dry_run,
                )
    except PatchyError as e:
        logger.opt(exception=e).critical(str(e))

        return EXIT_FAILURE
    finally:
        logger.complete()

    return EXIT_OK


@contextmanager
def _open_database(settings: Settings) -> Generator[Database]:
    """Open the database for the duration of a ``with`` block."""
    database: Database = Database(settings.database.path)

    try:
        yield database
    finally:
        database.close()


def _run(settings: Settings, *, once: bool, dry_run: bool) -> None:
    """Check titles once, or repeatedly when an interval is configured."""
    logger.info("Patchy")
    logger.info("https://github.com/EthanC/Patchy")

    if dry_run:
        logger.warning("Dry run, versions will not be saved and nothing will be sent")

    notifier: Notifier | None = None

    if settings.discord.webhook_url is not None:
        notifier = DiscordNotifier(settings.discord, str(settings.discord.webhook_url))
    else:
        logger.warning("No Discord webhook is configured, updates will only be logged")

    interval: int = 0 if once else settings.interval

    for signum in (signal.SIGINT, signal.SIGTERM):
        signal.signal(signum, _request_stop)

    with (
        HttpClient(
            timeout=settings.http.timeout, retries=settings.http.retries
        ) as client,
        _open_database(settings) as database,
    ):
        platforms: list[Platform[Any]] = build_platforms(settings.platforms, client)

        if not platforms:
            logger.warning("No titles are configured, nothing to check")

            return

        runner: Runner = Runner(platforms, database, notifier, dry_run=dry_run)

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
