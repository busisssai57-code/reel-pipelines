"""VTube Studio client, exercised against the mock server."""

from __future__ import annotations

import asyncio

import pytest

from bta.avatar.vtube import VTubeStudioClient, VTubeStudioError
from bta.config import VTubeConfig
from tools.mock_vts import MockVTubeStudio


async def start_mock(**kwargs) -> MockVTubeStudio:
    mock = MockVTubeStudio(**kwargs)
    await mock.start()
    return mock


def config_for(mock: MockVTubeStudio, token_file: str) -> VTubeConfig:
    return VTubeConfig(host="127.0.0.1", port=mock.port, token_file=token_file)


async def test_handshake_issues_and_persists_token(token_file):
    mock = await start_mock()
    client = VTubeStudioClient(config_for(mock, token_file))
    try:
        await client.connect()
        assert client.authenticated
        assert client.model_name == "MockChan"
        assert mock.request_types.count("AuthenticationTokenRequest") == 1
    finally:
        await client.close()
        await mock.stop()


async def test_saved_token_is_reused_on_reconnect(token_file):
    mock = await start_mock()
    cfg = config_for(mock, token_file)
    for _ in range(3):
        client = VTubeStudioClient(cfg)
        await client.connect()
        assert client.authenticated
        await client.close()
    # Only the very first connection should have prompted the user.
    assert mock.request_types.count("AuthenticationTokenRequest") == 1
    await mock.stop()


async def test_stale_token_triggers_a_fresh_request(token_file, tmp_path):
    (tmp_path / "vts_token").write_text("not-a-real-token")
    mock = await start_mock()
    client = VTubeStudioClient(config_for(mock, str(tmp_path / "vts_token")))
    try:
        await client.connect()
        assert client.authenticated
        assert mock.request_types.count("AuthenticationTokenRequest") == 1
    finally:
        await client.close()
        await mock.stop()


async def test_denied_popup_raises(token_file):
    mock = await start_mock(auto_grant=False)
    client = VTubeStudioClient(config_for(mock, token_file))
    with pytest.raises(VTubeStudioError):
        await client.connect()
    await client.close()
    await mock.stop()


async def test_unreachable_server_raises_helpful_error(token_file):
    cfg = VTubeConfig(host="127.0.0.1", port=1, token_file=token_file)
    client = VTubeStudioClient(cfg)
    with pytest.raises(VTubeStudioError, match="Is VTube Studio running"):
        await client.connect(timeout=2.0)


async def test_injection_sends_expected_protocol(token_file):
    mock = await start_mock()
    client = VTubeStudioClient(config_for(mock, token_file))
    try:
        await client.connect()
        await client.set_mouth(0.75, 0.25)
        await asyncio.sleep(0.1)

        assert mock.injections, "no injection reached the server"
        payload = mock.injections[-1]
        assert payload["mode"] == "set"
        assert payload["faceFound"] is False
        by_id = {p["id"]: p for p in payload["parameterValues"]}
        assert by_id["MouthOpen"]["value"] == pytest.approx(0.75)
        assert by_id["MouthSmile"]["value"] == pytest.approx(0.25)
        assert by_id["MouthOpen"]["weight"] == pytest.approx(1.0)
    finally:
        await client.close()
        await mock.stop()


async def test_custom_parameter_names_are_used(token_file):
    mock = await start_mock()
    cfg = config_for(mock, token_file)
    cfg.mouth_open_param = "MyMouth"
    cfg.mouth_form_param = ""
    client = VTubeStudioClient(cfg)
    try:
        await client.connect()
        await client.set_mouth(0.5)
        await asyncio.sleep(0.1)
        ids = [p["id"] for p in mock.injections[-1]["parameterValues"]]
        assert ids == ["MyMouth"]
    finally:
        await client.close()
        await mock.stop()


async def test_high_rate_injection_does_not_back_up(token_file):
    """The reader task must keep draining acks, or memory grows unbounded."""
    mock = await start_mock()
    client = VTubeStudioClient(config_for(mock, token_file))
    try:
        await client.connect()
        for i in range(1500):
            await client.set_mouth((i % 10) / 10)
        await asyncio.sleep(0.4)

        assert len(mock.injections) >= 1400
        assert not client._pending, "requests leaked"
        # A normal request still resolves after the burst.
        assert await client.current_model_name() == "MockChan"
    finally:
        await client.close()
        await mock.stop()


async def test_available_parameters_lists_defaults(token_file):
    mock = await start_mock()
    client = VTubeStudioClient(config_for(mock, token_file))
    try:
        await client.connect()
        parameters = await client.available_parameters()
        assert "MouthOpen" in parameters
        assert "MouthSmile" in parameters
    finally:
        await client.close()
        await mock.stop()


async def test_request_after_close_raises(token_file):
    mock = await start_mock()
    client = VTubeStudioClient(config_for(mock, token_file))
    await client.connect()
    await client.close()
    with pytest.raises(VTubeStudioError):
        await client.current_model_name()
    await mock.stop()


async def test_server_disappearing_mid_stream_fails_pending(token_file):
    mock = await start_mock()
    client = VTubeStudioClient(config_for(mock, token_file))
    try:
        await client.connect()
        await mock.stop()
        with pytest.raises(VTubeStudioError):
            await client.current_model_name()
    finally:
        await client.close()
