from collections.abc import Callable
from datetime import UTC, datetime
from typing import Any

import pytest

from patchy.errors import ConfigError, PayloadError, TitleNotFoundError
from patchy.platforms import Platform, registry
from patchy.platforms.battlenet import API_URL as BLIZZTRACK
from patchy.platforms.steam import API_URL as STEAMCMD
lazy from tests.conftest import FakeClient

type MakePlatform = Callable[..., Platform[Any]]


def test_registry_discovers_every_platform() -> None:
    assert set(registry()) == {"steam", "battlenet", "prospero", "orbis"}


class TestSteam:
    def test_fetch_public_branch(
        self, client: FakeClient, make_platform: MakePlatform
    ) -> None:
        client.serve(f"{STEAMCMD}/730", "steam_730.json")

        release = make_platform("steam", titles=["730"]).fetch("730")

        assert release.name == "Counter-Strike 2"
        assert release.version == "20480931"
        assert release.released_at == datetime.fromtimestamp(1760650000, UTC)
        assert release.icon_url is not None
        assert release.icon_url.endswith(
            "/730/8dbc71957312bbd3baea65848b545be9eae2a355.jpg"
        )
        assert release.details == {}

    def test_fetch_other_branch_accepts_numeric_build_id(
        self, client: FakeClient, make_platform: MakePlatform
    ) -> None:
        client.serve(f"{STEAMCMD}/730", "steam_730.json")

        release = make_platform("steam", titles=["730"], branch="beta").fetch("730")

        assert release.version == "20491111"
        assert release.details == {"Branch": "beta"}

    def test_missing_branch_is_a_payload_error(
        self, client: FakeClient, make_platform: MakePlatform
    ) -> None:
        client.serve(f"{STEAMCMD}/730", "steam_730.json")

        with pytest.raises(PayloadError, match="no 'nope' branch"):
            make_platform("steam", titles=["730"], branch="nope").fetch("730")

    def test_missing_token_is_a_payload_error(
        self, client: FakeClient, make_platform: MakePlatform
    ) -> None:
        client.serve(f"{STEAMCMD}/1234", "steam_missing_token.json")

        with pytest.raises(PayloadError, match="no details"):
            make_platform("steam", titles=["1234"]).fetch("1234")

    def test_unknown_app_is_not_found(
        self, client: FakeClient, make_platform: MakePlatform
    ) -> None:
        client.serve(f"{STEAMCMD}/999", "steam_730.json")

        with pytest.raises(TitleNotFoundError):
            make_platform("steam", titles=["999"]).fetch("999")

    def test_rejects_non_numeric_ids(self, make_platform: MakePlatform) -> None:
        with pytest.raises(ConfigError, match="must be numeric"):
            make_platform("steam").normalize_title_id("csgo")


class TestBattlenet:
    def serve(self, client: FakeClient) -> None:
        client.serve(f"{BLIZZTRACK}/manifest/wow/versions", "battlenet_versions.json")
        client.serve(f"{BLIZZTRACK}/fragments/wow", "battlenet_fragments.json")
        client.serve(f"{BLIZZTRACK}/manifest/wow/cdns", "battlenet_cdns.json")
        client.serve(
            "http://us.cdn.blizzard.com/tpr/wow/config/c3/b2/c3b2f9e8d7a6b5c4d3e2f1a0b9c8d7e6",
            "battlenet_build_config.txt",
        )

    def test_fetch_prefers_configured_region(
        self, client: FakeClient, make_platform: MakePlatform
    ) -> None:
        self.serve(client)

        release = make_platform("battlenet", titles=["wow"]).fetch("wow")

        assert release.version == "11.2.5.63904"
        assert release.region == "Americas"
        assert release.details == {}
        assert len(client.requests) == 1

    def test_fetch_falls_back_to_first_region(
        self, client: FakeClient, make_platform: MakePlatform
    ) -> None:
        self.serve(client)

        release = make_platform("battlenet", region="Antarctica").fetch("wow")

        assert release.region == "Europe"

    def test_enrich_adds_artwork_and_build_name(
        self, client: FakeClient, make_platform: MakePlatform
    ) -> None:
        self.serve(client)
        platform = make_platform("battlenet", titles=["wow"])

        release = platform.enrich(platform.fetch("wow"))

        assert (
            release.icon_url
            == "https://wsrv.nl/?url=https://blizzard.blizzmeta.com/1111aaaa"
        )
        assert (
            release.image_url
            == "https://wsrv.nl/?url=https://blizzard.blizzmeta.com/2222bbbb"
        )
        assert release.details == {"Build Name": "WOW-63904patch11.2.5_Retail"}

    def test_enrich_survives_upstream_failures(
        self, client: FakeClient, make_platform: MakePlatform
    ) -> None:
        client.serve(f"{BLIZZTRACK}/manifest/wow/versions", "battlenet_versions.json")
        platform = make_platform("battlenet", titles=["wow"])
        release = platform.fetch("wow")

        enriched = platform.enrich(release)

        assert enriched.version == release.version
        assert enriched.icon_url is None
        assert enriched.details == {}


class TestPlayStation:
    def test_fetch(self, client: FakeClient, make_platform: MakePlatform) -> None:
        client.serve(
            "https://prosperopatches.com/api/lookup?titleid=PPSA01284",
            "prospero_PPSA01284.json",
        )

        release = make_platform("prospero").fetch("PPSA01284")

        assert release.name == "Returnal"
        assert release.version == "01.004.002"
        assert release.region == "EU"
        assert release.url == "https://prosperopatches.com/PPSA01284"
        assert release.image_url is None, "blank strings are treated as missing"

    def test_not_found(self, client: FakeClient, make_platform: MakePlatform) -> None:
        client.serve(
            "https://orbispatches.com/api/lookup?titleid=CUSA00000",
            "playstation_not_found.json",
        )

        with pytest.raises(TitleNotFoundError):
            make_platform("orbis").fetch("CUSA00000")

    def test_normalizes_ids(self, make_platform: MakePlatform) -> None:
        assert (
            make_platform("orbis").normalize_title_id(" cusa00419 ")
            == "CUSA00419"
        )

        with pytest.raises(ConfigError):
            make_platform("orbis").normalize_title_id("12345")


def test_invalid_platform_settings_raise_config_error(
    make_platform: MakePlatform,
) -> None:
    with pytest.raises(ConfigError, match="Invalid settings for platform steam"):
        make_platform("steam", titles=["730"], bogus=True)


def test_titles_accept_comma_separated_strings(make_platform: MakePlatform) -> None:
    assert make_platform("steam", titles="730, 440,730").titles == ["730", "440"]


def test_titles_are_normalized_and_deduplicated(make_platform: MakePlatform) -> None:
    platform = make_platform("prospero", titles=["ppsa01284", "PPSA01284", "bad"])

    assert platform.titles == ["PPSA01284"]
