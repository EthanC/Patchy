from datetime import UTC, datetime
from typing import Any

import msgspec
import pytest
from clyde import Webhook
from clyde.components import Container

from patchy.client import HttpClient
from patchy.errors import NotificationError
from patchy.notifier import DiscordNotifier, media
from patchy.platforms import Release, Update
from patchy.platforms.steam import Steam, SteamSettings

WEBHOOK_URL: str = "https://discord.com/api/webhooks/1/token"


def make_update(**release: Any) -> Update:  # noqa: ANN401
    defaults: dict[str, Any] = {
        "title_id": "730",
        "name": "Counter-Strike 2",
        "version": "20480931",
        "url": "https://steamdb.info/app/730/patchnotes/",
        "icon_url": "https://cdn.example/icon.jpg",
        "image_url": "https://cdn.example/header.jpg",
        "released_at": datetime(2026, 10, 16, tzinfo=UTC),
        "details": {
            "Build Name": "WOW-1",
            "Depots": ("Windows +1.0 MB", "Linux added"),
        },
    }

    return Update(
        platform=Steam(SteamSettings(), HttpClient(timeout=1, retries=0)),
        release=Release(**(defaults | release)),
        previous_version="20480000",
    )


def payload(webhook: Webhook) -> dict[str, Any]:
    return msgspec.json.decode(msgspec.json.encode(webhook))


@pytest.mark.parametrize(
    "release",
    [
        {},
        {"icon_url": None, "image_url": None, "url": None, "released_at": None},
        {"details": {}},
    ],
)
def test_builds_valid_components(release: dict[str, Any]) -> None:
    notifier = DiscordNotifier(WEBHOOK_URL)
    webhook = notifier.build(make_update(**release))

    # Clyde enforces Discord's limits (component counts, lengths) on decode.
    data = payload(webhook)
    container, _buttons = data["components"]
    msgspec.json.decode(msgspec.json.encode(container), type=Container)

    assert "username" not in data
    assert "avatar_url" not in data
    assert container["accent_color"] == Steam.color
    assert all(c["type"] != 1 for c in container["components"]), (
        "buttons sit below the container"
    )
    text = msgspec.json.encode(container).decode()
    assert "- 20480000" in text
    assert "+ 20480931" in text


def test_layout() -> None:
    data = payload(DiscordNotifier(WEBHOOK_URL).build(make_update()))
    container, buttons = data["components"]
    text = msgspec.json.encode(container).decode()

    assert [(b["label"], b["url"]) for b in buttons["components"]] == [
        ("View on SteamDB", "https://steamdb.info/app/730/patchnotes/"),
        ("Powered by Patchy", "https://github.com/EthanC/Patchy"),
    ]
    assert "**Build Name**\\n`WOW-1`" in text
    assert "**Depots**\\n- Windows +1.0 MB\\n- Linux added" in text
    assert '"description":"Counter-Strike 2 icon"' in text
    assert '"description":"Counter-Strike 2 artwork"' in text


def test_buttons_without_release_url() -> None:
    data = payload(DiscordNotifier(WEBHOOK_URL).build(make_update(url=None)))

    assert [b["label"] for b in data["components"][1]["components"]] == [
        "Powered by Patchy"
    ]


def test_send_wraps_delivery_errors(monkeypatch: pytest.MonkeyPatch) -> None:
    def fail(*_args: object, **_kwargs: object) -> None:
        msg = "Discord rejected the payload"
        raise ValueError(msg)

    monkeypatch.setattr(Webhook, "execute", fail)

    with pytest.raises(NotificationError, match="Counter-Strike 2"):
        DiscordNotifier(WEBHOOK_URL).send(make_update())


def test_media_cache_busting_respects_existing_query() -> None:
    now = datetime(2026, 1, 1, tzinfo=UTC)

    assert media("https://a/b.png", now).url == "https://a/b.png?patchy=1767225600"
    assert media("https://a/?url=b", now).url == "https://a/?url=b&patchy=1767225600"
