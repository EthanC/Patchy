from datetime import datetime
from typing import Any, Self

from discord_webhook import DiscordEmbed
from loguru import logger

from handlers import HTTP


class Steam:
    """
    Class to integrate with the SteamCMD API and build objects specific
    to the Steam platform.
    """

    def IsUpdated(self: Self, appId: int) -> DiscordEmbed | bool:
        """
        Fetch the current version of the specified Steam title and
        return a Discord embed object if it has updated.
        """

        previous: str | None = self.history["steam"].get(str(appId))

        data: dict[str, Any] | None = HTTP.GET(
            self, f"https://api.steamcmd.net/v1/info/{appId}"
        )

        if (not data) or (data.get("status") != "success"):
            return False

        if not data["data"][str(appId)].get("common"):
            logger.warning(f"Failed to fetch Steam app {appId}, no common data")

            return False

        name: str = data["data"][str(appId)]["common"]["name"]
        icon: str = data["data"][str(appId)]["common"]["icon"]
        current: str | None = None

        try:
            depots: dict[str, Any] = data["data"][str(appId)]["depots"]
            current = depots["branches"]["public"]["buildid"]
        except Exception as e:
            logger.opt(exception=e).error(
                f"Failed to determine current version for Steam title {name}"
            )

            return

        if not previous:
            self.history["steam"][str(appId)] = current
            self.changed = True

            logger.success(
                f"Steam title {name} previously untracked, saved version {current} to title history"
            )

            return
        elif previous == current:
            logger.info(f"Steam title {name} not updated ({current})")

            return

        logger.success(f"Steam title {name} updated, {previous} -> {current}")

        self.history["steam"][str(appId)] = current
        self.changed = True

        return Steam.BuildEmbed(
            self,
            name,
            str(appId),
            f"https://steamdb.info/app/{appId}/patchnotes/",
            f"https://cdn.cloudflare.steamstatic.com/steamcommunity/public/images/apps/{appId}/{icon}.jpg",
            previous,
            current,
            f"https://cdn.cloudflare.steamstatic.com/steam/apps/{appId}/header.jpg",
        )

    def BuildEmbed(
        self: Self,
        name: str,
        titleId: str,
        url: str,
        thumbnail: str | None,
        previous: str,
        current: str,
        image: str | None,
    ) -> DiscordEmbed:
        """Build a Discord embed object for a Steam title update."""

        now: float = datetime.now().timestamp()
        embed: DiscordEmbed = DiscordEmbed()

        embed.set_title(name)
        embed.set_url(url)
        embed.set_color("1B2838")
        embed.add_embed_field("Previous Version", f"```diff\n- {previous}\n```")
        embed.add_embed_field("Current Version", f"```diff\n+ {current}\n```")
        embed.set_footer(text=titleId, icon_url="https://i.imgur.com/oYkhH6s.png")

        if thumbnail:
            # Append timestamp to thumbnail URL to prevent Discord CDN
            # from serving cached, outdated images.
            embed.set_thumbnail(f"{thumbnail}?{str(int(now))}")

        if image:
            # Append timestamp to image URL to prevent Discord CDN
            # from serving cached, outdated images.
            embed.set_image(f"{image}?{str(int(now))}")

        return embed
