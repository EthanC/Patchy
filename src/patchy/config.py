"""Load Patchy's settings, each from exactly one place.

Runtime settings come from ``PATCHY_*`` environment variables (or a ``.env`` file):
dry run, logging, the database path, HTTP behaviour, and the ``config.toml`` path.

What to watch and where to report it comes from ``config.toml``: the interval, the
notification webhook, and every platform's titles and options.

A setting is never read from both. Environment variables for ``config.toml``
settings, or for options that do not exist, are ignored; environment settings
placed in ``config.toml`` are a configuration error.
"""

import tomllib
from pathlib import Path
from typing import Annotated, Any, ClassVar, Literal, Self

from pydantic import (
    BaseModel,
    ConfigDict,
    Field,
    HttpUrl,
    ValidationError,
    field_validator,
)
from pydantic_settings import BaseSettings, SettingsConfigDict

from patchy.errors import ConfigError

DEFAULT_CONFIG_PATH: Path = Path("config.toml")

type LogLevel = Literal[
    "TRACE", "DEBUG", "INFO", "SUCCESS", "WARNING", "ERROR", "CRITICAL"
]


class LogSettings(BaseModel):
    """Console logging and log forwarding to Discord."""

    model_config: ClassVar[ConfigDict] = ConfigDict(extra="ignore")

    level: LogLevel = "INFO"
    discord_webhook_url: HttpUrl | None = None
    discord_level: LogLevel = "WARNING"

    @field_validator("level", "discord_level", mode="before")
    @classmethod
    def _uppercase(cls, value: object) -> object:
        return value.upper() if isinstance(value, str) else value


class DiscordSettings(BaseModel):
    """Where update notifications are delivered.

    The webhook's name and avatar are managed in Discord.
    """

    model_config: ClassVar[ConfigDict] = ConfigDict(extra="forbid")

    webhook_url: HttpUrl | None = None


class DatabaseSettings(BaseModel):
    """SQLite persistence."""

    model_config: ClassVar[ConfigDict] = ConfigDict(extra="ignore")

    path: Path = Path("patchy.db")


class HttpSettings(BaseModel):
    """Behaviour of requests made to upstream services."""

    model_config: ClassVar[ConfigDict] = ConfigDict(extra="ignore")

    timeout: Annotated[float, Field(gt=0)] = 30.0
    retries: Annotated[int, Field(ge=0)] = 3


class PlatformSettings(BaseModel):
    """Settings shared by every platform.

    Platforms needing more options subclass this and set ``Platform.settings_model``.
    """

    model_config: ClassVar[ConfigDict] = ConfigDict(extra="forbid")

    enabled: bool = True
    titles: list[str] = Field(default_factory=list)

    @field_validator("titles")
    @classmethod
    def _dedupe_titles(cls, value: list[str]) -> list[str]:
        return list(dict.fromkeys(value))


class EnvironmentSettings(BaseSettings):
    """Runtime settings, read only from ``PATCHY_*`` environment variables.

    Variable names join the setting's path with underscores, so ``log.level`` is
    ``PATCHY_LOG_LEVEL``. Unknown variables are ignored.
    """

    model_config: ClassVar[SettingsConfigDict] = SettingsConfigDict(
        env_prefix="PATCHY_",
        env_nested_delimiter="_",
        env_nested_max_split=1,
        env_file=".env",
        extra="ignore",
    )

    config: Path = DEFAULT_CONFIG_PATH
    """Location of ``config.toml``."""

    dry_run: bool = False
    """Check titles without saving versions or sending notifications."""

    log: LogSettings = Field(default_factory=LogSettings)
    database: DatabaseSettings = Field(default_factory=DatabaseSettings)
    http: HttpSettings = Field(default_factory=HttpSettings)

    @classmethod
    def load(cls) -> Self:
        """Read settings from the environment and ``.env``.

        Returns:
            The validated settings.

        Raises:
            ConfigError: An environment variable has an invalid value.
        """
        try:
            return cls()
        except ValidationError as e:
            raise ConfigError(_describe(e, prefix="PATCHY_")) from e


class FileSettings(BaseModel):
    """What to watch and where to report it, read only from ``config.toml``."""

    model_config: ClassVar[ConfigDict] = ConfigDict(extra="forbid")

    interval: Annotated[int, Field(ge=0)] = 0
    """Minutes between checks. ``0`` checks once and exits."""

    discord: DiscordSettings = Field(default_factory=DiscordSettings)

    platforms: dict[str, dict[str, Any]] = Field(default_factory=dict)
    """Raw settings per platform key, validated by each platform's own model."""

    @field_validator("platforms", mode="before")
    @classmethod
    def _lowercase_platforms(cls, value: object) -> object:
        if isinstance(value, dict):
            return {str(key).lower(): item for key, item in value.items()}

        return value

    @classmethod
    def load(cls, path: Path) -> Self:
        """Read settings from a TOML file. A missing file yields the defaults.

        Args:
            path: Location of ``config.toml``.

        Returns:
            The validated settings.

        Raises:
            ConfigError: The file is unreadable or contains invalid settings.
        """
        document: dict[str, Any] = {}

        if path.is_file():
            try:
                document = tomllib.loads(path.read_text(encoding="utf-8"))
            except (OSError, UnicodeDecodeError, tomllib.TOMLDecodeError) as e:
                msg: str = f"Failed to read {path}: {e}"

                raise ConfigError(msg) from e

        problems: list[str] = [
            f"{key}: set with {_variable(key)}, not in config.toml"
            for key in document
            if key in EnvironmentSettings.model_fields
        ]
        document = {
            k: v
            for k, v in document.items()
            if k not in EnvironmentSettings.model_fields
        }

        try:
            settings: Self = cls.model_validate(document)
        except ValidationError as e:
            problems.extend(_problems(e))
        else:
            if not problems:
                return settings

        msg = f"Invalid configuration in {path}:\n  " + "\n  ".join(problems)

        raise ConfigError(msg)


def _variable(field_name: str) -> str:
    """Name the environment variable (or variables) for an environment setting."""
    annotation: object = EnvironmentSettings.model_fields[field_name].annotation
    name: str = f"PATCHY_{field_name.upper()}"

    if isinstance(annotation, type) and issubclass(annotation, BaseModel):
        return f"{name}_* environment variables"

    return f"the {name} environment variable"


def _problems(error: ValidationError, prefix: str = "") -> list[str]:
    """Describe each validation failure on one line."""
    lines: list[str] = []

    for item in error.errors():
        path: list[str] = [str(part) for part in item["loc"]]
        name: str = (
            prefix + "_".join(path).upper() if prefix else ".".join(path) or "(root)"
        )

        lines.append(f"{name}: {item['msg']}")

    return lines


def _describe(error: ValidationError, prefix: str = "") -> str:
    """Summarize a validation error as one line per invalid setting."""
    return "Invalid configuration:\n  " + "\n  ".join(_problems(error, prefix))
