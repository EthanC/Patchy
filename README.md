# Patchy

![GitHub Workflow Status](https://img.shields.io/github/actions/workflow/status/EthanC/Patchy/ci.yaml?branch=main) ![Python](https://img.shields.io/badge/python-3.15-blue)

Patchy monitors games on Steam, Battle.net, and PlayStation and notifies about updates via Discord.

Patchy is the successor to Renovate. It checks each configured title's current version, remembers it in a SQLite database, and posts a Discord message when the version changes.

## Setup

A [Discord Webhook](https://support.discord.com/hc/en-us/articles/228383668-Intro-to-Webhooks) is required to receive update notifications.

Patchy reads each setting from exactly one place.

**`config.toml`** holds what to watch and where to report it. Copy [`config.example.toml`](config.example.toml) to `config.toml` and edit it.

| Option                       | Description                                                  |
| ---------------------------- | ------------------------------------------------------------ |
| `interval`                   | Minutes between checks. `0` (default) checks once and exits. |
| `discord.webhook_url`        | Discord Webhook URL to post update notifications to.         |
| `platforms.<key>.enabled`    | Whether to check the platform. Default `true`.               |
| `platforms.<key>.titles`     | Title IDs to watch on the platform.                          |
| `platforms.steam.branch`     | Steam depot branch to track. Default `public`.               |
| `platforms.battlenet.region` | Battle.net region to track. Default `Americas`.              |

Platform keys are `steam` (Steam app IDs), `battlenet` (BlizzTrack product codes), `prospero` (PlayStation 5 title IDs), and `orbis` (PlayStation 4 title IDs).

**Environment variables** hold runtime settings. Set them directly, or copy [`.env.example`](.env.example) to `.env`.

| Variable                         | Description                                                  |
| -------------------------------- | ------------------------------------------------------------ |
| `PATCHY_CONFIG`                  | Path to `config.toml`. Default `config.toml`.                |
| `PATCHY_DRY_RUN`                 | Check titles without saving versions or sending notifications. Default `false`. |
| `PATCHY_LOG_LEVEL`               | Console [log level](https://loguru.readthedocs.io/en/stable/api/logger.html). Default `INFO`. |
| `PATCHY_LOG_DISCORD_WEBHOOK_URL` | Discord Webhook URL to forward log events to.                |
| `PATCHY_LOG_DISCORD_LEVEL`       | Minimum level forwarded to Discord. Default `WARNING`.       |
| `PATCHY_DATABASE_PATH`           | SQLite database location. Default `patchy.db`.               |
| `PATCHY_HTTP_TIMEOUT`            | Seconds to wait for upstream services. Default `30`.         |
| `PATCHY_HTTP_RETRIES`            | Retries for transient upstream failures. Default `3`.        |

Runtime settings placed in `config.toml` are reported as an error. Environment variables for `config.toml` settings, or for options that don't exist, are ignored.

The first time Patchy sees a title it records the current version without notifying. Later checks notify only when the version changes. A notification that fails to send is retried on the next check.

### Docker (Recommended)

Images are published to the GitHub Container Registry for `linux/amd64` and `linux/arm64`. Patchy reads `config.toml` from, and stores `patchy.db` in, the `/data` volume, and runs as the user and group set by `PUID` and `PGID` (default `1000`).

Place your `config.toml` in `./data`, modify the following `compose.yaml` example file, then run `docker compose up -d`.

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
      PATCHY_LOG_LEVEL: INFO
    volumes:
      - ./data:/data
```

Set `interval` in `config.toml` to have Patchy check on its own. To use cron or another scheduler instead, leave `interval` at `0` and run the container on your schedule without `restart`.

### Standalone

Patchy requires [Python 3.15](https://www.python.org/) and [uv](https://github.com/astral-sh/uv).

1. Install dependencies: `uv sync --no-dev`
2. Copy `config.example.toml` to `config.toml` and fill it in. Optionally copy `.env.example` to `.env` to change runtime settings.
3. Start Patchy: `uv run patchy`

Run `uv run patchy --help` for every command and option.

### Migrating from Renovate

Patchy can import Renovate's `history.json` so titles you already track aren't reported as new:

```sh
uv run patchy import-history path/to/history.json
# or, with Docker
docker compose run --rm patchy patchy import-history /data/history.json
```

Renovate's `STEAM_TITLES`, `BATTLE_TITLES`, `PROSPERO_TITLES`, and `ORBIS_TITLES` become the `titles` lists under `[platforms.steam]`, `[platforms.battlenet]`, `[platforms.prospero]`, and `[platforms.orbis]` in `config.toml`.

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
