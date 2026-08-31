"""HTTP transport for the studio.

A thin adapter over :class:`~studio.api.StudioAPI`: parse the request, hand it
to the router, write the response. All routing decisions live in the API so
they stay testable without a socket.

The server binds to loopback by default. The control endpoints fulfil and
cancel real orders and carry no authentication, so a wider bind puts order
control on the network — :func:`serve` warns when asked to do that.
"""

from __future__ import annotations

import ipaddress
import json
import threading
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from typing import Any, Callable

from .api import StudioAPI
from .state import StudioState
from .ui import PAGE

DEFAULT_HOST = "127.0.0.1"
DEFAULT_PORT = 8722

#: Refuse bodies larger than this. The studio only ever receives small JSON
#: objects, and an unbounded read is a trivial way to exhaust memory.
MAX_BODY_BYTES = 64 * 1024


def is_loopback(host: str) -> bool:
    if host in ("localhost", ""):
        return True
    try:
        return ipaddress.ip_address(host).is_loopback
    except ValueError:
        return False


def _handler_class(api: StudioAPI, on_log: Callable[[str], None] | None):
    class StudioHandler(BaseHTTPRequestHandler):
        server_version = "BTAStudio/1.0"
        protocol_version = "HTTP/1.1"

        def log_message(self, fmt: str, *args: Any) -> None:
            if on_log is not None:
                on_log(fmt % args)

        # -- responses ---------------------------------------------------

        def _send(self, status: int, body: bytes, content_type: str) -> None:
            self.send_response(status)
            self.send_header("Content-Type", content_type)
            self.send_header("Content-Length", str(len(body)))
            # A local operator tool has no business being framed or sniffed.
            self.send_header("X-Content-Type-Options", "nosniff")
            self.send_header("X-Frame-Options", "DENY")
            self.send_header("Cache-Control", "no-store")
            self.end_headers()
            if self.command != "HEAD":
                self.wfile.write(body)

        def _send_json(self, status: int, payload: dict[str, Any]) -> None:
            self._send(
                status,
                json.dumps(payload, default=str).encode("utf-8"),
                "application/json; charset=utf-8",
            )

        # -- verbs -------------------------------------------------------

        def do_GET(self) -> None:  # noqa: N802 - BaseHTTPRequestHandler API
            path = self.path.split("?", 1)[0]
            if path in ("/", "/index.html"):
                self._send(200, PAGE.encode("utf-8"), "text/html; charset=utf-8")
                return
            response = api.handle("GET", path)
            self._send_json(response.status, response.body)

        do_HEAD = do_GET

        def do_POST(self) -> None:  # noqa: N802 - BaseHTTPRequestHandler API
            path = self.path.split("?", 1)[0]
            try:
                length = int(self.headers.get("Content-Length") or 0)
            except ValueError:
                self._send_json(400, {"error": "invalid Content-Length"})
                return
            if length > MAX_BODY_BYTES:
                self._send_json(413, {"error": "request body too large"})
                return
            body = self.rfile.read(length) if length > 0 else b""
            response = api.handle("POST", path, body)
            self._send_json(response.status, response.body)

    return StudioHandler


class StudioServer:
    """A studio dashboard bound to a port.

    Usable as a context manager, or started in the background alongside a
    running stream::

        with StudioServer(state) as studio:
            print(studio.url)
    """

    def __init__(
        self,
        state: StudioState,
        *,
        host: str = DEFAULT_HOST,
        port: int = DEFAULT_PORT,
        read_only: bool = False,
        on_log: Callable[[str], None] | None = None,
    ) -> None:
        self.state = state
        self.api = StudioAPI(state, read_only=read_only)
        self._httpd = ThreadingHTTPServer(
            (host, port), _handler_class(self.api, on_log)
        )
        self._httpd.daemon_threads = True
        self._thread: threading.Thread | None = None

    @property
    def address(self) -> tuple[str, int]:
        host, port = self._httpd.server_address[:2]
        return str(host), int(port)

    @property
    def url(self) -> str:
        host, port = self.address
        return f"http://{host}:{port}/"

    def start(self) -> StudioServer:
        """Serve in a daemon thread and return immediately."""
        if self._thread is None:
            self._thread = threading.Thread(
                target=self._httpd.serve_forever,
                name="studio-server",
                daemon=True,
            )
            self._thread.start()
        return self

    def stop(self) -> None:
        self._httpd.shutdown()
        if self._thread is not None:
            self._thread.join(timeout=5)
            self._thread = None
        self._httpd.server_close()

    def wait(self, timeout: float | None = None) -> None:
        """Block the caller while the background thread serves."""
        if self._thread is not None:
            self._thread.join(timeout)

    def serve_forever(self) -> None:
        """Block on the calling thread until interrupted."""
        try:
            self._httpd.serve_forever()
        finally:
            self._httpd.server_close()

    def __enter__(self) -> StudioServer:
        return self.start()

    def __exit__(self, *exc: object) -> None:
        self.stop()


def serve(
    state: StudioState,
    *,
    host: str = DEFAULT_HOST,
    port: int = DEFAULT_PORT,
    read_only: bool = False,
    on_log: Callable[[str], None] | None = None,
    warn: Callable[[str], None] | None = None,
) -> StudioServer:
    """Build a started :class:`StudioServer`, warning on a non-loopback bind."""
    if not is_loopback(host) and not read_only:
        message = (
            f"Studio is bound to {host}, not loopback, with controls enabled. "
            "Fulfil and cancel are reachable by anyone who can route to this "
            "port and there is no authentication. Use --read-only, or bind to "
            "127.0.0.1 and tunnel."
        )
        (warn or print)(message)
    return StudioServer(
        state, host=host, port=port, read_only=read_only, on_log=on_log
    ).start()
