"""Steam titles, via the SteamCMD API (https://www.steamcmd.net)."""

from datetime import UTC, datetime
from typing import ClassVar, Self, override

from pydantic import Field

from patchy.config import PlatformSettings
from patchy.errors import ConfigError, PayloadError, TitleNotFoundError
from patchy.platforms import register
from patchy.platforms.base import OptionalText, Platform, Release, UpstreamModel

API_URL: str = "https://api.steamcmd.net/v1/info"
CDN_URL: str = "https://cdn.cloudflare.steamstatic.com"


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


class _Depots(UpstreamModel):
    branches: dict[str, _Branch] = Field(default_factory=dict)


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
        ).with_details(Branch=branch_name if branch_name != "public" else None)
