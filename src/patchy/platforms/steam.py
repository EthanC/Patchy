"""Steam titles, via the SteamCMD API (https://www.steamcmd.net)."""

from datetime import UTC, datetime
from typing import ClassVar, Self, override

from loguru import logger
from pydantic import BaseModel, Field, ValidationError, model_validator

from patchy.config import PlatformSettings
from patchy.errors import ConfigError, PayloadError, TitleNotFoundError
from patchy.platforms import register
from patchy.platforms.base import OptionalText, Platform, Release, UpstreamModel

API_URL: str = "https://api.steamcmd.net/v1/info"
CDN_URL: str = "https://cdn.cloudflare.steamstatic.com"

MAX_LISTED_DEPOTS: int = 8
"""Changed depots named in a notification before the rest are summarized."""

OS_NAMES: dict[str, str] = {"windows": "Windows", "macos": "macOS", "linux": "Linux"}


class SteamSettings(PlatformSettings):
    """Settings for the Steam platform."""

    branch: str = "public"
    """Depot branch whose build ID is tracked, such as ``public`` or a beta name."""


class _Common(UpstreamModel):
    name: str
    icon: OptionalText = None


class _Branch(UpstreamModel):
    buildid: str
    timeupdated: int | None = None


class _Manifest(UpstreamModel):
    gid: OptionalText = None
    size: int | None = None

    @model_validator(mode="before")
    @classmethod
    def _accept_bare_gid(cls, value: object) -> object:
        """Older app info lists a branch's manifest as just its ID."""
        return {"gid": value} if isinstance(value, str | int) else value


class _DepotConfig(UpstreamModel):
    oslist: OptionalText = None
    language: OptionalText = None


class _Depot(UpstreamModel):
    name: OptionalText = None
    config: _DepotConfig | None = None
    manifests: dict[str, _Manifest] = Field(default_factory=dict)

    @property
    def label(self: Self) -> str | None:
        """Describe the depot by its name, or else its platforms and language."""
        if self.name is not None:
            return self.name

        if self.config is None or self.config.oslist is None:
            return None

        label: str = "/".join(
            OS_NAMES.get(os, os) for os in self.config.oslist.split(",") if os
        )

        if self.config.language is not None:
            label += f" ({self.config.language.title()})"

        return label


class _Depots(UpstreamModel):
    branches: dict[str, _Branch] = Field(default_factory=dict)
    depots: dict[str, _Depot] = Field(default_factory=dict)
    """Depots keyed by ID. Upstream mixes these in with the other keys."""

    @model_validator(mode="before")
    @classmethod
    def _collect_depots(cls, value: object) -> object:
        if not isinstance(value, dict):
            return value

        return {
            **value,
            "depots": {
                key: depot
                for key, depot in value.items()
                if str(key).isdigit() and isinstance(depot, dict)
            },
        }


class _DepotSnapshot(BaseModel):
    """A depot's manifest on the tracked branch, stored between checks."""

    name: str
    gid: str
    size: int | None = None


class _State(BaseModel):
    """What Patchy remembers about a Steam app between checks."""

    depots: dict[str, _DepotSnapshot] = Field(default_factory=dict)


class _App(UpstreamModel):
    common: _Common | None = None
    depots: _Depots | None = None


class _Response(UpstreamModel):
    status: str
    data: dict[str, _App] = Field(default_factory=dict)


