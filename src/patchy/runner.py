"""Check every configured title and report updates."""

import time
from dataclasses import dataclass
from enum import StrEnum, auto
from typing import Any, Self, override
lazy from collections.abc import Callable, Mapping, Sequence

from loguru import logger

from patchy.database import Database, TitleRecord, UpdateRecord, utcnow
from patchy.errors import (
    ConfigError,
    FetchError,
    NotificationError,
    PatchyError,
    StorageError,
)
from patchy.notifier import discord_notifier
from patchy.platforms import Platform, Update, registry
lazy from patchy.client import HttpClient
lazy from patchy.notifier import Notifier


class Outcome(StrEnum):
    """Result of checking a single title."""

    NEW = auto()
    UNCHANGED = auto()
    UPDATED = auto()
    FAILED = auto()


@dataclass(slots=True)
class Summary:
    """Counts of outcomes for one run."""

    new: int = 0
    unchanged: int = 0
    updated: int = 0
    failed: int = 0

    def add(self: Self, outcome: Outcome) -> None:
        """Count an outcome."""
        match outcome:
            case Outcome.NEW:
                self.new += 1
            case Outcome.UNCHANGED:
                self.unchanged += 1
            case Outcome.UPDATED:
                self.updated += 1
            case Outcome.FAILED:
                self.failed += 1

    @override
    def __str__(self: Self) -> str:
        """Describe the run in one line."""
        return (
            f"{self.updated} updated, {self.unchanged} unchanged, "
            f"{self.new} newly tracked, {self.failed} failed"
        )


def build_platforms(
    configured: Mapping[str, Sequence[Mapping[str, Any]]], client: HttpClient
) -> list[Platform[Any]]:
    """Instantiate every enabled platform instance that has titles configured.

    Args:
        configured: Raw instance settings, keyed by platform key.
        client: HTTP client shared by all instances.

    Returns:
        The platform instances to check.

    Raises:
        ConfigError: A platform key is unknown, instance names are not unique, or
            an instance's settings are invalid.
    """
    available: dict[str, type[Platform[Any]]] = registry()
    platforms: list[Platform[Any]] = []

    for key, instances in configured.items():
        if (cls := available.get(key)) is None:
            msg: str = (
                f"Unknown platform {key!r}; available platforms are "
                f"{', '.join(available)}"
            )

            raise ConfigError(msg)

        names: set[str] = set()

        for index, raw in enumerate(instances):
            platform: Platform[Any] = cls.from_config(
                raw, client, location=f"platforms.{key}[{index}]"
            )

            if platform.instance in names:
                msg = (
                    f"platforms.{key}[{index}]: another {platform.name} instance is "
                    f"named {platform.instance!r}; give each instance a unique name"
                )

                raise ConfigError(msg)

            names.add(platform.instance)

            if not platform.settings.enabled:
                logger.debug(f"Skipping {platform.label}, it is disabled")
            elif not platform.titles:
                logger.debug(f"Skipping {platform.label}, no titles are configured")
            else:
                if platform.settings.webhook_url is None:
                    logger.warning(
                        f"{platform.label} has no webhook_url, its updates will "
                        "only be logged"
                    )

                platforms.append(platform)

    return platforms


class Schedule:
    """When each platform instance is next due to be checked.

    Every instance is due immediately. After a check, an instance is due again
    after its own ``interval``, or the default when it sets none; an interval of
    ``0`` means it is not checked again.
    """

    def __init__(
        self: Self,
        platforms: Sequence[Platform[Any]],
        default_interval: int,
        *,
        once: bool = False,
        clock: Callable[[], float] = time.monotonic,
    ) -> None:
        """Create a schedule.

        Args:
            platforms: Platform instances to schedule.
            default_interval: Minutes between checks of instances that set none.
            once: Check every instance once, ignoring every interval.
            clock: Returns the current time in seconds.
        """
        self.clock: Callable[[], float] = clock
        self.intervals: dict[Platform[Any], int] = {
            platform: 0
            if once
            else (
                default_interval
                if platform.settings.interval is None
                else platform.settings.interval
            )
            for platform in platforms
        }
        now: float = clock()
        self.due_at: dict[Platform[Any], float] = dict.fromkeys(platforms, now)

    def pop_due(self: Self) -> list[Platform[Any]]:
        """Take the instances due now and schedule their next check.

        Returns:
            The instances to check, in configuration order.
        """
        now: float = self.clock()
        due: list[Platform[Any]] = [p for p, at in self.due_at.items() if at <= now]

        for platform in due:
            if (minutes := self.intervals[platform]) == 0:
                del self.due_at[platform]
            else:
                self.due_at[platform] = now + minutes * 60

        return due

    def next_check(self: Self) -> tuple[float, list[Platform[Any]]] | None:
        """Find the next instances due to be checked.

        Returns:
            Seconds until they are due and the instances, or ``None`` when no
            instance is checked again.
        """
        if not self.due_at:
            return None

        at: float = min(self.due_at.values())

        return (
            max(0.0, at - self.clock()),
            [p for p, due in self.due_at.items() if due == at],
        )


