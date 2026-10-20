"""The interface every platform implements."""

from abc import ABC, abstractmethod
from dataclasses import dataclass, field, replace
from typing import Annotated, Any, ClassVar, Self, cast
lazy from collections.abc import Mapping
lazy from datetime import datetime

from loguru import logger
from pydantic import BaseModel, BeforeValidator, ConfigDict, ValidationError

from patchy.config import PlatformSettings
from patchy.errors import ConfigError
lazy from patchy.client import HttpClient


def _blank_to_none(value: object) -> object:
    """Treat empty or whitespace-only strings from upstream services as missing."""
    if isinstance(value, str) and not value.strip():
        return None

    return value


type Detail = str | tuple[str, ...]
"""A notification detail: a single value, shown as code, or a list of entries."""

type OptionalText = Annotated[str | None, BeforeValidator(_blank_to_none)]
"""An optional string field in an upstream response where ``""`` means missing."""


class UpstreamModel(BaseModel):
    """Base for models describing upstream API responses.

    Unknown fields are ignored so upstream additions never break Patchy, and numbers
    are accepted where strings are expected because APIs are inconsistent about IDs.
    """

    model_config: ClassVar[ConfigDict] = ConfigDict(
        extra="ignore", coerce_numbers_to_str=True, frozen=True
    )


@dataclass(frozen=True, slots=True, kw_only=True)
class Release:
    """A snapshot of a title's current version on a platform."""

    title_id: str
    """Identifier of the title on its platform, as configured by the user."""

    name: str
    """Human-readable title name."""

    version: str
    """Current version string. Any change to this value is reported as an update."""

    build: str | None = None
    """Human-readable build shown after the version, such as a Battle.net build
    name. Usually filled in by ``enrich()``."""

    previous_build: str | None = None
    """The previous version's build, shown after it. Filled in by ``enrich()``,
    typically from ``previous_state``."""

    url: str | None = None
    """Page to open for more information, such as patch notes."""

    icon_url: str | None = None
    """Small square artwork."""

    image_url: str | None = None
    """Large banner or key artwork."""

    region: str | None = None
    """Region the version applies to, when the platform distinguishes regions."""

    released_at: datetime | None = None
    """When the platform published this version, if known."""

    details: Mapping[str, Detail] = field(default_factory=dict)
    """Additional labelled values to show in notifications, such as a build name or
    a list of changed depots."""

    state: str | None = field(default=None, repr=False)
    """Platform-private data stored with the version, such as Steam depot manifests.

    Saved on every check and handed back to ``enrich()`` as ``previous_state`` when
    the version changes, so a platform can describe what changed between versions.
    The format is up to the platform; serialize it with a Pydantic model.
    """

    def with_details(self: Self, **details: Detail | None) -> Self:
        """Return a copy with extra details added, skipping ``None`` values."""
        merged: dict[str, Detail] = dict(self.details)
        merged.update({k: v for k, v in details.items() if v is not None})

        return replace(self, details=merged)


@dataclass(frozen=True, slots=True, kw_only=True)
class Update:
    """A version change detected for a title."""

    platform: Platform[Any]
    release: Release
    previous_version: str


class Platform[S: PlatformSettings](ABC):
    """A source of title versions, such as Steam or Battle.net.

    To add a platform, subclass this in a new module under ``patchy.platforms``,
    fill in the class variables, implement ``fetch()``, and decorate the class with
    ``@register``. See AGENTS.md for a walkthrough.
    """

    key: ClassVar[str]
    """Unique, lowercase identifier used in configuration and the database."""

    name: ClassVar[str]
    """Display name."""

    source: ClassVar[str]
    """Name of the site ``Release.url`` links to, shown as "View on <source>"."""

    color: ClassVar[int]
    """Accent color for notifications, as a 24-bit RGB integer."""

    icon_url: ClassVar[str | None] = None
    """Platform logo shown alongside notifications."""

    proxy_media: ClassVar[bool] = False
    """Serve artwork through the wsrv.nl image proxy, for hosts whose images Discord
    may not render directly, such as ones sent without a content type."""

    title_id_as_code: ClassVar[bool] = True
    """Show title IDs as inline code in notifications, as they are usually codes."""

    settings_model: ClassVar[type[PlatformSettings]] = PlatformSettings
    """Model used to validate each ``[[platforms.<key>]]`` instance table."""

    def __init__(self: Self, settings: S, client: HttpClient) -> None:
        """Create a platform instance.

        Args:
            settings: This instance's validated settings.
            client: HTTP client to use for all upstream requests.
        """
        self.settings: S = settings
        self.client: HttpClient = client
        self.titles: list[str] = []
        """Normalized title identifiers. Invalid ones are logged and skipped."""

        for title_id in settings.titles:
            try:
                normalized: str = self.normalize_title_id(title_id)
            except ConfigError as e:
                logger.error(f"Skipping {self.label} title {title_id!r}: {e}")

                continue

            if normalized not in self.titles:
                self.titles.append(normalized)

    @property
    def instance(self: Self) -> str:
        """Name of this instance, unique within its platform."""
        return self.settings.name if self.settings.name is not None else self.key

    @property
    def label(self: Self) -> str:
        """How this instance is referred to in logs."""
        if self.instance == self.key:
            return self.name

        return f"{self.name} ({self.instance})"

    @classmethod
    def from_config(
        cls, raw: Mapping[str, Any], client: HttpClient, *, location: str | None = None
    ) -> Self:
        """Validate raw configuration and create a platform instance.

        Args:
            raw: One instance table from the configuration, before validation.
            client: HTTP client to use for all upstream requests.
            location: Where the table is in ``config.toml``, for error messages.

        Returns:
            The platform instance.

        Raises:
            ConfigError: The configuration is invalid for this platform.
        """
        try:
            settings: PlatformSettings = cls.settings_model.model_validate(raw)
        except ValidationError as e:
            problems: str = "; ".join(
                f"{'.'.join(str(p) for p in err['loc'])}: {err['msg']}"
                for err in e.errors()
            )
            msg: str = f"Invalid settings in {location or cls.key}: {problems}"

            raise ConfigError(msg) from e

        return cls(cast("S", settings), client)

    def normalize_title_id(self: Self, title_id: str) -> str:
        """Return the canonical form of a configured title identifier.

        Override this to reject identifiers that cannot be valid for the platform.
        Called once per configured title when the platform is created.

        Args:
            title_id: The identifier as configured.

        Returns:
            The identifier to request and store.

        Raises:
            ConfigError: The identifier is not valid for this platform.
        """
        return title_id.strip()

    def display_title_id(self: Self, title_id: str) -> str:
        """Return a title identifier as notifications should show it.

        Args:
            title_id: The normalized title identifier.

        Returns:
            The identifier to display.
        """
        return title_id

    @abstractmethod
    def fetch(self: Self, title_id: str) -> Release:
        """Return the current release of a title.

        Keep this to the requests needed to determine the version; anything only
        needed for notifications belongs in ``enrich()``.

        Args:
            title_id: The normalized title identifier.

        Returns:
            The title's current release.

        Raises:
            PatchyError: The release could not be determined.
        """

    def enrich(
        self: Self,
        release: Release,
        previous_state: str | None,  # noqa: ARG002 - for overrides.
    ) -> Release:
        """Add notification-only information to a release that has changed.

        Called only when an update is detected, so it may make extra requests.
        Failures here should be logged and swallowed: the update is still reported.

        Args:
            release: The release returned by ``fetch()``.
            previous_state: The ``state`` stored with the previous version, if any.

        Returns:
            The release with any extra information added.
        """
        return release
