"""Battle.net titles, via the BlizzTrack API (https://blizztrack.com)."""

from dataclasses import replace
from typing import ClassVar, Self, override
lazy from datetime import datetime

from loguru import logger
from pydantic import BaseModel, Field, ValidationError

from patchy.config import PlatformSettings
from patchy.errors import PatchyError, PayloadError, TitleNotFoundError
from patchy.platforms import register
from patchy.platforms.base import OptionalText, Platform, Release, UpstreamModel

API_URL: str = "https://blizztrack.com/api"

ASSET_URL: str = "https://blizzard.blizzmeta.com"

# BlizzTrack names artwork fragments after games rather than product codes, and one
# fragment can describe several products (World of Warcraft also holds Classic).
# Each entry maps a product code prefix to its fragment and the product ID in it;
# codes without an entry are looked up as a fragment of the same name.
FRAGMENTS: tuple[tuple[str, str, str | None], ...] = (
    ("wow_classic", "world_of_warcraft", "WoWC"),
    ("wow", "world_of_warcraft", "WoW"),
    ("pro", "overwatch", "Pro"),
    ("d3", "diablo_iii", None),
    ("hs", "hearthstone", None),
    ("s2", "starcraft_ii", None),
    ("hero", "heroes", None),
)


class BattlenetSettings(PlatformSettings):
    """Settings for the Battle.net platform."""

    region: str = "Americas"
    """Region whose version is tracked. Falls back to the first region listed."""


class _Version(UpstreamModel):
    name: str
    version_name: str
    build_config: str


class _Versions(UpstreamModel):
    tact: str
    name: str
    created_at: datetime | None = None
    data: list[_Version] = Field(min_length=1)


class _VersionsResponse(UpstreamModel):
    success: bool
    result: _Versions | None = None


class _ProductBase(UpstreamModel):
    icon_medium: OptionalText = None
    icon_small: OptionalText = None
    logo: OptionalText = None
    key_art: OptionalText = None


class _Product(UpstreamModel):
    id: str
    base: _ProductBase


class _File(UpstreamModel):
    hash: str


class _Files(UpstreamModel):
    default: dict[str, _File] = Field(default_factory=dict)


class _Fragments(UpstreamModel):
    products: list[_Product] = Field(default_factory=list)
    files: _Files = Field(default_factory=_Files)


class _FragmentsResponse(UpstreamModel):
    success: bool
    result: _Fragments | None = None


class _State(BaseModel):
    """What Patchy remembers about a product between checks."""

    build_config: str
    """Hash of the tracked region's build config, which names the build."""


class _Cdn(UpstreamModel):
    name: str
    path: str
    hosts: str


class _Cdns(UpstreamModel):
    data: list[_Cdn] = Field(default_factory=list)


class _CdnsResponse(UpstreamModel):
    success: bool
    result: _Cdns | None = None


