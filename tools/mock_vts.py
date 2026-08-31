"""A stand-in VTube Studio API server.

Implements enough of the real protocol (token issue, authentication, model
query, parameter injection) to exercise the client end-to-end without the
desktop app. Run it standalone to try the pipeline on a machine that has no
VTube Studio:

    python -m tools.mock_vts --port 8001
"""

from __future__ import annotations

import argparse
import asyncio
import json
import uuid

import websockets
from websockets.asyncio.server import ServerConnection, serve

API_NAME = "VTubeStudioPublicAPI"
API_VERSION = "1.0"

DEFAULT_PARAMETERS = [
    "FaceFound",
    "MouthOpen",
    "MouthSmile",
    "MouthX",
    "EyeOpenLeft",
    "EyeOpenRight",
    "FaceAngleX",
    "FaceAngleY",
    "FaceAngleZ",
]


class MockVTubeStudio:
    """Records what the client sent so tests can assert on it."""

    def __init__(
        self,
        *,
        model_name: str = "MockChan",
        auto_grant: bool = True,
        deny_token: bool = False,
    ) -> None:
        self.model_name = model_name
        self.auto_grant = auto_grant
        self.deny_token = deny_token

        self.issued_tokens: set[str] = set()
        self.authenticated_plugins: list[str] = []
        self.injections: list[dict] = []
        self.last_parameters: dict[str, float] = {}
        self.request_types: list[str] = []
        self._server: object | None = None
        self.port: int = 0

    # -- protocol ----------------------------------------------------------

    def _reply(self, request: dict, message_type: str, data: dict) -> str:
        return json.dumps(
            {
                "apiName": API_NAME,
                "apiVersion": API_VERSION,
                "timestamp": 0,
                "requestID": request.get("requestID", ""),
                "messageType": message_type,
                "data": data,
            }
        )

    def _error(self, request: dict, error_id: int, message: str) -> str:
        return self._reply(request, "APIError", {"errorID": error_id, "message": message})

    def handle_message(self, request: dict) -> str | None:
        message_type = request.get("messageType", "")
        self.request_types.append(message_type)
        data = request.get("data") or {}

        if request.get("apiName") != API_NAME:
            return self._error(request, 1, "Invalid apiName")

        if message_type == "APIStateRequest":
            return self._reply(
                request,
                "APIStateResponse",
                {
                    "active": True,
                    "vTubeStudioVersion": "1.28.0",
                    "currentSessionAuthenticated": bool(self.authenticated_plugins),
                },
            )

        if message_type == "AuthenticationTokenRequest":
            if not self.auto_grant:
                return self._error(request, 50, "User denied the plugin request")
            token = uuid.uuid4().hex
            self.issued_tokens.add(token)
            return self._reply(
                request, "AuthenticationTokenResponse", {"authenticationToken": token}
            )

        if message_type == "AuthenticationRequest":
            token = data.get("authenticationToken", "")
            ok = (not self.deny_token) and token in self.issued_tokens
            if ok:
                self.authenticated_plugins.append(data.get("pluginName", ""))
            return self._reply(
                request,
                "AuthenticationResponse",
                {
                    "authenticated": ok,
                    "reason": "" if ok else "Token invalid or expired",
                },
            )

        if not self.authenticated_plugins and message_type != "APIStateRequest":
            return self._error(request, 8, "Not authenticated")

        if message_type == "CurrentModelRequest":
            return self._reply(
                request,
                "CurrentModelResponse",
                {
                    "modelLoaded": bool(self.model_name),
                    "modelName": self.model_name,
                    "modelID": "mock-model-id",
                },
            )

        if message_type == "InputParameterListRequest":
            return self._reply(
                request,
                "InputParameterListResponse",
                {
                    "modelLoaded": True,
                    "modelName": self.model_name,
                    "defaultParameters": [
                        {"name": name, "value": 0.0, "min": 0.0, "max": 1.0}
                        for name in DEFAULT_PARAMETERS
                    ],
                    "customParameters": [],
                },
            )

        if message_type == "InjectParameterDataRequest":
            self.injections.append(data)
            for entry in data.get("parameterValues", []):
                self.last_parameters[entry.get("id", "")] = float(entry.get("value", 0.0))
            # The real API acknowledges, but the client does not wait for it.
            return self._reply(request, "InjectParameterDataResponse", {})

        return self._error(request, 100, f"Unknown request type {message_type}")

    async def _handler(self, connection: ServerConnection) -> None:
        try:
            async for raw in connection:
                try:
                    request = json.loads(raw)
                except json.JSONDecodeError:
                    continue
                reply = self.handle_message(request)
                if reply is not None:
                    await connection.send(reply)
        except websockets.WebSocketException:
            pass

    # -- lifecycle ---------------------------------------------------------

    async def start(self, host: str = "127.0.0.1", port: int = 0) -> int:
        """Start serving; returns the bound port (useful when port=0)."""
        server = await serve(self._handler, host, port)
        self._server = server
        self.port = server.sockets[0].getsockname()[1]
        return self.port

    async def stop(self) -> None:
        server = self._server
        self._server = None
        if server is not None:
            server.close()
            await server.wait_closed()

    @property
    def url(self) -> str:
        return f"ws://127.0.0.1:{self.port}"


async def _main() -> None:
    parser = argparse.ArgumentParser(description="Mock VTube Studio API server")
    parser.add_argument("--host", default="127.0.0.1")
    parser.add_argument("--port", type=int, default=8001)
    parser.add_argument("--model", default="MockChan")
    parser.add_argument(
        "--verbose", action="store_true", help="print every injected mouth value"
    )
    args = parser.parse_args()

    mock = MockVTubeStudio(model_name=args.model)
    port = await mock.start(args.host, args.port)
    print(f"Mock VTube Studio listening on ws://{args.host}:{port}")

    if args.verbose:
        seen = 0
        while True:
            await asyncio.sleep(1.0)
            if len(mock.injections) != seen:
                seen = len(mock.injections)
                print(f"injections={seen} last={mock.last_parameters}")
    else:
        await asyncio.Future()


if __name__ == "__main__":
    try:
        asyncio.run(_main())
    except KeyboardInterrupt:
        pass
