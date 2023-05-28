from datetime import datetime
from typing import Any, Dict, Optional, Self, Union

from discord_webhook import DiscordEmbed
from loguru import logger

from handlers import HTTP


class Orbis:
    """
    Class to integrate with the OrbisPatches API and build objects specific
    to the PlayStation 4 platform.
    """

    def IsUpdated(self: Self, titleId: str) -> Union[DiscordEmbed, bool]:
        """
        Fetch the current version of the specified PlayStation 4 title and
        return a Discord embed object if it has updated.
        """

        previous: Optional[str] = self.history["orbis"].get(titleId)

        data: Optional[Dict[str, Any]] = HTTP.GET(
            self, f"https://orbispatches.com/api/lookup?titleid={titleId}"
        )

        if (not data) or (not data.get("success")):
            return

        name: str = data["metadata"]["name"]
        current: str = data["metadata"]["currentVersion"]

        if not previous:
            self.history["orbis"][titleId] = current
            self.changed = True

            logger.success(
                f"Orbis title {name} previously untracked, saved version {current} to title history"
            )

            return
        elif previous == current:
            logger.info(f"Orbis title {name} not updated ({current})")

            return

        logger.success(f"Orbis title {name} updated, {previous} -> {current}")

        self.history["orbis"][titleId] = current
        self.changed = True

        return Orbis.BuildEmbed(
            self,
            name,
            titleId,
            f"https://orbispatches.com/{titleId}",
            data["metadata"]["icon"],
            previous,
            current,
            data["metadata"]["background"],
            data["metadata"]["region"],
        )

    def BuildEmbed(
        self: Self,
        name: str,
        titleId: str,
        url: str,
        thumbnail: Optional[str],
        previous: str,
        current: str,
        image: Optional[str],
        region: str,
    ) -> DiscordEmbed:
        """Build a Discord embed object for a PlayStation 4 title update."""

        now: float = datetime.now().timestamp()
        embed: DiscordEmbed = DiscordEmbed()

        embed.set_title(name)
        embed.set_url(url)
        embed.set_color("00439C")
        embed.add_embed_field("Previous Version", f"`{previous}`")
        embed.add_embed_field("Current Version", f"`{current}`")
        embed.set_footer(
            text=f"{titleId} ({region})", icon_url="https://i.imgur.com/ccNqLcb.png"
        )

        if thumbnail:
            # Append timestamp to thumbnail URL to prevent Discord CDN
            # from serving cached, outdated images.
            embed.set_thumbnail(f"{thumbnail}?{str(int(now))}")

        if image:
            # Append timestamp to image URL to prevent Discord CDN
            # from serving cached, outdated images.
            embed.set_image(f"{image}?{str(int(now))}")

        return embed
