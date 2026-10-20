from collections.abc import Callable
from typing import Any, Self

import pytest

from patchy.database import Database, TitleRecord
from patchy.errors import FetchError, NotificationError, StorageError
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


def track(database: Database, version: str) -> None:
    database.save_title(TitleRecord(platform="steam", title_id="730", version=version))


def test_first_sighting_is_tracked_without_notifying(
    steam: Platform[Any], database: Database
) -> None:
    notifier = RecordingNotifier()

    assert Runner([steam], database, notifier).check(steam, "730") is Outcome.NEW

    stored = database.get_title("steam", "730")
    assert stored is not None
    assert stored.version == "20480931"
    assert stored.name == "Counter-Strike 2"
    assert notifier.sent == []


def test_unchanged_version_is_not_reported(
    steam: Platform[Any], database: Database
) -> None:
    track(database, "20480931")
    notifier = RecordingNotifier()

    assert Runner([steam], database, notifier).check(steam, "730") is Outcome.UNCHANGED
    assert notifier.sent == []


def test_update_is_notified_and_recorded(
    steam: Platform[Any], database: Database
) -> None:
    track(database, "20480000")
    notifier = RecordingNotifier()

    assert Runner([steam], database, notifier).check(steam, "730") is Outcome.UPDATED

    assert [u.previous_version for u in notifier.sent] == ["20480000"]
    stored = database.get_title("steam", "730")
    assert stored is not None
    assert stored.version == "20480931"
    assert stored.last_updated is not None
    [update] = database.list_updates()
    assert (update.previous_version, update.current_version) == ("20480000", "20480931")


def test_failed_notification_keeps_old_version_for_retry(
    steam: Platform[Any], database: Database
) -> None:
    track(database, "20480000")

    summary = Runner([steam], database, RecordingNotifier(fail=True)).run()

    assert summary.failed == 1
    stored = database.get_title("steam", "730")
    assert stored is not None
    assert stored.version == "20480000"
    assert database.list_updates() == []


def test_dry_run_changes_nothing(steam: Platform[Any], database: Database) -> None:
    track(database, "20480000")
    notifier = RecordingNotifier()

    assert (
        Runner([steam], database, notifier, dry_run=True).check(steam, "730")
        is Outcome.UPDATED
    )

    assert notifier.sent == []
    stored = database.get_title("steam", "730")
    assert stored is not None
    assert stored.version == "20480000"


def test_one_failing_title_does_not_stop_the_others(
    client: FakeClient, make_platform: MakePlatform, database: Database
) -> None:
    client.serve(f"{STEAMCMD}/730", "steam_730.json")
    client.responses[f"{STEAMCMD}/440"] = FetchError(f"{STEAMCMD}/440", "timed out")
    platform = make_platform("steam", titles=["440", "bad id", "730"])

    summary = Runner([platform], database, None).run()

    assert platform.titles == ["440", "730"], "invalid IDs are dropped up front"
    assert (summary.failed, summary.new) == (1, 1)
    assert database.get_title("steam", "730") is not None


def test_unexpected_errors_are_contained(
    steam: Platform[Any], database: Database, monkeypatch: pytest.MonkeyPatch
) -> None:
    def explode(_title_id: str) -> None:
        raise RuntimeError

    monkeypatch.setattr(steam, "fetch", explode)

    assert Runner([steam], database, None).run().failed == 1


def test_storage_errors_stop_the_run(
    steam: Platform[Any], database: Database, monkeypatch: pytest.MonkeyPatch
) -> None:
    def broken(*_args: object) -> None:
        msg = "disk full"
        raise StorageError(msg)

    monkeypatch.setattr(database, "get_title", broken)

    with pytest.raises(StorageError):
        Runner([steam], database, None).run()


class TestBuildPlatforms:
    def test_skips_disabled_and_empty_platforms(self, client: FakeClient) -> None:
        platforms = build_platforms(
            {
                "steam": {"titles": ["730"]},
                "battlenet": {"titles": ["wow"], "enabled": False},
                "prospero": {},
            },
            client,
        )

        assert [p.key for p in platforms] == ["steam"]

    def test_unknown_platform(self, client: FakeClient) -> None:
        with pytest.raises(Exception, match="Unknown platform 'xbox'"):
            build_platforms({"xbox": {"titles": ["halo"]}}, client)
