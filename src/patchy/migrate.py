"""Import title history from Renovate, Patchy's predecessor."""

import json
lazy from pathlib import Path

from loguru import logger

from patchy.database import Database, TitleRecord
from patchy.errors import ConfigError

# Renovate's history.json sections, mapped to Patchy platform keys.
RENOVATE_PLATFORMS: dict[str, str] = {
    "steam": "steam",
    "battle": "battlenet",
    "prospero": "playstation5",
    "orbis": "playstation4",
}


def import_renovate_history(path: Path, database: Database) -> int:
    """Seed the database with versions from a Renovate ``history.json`` file.

    Titles Patchy already tracks are left untouched, so this is safe to rerun.

    Args:
        path: Location of ``history.json``.
        database: Database to import into.

    Returns:
        The number of titles imported.

    Raises:
        ConfigError: The file could not be read or is not Renovate history.
    """
    try:
        history: object = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, UnicodeDecodeError, json.JSONDecodeError) as e:
        msg: str = f"Failed to read {path}: {e}"

        raise ConfigError(msg) from e

    if not isinstance(history, dict):
        msg = f"{path} is not a Renovate history file"

        raise ConfigError(msg)

    imported: int = 0

    for section, platform in RENOVATE_PLATFORMS.items():
        titles: object = history.get(section) or {}

        if not isinstance(titles, dict):
            logger.warning(f"Skipping section {section!r} in {path}, not a mapping")

            continue

        for title_id, version in titles.items():
            if not isinstance(version, str | int):
                logger.warning(f"Skipping {section} title {title_id}, no version")

                continue

            if database.get_title(platform, str(title_id)) is not None:
                logger.debug(f"Skipping {platform} title {title_id}, already tracked")

                continue

            database.save_title(
                TitleRecord(
                    platform=platform, title_id=str(title_id), version=str(version)
                )
            )

            imported += 1

    logger.success(f"Imported {imported} titles from {path}")

    return imported
