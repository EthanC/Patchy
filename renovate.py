import json
from datetime import datetime
from sys import exit, stderr
from typing import Any, Dict, Optional

from loguru import logger
from notifiers.logging import NotificationHandler

from utils import Utility


class Renovate:
    """
    Renovate is a PlayStation title watcher that reports updates via Discord.

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

        # PlayStation 5
        for title in self.config["titles"]["prospero"]:
            Renovate.ProcessProsperoTitle(self, title)

        if self.changed is True:
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

        if settings["discord"]["enable"] is True:
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
            history: Dict[str, Any] = {"prospero": {}}

            logger.success("Title history not found, created empty file")
        except Exception as e:
            logger.critical(f"Failed to load title history, {e}")

            exit(1)

        logger.success("Loaded title history")

        return history

    def ProcessProsperoTitle(self: Any, titleId: str) -> None:
        """
        Get the current version of the specified PlayStation 5 title and
        determine whether or not it has updated.
        """

        past: Optional[str] = self.history["prospero"].get(titleId)

        data: Optional[Dict[str, Any]] = Utility.GET(
            self, f"https://prosperopatches.com/api/lookup?titleid={titleId}"
        )

        if (data is None) or (data["success"] is False):
            logger.error(f"Failed to get current version for Prospero title {titleId}")

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

        # Prepare data for Discord embed
        data["metadata"]["titleId"] = titleId
        data["metadata"]["pastVersion"] = past
        data["metadata"]["platformLogo"] = "https://i.imgur.com/ccNqLcb.png"
        data["metadata"]["platformColor"] = "00439C"
        data["metadata"]["url"] = f"https://prosperopatches.com/{titleId}"

        # Discord does not support webp images in embeds at this time
        data["metadata"].pop("background")
        data["metadata"].pop("icon")

        success: bool = Renovate.Notify(self, data["metadata"])

        # Ensure no changes go without notification
        if success is True:
            self.history["prospero"][titleId] = current
            self.changed = True

    def Notify(self: Any, data: Dict[str, Any]) -> bool:
        """Report title version change to the configured Discord webhook."""

        settings: Dict[str, Any] = self.config["discord"]

        name: str = data["name"]
        region: str = data["region"]

        payload: Dict[str, Any] = {
            "username": settings["username"],
            "avatar_url": settings["avatarUrl"],
            "embeds": [
                {
                    "title": f"{name} ({region})",
                    "url": data.get("url"),
                    "timestamp": datetime.utcnow().isoformat(),
                    "color": int(data["platformColor"], base=16),
                    "footer": {
                        "text": data["titleId"],
                        "icon_url": data["platformLogo"],
                    },
                    "image": data.get("background"),
                    "thumbnail": data.get("icon"),
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

        return Utility.POST(self, settings["webhookUrl"], payload)

    def SaveHistory(self: Any) -> None:
        """Save the latest title versions to history.json"""

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
