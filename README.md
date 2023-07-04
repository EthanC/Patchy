# Renovate

![GitHub Workflow Status](https://img.shields.io/github/actions/workflow/status/EthanC/Renovate/main.yml?branch=main) ![Docker Pulls](https://img.shields.io/docker/pulls/ethanchrisp/renovate?label=Docker%20Pulls) ![Docker Image Size (tag)](https://img.shields.io/docker/image-size/ethanchrisp/renovate/latest?label=Docker%20Image%20Size)

Renovate is a Steam, Battle.net, and PlayStation title watcher that reports updates via Discord.

<p align="center">
    <img src="https://i.imgur.com/XVGizWC.png" draggable="false">
</p>

## Setup

A [Discord Webhook](https://support.discord.com/hc/en-us/articles/228383668-Intro-to-Webhooks) is recommended for notifications.

Regardless of your chosen setup method, Renovate is intended for use with a task scheduler, such as [cron](https://crontab.guru/).

**Environment Variables:**

-   `LOG_LEVEL`: [Loguru](https://loguru.readthedocs.io/en/stable/api/logger.html) severity level to write to the console.
-   `LOG_DISCORD_WEBHOOK_URL`: [Discord Webhook](https://support.discord.com/hc/en-us/articles/228383668-Intro-to-Webhooks) URL to receive log events.
-   `LOG_DISCORD_WEBHOOK_LEVEL`: Minimum [Loguru](https://loguru.readthedocs.io/en/stable/api/logger.html) severity level to forward to Discord.
-   `STEAM_TITLES`: Comma-separated list of Steam title IDs to watch.
-   `BATTLE_TITLES`: Comma-separated list of Battle.net title IDs to watch.
-   `PROSPERO_TITLES`: Comma-separated list of PlayStation 5 title IDs to watch.
-   `ORBIS_TITLES`: Comma-separated list of PlayStation 4 title IDs to watch.
-   `DISCORD_WEBHOOK_URL`: [Discord Webhook](https://support.discord.com/hc/en-us/articles/228383668-Intro-to-Webhooks) URL to receive available update notifications.

### Docker (Recommended)

Modify the following `docker-compose.yml` example file, then run `docker compose up`.

```yml
version: "3"
services:
  renovate:
    container_name: renovate
    image: ethanchrisp/renovate:latest
    environment:
      LOG_LEVEL: INFO
      LOG_DISCORD_WEBHOOK_URL: https://discord.com/api/webhooks/YYYYYYYY/YYYYYYYY
      LOG_DISCORD_WEBHOOK_LEVEL: WARNING
      STEAM_TITLES: XXXXXXXX,YYYYYYYY,ZZZZZZZZ
      BATTLE_TITLES: XXXXXXXX,YYYYYYYY,ZZZZZZZZ
      PROSPERO_TITLES: XXXXXXXX,YYYYYYYY,ZZZZZZZZ
      ORBIS_TITLES: XXXXXXXX,YYYYYYYY,ZZZZZZZZ
      DISCORD_WEBHOOK_URL: https://discord.com/api/webhooks/XXXXXXXX/XXXXXXXX
```

### Standalone

Renovate is built for [Python 3.11](https://www.python.org/) or greater.

1. Install required dependencies using [Poetry](https://python-poetry.org/): `poetry install`
2. Rename `.env_example` to `.env`, then provide the environment variables.
3. Start Renovate: `python renovate.py`

## Credits

-   [Helba](https://twitter.com/helba_the_ai): [BlizzTrack.com](https://blizztrack.com/)
-   [0x199](https://twitter.com/0x199): [PROSPEROPatches.com](https://prosperopatches.com/) & [ORBISPatches.com](https://orbispatches.com/)
-   [JonaKoudijs](https://github.com/jonakoudijs): [SteamCMD.net](https://www.steamcmd.net/)
