import json
from datetime import datetime
from sys import exit, stderr
from typing import Any, Dict, Optional

from loguru import logger
from notifiers.logging import NotificationHandler

from utils import Utility


class Renovate:
    """
    Renovate is a Battle.net, PlayStation, and Steam title watcher that
    reports updates via Discord.

    https://github.com/EthanC/Renovate
    """

    def Initialize(self: Any) -> None:
        """Initialize Renovate and begin primary functionality."""

        logger.info("Renovate")
        logger.info("https://github.com/EthanC/Renovate")

        self.config: Dict[str, Any] = Renovate.LoadConfig(self)

        Renovate.SetupLogging(self)

        self.history: Dict[str, Any] = Renovate.LoadHistory(self)
        self.changed: bool = False

        # Battle.net
        for title in self.config["titles"]["battle"]:
            Renovate.ProcessBattleTitle(self, title)

        # PlayStation 5
        for title in self.config["titles"]["prospero"]:
            Renovate.ProcessProsperoTitle(self, title)

        # PlayStation 4
        for title in self.config["titles"]["orbis"]:
            Renovate.ProcessOrbisTitle(self, title)

        # Steam
        for title in self.config["titles"]["steam"]:
            Renovate.ProcessSteamTitle(self, title)

        if self.changed:
            Renovate.SaveHistory(self)

        logger.success("Finished processing titles")

    def LoadConfig(self: Any) -> Dict[str, Any]:
        """Load the configuration values specified in config.json"""

        try:
            with open("config.json", "r") as file:
                config: Dict[str, Any] = json.loads(file.read())
        except Exception as e:
            logger.critical(f"Failed to load configuration, {e}")

            exit(1)

        logger.success("Loaded configuration")

        return config

    def SetupLogging(self: Any) -> None:
        """Setup the logger using the configured values."""

        settings: Dict[str, Any] = self.config["logging"]

        if (level := settings["severity"].upper()) != "DEBUG":
            try:
                logger.remove()
                logger.add(stderr, level=level)

                logger.success(f"Set logger severity to {level}")
            except Exception as e:
                # Fallback to default logger settings
                logger.add(stderr, level="DEBUG")

                logger.error(f"Failed to set logger severity to {level}, {e}")

        if settings["discord"]["enable"]:
            level: str = settings["discord"]["severity"].upper()
            url: str = settings["discord"]["webhookUrl"]

            try:
                # Notifiers library does not natively support Discord at
                # this time. However, Discord will accept payloads which
                # are compatible with Slack by appending to the url.
                # https://github.com/liiight/notifiers/issues/400
                handler: NotificationHandler = NotificationHandler(
                    "slack", defaults={"webhook_url": f"{url}/slack"}
                )

                logger.add(
                    handler,
                    level=level,
                    format="```\n{time:YYYY-MM-DD HH:mm:ss.SSS} | {level:<8} | {name}:{function}:{line} - {message}\n```",
                )

                logger.success(f"Enabled logging to Discord with severity {level}")
            except Exception as e:
                logger.error(f"Failed to enable logging to Discord, {e}")

    def LoadHistory(self: Any) -> Dict[str, Any]:
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

    def ProcessBattleTitle(self: Any, title: Dict[str, str]) -> None:
        """
        Get the current version of the specified Battle.net title and
        determine whether or not it has updated.
        """

        titleId: str = title["titleId"]
        region: str = title["region"]

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

        # Try to select desired region, otherwise default to first
        for entry in data["result"]["data"]:
            if entry["name"].lower() == region.lower():
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

    def ProcessProsperoTitle(self: Any, titleId: str) -> None:
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

    def ProcessOrbisTitle(self: Any, titleId: str) -> None:
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

    def ProcessSteamTitle(self: Any, appId: int) -> None:
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

    def Notify(self: Any, data: Dict[str, str]) -> bool:
        """Report title version change to the configured Discord webhook."""

        settings: Dict[str, Any] = self.config["discord"]

        region: Optional[str] = data.get("region")
        titleId: str = data["titleId"]

        payload: Dict[str, Any] = {
            "username": settings["username"],
            "avatar_url": settings["avatarUrl"],
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
                    "thumbnail": {"url": data.get("thumbnail")},
                    "image": {"url": data.get("image")},
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

        return Utility.POST(self, settings["webhookUrl"], payload)

    def SaveHistory(self: Any) -> None:
        """Save the latest title versions to history.json"""

        if self.config.get("debug"):
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
        Renovate.Initialize(Renovate)
    except KeyboardInterrupt:
        exit()
