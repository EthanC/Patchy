from datetime import datetime
from typing import Any, Dict, Optional, Self, Union

from discord_webhook import DiscordEmbed
from loguru import logger

from handlers import HTTP


class Battlenet:
    """
    Class to integrate with the BlizzTrack API and build objects specific
    to the Battle.net platform.
    """

    def IsUpdated(self: Self, titleId: str) -> Union[DiscordEmbed, bool]:
        """
        Fetch the current version of the specified Battle.net title and
        return a Discord embed object if it has updated.
        """

        previous: Optional[str] = self.history["battle"].get(titleId)

        data: Optional[Dict[str, Any]] = HTTP.GET(
            self, f"https://blizztrack.com/api/manifest/{titleId}/versions"
        )

        if (not data) or (not data.get("success")):
            return False

        titleId = data["result"]["tact"]
        name: str = data["result"]["name"]
        current: str = data["result"]["data"][0]["version_name"]
        build: str = data["result"]["data"][0]["build_config"]
        region: str = data["result"]["data"][0]["name"]

        # Attempt to locate and utilize the Americas region.
        for entry in data["result"]["data"]:
            if entry["name"].lower() == "americas":
                region = entry["name"]
                current = entry["version_name"]
                build = entry["build_config"]

        if not previous:
            self.history["battle"][titleId] = current
            self.changed = True

            logger.success(
                f"Battle.net title {name} previously untracked, saved version {current} to title history"
            )

            return False
        elif previous == current:
            logger.info(f"Battle.net title {name} not updated ({current})")

            return False

        logger.success(f"Battle.net title {name} updated, {previous} -> {current}")

        self.history["battle"][titleId] = current
        self.changed = True

        fragments: Optional[Dict[str, Any]] = HTTP.GET(
            self, f"https://blizztrack.com/api/fragments/{titleId}"
        )

        return Battlenet.BuildEmbed(
            self,
            name,
            titleId,
            f"https://blizztrack.com/view/{titleId}?type=versions",
            Battlenet.GetIcon(self, titleId, fragments),
            previous,
            current,
            Battlenet.GetKeyArt(self, titleId, fragments),
            Battlenet.GetBuild(self, titleId, region, build),
            region,
            data["result"]["created_at"],
        )

    def GetIcon(
        self: Self, titleId: str, data: Optional[Union[Dict[str, Any], str]]
    ) -> Optional[str]:
        """Get the icon for the specified Battle.net title."""

        if (not data) or (not data.get("success")):
            return

        try:
            key: str = data["result"]["products"][0]["base"]["icon_medium"]
            hash: str = data["result"]["files"]["default"][key]["hash"]

            # Use wsrv.nl proxy as BlizzTrack does not return a compatible
            # content-type header for the Discord client to display in the embed.
            return f"https://wsrv.nl/?url=https://blizzard.blizzmeta.com/{hash}"
        except Exception as e:
            logger.warning(f"Failed to get icon for Battle.net title {titleId}, {e}")

    def GetKeyArt(
        self: Self, titleId: str, data: Optional[Union[Dict[str, Any], str]]
    ) -> Optional[str]:
        """Get the keyart for the specified Battle.net title."""

        if (not data) or (not data.get("success")):
            return

        try:
            key: str = data["result"]["products"][0]["base"]["key_art"]
            hash: str = data["result"]["files"]["default"][key]["hash"]

            # Use wsrv.nl proxy as BlizzTrack does not return a compatible
            # content-type header for the Discord client to display in the embed.
            return f"https://wsrv.nl/?url=https://blizzard.blizzmeta.com/{hash}"
        except Exception as e:
            logger.warning(f"Failed to get keyart for Battle.net title {titleId}, {e}")

    def GetBuild(self: Self, titleId: str, region: str, build: str) -> Optional[str]:
        """Get the build name for the specified Battle.net title."""

        data: Optional[Dict[str, Any]] = HTTP.GET(
            self, f"https://blizztrack.com/api/manifest/{titleId}/cdns"
        )

        if (not data) or (not data.get("success")):
            return

        path: Optional[str] = None
        host: Optional[str] = None

        for entry in data["result"]["data"]:
            if entry["name"].lower() != region.lower():
                continue

            path = entry["path"]
            host = entry["hosts"].split(" ")[0]

        if (not path) or (not host):
            return

        # Build the destination URL as the BlizzTrack front-end does.
        # https://github.com/BlizzTrack/BlizzTrack/blob/d10e550bd1588338c39f10f48c744679aef3b62c/BlizzTrack/Pages/Partials/_view_versions.cshtml#L89
        dest: str = f"config/{build[:2]}/{build[2:4]}/{build}"
        buildConfig: Optional[str] = HTTP.GET(self, f"http://{host}/{path}/{dest}")

        if not buildConfig:
            return

        for line in str(buildConfig).splitlines():
            if not line.startswith("build-name"):
                continue

            return line.split(" = ")[1]

    def BuildEmbed(
        self: Self,
        name: str,
        titleId: str,
        url: str,
        thumbnail: Optional[str],
        previous: str,
        current: str,
        image: Optional[str],
        build: Optional[str],
        region: str,
        time: str,
    ) -> DiscordEmbed:
        """Build a Discord embed object for a Battle.net title update."""

        now: float = datetime.now().timestamp()
        embed: DiscordEmbed = DiscordEmbed()

        embed.set_title(name)
        embed.set_url(url)
        embed.set_color("148EFF")
        embed.add_embed_field("Previous Version", f"```diff\n- {previous}\n```")
        embed.add_embed_field("Current Version", f"```diff\n+ {current}\n```")
        embed.set_footer(
            text=f"{titleId} ({region})", icon_url="https://i.imgur.com/dI6bDr7.png"
        )
        embed.set_timestamp(datetime.fromisoformat(time).timestamp())

        if thumbnail:
            # Append timestamp to thumbnail URL to prevent Discord CDN
            # from serving cached, outdated images.
            embed.set_thumbnail(f"{thumbnail}?{str(int(now))}")

        if build:
            embed.add_embed_field("Build Name", f"```\n{build}```", False)

        if image:
            # Append timestamp to image URL to prevent Discord CDN
            # from serving cached, outdated images.
            embed.set_image(f"{image}?{str(int(now))}")

        return embed
