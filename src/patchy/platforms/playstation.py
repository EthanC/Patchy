"""PlayStation 5 and PlayStation 4 titles, via ProsperoPatches and OrbisPatches."""

import re
from typing import ClassVar, Self, override

from pydantic import Field

from patchy.config import PlatformSettings
from patchy.errors import ConfigError, TitleNotFoundError
from patchy.platforms import register
from patchy.platforms.base import OptionalText, Platform, Release, UpstreamModel

TITLE_ID_PATTERN: re.Pattern[str] = re.compile(r"^[A-Z]{4}\d{5}$")


class _Metadata(UpstreamModel):
    name: str
    current_version: str = Field(alias="currentVersion")
    region: OptionalText = None
    icon: OptionalText = None
    background: OptionalText = None


class _Response(UpstreamModel):
    success: bool
    metadata: _Metadata | None = None


class PlayStation(Platform[PlatformSettings]):
    """Shared behaviour for the PlayStation patch trackers, which share one API."""

    site_url: ClassVar[str]
    """Base URL of the patch tracker for this console generation."""

    @override
    def normalize_title_id(self: Self, title_id: str) -> str:
        title_id = title_id.strip().upper()

        if not TITLE_ID_PATTERN.match(title_id):
            msg: str = (
                f"{self.name} title ID {title_id!r} must look like four letters "
                "followed by five digits, such as PPSA01284 or CUSA00419"
            )

            raise ConfigError(msg)

        return title_id

    @override
    def fetch(self: Self, title_id: str) -> Release:
        res: _Response = self.client.get_model(
            f"{self.site_url}/api/lookup?titleid={title_id}", _Response
        )

        if not res.success or res.metadata is None:
            msg: str = f"{self.site_url} has no data for title {title_id}"

            raise TitleNotFoundError(msg)

        return Release(
            title_id=title_id,
            name=res.metadata.name,
            version=res.metadata.current_version,
            url=f"{self.site_url}/{title_id}",
            icon_url=res.metadata.icon,
            image_url=res.metadata.background,
            region=res.metadata.region,
        )


@register
class Prospero(PlayStation):
    """PlayStation 5 titles, via ProsperoPatches."""

    key: ClassVar[str] = "prospero"
    name: ClassVar[str] = "PlayStation 5"
    source: ClassVar[str] = "PROSPEROPatches"
    color: ClassVar[int] = 0x00439C
    icon_url: ClassVar[str | None] = "https://i.imgur.com/ccNqLcb.png"
    site_url: ClassVar[str] = "https://prosperopatches.com"


@register
class Orbis(PlayStation):
    """PlayStation 4 titles, via OrbisPatches."""

    key: ClassVar[str] = "orbis"
    name: ClassVar[str] = "PlayStation 4"
    source: ClassVar[str] = "ORBISPatches"
    color: ClassVar[int] = 0x00439C
    icon_url: ClassVar[str | None] = "https://i.imgur.com/ccNqLcb.png"
    site_url: ClassVar[str] = "https://orbispatches.com"
