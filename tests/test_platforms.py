import json
from collections.abc import Callable
from datetime import UTC, datetime
from typing import Any

import pytest

from patchy.errors import ConfigError, PayloadError, TitleNotFoundError
from patchy.platforms import Platform, Release, registry
from patchy.platforms.battlenet import API_URL as BLIZZTRACK
from patchy.platforms.battlenet import fragment_for
from patchy.platforms.steam import API_URL as STEAMCMD
from patchy.platforms.steam import format_size
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

    def test_fetch_stores_branch_manifests(
        self, client: FakeClient, make_platform: MakePlatform
    ) -> None:
        client.serve(f"{STEAMCMD}/730", "steam_730.json")

        release = make_platform("steam", titles=["730"]).fetch("730")

        assert release.state is not None
        depots = json.loads(release.state)["depots"]
        assert {key: depot["name"] for key, depot in depots.items()} == {
            "2347770": "Windows",
            "2347771": "Linux",
            "2347772": "Counter-Strike 2 Mac Legacy",
            "2347779": "Windows/Linux (French)",
        }, "shared depots and depots without a branch manifest are skipped"
        assert depots["2347772"] == {
            "name": "Counter-Strike 2 Mac Legacy",
            "gid": "5550001112223334445",
        }, "a bare manifest ID is accepted"

    def test_enrich_describes_depot_changes(
        self, client: FakeClient, make_platform: MakePlatform
    ) -> None:
        client.serve(f"{STEAMCMD}/730", "steam_730.json")
        platform = make_platform("steam", titles=["730"])
        previous = {
            "depots": {
                "2347770": {
                    "name": "Windows",
                    "gid": "1",
                    "size": 39045203018 - 126_248_550,
                },
                "2347771": {
                    "name": "Linux",
                    "gid": "8834221556109875226",
                    "size": 1503238553,
                },
                "2347779": {"name": "Windows/Linux (French)", "gid": "2"},
                "2347790": {"name": "Windows (German)", "gid": "3", "size": 1},
            }
        }

        release = platform.enrich(platform.fetch("730"), json.dumps(previous))

        assert release.details == {
            "Depots": (
                "Windows +120.4 MB",
                "Counter-Strike 2 Mac Legacy added",
                "Windows/Linux (French) changed",
                "Windows (German) removed",
            )
        }

    def test_enrich_lists_a_limited_number_of_depots(
        self, client: FakeClient, make_platform: MakePlatform
    ) -> None:
        client.serve(f"{STEAMCMD}/730", "steam_730.json")
        platform = make_platform("steam", titles=["730"])
        previous = {
            "depots": {str(i): {"name": f"Old {i}", "gid": "1"} for i in range(10)}
        }

        release = platform.enrich(platform.fetch("730"), json.dumps(previous))

        assert release.details["Depots"][-2:] == ("Old 3 removed", "6 more")

    @pytest.mark.parametrize("previous_state", [None, "not json", '{"depots": 5}'])
    def test_enrich_without_usable_previous_state(
        self,
        client: FakeClient,
        make_platform: MakePlatform,
        previous_state: str | None,
    ) -> None:
        client.serve(f"{STEAMCMD}/730", "steam_730.json")
        platform = make_platform("steam", titles=["730"])
        release = platform.fetch("730")

        assert platform.enrich(release, previous_state) == release

    def test_enrich_omits_depots_when_none_changed(
        self, client: FakeClient, make_platform: MakePlatform
    ) -> None:
        client.serve(f"{STEAMCMD}/730", "steam_730.json")
        platform = make_platform("steam", titles=["730"])
        release = platform.fetch("730")

        assert platform.enrich(release, release.state).details == {}


@pytest.mark.parametrize(
    ("size", "signed", "expected"),
    [
        (0, False, "0 B"),
        (512, True, "+512 B"),
        (-1536, True, "-1.5 KB"),
        (126_248_550, True, "+120.4 MB"),
        (39_045_203_018, False, "36.4 GB"),
        (3 * 1024**4, False, "3.0 TB"),
    ],
)
def test_format_size(size: int, *, signed: bool, expected: str) -> None:
    assert format_size(size, signed=signed) == expected