@register
class Battlenet(Platform[BattlenetSettings]):
    """Track the version name of a Battle.net product in one region."""

    key: ClassVar[str] = "battlenet"
    name: ClassVar[str] = "Battle.net"
    source: ClassVar[str] = "BlizzTrack"
    color: ClassVar[int] = 0x148EFF
    icon_url: ClassVar[str | None] = "https://i.imgur.com/dI6bDr7.png"
    settings_model: ClassVar[type[PlatformSettings]] = BattlenetSettings

    @override
    def normalize_title_id(self: Self, title_id: str) -> str:
        return title_id.strip().lower()

    @override
    def display_title_id(self: Self, title_id: str) -> str:
        return title_id.upper()

    @override
    def fetch(self: Self, title_id: str) -> Release:
        res: _VersionsResponse = self.client.get_model(
            f"{API_URL}/manifest/{title_id}/versions", _VersionsResponse
        )

        if not res.success or res.result is None:
            msg: str = f"BlizzTrack has no data for product {title_id}"

            raise TitleNotFoundError(msg)

        wanted: str = self.settings.region.lower()
        version: _Version = next(
            (entry for entry in res.result.data if entry.name.lower() == wanted),
            res.result.data[0],
        )

        return Release(
            title_id=title_id,
            name=res.result.name,
            version=version.version_name,
            url=f"https://blizztrack.com/view/{res.result.tact}?type=versions",
            region=version.name,
            released_at=res.result.created_at,
            state=_State(build_config=version.build_config).model_dump_json(),
        )

    @override
    def enrich(self: Self, release: Release, previous_state: str | None) -> Release:
        icon_url: str | None = None
        image_url: str | None = None
        build: str | None = None
        previous_build: str | None = None

        try:
            icon_url, image_url = self._artwork(release.title_id)
        except PatchyError as e:
            logger.opt(exception=e).warning(
                f"Failed to fetch artwork for Battle.net title {release.name}"
            )

        current: _State | None = _read_state(release.state)
        previous: _State | None = _read_state(previous_state)

        if current is not None and release.region is not None:
            try:
                build, previous_build = self._build_names(
                    release.title_id,
                    release.region,
                    current.build_config,
                    previous.build_config if previous is not None else None,
                )
            except PatchyError as e:
                logger.opt(exception=e).warning(
                    f"Failed to fetch build names for Battle.net title {release.name}"
                )

        return replace(
            release,
            icon_url=icon_url,
            image_url=image_url,
            build=build,
            previous_build=previous_build,
        )

    def _artwork(self: Self, title_id: str) -> tuple[str | None, str | None]:
        """Return the icon and key art URLs for a product."""
        fragment, product_id = fragment_for(title_id)
        res: _FragmentsResponse = self.client.get_model(
            f"{API_URL}/fragments/{fragment}", _FragmentsResponse
        )

        if not res.success or res.result is None or not res.result.products:
            msg: str = f"BlizzTrack has no artwork for product {title_id}"

            raise PayloadError(msg)

        wanted: str = (product_id or title_id).lower()
        base: _ProductBase = next(
            (p.base for p in res.result.products if p.id.lower() == wanted),
            res.result.products[0].base,
        )
        files: dict[str, _File] = res.result.files.default

        def resolve(*keys: str | None) -> str | None:
            for key in keys:
                if key is not None and (file := files.get(key)) is not None:
                    return f"{ASSET_URL}/{file.hash}"

            return None

        return (
            resolve(base.icon_medium, base.icon_small, base.logo),
            resolve(base.key_art),
        )

    def _build_names(
        self: Self,
        title_id: str,
        region: str,
        build_config: str,
        previous_build_config: str | None,
    ) -> tuple[str, str | None]:
        """Name the current build and, when its config is known, the previous one.

        The previous build is best effort: its config may have left the CDN.
        """
        res: _CdnsResponse = self.client.get_model(
            f"{API_URL}/manifest/{title_id}/cdns", _CdnsResponse
        )

        if not res.success or res.result is None:
            msg: str = f"BlizzTrack has no CDN data for product {title_id}"

            raise PayloadError(msg)

        cdn: _Cdn | None = next(
            (e for e in res.result.data if e.name.lower() == region.lower()), None
        )

        if cdn is None or not (hosts := cdn.hosts.split()):
            msg = f"BlizzTrack lists no CDN for product {title_id} in {region}"

            raise PayloadError(msg)

        base_url: str = f"http://{hosts[0]}/{cdn.path}"
        previous: str | None = None

        if previous_build_config is not None:
            try:
                previous = self._build_name(base_url, title_id, previous_build_config)
            except PatchyError as e:
                logger.opt(exception=e).debug(
                    f"Failed to name the previous build of Battle.net title {title_id}"
                )

        return self._build_name(base_url, title_id, build_config), previous

    def _build_name(self: Self, base_url: str, title_id: str, build_config: str) -> str:
        """Read the human-readable build name from a build config on a CDN."""
        # Mirrors how the BlizzTrack front-end locates a build config.
        # https://github.com/BlizzTrack/BlizzTrack/blob/d10e550bd1588338c39f10f48c744679aef3b62c/BlizzTrack/Pages/Partials/_view_versions.cshtml#L89
        path: str = f"config/{build_config[:2]}/{build_config[2:4]}/{build_config}"
        config: str = self.client.get_text(f"{base_url}/{path}")

        for line in config.splitlines():
            key, _, value = line.partition(" = ")

            if key.strip() == "build-name" and value.strip():
                return value.strip()

        msg: str = f"Build config for product {title_id} has no build name"

        raise PayloadError(msg)


def fragment_for(product: str) -> tuple[str, str | None]:
    """Name the BlizzTrack fragment and product ID holding a product's artwork.

    Args:
        product: The Battle.net product code, such as ``wow`` or ``wow_classic``.

    Returns:
        The fragment name and, when known, the product's ID within it.
    """
    for prefix, fragment, product_id in FRAGMENTS:
        if product.startswith(prefix):
            return fragment, product_id

    return product, None


def _read_state(state: str | None) -> _State | None:
    """Parse stored state, treating anything unreadable as missing."""
    if state is None:
        return None

    try:
        return _State.model_validate_json(state)
    except ValidationError:
        return None