@register
class Steam(Platform[SteamSettings]):
    """Track the build ID of a Steam app's depot branch."""

    key: ClassVar[str] = "steam"
    name: ClassVar[str] = "Steam"
    color: ClassVar[int] = 0x1B2838
    icon_url: ClassVar[str | None] = "https://i.imgur.com/oYkhH6s.png"
    settings_model: ClassVar[type[PlatformSettings]] = SteamSettings

    @override
    def normalize_title_id(self: Self, title_id: str) -> str:
        title_id = title_id.strip()

        if not title_id.isdigit():
            msg: str = f"Steam app ID {title_id!r} must be numeric"

            raise ConfigError(msg)

        return title_id

    @override
    def fetch(self: Self, title_id: str) -> Release:
        res: _Response = self.client.get_model(f"{API_URL}/{title_id}", _Response)

        if res.status != "success" or (app := res.data.get(title_id)) is None:
            msg: str = f"SteamCMD has no data for app {title_id} ({res.status})"

            raise TitleNotFoundError(msg)

        if app.common is None:
            # Apps without a public access token omit their common section.
            msg = f"SteamCMD returned no details for app {title_id}"

            raise PayloadError(msg)

        branch_name: str = self.settings.branch

        if (
            app.depots is None
            or (branch := app.depots.branches.get(branch_name)) is None
        ):
            msg = f"Steam app {app.common.name} has no {branch_name!r} branch"

            raise PayloadError(msg)

        state: _State = _State(
            depots={
                depot_id: _DepotSnapshot(
                    name=depot.label or f"Depot {depot_id}",
                    gid=manifest.gid,
                    size=manifest.size,
                )
                for depot_id, depot in app.depots.depots.items()
                if (manifest := depot.manifests.get(branch_name)) is not None
                and manifest.gid is not None
            }
        )

        return Release(
            title_id=title_id,
            name=app.common.name,
            version=branch.buildid,
            url=f"https://steamdb.info/app/{title_id}/patchnotes/",
            icon_url=(
                f"{CDN_URL}/steamcommunity/public/images/apps/{title_id}/{app.common.icon}.jpg"
                if app.common.icon is not None
                else None
            ),
            image_url=f"{CDN_URL}/steam/apps/{title_id}/header.jpg",
            released_at=(
                datetime.fromtimestamp(branch.timeupdated, UTC)
                if branch.timeupdated is not None
                else None
            ),
            state=state.model_dump_json(exclude_defaults=True),
        ).with_details(Branch=branch_name if branch_name != "public" else None)

    @override
    def enrich(self: Self, release: Release, previous_state: str | None) -> Release:
        if previous_state is None or release.state is None:
            return release

        try:
            previous: _State = _State.model_validate_json(previous_state)
            current: _State = _State.model_validate_json(release.state)
        except ValidationError as e:
            logger.opt(exception=e).warning(
                f"Ignoring unreadable depot state for Steam app {release.name}"
            )

            return release

        return release.with_details(Depots=describe_depots(previous, current))


def describe_depots(previous: _State, current: _State) -> str | None:
    """Summarize which depots were added, removed, or changed between two states.

    Args:
        previous: The depots stored with the previous version.
        current: The depots of the new version.

    Returns:
        One line such as ``Windows +120.4 MB, Linux added``, or ``None`` when no
        depot changed.
    """
    changes: list[str] = []

    for depot_id, depot in current.depots.items():
        if (old := previous.depots.get(depot_id)) is None:
            changes.append(f"{depot.name} added")
        elif old.gid != depot.gid:
            changes.append(
                f"{depot.name} {format_size(depot.size - old.size, signed=True)}"
                if depot.size is not None and old.size is not None
                else depot.name
            )

    changes.extend(
        f"{depot.name} removed"
        for depot_id, depot in previous.depots.items()
        if depot_id not in current.depots
    )

    if not changes:
        return None

    if len(changes) > MAX_LISTED_DEPOTS:
        hidden: int = len(changes) - MAX_LISTED_DEPOTS
        changes = [*changes[:MAX_LISTED_DEPOTS], f"{hidden} more"]

    return ", ".join(changes)


def format_size(size: int, *, signed: bool = False) -> str:
    """Format a byte count the way Steam does, in binary units.

    Args:
        size: Number of bytes, negative for a decrease.
        signed: Prefix positive sizes with ``+``.

    Returns:
        A size such as ``120.4 MB``, ``+1.2 GB``, or ``-512 B``.
    """
    sign: str = "-" if size < 0 else "+" if signed else ""
    value: float = abs(size)

    for unit in ("B", "KB", "MB", "GB"):
        if value < 1024:  # noqa: PLR2004
            return (
                f"{sign}{value:.0f} {unit}"
                if unit == "B"
                else f"{sign}{value:.1f} {unit}"
            )

        value /= 1024

    return f"{sign}{value:.1f} TB"
