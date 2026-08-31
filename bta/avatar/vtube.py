"""VTube Studio public API client.

Protocol reference: https://github.com/DenchiSoft/VTubeStudio

Note on lip sync: the VTS API accepts numeric parameter values only — there is
no endpoint that takes audio. So we send the mouth envelope computed in
bta.audio.lipsync as InjectParameterDataRequest frames, while the audio itself
goes to a sound device. The two stay aligned because SpeechPlayer derives them
from the same frames at the same moment.
"""

from __future__ import annotations

import asyncio
import contextlib
import json
import uuid
from pathlib import Path

import websockets
from websockets.asyncio.client import ClientConnection

from bta.config import VTubeConfig
from bta.log import get_logger

log = get_logger("avatar.vts")

API_NAME = "VTubeStudioPublicAPI"
API_VERSION = "1.0"


class VTubeStudioError(RuntimeError):
    """VTube Studio refused a request or is unreachable."""


class VTubeStudioClient:
    """Authenticates with VTube Studio and injects mouth parameters."""

    def __init__(self, cfg: VTubeConfig) -> None:
        self.cfg = cfg
        self._ws: ClientConnection | None = None
        self._token_path = Path(cfg.token_file)
        self.authenticated = False
        self.model_name: str = ""
        self._pending: dict[str, asyncio.Future[dict]] = {}
        self._reader: asyncio.Task[None] | None = None
        self._closed_reason: str = ""

    # -- connection --------------------------------------------------------

    @property
    def connected(self) -> bool:
        return self._ws is not None

    async def connect(self, timeout: float = 10.0) -> None:
        """Open the socket and complete the plugin authentication handshake."""
        log.info("Connecting to VTube Studio at %s", self.cfg.url)
        try:
            self._ws = await asyncio.wait_for(
                websockets.connect(self.cfg.url, max_size=8 * 1024 * 1024),
                timeout=timeout,
            )
        except (OSError, asyncio.TimeoutError, websockets.WebSocketException) as exc:
            raise VTubeStudioError(
                f"Could not reach VTube Studio at {self.cfg.url}. "
                "Is VTube Studio running with the API enabled "
                "(Settings -> API -> 'Start API')?"
            ) from exc

        self._closed_reason = ""
        self._reader = asyncio.create_task(self._read_loop(), name="vts-reader")

        await self._authenticate()
        with contextlib.suppress(VTubeStudioError):
            self.model_name = await self.current_model_name()
        log.info(
            "VTube Studio ready%s", f" (model: {self.model_name})" if self.model_name else ""
        )

    async def close(self) -> None:
        ws, self._ws = self._ws, None
        reader, self._reader = self._reader, None
        self.authenticated = False
        if ws is not None:
            with contextlib.suppress(Exception):
                await ws.close()
        if reader is not None:
            reader.cancel()
            with contextlib.suppress(asyncio.CancelledError, Exception):
                await reader
        self._fail_pending("Connection closed")

    # -- background reader -------------------------------------------------

    def _fail_pending(self, reason: str) -> None:
        pending, self._pending = self._pending, {}
        for future in pending.values():
            if not future.done():
                future.set_exception(VTubeStudioError(reason))

    async def _read_loop(self) -> None:
        """Drain the socket continuously.

        Injection is fire-and-forget, so VTube Studio's acknowledgements would
        otherwise pile up unread — at 60 fps that is millions of queued
        messages over a long stream. Reading here keeps memory flat and lets
        request() wait on a future instead of scanning a backlog.
        """
        ws = self._ws
        if ws is None:
            return
        try:
            async for raw in ws:
                try:
                    message = json.loads(raw)
                except (json.JSONDecodeError, TypeError):
                    continue
                future = self._pending.pop(message.get("requestID", ""), None)
                if future is None or future.done():
                    continue  # an ack we do not wait for, or an event
                if message.get("messageType") == "APIError":
                    detail = message.get("data", {})
                    future.set_exception(
                        VTubeStudioError(
                            f"VTube Studio error {detail.get('errorID')}: "
                            f"{detail.get('message')}"
                        )
                    )
                else:
                    future.set_result(message.get("data", {}))
        except asyncio.CancelledError:
            raise
        except Exception as exc:
            self._closed_reason = str(exc) or exc.__class__.__name__
        finally:
            self._fail_pending(self._closed_reason or "VTube Studio closed the connection")

    async def __aenter__(self) -> VTubeStudioClient:
        await self.connect()
        return self

    async def __aexit__(self, *_: object) -> None:
        await self.close()

    # -- raw request/response ---------------------------------------------

    def _envelope(self, message_type: str, data: dict | None = None) -> dict:
        return {
            "apiName": API_NAME,
            "apiVersion": API_VERSION,
            "requestID": uuid.uuid4().hex[:12],
            "messageType": message_type,
            "data": data or {},
        }

    async def request(
        self, message_type: str, data: dict | None = None, *, timeout: float = 10.0
    ) -> dict:
        """Send a request and wait for its matching response."""
        if self._ws is None:
            raise VTubeStudioError("Not connected to VTube Studio")

        payload = self._envelope(message_type, data)
        request_id = payload["requestID"]
        future: asyncio.Future[dict] = asyncio.get_running_loop().create_future()
        self._pending[request_id] = future

        try:
            await self._ws.send(json.dumps(payload))
        except websockets.WebSocketException as exc:
            self._pending.pop(request_id, None)
            raise VTubeStudioError("VTube Studio closed the connection") from exc

        try:
            return await asyncio.wait_for(future, timeout=timeout)
        except asyncio.TimeoutError as exc:
            raise VTubeStudioError(
                f"Timed out waiting for {message_type} response"
            ) from exc
        finally:
            self._pending.pop(request_id, None)

    async def send_only(self, message_type: str, data: dict | None = None) -> None:
        """Fire-and-forget. Used for the parameter stream, where waiting for a
        response every frame would halve our effective injection rate."""
        if self._ws is None:
            raise VTubeStudioError("Not connected to VTube Studio")
        try:
            await self._ws.send(json.dumps(self._envelope(message_type, data)))
        except (websockets.WebSocketException, OSError) as exc:
            # VTube Studio was closed or crashed. Surface it as our own error so
            # the avatar loop reconnects instead of dying on a raw socket error.
            raise VTubeStudioError(
                f"VTube Studio connection lost: {exc.__class__.__name__}"
            ) from exc

    # -- authentication ----------------------------------------------------

    def _read_token(self) -> str:
        try:
            return self._token_path.read_text(encoding="utf-8").strip()
        except OSError:
            return ""

    def _write_token(self, token: str) -> None:
        try:
            self._token_path.parent.mkdir(parents=True, exist_ok=True)
            self._token_path.write_text(token, encoding="utf-8")
        except OSError as exc:
            log.warning("Could not save VTS token to %s: %s", self._token_path, exc)

    async def _authenticate(self) -> None:
        token = self._read_token()
        if token and await self._try_token(token):
            self.authenticated = True
            return

        log.warning(
            "Requesting a new VTube Studio API token — "
            "ACCEPT THE POPUP in VTube Studio now."
        )
        data = await self.request(
            "AuthenticationTokenRequest",
            {
                "pluginName": self.cfg.plugin_name,
                "pluginDeveloper": self.cfg.plugin_developer,
            },
            timeout=120.0,  # the popup waits on a human
        )
        token = data.get("authenticationToken", "")
        if not token:
            raise VTubeStudioError(
                "VTube Studio did not grant a token (the popup was denied or ignored)."
            )
        self._write_token(token)

        if not await self._try_token(token):
            raise VTubeStudioError("VTube Studio rejected the token it just issued.")
        self.authenticated = True

    async def _try_token(self, token: str) -> bool:
        try:
            data = await self.request(
                "AuthenticationRequest",
                {
                    "pluginName": self.cfg.plugin_name,
                    "pluginDeveloper": self.cfg.plugin_developer,
                    "authenticationToken": token,
                },
            )
        except VTubeStudioError as exc:
            log.debug("Stored token rejected: %s", exc)
            return False
        if data.get("authenticated"):
            return True
        log.debug("Token not accepted: %s", data.get("reason"))
        return False

    # -- convenience calls -------------------------------------------------

    async def api_state(self) -> dict:
        """APIStateRequest works before authentication — good for a preflight."""
        return await self.request("APIStateRequest")

    async def current_model_name(self) -> str:
        data = await self.request("CurrentModelRequest")
        if not data.get("modelLoaded"):
            return ""
        return str(data.get("modelName", ""))

    async def available_parameters(self) -> list[str]:
        data = await self.request("InputParameterListRequest")
        names = [p.get("name", "") for p in data.get("defaultParameters", [])]
        names += [p.get("name", "") for p in data.get("customParameters", [])]
        return [n for n in names if n]

    async def inject(self, values: dict[str, float]) -> None:
        """Set input parameters. `mode: set` overrides tracking for these only."""
        await self.send_only(
            "InjectParameterDataRequest",
            {
                "faceFound": self.cfg.face_found,
                "mode": "set",
                "parameterValues": [
                    {"id": name, "value": float(value), "weight": self.cfg.weight}
                    for name, value in values.items()
                ],
            },
        )

    async def set_mouth(self, mouth_open: float, mouth_form: float = 0.0) -> None:
        values = {self.cfg.mouth_open_param: mouth_open}
        if self.cfg.mouth_form_param:
            values[self.cfg.mouth_form_param] = mouth_form
        await self.inject(values)