class Runner:
    """Check titles, persist versions, and send notifications."""

    def __init__(
        self: Self,
        platforms: list[Platform[Any]],
        database: Database,
        *,
        notifier_for: Callable[[Platform[Any]], Notifier | None] = discord_notifier,
        dry_run: bool = False,
    ) -> None:
        """Create a runner.

        Args:
            platforms: Platform instances to check.
            database: Where versions are stored.
            notifier_for: Returns where an instance's updates are announced, or
                ``None`` to only log them.
            dry_run: Check titles without saving versions or sending notifications.
        """
        self.platforms: list[Platform[Any]] = platforms
        self.database: Database = database
        self.notifiers: dict[Platform[Any], Notifier | None] = {
            platform: notifier_for(platform) for platform in platforms
        }
        self.dry_run: bool = dry_run

    def run(self: Self, platforms: Sequence[Platform[Any]] | None = None) -> Summary:
        """Check every title in the given platform instances once.

        A failure checking one title is logged and does not stop the others.

        Args:
            platforms: Instances to check. ``None`` checks every instance.

        Returns:
            Counts of each outcome.

        Raises:
            StorageError: The database failed, so no further progress can be saved.
        """
        summary: Summary = Summary()

        for platform in self.platforms if platforms is None else platforms:
            for title_id in platform.titles:
                summary.add(self._check_safely(platform, title_id))

        return summary

    def _check_safely(self: Self, platform: Platform[Any], title_id: str) -> Outcome:
        """Check a title, converting any non-fatal failure into ``FAILED``."""
        try:
            return self.check(platform, title_id)
        except StorageError:
            raise
        except FetchError as e:
            # Upstream outages are routine, so a traceback adds nothing.
            logger.warning(f"{platform.label} title {title_id}: {e}")
        except NotificationError as e:
            logger.opt(exception=e).error(
                f"{platform.label} title {title_id}: {e}; will retry next run"
            )
        except PatchyError as e:
            logger.opt(exception=e).error(f"{platform.label} title {title_id}: {e}")
        except Exception as e:  # noqa: BLE001 - one bad title must not stop the run.
            logger.opt(exception=e).error(
                f"Unexpected error checking {platform.label} title {title_id}"
            )

        return Outcome.FAILED

    def check(self: Self, platform: Platform[Any], title_id: str) -> Outcome:
        """Check a single title.

        A new version is only stored once its notification has been delivered, so
        an undelivered update is retried on the next run.

        Args:
            platform: The platform the title belongs to.
            title_id: The normalized title identifier.

        Returns:
            What happened.

        Raises:
            PatchyError: The title could not be checked or reported.
        """
        release = platform.fetch(title_id)
        stored: TitleRecord | None = self.database.get_title(
            platform.key, platform.instance, title_id
        )
        label: str = f"{platform.label} title {release.name}"

        if stored is None:
            logger.success(f"Now tracking {label} at version {release.version}")

            self._save(
                TitleRecord(
                    platform=platform.key,
                    instance=platform.instance,
                    title_id=title_id,
                    name=release.name,
                    version=release.version,
                    state=release.state,
                )
            )

            return Outcome.NEW

        stored.name = release.name
        stored.last_checked = utcnow()

        if stored.version == release.version:
            logger.info(f"{label} is unchanged at version {release.version}")

            stored.state = release.state

            self._save(stored)

            return Outcome.UNCHANGED

        update: Update = Update(
            platform=platform,
            release=platform.enrich(release, stored.state),
            previous_version=stored.version,
        )

        logger.success(f"{label} updated from {stored.version} to {release.version}")

        if self.dry_run:
            logger.info(f"Dry run, not reporting or saving the update to {label}")

            return Outcome.UPDATED

        if (notifier := self.notifiers.get(platform)) is not None:
            notifier.send(update)

        stored.version = release.version
        stored.state = release.state
        stored.last_updated = stored.last_checked

        self.database.record_update(
            stored,
            UpdateRecord(
                platform=platform.key,
                instance=platform.instance,
                title_id=title_id,
                name=release.name,
                previous_version=update.previous_version,
                current_version=release.version,
            ),
        )

        return Outcome.UPDATED

    def _save(self: Self, record: TitleRecord) -> None:
        if not self.dry_run:
            self.database.save_title(record)
