from collections.abc import Callable
from pathlib import Path
from typing import Any, Self

import pytest

from patchy.config import FileSettings
from patchy.database import Database, TitleRecord
from patchy.errors import ConfigError, FetchError, NotificationError, StorageError
from patchy.notifier import DiscordNotifier, discord_notifier
from patchy.platforms import Platform, Update
from patchy.platforms.steam import API_URL as STEAMCMD
from patchy.runner import Outcome, Runner, build_platforms
lazy from tests.conftest import FakeClient

type MakePlatform = Callable[..., Platform[Any]]


class RecordingNotifier:
    def __init__(self: Self, *, fail: bool = False) -> None:
        self.sent: list[Update] = []
        self.fail: bool = fail

    def send(self: Self, update: Update) -> None:
        if self.fail:
            msg = "Discord is down"
            raise NotificationError(msg)

        self.sent.append(update)


@pytest.fixture
def steam(client: FakeClient, make_platform: MakePlatform) -> Platform[Any]:
    client.serve(f"{STEAMCMD}/730", "steam_730.json")

    return make_platform("steam", titles=["730"])


def make_runner(
    platforms: list[Platform[Any]],
    database: Database,
    notifier: RecordingNotifier | None,
    *,
    dry_run: bool = False,
) -> Runner:
    return Runner(platforms, database, notifier_for=lambda _: notifier, dry_run=dry_run)


def track(database: Database, version: str, state: str | None = None) -> None:
    database.save_title(
        TitleRecord(
            platform="steam",
            instance="steam",
            title_id="730",
            version=version,
            state=state,
        )
    )


def test_first_sighting_is_tracked_without_notifying(
    steam: Platform[Any], database: Database
) -> None:
    notifier = RecordingNotifier()

    assert make_runner([steam], database, notifier).check(steam, "730") is Outcome.NEW

    stored = database.get_title("steam", "steam", "730")
    assert stored is not None
    assert stored.version == "20480931"
    assert stored.name == "Counter-Strike 2"
    assert notifier.sent == []


def test_state_is_stored_and_compared_on_update(
    steam: Platform[Any], database: Database
) -> None:
    runner = make_runner([steam], database, notifier := RecordingNotifier())
    track(
        database, "20480000", '{"depots": {"2347771": {"name": "Linux", "gid": "1"}}}'
    )

    assert runner.check(steam, "730") is Outcome.UPDATED

    [update] = notifier.sent
    assert update.release.details["Depots"][:2] == ("Windows added", "Linux changed")
    stored = database.get_title("steam", "steam", "730")
    assert stored is not None
    assert stored.state == update.release.state


def test_unchanged_version_refreshes_state(
    steam: Platform[Any], database: Database
) -> None:
    track(database, "20480931", "{}")

    make_runner([steam], database, None).check(steam, "730")

    stored = database.get_title("steam", "steam", "730")
    assert stored is not None
    assert stored.state is not None
    assert "2347770" in stored.state


def test_unchanged_version_is_not_reported(
    steam: Platform[Any], database: Database
) -> None:
    track(database, "20480931")
    notifier = RecordingNotifier()

    assert (
        make_runner([steam], database, notifier).check(steam, "730")
        is Outcome.UNCHANGED
    )
    assert notifier.sent == []


def test_update_is_notified_and_recorded(
    steam: Platform[Any], database: Database
) -> None:
    track(database, "20480000")
    notifier = RecordingNotifier()

    assert (
        make_runner([steam], database, notifier).check(steam, "730") is Outcome.UPDATED
    )

    assert [u.previous_version for u in notifier.sent] == ["20480000"]
    stored = database.get_title("steam", "steam", "730")
    assert stored is not None
    assert stored.version == "20480931"
    assert stored.last_updated is not None
    [update] = database.list_updates()
    assert (update.previous_version, update.current_version) == ("20480000", "20480931")


def test_failed_notification_keeps_old_version_for_retry(
    steam: Platform[Any], database: Database
) -> None:
    track(database, "20480000")

    summary = make_runner([steam], database, RecordingNotifier(fail=True)).run()

    assert summary.failed == 1
    stored = database.get_title("steam", "steam", "730")
    assert stored is not None
    assert stored.version == "20480000"
    assert database.list_updates() == []


def test_dry_run_changes_nothing(steam: Platform[Any], database: Database) -> None:
    track(database, "20480000")
    notifier = RecordingNotifier()

    assert (
        make_runner([steam], database, notifier, dry_run=True).check(steam, "730")
        is Outcome.UPDATED
    )

    assert notifier.sent == []
    stored = database.get_title("steam", "steam", "730")
    assert stored is not None
    assert stored.version == "20480000"


def test_one_failing_title_does_not_stop_the_others(
    client: FakeClient, make_platform: MakePlatform, database: Database
) -> None:
    client.serve(f"{STEAMCMD}/730", "steam_730.json")
    client.responses[f"{STEAMCMD}/440"] = FetchError(f"{STEAMCMD}/440", "timed out")
    platform = make_platform("steam", titles=["440", "bad id", "730"])

    summary = make_runner([platform], database, None).run()

    assert platform.titles == ["440", "730"], "invalid IDs are dropped up front"
    assert (summary.failed, summary.new) == (1, 1)
    assert database.get_title("steam", "steam", "730") is not None


