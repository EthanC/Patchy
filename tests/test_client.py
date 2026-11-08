"""HttpClient retries, exercised against a server on the loopback interface."""

import logging
import socket
import threading
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from typing import ClassVar, Self, override
lazy from collections.abc import Generator

import pytest

from patchy.client import HttpClient
from patchy.config import LogSettings
from patchy.errors import FetchError
from patchy.logs import configure_logging


class _Handler(BaseHTTPRequestHandler):
    """Answer each GET with the next queued status, then 200 once they run out."""

    statuses: ClassVar[list[int]] = []
    requests: ClassVar[int] = 0

    def do_GET(self: Self) -> None:
        type(self).requests += 1
        status: int = type(self).statuses.pop(0) if type(self).statuses else 200
        body: bytes = b"ok" if status == 200 else b"error"

        self.send_response(status)
        self.send_header("Content-Length", str(len(body)))
        self.end_headers()
        self.wfile.write(body)

    @override
    def log_message(self: Self, format: str, *args: object) -> None:
        pass


@pytest.fixture
def server() -> Generator[str]:
    _Handler.statuses = []
    _Handler.requests = 0
    httpd: ThreadingHTTPServer = ThreadingHTTPServer(("127.0.0.1", 0), _Handler)
    thread: threading.Thread = threading.Thread(target=httpd.serve_forever)

    thread.start()

    try:
        yield f"http://127.0.0.1:{httpd.server_address[1]}/"
    finally:
        httpd.shutdown()
        httpd.server_close()
        thread.join()


@pytest.fixture
def closed_port() -> int:
    with socket.socket() as sock:
        sock.bind(("127.0.0.1", 0))

        port: object = sock.getsockname()[1]

    assert isinstance(port, int)

    return port


@pytest.mark.parametrize("status", [503, 522])
def test_transient_status_is_retried(server: str, status: int) -> None:
    _Handler.statuses = [status]

    with HttpClient(timeout=5, retries=1, connect_retries=0) as client:
        assert client.get_text(server) == "ok"

    assert _Handler.requests == 2


def test_status_retries_are_limited(server: str) -> None:
    _Handler.statuses = [503, 503, 503]

    with (
        HttpClient(timeout=5, retries=1, connect_retries=5) as client,
        pytest.raises(FetchError, match="HTTP 503"),
    ):
        client.get_text(server)

    assert _Handler.requests == 2


def test_unreachable_host_is_retried_quietly(
    closed_port: int, caplog: pytest.LogCaptureFixture
) -> None:
    configure_logging(LogSettings())
    caplog.set_level(logging.DEBUG)

    with (
        HttpClient(timeout=1, retries=0, connect_retries=1) as client,
        pytest.raises(FetchError),
    ):
        client.get_text(f"http://127.0.0.1:{closed_port}/")

    retries: list[logging.LogRecord] = [
        r for r in caplog.records if r.getMessage().startswith("Retrying (")
    ]

    assert len(retries) == 1
    assert retries[0].levelno == logging.DEBUG
