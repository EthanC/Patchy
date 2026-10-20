# Patchy

![GitHub Workflow Status](https://img.shields.io/github/actions/workflow/status/EthanC/Patchy/ci.yaml?branch=main) ![Python](https://img.shields.io/badge/python-3.15-blue)

Patchy monitors games on Steam, Battle.net, and PlayStation and notifies about updates via Discord.

Patchy is the successor to Renovate. It checks each configured title's current version, remembers it in a SQLite database, and posts a Discord message when the version changes.

## Setup

A [Discord Webhook](https://support.discord.com/hc/en-us/articles/228383668-Intro-to-Webhooks) is required to receive update notifications.

Patchy is configured with a `config.toml` file, environment variables, or both. Copy [`config.example.toml`](config.example.toml) to `config.toml` and edit it; every option is documented there.

Any option can instead be set with an environment variable named `PATCHY_` followed by the option's path joined with double underscores. Environment variables take precedence over `config.toml`. Lists accept comma-separated values.

| Option                   | Environment Variable                   | Description                                                     |
| ------------------------ | -------------------------------------- | --------------------------------------------------------------- |
| `interval`               | `PATCHY_INTERVAL`                      | Minutes between checks. `0` (default) checks once and exits.    |
| `dry_run`                | `PATCHY_DRY_RUN`                       | Check titles without saving versions or sending notifications. |
| `log.level`              | `PATCHY_LOG__LEVEL`                    | Console [log level](https://loguru.readthedocs.io/en/stable/api/logger.html). Default `INFO`. |
| `log.discord_webhook_url`| `PATCHY_LOG__DISCORD_WEBHOOK_URL`      | Discord Webhook URL to forward log events to.                   |
| `log.discord_level`      | `PATCHY_LOG__DISCORD_LEVEL`            | Minimum level forwarded to Discord. Default `WARNING`.          |
| `discord.webhook_url`    | `PATCHY_DISCORD__WEBHOOK_URL`          | Discord Webhook URL to post update notifications to.            |
| `database.path`          | `PATCHY_DATABASE__PATH`                | SQLite database location. Default `patchy.db`.                  |
| `platforms.steam.titles` | `PATCHY_PLATFORMS__STEAM__TITLES`      | Steam app IDs to watch.                                         |
| `platforms.battlenet.titles` | `PATCHY_PLATFORMS__BATTLENET__TITLES` | Battle.net (BlizzTrack) product codes to watch.              |
| `platforms.prospero.titles` | `PATCHY_PLATFORMS__PROSPERO__TITLES` | PlayStation 5 title IDs to watch.                              |
| `platforms.orbis.titles` | `PATCHY_PLATFORMS__ORBIS__TITLES`      | PlayStation 4 title IDs to watch.                               |

The first time Patchy sees a title it records the current version without notifying. Later checks notify only when the version changes. A notification that fails to send is retried on the next check.

### Docker (Recommended)

Images are published to the GitHub Container Registry for `linux/amd64` and `linux/arm64`. Patchy stores `config.toml` and `patchy.db` in the `/data` volume and runs as the user and group set by `PUID` and `PGID` (default `1000`).

Modify the following `compose.yaml` example file, then run `docker compose up -d`.

```yaml
services:
  patchy:
    container_name: patchy
    image: ghcr.io/ethanc/patchy:latest
    restart: unless-stopped
    environment:
      PUID: 1000
      PGID: 1000
      TZ: America/New_York
      PATCHY_INTERVAL: 30
      PATCHY_DISCORD__WEBHOOK_URL: https://discord.com/api/webhooks/XXXXXXXX/XXXXXXXX
      PATCHY_PLATFORMS__STEAM__TITLES: 730,440
      PATCHY_PLATFORMS__PROSPERO__TITLES: PPSA01284
    volumes:
      - ./data:/data
```

To use cron or another scheduler instead, leave `PATCHY_INTERVAL` unset and run the container on your schedule without `restart`.

### Standalone

Patchy requires [Python 3.15](https://www.python.org/) and [uv](https://github.com/astral-sh/uv).

1. Install dependencies: `uv sync --no-dev`
2. Copy `config.example.toml` to `config.toml`, then fill it in.
3. Start Patchy: `uv run patchy`

Run `uv run patchy --help` for every command and option.

### Migrating from Renovate

Patchy can import Renovate's `history.json` so titles you already track aren't reported as new:

```sh
uv run patchy import-history path/to/history.json
# or, with Docker
docker compose run --rm patchy patchy import-history /data/history.json
```

Renovate's `STEAM_TITLES`, `BATTLE_TITLES`, `PROSPERO_TITLES`, and `ORBIS_TITLES` become `PATCHY_PLATFORMS__STEAM__TITLES`, `PATCHY_PLATFORMS__BATTLENET__TITLES`, `PATCHY_PLATFORMS__PROSPERO__TITLES`, and `PATCHY_PLATFORMS__ORBIS__TITLES`.

## Development

See [AGENTS.md](AGENTS.md) for the project layout, conventions, and how to add a platform.

```sh
uv sync
uv run ruff format && uv run ruff check && uv run ty check && uv run pytest
```

## Credits

-   [Helba](https://twitter.com/helba_the_ai): [BlizzTrack.com](https://blizztrack.com/)
-   [0x199](https://twitter.com/0x199): [PROSPEROPatches.com](https://prosperopatches.com/) & [ORBISPatches.com](https://orbispatches.com/)
-   [JonaKoudijs](https://github.com/jonakoudijs): [SteamCMD.net](https://www.steamcmd.net/)
