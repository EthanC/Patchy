"""Deliver update notifications."""

from datetime import UTC, datetime
from typing import Protocol, Self

import niquests
from clyde import Markdown, RequestPolicy, Timestamp, Webhook
from clyde.components import (
    ActionRow,
    Container,
    LinkButton,
    MediaGallery,
    MediaGalleryItem,
    Section,
    Seperator,
    TextDisplay,
    Thumbnail,
    UnfurledMediaItem,
)
from loguru import logger
lazy from clyde.components.container import ContainerComponent

from patchy.errors import NotificationError
lazy from patchy.config import DiscordSettings
lazy from patchy.platforms import Update

REQUEST_POLICY: RequestPolicy = RequestPolicy(
    connect_timeout=10.0,
    read_timeout=30.0,
    max_rate_limit_retries=5,
    total_timeout=120.0,
)


class Notifier(Protocol):
    """Something that can announce an update."""

    def send(self: Self, update: Update) -> None:
        """Announce an update.

        Args:
            update: The detected update.

        Raises:
            NotificationError: The notification could not be delivered.
        """
        ...


class DiscordNotifier:
    """Post updates to a Discord webhook as Components V2 messages."""

    def __init__(self: Self, settings: DiscordSettings, webhook_url: str) -> None:
        """Create a notifier.

        Args:
            settings: Discord settings.
            webhook_url: Webhook to post notifications to.
        """
        self.settings: DiscordSettings = settings
        self.webhook_url: str = webhook_url

    def send(self: Self, update: Update) -> None:
        """Post an update to Discord.

        Args:
            update: The detected update.

        Raises:
            NotificationError: Discord rejected the message or could not be reached.
        """
        webhook: Webhook = self.build(update)

        try:
            webhook.execute(request_policy=REQUEST_POLICY)
        except (niquests.RequestException, ValueError) as e:
            msg: str = (
                f"Failed to send notification for {update.platform.name} title "
                f"{update.release.name}: {e}"
            )

            raise NotificationError(msg) from e

        logger.debug(f"Sent notification for {update.release.name}")

    def build(self: Self, update: Update) -> Webhook:
        """Build the webhook message for an update without sending it.

        Args:
            update: The detected update.

        Returns:
            The webhook message.
        """
        webhook: Webhook = Webhook(
            url=self.webhook_url, username=self.settings.username
        )

        if self.settings.avatar_url is not None:
            webhook.set_avatar_url(str(self.settings.avatar_url))

        webhook.add_component(build_container(update))

        return webhook


def build_container(update: Update) -> Container:
    """Lay out an update as a Components V2 container.

    Args:
        update: The detected update.

    Returns:
        A container holding the whole notification.
    """
    release = update.release
    now: datetime = datetime.now(UTC)

    subtitle: list[str] = [update.platform.name, release.title_id]

    if release.region is not None:
        subtitle.append(release.region)

    title: str = (
        Markdown.masked_link(release.name, release.url)
        if release.url is not None
        else release.name
    )
    heading: TextDisplay = TextDisplay(
        content=f"### {title}\n{Markdown.subtext(' · '.join(subtitle))}"
    )

    components: list[ContainerComponent] = []

    if release.icon_url is not None:
        components.append(
            Section(
                components=[heading],
                accessory=Thumbnail(media=media(release.icon_url, now)),
            )
        )
    else:
        components.append(heading)

    components.append(
        TextDisplay(
            content=Markdown.code_block(
                f"- {update.previous_version}\n+ {release.version}", "diff"
            )
        )
    )

    if release.details:
        components.append(
            TextDisplay(
                content="\n".join(
                    f"{Markdown.bold(label)}\n{Markdown.inline_code(value)}"
                    for label, value in release.details.items()
                )
            )
        )

    if release.image_url is not None:
        components.append(
            MediaGallery(items=[MediaGalleryItem(media=media(release.image_url, now))])
        )

    components.append(Seperator())
    components.append(
        TextDisplay(
            content=Markdown.subtext(
                f"Released {Timestamp.relative_time(release.released_at)}"
                if release.released_at is not None
                else f"Detected {Timestamp.relative_time(now)}"
            )
        )
    )

    if release.url is not None:
        components.append(
            ActionRow(components=[LinkButton(label="View Details", url=release.url)])
        )

    return Container(components=components).set_accent_color(update.platform.color)


def media(url: str, now: datetime) -> UnfurledMediaItem:
    """Reference an image, busting Discord's media cache.

    Discord caches media by URL, so artwork that changes with an update would
    otherwise keep showing the old image.

    Args:
        url: The image URL.
        now: The time to embed in the URL.

    Returns:
        A media item for the image.
    """
    separator: str = "&" if "?" in url else "?"

    return UnfurledMediaItem(url=f"{url}{separator}patchy={int(now.timestamp())}")
