"""Load Patchy's settings from ``config.toml`` and environment variables.

Precedence, highest first: environment variables, a ``.env`` file, ``config.toml``,
then defaults. Environment variables use the ``PATCHY_`` prefix and ``_`` between
nested keys, for example ``PATCHY_DISCORD_WEBHOOK_URL``.

Titles and other platform settings are the exception: they are read from
``config.toml`` only. Environment variables for them, or for options that do not
exist, are ignored.
"""

import tomllib
from pathlib import Path
from typing import Annotated, Any, ClassVar, Literal, Self, override

from pydantic import (
    BaseModel,
    ConfigDict,
    Field,
    HttpUrl,
    ValidationError,
    field_validator,
)
from pydantic_settings import (
    BaseSettings,
    PydanticBaseSettingsSource,
    SettingsConfigDict,
)
lazy from pydantic.fields import FieldInfo

from patchy.errors import ConfigError

DEFAULT_CONFIG_PATH: Path = Path("config.toml")

type LogLevel = Literal[
    "TRACE", "DEBUG", "INFO", "SUCCESS", "WARNING", "ERROR", "CRITICAL"
]


class LogSettings(BaseModel):
    """Console logging and log forwarding to Discord."""

    model_config: ClassVar[ConfigDict] = ConfigDict(extra="forbid")

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

    model_config: ClassVar[ConfigDict] = ConfigDict(extra="forbid")

    path: Path = Path("patchy.db")


class HttpSettings(BaseModel):
    """Behaviour of requests made to upstream services."""

    model_config: ClassVar[ConfigDict] = ConfigDict(extra="forbid")

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


class Settings(BaseSettings):
    """The complete Patchy configuration."""

    model_config: ClassVar[SettingsConfigDict] = SettingsConfigDict(
        env_prefix="PATCHY_",
        env_nested_delimiter="_",
        env_nested_max_split=1,
        env_file=".env",
        extra="forbid",
    )

    interval: Annotated[int, Field(ge=0)] = 0
    """Minutes between checks. ``0`` checks once and exits."""

    dry_run: bool = False
    """Check titles without saving versions or sending notifications."""

    log: LogSettings = Field(default_factory=LogSettings)
    discord: DiscordSettings = Field(default_factory=DiscordSettings)
    database: DatabaseSettings = Field(default_factory=DatabaseSettings)
    http: HttpSettings = Field(default_factory=HttpSettings)

    platforms: dict[str, dict[str, Any]] = Field(default_factory=dict)
    """Raw settings per platform key, validated by each platform's own model.

    Read from ``config.toml`` only.
    """

    @field_validator("platforms", mode="before")
    @classmethod
    def _lowercase_platforms(cls, value: object) -> object:
        if isinstance(value, dict):
            return {str(key).lower(): item for key, item in value.items()}

        return value

    @classmethod
    @override
    def settings_customise_sources(
        cls,
        settings_cls: type[BaseSettings],
        init_settings: PydanticBaseSettingsSource,
        env_settings: PydanticBaseSettingsSource,
        dotenv_settings: PydanticBaseSettingsSource,
        file_secret_settings: PydanticBaseSettingsSource,
    ) -> tuple[PydanticBaseSettingsSource, ...]:
        """Rank environment variables above values passed in from ``config.toml``.

        ``load()`` passes the TOML document as initialization arguments, so those are
        placed beneath the environment rather than above it. Environment sources
        cannot set platforms, and ignore variables for options that do not exist.
        """
        return (
            _KnownEnvironment(env_settings, toml_only={"platforms"}),
            _KnownEnvironment(dotenv_settings, toml_only={"platforms"}),
            init_settings,
            file_secret_settings,
        )

    @classmethod
    def load(cls, path: Path = DEFAULT_CONFIG_PATH) -> Self:
        """Load settings, reading TOML from ``path`` when it exists.

        Args:
            path: Location of the TOML configuration file.

        Returns:
            The validated settings.

        Raises:
            ConfigError: The TOML file or a value in it is invalid.
        """
        document: dict[str, Any] = {}

        if path.is_file():
            try:
                document = tomllib.loads(path.read_text(encoding="utf-8"))
            except (OSError, UnicodeDecodeError, tomllib.TOMLDecodeError) as e:
                msg: str = f"Failed to read {path}: {e}"

                raise ConfigError(msg) from e

        try:
            return cls(**document)
        except ValidationError as e:
            raise ConfigError(_describe(e)) from e


class _KnownEnvironment(PydanticBaseSettingsSource):
    """Wrap an environment source so it only supplies known, non-TOML-only settings.

    ``PATCHY_*`` variables for removed or unknown options, and for TOML-only fields,
    are ignored rather than rejected, so stale variables never stop Patchy.
    """

    def __init__(
        self: Self, source: PydanticBaseSettingsSource, *, toml_only: set[str]
    ) -> None:
        super().__init__(source.settings_cls)

        self._source: PydanticBaseSettingsSource = source
        self._toml_only: set[str] = toml_only

    @override
    def get_field_value(
        self: Self, field: FieldInfo, field_name: str
    ) -> tuple[Any, str, bool]:
        return self._source.get_field_value(field, field_name)

    @override
    def __call__(self: Self) -> dict[str, Any]:
        values: dict[str, Any] = {
            key: value
            for key, value in self._source().items()
            if key not in self._toml_only
        }

        return _known(values, self.settings_cls)


def _known(values: dict[str, Any], model: type[BaseModel]) -> dict[str, Any]:
    """Drop keys that ``model`` (or a nested model) does not define."""
    known: dict[str, Any] = {}

    for key, value in values.items():
        if (field := model.model_fields.get(key)) is None:
            continue

        annotation: object = field.annotation

        if (
            isinstance(value, dict)
            and isinstance(annotation, type)
            and issubclass(annotation, BaseModel)
        ):
            known[key] = _known(value, annotation)
        else:
            known[key] = value

    return known


def _describe(error: ValidationError) -> str:
    """Summarize a validation error as one line per invalid setting."""
    lines: list[str] = [
        f"{'.'.join(str(part) for part in item['loc']) or '(root)'}: {item['msg']}"
        for item in error.errors()
    ]

    return "Invalid configuration:\n  " + "\n  ".join(lines)
