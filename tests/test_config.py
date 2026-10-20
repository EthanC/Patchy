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
        "PATCHY_DISCORD_WEBHOOK_URL", "https://discord.com/api/webhooks/1/env"
    )

    settings = Settings.load(path)

    assert settings.interval == 30
    assert settings.log.level == "DEBUG"
    assert str(settings.discord.webhook_url) == "https://discord.com/api/webhooks/1/env"
    assert settings.platforms["steam"] == {"titles": ["730"], "branch": "beta"}


def test_every_option_has_a_single_underscore_variable(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    variables: dict[str, str] = {
        "PATCHY_INTERVAL": "5",
        "PATCHY_DRY_RUN": "true",
        "PATCHY_LOG_LEVEL": "trace",
        "PATCHY_LOG_DISCORD_WEBHOOK_URL": "https://discord.com/api/webhooks/2/log",
        "PATCHY_LOG_DISCORD_LEVEL": "error",
        "PATCHY_DISCORD_WEBHOOK_URL": "https://discord.com/api/webhooks/1/x",
        "PATCHY_DATABASE_PATH": "elsewhere.db",
        "PATCHY_HTTP_TIMEOUT": "7",
        "PATCHY_HTTP_RETRIES": "1",
    }

    for key, value in variables.items():
        monkeypatch.setenv(key, value)

    settings = Settings.load(tmp_path / "absent.toml")

    assert settings.interval == 5
    assert settings.dry_run is True
    assert (settings.log.level, settings.log.discord_level) == ("TRACE", "ERROR")
    assert str(settings.log.discord_webhook_url).endswith("/2/log")
    assert str(settings.discord.webhook_url).endswith("/1/x")
    assert settings.database.path == Path("elsewhere.db")
    assert (settings.http.timeout, settings.http.retries) == (7.0, 1)


@pytest.mark.parametrize("source", ["env", "dotenv"])
def test_removed_and_toml_only_variables_are_ignored(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch, source: str
) -> None:
    variables: dict[str, str] = {
        "PATCHY_PLATFORMS_STEAM_TITLES": "440",
        "PATCHY_DISCORD_USERNAME": "Renovate",
        "PATCHY_DISCORD_AVATAR_URL": "https://example.com/avatar.png",
        "PATCHY_NOT_AN_OPTION": "1",
        "PATCHY_LOG_LEVEL": "debug",
    }

    if source == "env":
        for key, value in variables.items():
            monkeypatch.setenv(key, value)
    else:
        (tmp_path / ".env").write_text(
            "".join(f"{key}={value}\n" for key, value in variables.items())
        )

    settings = Settings.load(write(tmp_path, '[platforms.steam]\ntitles = ["730"]\n'))

    assert settings.platforms == {"steam": {"titles": ["730"]}}
    assert settings.log.level == "DEBUG"


def test_unknown_keys_in_toml_are_still_rejected(tmp_path: Path) -> None:
    with pytest.raises(ConfigError, match=r"discord\.username"):
        Settings.load(write(tmp_path, '[discord]\nusername = "Patchy"\n'))


def test_invalid_values_are_reported_together(tmp_path: Path) -> None:
    path = write(tmp_path, 'interval = -1\n[discord]\nwebhook_url = "nope"\n')

    with pytest.raises(ConfigError) as info:
        Settings.load(path)

    assert "interval" in str(info.value)
    assert "discord.webhook_url" in str(info.value)


def test_malformed_toml(tmp_path: Path) -> None:
    with pytest.raises(ConfigError, match="Failed to read"):
        Settings.load(write(tmp_path, "interval = ["))
