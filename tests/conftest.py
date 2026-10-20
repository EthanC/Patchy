"""Shared fixtures: a fake HTTP client, a temporary database, and sample payloads."""

from pathlib import Path
from typing import Any, Self, override
lazy from collections.abc import Callable, Generator

import pytest

from patchy.client import HttpClient
from patchy.database import Database
from patchy.errors import FetchError
from patchy.platforms import Platform, registry

FIXTURES: Path = Path(__file__).parent / "fixtures"


def fixture_text(name: str) -> str:
    return (FIXTURES / name).read_text(encoding="utf-8")


class FakeClient(HttpClient):
    """An HttpClient that serves canned responses instead of using the network."""

    def __init__(self: Self) -> None:
        self.responses: dict[str, str | FetchError] = {}
        self.requests: list[str] = []

    @override
    def close(self: Self) -> None:
        pass

    @override
    def get_text(self: Self, url: str) -> str:
        self.requests.append(url)

        response: str | FetchError | None = self.responses.get(url)

        if response is None:
            raise FetchError(url, "HTTP 404", status=404)

        if isinstance(response, FetchError):
            raise response

        return response

    def serve(self: Self, url: str, fixture: str) -> None:
        self.responses[url] = fixture_text(fixture)


@pytest.fixture
def client() -> FakeClient:
    return FakeClient()


@pytest.fixture
def database(tmp_path: Path) -> Generator[Database]:
    db: Database = Database(tmp_path / "data" / "patchy.db")

    yield db

    db.close()


@pytest.fixture
def make_platform(
    client: FakeClient,
) -> Callable[..., Platform[Any]]:
    def make(key: str, **settings: Any) -> Platform[Any]:  # noqa: ANN401
        return registry()[key].from_config(settings, client)

    return make