def test_unexpected_errors_are_contained(
    steam: Platform[Any], database: Database, monkeypatch: pytest.MonkeyPatch
) -> None:
    def explode(_title_id: str) -> None:
        raise RuntimeError

    monkeypatch.setattr(steam, "fetch", explode)

    assert make_runner([steam], database, None).run().failed == 1


def test_storage_errors_stop_the_run(
    steam: Platform[Any], database: Database, monkeypatch: pytest.MonkeyPatch
) -> None:
    def broken(*_args: object) -> None:
        msg = "disk full"
        raise StorageError(msg)

    monkeypatch.setattr(database, "get_title", broken)

    with pytest.raises(StorageError):
        make_runner([steam], database, None).run()


class TestBuildPlatforms:
    def test_skips_disabled_and_empty_instances(self, client: FakeClient) -> None:
        platforms = build_platforms(
            {
                "steam": [
                    {"name": "on", "titles": ["730"]},
                    {"name": "off", "titles": ["440"], "enabled": False},
                ],
                "battlenet": [{"titles": ["wow"], "enabled": False}],
                "prospero": [{}],
            },
            client,
        )

        assert [(p.key, p.instance) for p in platforms] == [("steam", "on")]

    def test_instance_names_must_be_unique(self, client: FakeClient) -> None:
        with pytest.raises(ConfigError, match=r"platforms\.steam\[1\].*unique name"):
            build_platforms(
                {"steam": [{"titles": ["730"]}, {"titles": ["440"]}]}, client
            )

    def test_invalid_instance_is_located(self, client: FakeClient) -> None:
        with pytest.raises(ConfigError, match=r"platforms\.steam\[1\]"):
            build_platforms(
                {"steam": [{"name": "a"}, {"name": "b", "titles": 5}]}, client
            )

    def test_example_config_builds_every_instance(self, client: FakeClient) -> None:
        example = Path(__file__).parents[1] / "config.example.toml"
        platforms = build_platforms(FileSettings.load(example).platforms, client)

        assert [(p.key, p.instance) for p in platforms] == [
            ("steam", "favorites"),
            ("steam", "betas"),
            ("battlenet", "battlenet"),
            ("prospero", "prospero"),
            ("orbis", "orbis"),
        ]

    def test_unknown_platform(self, client: FakeClient) -> None:
        with pytest.raises(ConfigError, match="Unknown platform 'xbox'"):
            build_platforms({"xbox": [{"titles": ["halo"]}]}, client)


class TestInstances:
    def test_each_instance_reports_to_its_own_notifier(
        self, client: FakeClient, database: Database
    ) -> None:
        client.serve(f"{STEAMCMD}/730", "steam_730.json")
        client.serve(f"{STEAMCMD}/440", "steam_440.json")
        platforms = build_platforms(
            {
                "steam": [
                    {
                        "name": "friends",
                        "titles": ["730"],
                        "webhook_url": "https://discord.com/api/webhooks/1/a",
                    },
                    {
                        "name": "work",
                        "titles": ["730", "440"],
                        "webhook_url": "https://discord.com/api/webhooks/2/b",
                    },
                ]
            },
            client,
        )
        for platform in platforms:
            database.save_title(
                TitleRecord(
                    platform="steam",
                    instance=platform.instance,
                    title_id="730",
                    version="old",
                )
            )
        notifiers: dict[str, RecordingNotifier] = {
            "https://discord.com/api/webhooks/1/a": RecordingNotifier(),
            "https://discord.com/api/webhooks/2/b": RecordingNotifier(),
        }

        summary = Runner(
            platforms,
            database,
            notifier_for=lambda p: notifiers[str(p.settings.webhook_url)],
        ).run()

        assert (summary.updated, summary.new) == (2, 1)
        assert [
            u.platform.instance
            for u in notifiers["https://discord.com/api/webhooks/1/a"].sent
        ] == ["friends"]
        assert [
            u.platform.instance
            for u in notifiers["https://discord.com/api/webhooks/2/b"].sent
        ] == ["work"]

    def test_versions_are_tracked_per_instance(
        self, client: FakeClient, database: Database
    ) -> None:
        client.serve(f"{STEAMCMD}/730", "steam_730.json")
        public, beta = build_platforms(
            {
                "steam": [
                    {"name": "public", "titles": ["730"]},
                    {"name": "beta", "titles": ["730"], "branch": "beta"},
                ]
            },
            client,
        )

        make_runner([public, beta], database, None).run()

        stored_public = database.get_title("steam", "public", "730")
        stored_beta = database.get_title("steam", "beta", "730")
        assert stored_public is not None
        assert stored_beta is not None
        assert (stored_public.version, stored_beta.version) == ("20480931", "20491111")

    def test_default_notifier_uses_the_instance_webhook(
        self, make_platform: MakePlatform
    ) -> None:
        with_webhook = make_platform(
            "steam", titles=["730"], webhook_url="https://discord.com/api/webhooks/1/a"
        )

        assert discord_notifier(make_platform("steam", titles=["730"])) is None
        notifier = discord_notifier(with_webhook)
        assert isinstance(notifier, DiscordNotifier)
        assert notifier.webhook_url == "https://discord.com/api/webhooks/1/a"