class TestBattlenet:
    def serve(self, client: FakeClient) -> None:
        client.serve(f"{BLIZZTRACK}/manifest/wow/versions", "battlenet_versions.json")
        client.serve(
            f"{BLIZZTRACK}/fragments/world_of_warcraft", "battlenet_fragments.json"
        )
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

        release = platform.enrich(platform.fetch("wow"), None)

        assert release.icon_url == (
            "https://blizzard.blizzmeta.com/ff00e970977dfc21edacec3d1863b617"
        ), "the retail product is chosen by ID, not position"
        assert release.image_url == (
            "https://blizzard.blizzmeta.com/e0f924301ba015c64ce7ceb0a3fb8942"
        )
        assert release.build == "WOW-63904patch11.2.5_Retail"
        assert release.previous_build is None, "no previous build config is known"
        assert release.details == {}

    def test_enrich_names_the_previous_build(
        self, client: FakeClient, make_platform: MakePlatform
    ) -> None:
        self.serve(client)
        client.serve(
            "http://us.cdn.blizzard.com/tpr/wow/config/0f/1e/0f1e2d3c4b5a69788796a5b4c3d2e1f0",
            "battlenet_build_config_previous.txt",
        )
        platform = make_platform("battlenet", titles=["wow"])
        previous = '{"build_config": "0f1e2d3c4b5a69788796a5b4c3d2e1f0"}'

        release = platform.enrich(platform.fetch("wow"), previous)

        assert release.build == "WOW-63904patch11.2.5_Retail"
        assert release.previous_build == "WOW-63796patch11.2.5_Retail"

    @pytest.mark.parametrize(
        "previous",
        ['{"build_config": "deadbeefdeadbeefdeadbeefdeadbeef"}', "not json"],
    )
    def test_enrich_survives_a_missing_previous_build(
        self, client: FakeClient, make_platform: MakePlatform, previous: str
    ) -> None:
        self.serve(client)
        platform = make_platform("battlenet", titles=["wow"])

        release = platform.enrich(platform.fetch("wow"), previous)

        assert release.build == "WOW-63904patch11.2.5_Retail"
        assert release.previous_build is None

    def test_title_ids_are_displayed_uppercase(
        self, make_platform: MakePlatform
    ) -> None:
        assert make_platform("battlenet").display_title_id("wow") == "WOW"

    def test_enrich_falls_back_to_logo_without_an_icon(
        self, client: FakeClient, make_platform: MakePlatform
    ) -> None:
        self.serve(client)
        platform = make_platform("battlenet", titles=["wow_classic"])
        release = Release(title_id="wow_classic", name="WoW Classic", version="1")

        enriched = platform.enrich(release, None)

        assert enriched.icon_url == (
            "https://blizzard.blizzmeta.com/b40a2bdbc4cf91e111e0a52a47c7bde1"
        )
        assert enriched.image_url == (
            "https://blizzard.blizzmeta.com/c788a4b8363f361b02c1408a6c043bee"
        )

    def test_missing_fragment_leaves_artwork_out(
        self, client: FakeClient, make_platform: MakePlatform
    ) -> None:
        client.serve(
            f"{BLIZZTRACK}/fragments/fenris", "battlenet_fragment_not_found.json"
        )
        platform = make_platform("battlenet", titles=["fenris"])
        release = Release(title_id="fenris", name="Diablo IV", version="1")

        assert platform.enrich(release, None) == release

    @pytest.mark.parametrize(
        ("product", "expected"),
        [
            ("wow", ("world_of_warcraft", "WoW")),
            ("wowt", ("world_of_warcraft", "WoW")),
            ("wow_classic_ptr", ("world_of_warcraft", "WoWC")),
            ("pro", ("overwatch", "Pro")),
            ("fenris", ("fenris", None)),
        ],
    )
    def test_fragment_for(self, product: str, expected: tuple[str, str | None]) -> None:
        assert fragment_for(product) == expected

    def test_enrich_survives_upstream_failures(
        self, client: FakeClient, make_platform: MakePlatform
    ) -> None:
        client.serve(f"{BLIZZTRACK}/manifest/wow/versions", "battlenet_versions.json")
        platform = make_platform("battlenet", titles=["wow"])
        release = platform.fetch("wow")

        enriched = platform.enrich(release, None)

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
        assert release.version == "03.000.005"
        assert release.region == "US"
        assert release.url == "https://prosperopatches.com/PPSA01284"
        assert release.icon_url is not None
        assert release.icon_url.endswith("/icon0.webp")
        assert release.image_url is not None
        assert release.image_url.endswith("/pic0.webp")

    def test_fetch_orbis(self, client: FakeClient, make_platform: MakePlatform) -> None:
        client.serve(
            "https://orbispatches.com/api/lookup?titleid=CUSA00900",
            "orbis_CUSA00900.json",
        )

        release = make_platform("orbis").fetch("CUSA00900")

        assert (release.name, release.version) == ("Bloodborne™", "01.09")
        assert release.url == "https://orbispatches.com/CUSA00900"

    def test_blank_artwork_is_missing(
        self, client: FakeClient, make_platform: MakePlatform
    ) -> None:
        client.responses["https://orbispatches.com/api/lookup?titleid=CUSA00419"] = (
            '{"success": true, "metadata": {"name": "Grand Theft Auto V", '
            '"currentVersion": "01.57", "icon": "", "background": ""}}'
        )

        release = make_platform("orbis").fetch("CUSA00419")

        assert (release.icon_url, release.image_url) == (None, None)

    def test_not_found(self, client: FakeClient, make_platform: MakePlatform) -> None:
        client.serve(
            "https://orbispatches.com/api/lookup?titleid=CUSA00000",
            "playstation_not_found.json",
        )

        with pytest.raises(TitleNotFoundError):
            make_platform("orbis").fetch("CUSA00000")

    def test_normalizes_ids(self, make_platform: MakePlatform) -> None:
        assert make_platform("orbis").normalize_title_id(" cusa00419 ") == "CUSA00419"

        with pytest.raises(ConfigError):
            make_platform("orbis").normalize_title_id("12345")


def test_invalid_platform_settings_raise_config_error(
    make_platform: MakePlatform,
) -> None:
    with pytest.raises(ConfigError, match="Invalid settings in steam"):
        make_platform("steam", titles=["730"], bogus=True)


def test_titles_are_normalized_and_deduplicated(make_platform: MakePlatform) -> None:
    platform = make_platform("prospero", titles=["ppsa01284", "PPSA01284", "bad"])

    assert platform.titles == ["PPSA01284"]


def test_playstation_names_include_codenames() -> None:
    assert registry()["prospero"].name == "PlayStation 5 (Prospero)"
    assert registry()["orbis"].name == "PlayStation 4 (Orbis)"
