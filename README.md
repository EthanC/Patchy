# Renovate

Renovate is a Battle.net and PlayStation 5 title watcher that reports updates via Discord.

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

-   Battle.net ([Battle](https://blizztrack.com/))
-   PlayStation 5 ([Prospero](https://prosperopatches.com/))

## Credits

-   [Helba](https://twitter.com/helba_the_ai): [BlizzTrack.com](https://blizztrack.com/)
-   [0x199](https://twitter.com/0x199): [PROSPEROPatches.com](https://prosperopatches.com/)
