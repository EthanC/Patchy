from pathlib import Path

import pytest

from patchy.config import EnvironmentSettings, FileSettings
from patchy.errors import ConfigError


def write(tmp_path: Path, text: str) -> Path:
    path = tmp_path / "config.toml"
    path.write_text(text, encoding="utf-8")

    return path


@pytest.fixture(autouse=True)
def isolated(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.chdir(tmp_path)


class TestEnvironment:
    def test_defaults(self) -> None:
        settings = EnvironmentSettings.load()

        assert settings.config == Path("config.toml")
        assert settings.dry_run is False
        assert settings.log.level == "INFO"
        assert settings.database.path == Path("patchy.db")

    def test_every_variable(self, monkeypatch: pytest.MonkeyPatch) -> None:
        variables: dict[str, str] = {
            "PATCHY_CONFIG": "/data/config.toml",
            "PATCHY_DRY_RUN": "true",
            "PATCHY_LOG_LEVEL": "trace",
            "PATCHY_LOG_DISCORD_WEBHOOK_URL": "https://discord.com/api/webhooks/2/log",
            "PATCHY_LOG_DISCORD_LEVEL": "error",
            "PATCHY_DATABASE_PATH": "elsewhere.db",
            "PATCHY_HTTP_TIMEOUT": "7",
            "PATCHY_HTTP_RETRIES": "1",
        }

        for key, value in variables.items():
            monkeypatch.setenv(key, value)

        settings = EnvironmentSettings.load()

        assert settings.config == Path("/data/config.toml")
        assert settings.dry_run is True
        assert (settings.log.level, settings.log.discord_level) == ("TRACE", "ERROR")
        assert str(settings.log.discord_webhook_url).endswith("/2/log")
        assert settings.database.path == Path("elsewhere.db")
        assert (settings.http.timeout, settings.http.retries) == (7.0, 1)

    @pytest.mark.parametrize("source", ["env", "dotenv"])
    def test_file_owned_and_unknown_variables_are_ignored(
        self, tmp_path: Path, monkeypatch: pytest.MonkeyPatch, source: str
    ) -> None:
        variables: dict[str, str] = {
            "PATCHY_INTERVAL": "30",
            "PATCHY_DISCORD_WEBHOOK_URL": "https://discord.com/api/webhooks/1/env",
            "PATCHY_PLATFORMS_STEAM_TITLES": "440",
            "PATCHY_DISCORD_USERNAME": "Renovate",
            "PATCHY_LOG_SOMETHING_OLD": "1",
            "PATCHY_NOT_AN_OPTION": "1",
            "STEAM_TITLES": "730",
            "PATCHY_LOG_LEVEL": "debug",
        }

        if source == "env":
            for key, value in variables.items():
                monkeypatch.setenv(key, value)
        else:
            (tmp_path / ".env").write_text(
                "".join(f"{key}={value}\n" for key, value in variables.items())
            )

        assert EnvironmentSettings.load().log.level == "DEBUG"

        file = FileSettings.load(write(tmp_path, "interval = 5\n"))

        assert file.interval == 5
        assert file.discord.webhook_url is None
        assert file.platforms == {}

    def test_invalid_values_name_the_variable(
        self, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        monkeypatch.setenv("PATCHY_HTTP_TIMEOUT", "-1")

        with pytest.raises(ConfigError, match="PATCHY_HTTP_TIMEOUT"):
            EnvironmentSettings.load()


class TestFile:
    def test_missing_file_uses_defaults(self, tmp_path: Path) -> None:
        settings = FileSettings.load(tmp_path / "absent.toml")

        assert settings.interval == 0
        assert settings.discord.webhook_url is None
        assert settings.platforms == {}

    def test_reads_every_option(self, tmp_path: Path) -> None:
        settings = FileSettings.load(
            write(
                tmp_path,
                """
                interval = 15

                [discord]
                webhook_url = "https://discord.com/api/webhooks/1/toml"

                [platforms.Steam]
                titles = ["730"]
                branch = "beta"
                """,
            )
        )

        assert settings.interval == 15
        assert str(settings.discord.webhook_url).endswith("/1/toml")
        assert settings.platforms == {"steam": {"titles": ["730"], "branch": "beta"}}

    def test_environment_settings_are_rejected(self, tmp_path: Path) -> None:
        path = write(
            tmp_path,
            'dry_run = true\n[log]\nlevel = "DEBUG"\n[http]\ntimeout = 5\n',
        )

        with pytest.raises(ConfigError) as info:
            FileSettings.load(path)

        message = str(info.value)
        assert "dry_run: set with the PATCHY_DRY_RUN environment variable" in message
        assert "log: set with PATCHY_LOG_* environment variables" in message
        assert "http: set with PATCHY_HTTP_* environment variables" in message

    def test_unknown_keys_are_rejected(self, tmp_path: Path) -> None:
        with pytest.raises(ConfigError, match=r"discord\.username"):
            FileSettings.load(write(tmp_path, '[discord]\nusername = "Patchy"\n'))

    def test_invalid_values_are_reported_together(self, tmp_path: Path) -> None:
        path = write(
            tmp_path,
            'interval = -1\nlog = 1\n[discord]\nwebhook_url = "nope"\n',
        )

        with pytest.raises(ConfigError) as info:
            FileSettings.load(path)

        message = str(info.value)
        assert "interval" in message
        assert "discord.webhook_url" in message
        assert "log: set with PATCHY_LOG_* environment variables" in message

    def test_malformed_toml(self, tmp_path: Path) -> None:
        with pytest.raises(ConfigError, match="Failed to read"):
            FileSettings.load(write(tmp_path, "interval = ["))
