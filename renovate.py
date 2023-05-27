import json
import os
from datetime import datetime
from sys import exit
from typing import Any, Dict, Optional, Self

import dotenv
from loguru import logger
from notifiers.logging import NotificationHandler

from utils import Utility


class Renovate:
    """
    Renovate is a Battle.net, PlayStation, and Steam title watcher that
    reports updates via Discord.

    https://github.com/EthanC/Renovate
    """

    def Start(self: Self) -> None:
        """Initialize Renovate and begin primary functionality."""

        logger.info("Renovate")
        logger.info("https://github.com/EthanC/Renovate")

        if dotenv.load_dotenv():
            logger.success("Loaded environment variables")
            logger.trace(os.environ)

        if logUrl := os.environ.get("DISCORD_LOG_WEBHOOK"):
            if not (logLevel := os.environ.get("DISCORD_LOG_LEVEL")):
                logger.critical("Level for Discord webhook logging is not set")

                return

            logger.add(
                NotificationHandler(
                    "slack", defaults={"webhook_url": f"{logUrl}/slack"}
                ),
                level=logLevel,
                format="```\n{time:YYYY-MM-DD HH:mm:ss.SSS} | {level:<8} | {name}:{function}:{line} - {message}\n```",
            )

            logger.success(f"Enabled logging to Discord webhook")
            logger.trace(logUrl)

        self.history: Dict[str, Any] = Renovate.LoadHistory(self)
        self.changed: bool = False

        # Battle.net
        if titles := os.environ.get("BATTLE_TITLES"):
            for title in titles.split(","):
                Renovate.ProcessBattleTitle(self, title)

        # PlayStation 5
        if titles := os.environ.get("PROSPERO_TITLES"):
            for title in titles.split(","):
                Renovate.ProcessProsperoTitle(self, title)

        # PlayStation 4
        if titles := os.environ.get("ORBIS_TITLES"):
            for title in titles.split(","):
                Renovate.ProcessOrbisTitle(self, title)

        # Steam
        if titles := os.environ.get("STEAM_TITLES"):
            for title in titles.split(","):
                Renovate.ProcessSteamTitle(self, title)

        if self.changed:
            Renovate.SaveHistory(self)

        logger.success("Finished processing titles")

    def LoadHistory(self: Self) -> Dict[str, Any]:
        """Load the last seen title versions specified in history.json"""

        try:
            with open("history.json", "r") as file:
                history: Dict[str, Any] = json.loads(file.read())
        except FileNotFoundError:
            history: Dict[str, Any] = {
                "battle": {},
                "prospero": {},
                "orbis": {},
                "steam": {},
            }

            with open("history.json", "w+") as file:
                file.write(json.dumps(history, indent=4))

            logger.success("Title history not found, created empty file")
        except Exception as e:
            logger.critical(f"Failed to load title history, {e}")

            exit(1)

        if history.get("battle") is None:
            history["battle"] = {}

        if history.get("prospero") is None:
            history["prospero"] = {}

        if history.get("orbis") is None:
            history["orbis"] = {}

        if history.get("steam") is None:
            history["steam"] = {}

        logger.success("Loaded title history")

        return history

    def ProcessBattleTitle(self: Self, titleId: str) -> None:
        """
        Get the current version of the specified Battle.net title and
        determine whether or not it has updated.
        """

        past: Optional[str] = self.history["battle"].get(titleId)

        data: Optional[Dict[str, Any]] = Utility.GET(
            self, f"https://blizztrack.com/api/manifest/{titleId}/versions"
        )

        if (data is None) or (not data["success"]):
            return

        titleId = data["result"]["tact"]
        name: str = data["result"]["name"]
        current: str = data["result"]["data"][0]["version_name"]
        build: str = data["result"]["data"][0]["build_config"]

        # Try to Americas region, otherwise default to first
        for entry in data["result"]["data"]:
            if entry["name"].lower() == "americas":
                region = entry["name"]
                current = entry["version_name"]
                build = entry["build_config"]

        if past is None:
            self.history["battle"][titleId] = current
            self.changed = True

            logger.success(
                f"Battle.net title {name} previously untracked, saved version {current} to title history"
            )

            return
        elif past == current:
            logger.info(f"Battle.net title {name} not updated ({current})")

            return

        logger.success(f"Battle.net title {name} updated, {past} -> {current}")

        thumbnail: Optional[str] = None

        fragments: Optional[Dict[str, Any]] = Utility.GET(
            self, f"https://blizztrack.com/api/fragments/{titleId}"
        )

        try:
            if fragments["success"]:
                iconKey: str = fragments["result"]["products"][0]["base"]["icon_medium"]
                iconHash: str = fragments["result"]["files"]["default"][iconKey]["hash"]

                thumbnail = f"https://blizzard.blizzmeta.com/{iconHash}"
        except Exception as e:
            logger.debug(f"Failed to locate icon for Battle.net title {titleId}, {e}")

        success: bool = Renovate.Notify(
            self,
            {
                "name": name,
                "url": f"https://blizztrack.com/view/{titleId}?type=versions",
                "timestamp": data["result"]["created_at"],
                "platformColor": "148EFF",
                "region": region,
                "titleId": titleId,
                "platformLogo": "https://i.imgur.com/dI6bDr7.png",
                "thumbnail": thumbnail,
                "pastVersion": f"`{past}`",
                "currentVersion": f"`{current}`",
                "build": None
                if data["result"]["encrypted"]
                else Utility.GetBattleBuild(self, titleId, region, build),
            },
        )

        # Ensure no changes go without notification
        if success:
            self.history["battle"][titleId] = current
            self.changed = True

    def ProcessProsperoTitle(self: Self, titleId: str) -> None:
        """
        Get the current version of the specified PlayStation 5 title and
        determine whether or not it has updated.
        """

        past: Optional[str] = self.history["prospero"].get(titleId)

        data: Optional[Dict[str, Any]] = Utility.GET(
            self, f"https://prosperopatches.com/api/lookup?titleid={titleId}"
        )

        if (data is None) or (not data.get("success")):
            return

        name: str = data["metadata"]["name"]
        current: str = data["metadata"]["currentVersion"]

        if past is None:
            self.history["prospero"][titleId] = current
            self.changed = True

            logger.success(
                f"Prospero title {name} previously untracked, saved version {current} to title history"
            )

            return
        elif past == current:
            logger.info(f"Prospero title {name} not updated ({current})")

            return

        logger.success(f"Prospero title {name} updated, {past} -> {current}")

        success: bool = Renovate.Notify(
            self,
            {
                "name": name,
                "url": f"https://prosperopatches.com/{titleId}",
                "platformColor": "00439C",
                "region": data["metadata"]["region"],
                "titleId": titleId,
                "platformLogo": "https://i.imgur.com/ccNqLcb.png",
                "thumbnail": data["metadata"]["icon"],
                "image": data["metadata"]["background"],
                "pastVersion": f"`{past}`",
                "currentVersion": f"`{current}`",
            },
        )

        # Ensure no changes go without notification
        if success:
            self.history["prospero"][titleId] = current
            self.changed = True

    def ProcessOrbisTitle(self: Self, titleId: str) -> None:
        """
        Get the current version of the specified PlayStation 4 title and
        determine whether or not it has updated.
        """

        past: Optional[str] = self.history["orbis"].get(titleId)

        data: Optional[Dict[str, Any]] = Utility.GET(
            self, f"https://orbispatches.com/api/lookup?titleid={titleId}"
        )

        if (data is None) or (not data.get("success")):
            return

        name: str = data["metadata"]["name"]
        current: str = data["metadata"]["currentVersion"]

        if past is None:
            self.history["orbis"][titleId] = current
            self.changed = True

            logger.success(
                f"Orbis title {name} previously untracked, saved version {current} to title history"
            )

            return
        elif past == current:
            logger.info(f"Orbis title {name} not updated ({current})")

            return

        logger.success(f"Orbis title {name} updated, {past} -> {current}")

        success: bool = Renovate.Notify(
            self,
            {
                "name": name,
                "url": f"https://orbispatches.com/{titleId}",
                "platformColor": "00439C",
                "region": data["metadata"]["region"],
                "titleId": titleId,
                "platformLogo": "https://i.imgur.com/ccNqLcb.png",
                "thumbnail": None if not (icon := data["metadata"]["icon"]) else icon,
                "image": None
                if not (background := data["metadata"]["background"])
                else background,
                "pastVersion": f"`{past}`",
                "currentVersion": f"`{current}`",
            },
        )

        # Ensure no changes go without notification
        if success:
            self.history["orbis"][titleId] = current
            self.changed = True

    def ProcessSteamTitle(self: Self, appId: int) -> None:
        """
        Get the current version of the specified Steam title and
        determine whether or not it has updated.
        """

        past: Optional[str] = self.history["steam"].get(str(appId))

        data: Optional[Dict[str, Any]] = Utility.GET(
            self, f"https://api.steamcmd.net/v1/info/{appId}"
        )

        if (data is None) or (data.get("status") != "success"):
            return

        name: str = data["data"][str(appId)]["common"]["name"]
        icon: str = data["data"][str(appId)]["common"]["icon"]
        current: Optional[str] = None

        try:
            depots: Dict[str, Any] = data["data"][str(appId)]["depots"]
            current = depots["branches"]["public"]["buildid"]
        except Exception as e:
            logger.error(
                f"Failed to determine current version for Steam title {name}, {e}"
            )

            return

        if past is None:
            self.history["steam"][str(appId)] = current
            self.changed = True

            logger.success(
                f"Steam title {name} previously untracked, saved version {current} to title history"
            )

            return
        elif past == current:
            logger.info(f"Steam title {name} not updated ({current})")

            return

        logger.success(f"Steam title {name} updated, {past} -> {current}")

        success: bool = Renovate.Notify(
            self,
            {
                "name": name,
                "url": f"https://steamdb.info/app/{appId}/patchnotes/",
                "platformColor": "1B2838",
                "titleId": str(appId),
                "platformLogo": "https://i.imgur.com/oYkhH6s.png",
                "thumbnail": f"https://cdn.cloudflare.steamstatic.com/steamcommunity/public/images/apps/{appId}/{icon}.jpg",
                "image": f"https://cdn.cloudflare.steamstatic.com/steam/apps/{appId}/header.jpg",
                "pastVersion": f"`{past}`",
                "currentVersion": f"`{current}`",
            },
        )

        # Ensure no changes go without notification
        if success:
            self.history["steam"][str(appId)] = current
            self.changed = True

    def Notify(self: Self, data: Dict[str, str]) -> bool:
        """Report title version change to the configured Discord webhook."""

        region: Optional[str] = data.get("region")
        titleId: str = data["titleId"]
        image: Optional[str] = data.get("image")
        thumbnail: Optional[str] = data.get("thumbnail")

        # Append timestamp to image URLs to prevent Discord CDN
        # from serving cached, outdated images.
        cacheBust: str = str(int(datetime.utcnow().timestamp()))

        payload: Dict[str, Any] = {
            "embeds": [
                {
                    "title": data["name"],
                    "url": data.get("url"),
                    "timestamp": datetime.utcnow().isoformat()
                    if (timestamp := data.get("timestamp")) is None
                    else timestamp,
                    "color": int(data["platformColor"], base=16),
                    "footer": {
                        "text": titleId if region is None else f"({region}) {titleId}",
                        "icon_url": data["platformLogo"],
                    },
                    "thumbnail": {
                        "url": None if thumbnail is None else f"{thumbnail}?{cacheBust}"
                    },
                    "image": {"url": None if image is None else f"{image}?{cacheBust}"},
                    "author": {
                        "name": "Renovate",
                        "url": "https://github.com/EthanC/Renovate",
                        "icon_url": "https://i.imgur.com/bNGKmG0.png",
                    },
                    "fields": [
                        {
                            "name": "Past Version",
                            "value": data["pastVersion"],
                            "inline": True,
                        },
                        {
                            "name": "Current Version",
                            "value": data["currentVersion"],
                            "inline": True,
                        },
                    ],
                }
            ],
        }

        if (build := data.get("build")) is not None:
            payload["embeds"][0]["fields"].append(
                {"name": "Build Name", "value": f"`{build}`"}
            )

        return Utility.POST(self, os.environ.get("DISCORD_NOTIFY_WEBHOOK"), payload)

    def SaveHistory(self: Self) -> None:
        """Save the latest title versions to history.json"""

        if os.environ.get("DEBUG"):
            logger.warning("Debug is active, not saving title history")

            return

        try:
            with open("history.json", "w+") as file:
                file.write(json.dumps(self.history, indent=4))
        except Exception as e:
            logger.critical(f"Failed to save title history, {e}")

            exit(1)

        logger.success("Saved title history")


if __name__ == "__main__":
    try:
        Renovate.Start(Renovate)
    except KeyboardInterrupt:
        exit()
