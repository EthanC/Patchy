lazy from pathlib import Path

import pytest

from patchy.config import Settings
from patchy.errors import ConfigError


def write(tmp_path: Path, text: str) -> Path:
    path = tmp_path / "config.toml"
    path.write_text(text, encoding="utf-8")

    return path


@pytest.fixture(autouse=True)
def isolated(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.chdir(tmp_path)


def test_missing_file_uses_defaults(tmp_path: Path) -> None:
    settings = Settings.load(tmp_path / "absent.toml")

    assert settings.interval == 0
    assert settings.platforms == {}


def test_environment_overrides_toml(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    path = write(
        tmp_path,
        """
        interval = 15

        [log]
        level = "debug"

        [discord]
        webhook_url = "https://discord.com/api/webhooks/1/toml"

        [platforms.steam]
        titles = ["730"]
        branch = "beta"
        """,
    )
    monkeypatch.setenv("PATCHY_INTERVAL", "30")
    monkeypatch.setenv(
        "PATCHY_DISCORD__WEBHOOK_URL", "https://discord.com/api/webhooks/1/env"
    )

    settings = Settings.load(path)

    assert settings.interval == 30
    assert settings.log.level == "DEBUG"
    assert str(settings.discord.webhook_url) == "https://discord.com/api/webhooks/1/env"
    assert settings.platforms["steam"] == {"titles": ["730"], "branch": "beta"}


@pytest.mark.parametrize("source", ["env", "dotenv"])
def test_platforms_cannot_come_from_the_environment(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch, source: str
) -> None:
    if source == "env":
        monkeypatch.setenv("PATCHY_PLATFORMS__STEAM__TITLES", "440")
    else:
        (tmp_path / ".env").write_text("PATCHY_PLATFORMS__STEAM__TITLES=440\n")

    with pytest.raises(ConfigError, match=r"must be configured in config\.toml"):
        Settings.load(write(tmp_path, '[platforms.steam]\ntitles = ["730"]\n'))


def test_invalid_values_are_reported_together(tmp_path: Path) -> None:
    path = write(tmp_path, 'interval = -1\n[discord]\nwebhook_url = "nope"\n')

    with pytest.raises(ConfigError) as info:
        Settings.load(path)

    assert "interval" in str(info.value)
    assert "discord.webhook_url" in str(info.value)


def test_malformed_toml(tmp_path: Path) -> None:
    with pytest.raises(ConfigError, match="Failed to read"):
        Settings.load(write(tmp_path, "interval = ["))
