"""HTTP client used by platforms to talk to upstream services."""

from typing import Self
lazy from types import TracebackType

import niquests
from loguru import logger
from niquests import RetryConfiguration, TimeoutConfiguration
from pydantic import BaseModel, ValidationError

from patchy import PROJECT_URL
from patchy.errors import FetchError, PayloadError

USER_AGENT: str = f"Patchy (+{PROJECT_URL})"

# Upstream services (SteamCMD in particular) frequently answer with transient
# 5xx responses, so these are retried with backoff before being reported. 520-524
# are Cloudflare's equivalents of 502 and 504 for an unreachable or slow origin.
RETRY_STATUSES: frozenset[int] = frozenset(
    {429, 500, 502, 503, 504, 520, 521, 522, 523, 524}
)

# Seconds to wait for a connection. Reaching a healthy host takes well under a
# second, so this stays short even when responses are allowed to take longer.
CONNECT_TIMEOUT: float = 10.0

# Retries wait 0, 2, 4, 8, 16, then 30 seconds (plus up to a second of jitter, so
# instances do not retry in lockstep). Eight connection retries therefore span
# about two minutes, long enough to ride out a local DNS server restarting.
BACKOFF_FACTOR: float = 1.0
BACKOFF_MAX: float = 30.0
BACKOFF_JITTER: float = 1.0


class HttpClient:
    """A thin, typed wrapper around a pooled niquests session.

    Every failure is raised as a ``FetchError`` or ``PayloadError`` so that callers
    never need to know about niquests exception types.
    """

    def __init__(
        self: Self, *, timeout: float, retries: int, connect_retries: int
    ) -> None:
        """Create a client.

        Args:
            timeout: Seconds to wait for a response before giving up. Connecting is
                limited to ``CONNECT_TIMEOUT`` seconds, or ``timeout`` if shorter.
            retries: Retries for failures after reaching the host: read timeouts,
                dropped connections, and transient statuses (``RETRY_STATUSES``).
            connect_retries: Retries for failures to reach the host at all, such as
                DNS resolution errors and refused connections. The request never
                reached the server, so these are always safe to retry.
        """
        self._session: niquests.Session = niquests.Session(
            timeout=TimeoutConfiguration(
                connect=min(CONNECT_TIMEOUT, timeout), read=timeout
            ),
            # With no total, each kind of failure has its own budget, so a DNS
            # outage does not use up the retries meant for a slow upstream.
            retries=RetryConfiguration(
                total=None,
                connect=connect_retries,
                read=retries,
                status=retries,
                other=retries,
                backoff_factor=BACKOFF_FACTOR,
                backoff_max=BACKOFF_MAX,
                backoff_jitter=BACKOFF_JITTER,
                status_forcelist=RETRY_STATUSES,
                allowed_methods=frozenset({"GET"}),
                raise_on_status=False,
                respect_retry_after_header=True,
            ),
            headers={"User-Agent": USER_AGENT},
        )

    def __enter__(self: Self) -> Self:
        """Return the client for use in a ``with`` block."""
        return self

    def __exit__(
        self: Self,
        exc_type: type[BaseException] | None,
        exc: BaseException | None,
        traceback: TracebackType | None,
    ) -> None:
        """Close the underlying session."""
        self.close()

    def close(self: Self) -> None:
        """Release pooled connections."""
        self._session.close()

    def get_text(self: Self, url: str) -> str:
        """Perform a GET request and return the response body as text.

        Args:
            url: The URL to request.

        Returns:
            The decoded response body.

        Raises:
            FetchError: The request failed or returned a non-success status.
        """
        logger.debug(f"GET {url}")

        try:
            res: niquests.Response = self._session.get(url)
        except niquests.Timeout as e:
            raise FetchError(url, "timed out") from e
        except niquests.RequestException as e:
            raise FetchError(url, _describe(e)) from e

        status: int = res.status_code or 0

        logger.trace(f"HTTP {status} GET {url}")

        if not res.ok:
            raise FetchError(url, f"HTTP {status}", status=status)

        return res.text or ""

    def get_model[T: BaseModel](self: Self, url: str, model: type[T]) -> T:
        """Perform a GET request and validate the JSON body against a model.

        Args:
            url: The URL to request.
            model: The Pydantic model describing the expected response.

        Returns:
            The validated response.

        Raises:
            FetchError: The request failed or returned a non-success status.
            PayloadError: The response body is not JSON or does not match the model.
        """
        text: str = self.get_text(url)

        try:
            return model.model_validate_json(text)
        except ValidationError as e:
            msg: str = (
                f"GET {url} returned an unexpected response "
                f"({e.error_count()} validation errors)"
            )

            raise PayloadError(msg) from e


def _describe(error: Exception, limit: int = 200) -> str:
    """Summarize a request exception in one short line."""
    detail: str = " ".join(str(error).split())

    if len(detail) > limit:
        detail = f"{detail[: limit - 1]}…"

    return f"{type(error).__name__}: {detail}" if detail else type(error).__name__
