# Renovate

Renovate is a Battle.net, PlayStation, and Steam title watcher that reports updates via Discord.

<p align="center">
    <img src="https://i.imgur.com/qEimihY.png" draggable="false">
</p>

## Usage

Open `config_example.json` and provide the configurable values, then save and rename the file to `config.json`.

Renovate is designed to be ran using a task scheduler, such as [cron](https://crontab.guru/).

```
python renovate.py
```

### Supported Platforms

-   Battle.net (`battle`)
-   PlayStation 5 (`prospero`)
-   PlayStation 4 (`orbis`)
-   Steam (`steam`)

## Credits

-   [Helba](https://twitter.com/helba_the_ai): [BlizzTrack.com](https://blizztrack.com/)
-   [0x199](https://twitter.com/0x199): [PROSPEROPatches.com](https://prosperopatches.com/) & [ORBISPatches.com](https://orbispatches.com/)
-   [JonaKoudijs](https://github.com/jonakoudijs): [SteamCMD.net](https://www.steamcmd.net/)
