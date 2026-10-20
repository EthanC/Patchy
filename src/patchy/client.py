"""HTTP client used by platforms to talk to upstream services."""

from typing import Self
lazy from types import TracebackType

import niquests
from loguru import logger
from niquests import RetryConfiguration
from pydantic import BaseModel, ValidationError

from patchy.errors import FetchError, PayloadError

USER_AGENT: str = "Patchy (+https://github.com/EthanC/Patchy)"

# Upstream services (SteamCMD in particular) frequently answer with transient
# 5xx responses, so these are retried with backoff before being reported.
RETRY_STATUSES: frozenset[int] = frozenset({429, 500, 502, 503, 504})


class HttpClient:
    """A thin, typed wrapper around a pooled niquests session.

    Every failure is raised as a ``FetchError`` or ``PayloadError`` so that callers
    never need to know about niquests exception types.
    """

    def __init__(self: Self, *, timeout: float, retries: int) -> None:
        """Create a client.

        Args:
            timeout: Seconds to wait for a connection or response before giving up.
            retries: Attempts to make after the first one for transient failures.
        """
        self._session: niquests.Session = niquests.Session(
            timeout=timeout,
            retries=RetryConfiguration(
                total=retries,
                backoff_factor=1.0,
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
