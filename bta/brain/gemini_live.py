"""Gemini Multimodal Live API session, producing native streaming audio.

Two things make this more than a thin wrapper:

* Live sessions are time-limited and the server sends GoAway before dropping
  us. We keep a session-resumption handle so a reconnect continues the same
  conversation instead of resetting the persona mid-stream.
* The Live API model IDs are preview names that Google rotates. We try a list
  and remember whichever one connects.
"""

from __future__ import annotations

import asyncio
import contextlib
import logging
from dataclasses import dataclass
from typing import Callable

from google import genai
from google.genai import types

from bta.brain.persona import build_system_instruction
from bta.config import Config
from bta.log import get_logger

log = get_logger("brain.gemini")

# Native-audio models only accept a single response modality; the spoken text
# comes back separately via output_audio_transcription.
RESPONSE_MODALITIES = ["AUDIO"]

# Substrings that mark a failure no amount of retrying will fix.
_FATAL_MARKERS = (
    "api key not valid",
    "api_key_invalid",
    "invalid authentication",
    "permission denied",
    "unauthenticated",
    "consumer_suspended",
    "billing",
)


# The categories a live chat audience will actually probe for.
#
# These only reach the wire on Vertex AI. The Gemini Developer API (the
# api_key path this app uses) has no safetySettings field in its
# BidiGenerateContent setup message and rejects the whole payload if one is
# sent -- see _live_config. Provider-side filtering still applies there at
# Google's own default posture; it just cannot be configured from here, which
# is why the inbound guard, the persona rules and the output cut in
# bta/safety.py are the defences that actually carry the stream.
_GUARDED_HARM_CATEGORIES = (
    "HARM_CATEGORY_HARASSMENT",
    "HARM_CATEGORY_HATE_SPEECH",
    "HARM_CATEGORY_SEXUALLY_EXPLICIT",
    "HARM_CATEGORY_DANGEROUS_CONTENT",
)


def _safety_settings(threshold: str) -> list[types.SafetySetting]:
    return [
        types.SafetySetting(category=category, threshold=threshold)
        for category in _GUARDED_HARM_CATEGORIES
    ]


class BrainAuthError(RuntimeError):
    """The API key or project is rejected — retrying cannot help."""


def _is_fatal(exc: object) -> bool:
    # Google reports these as both "PERMISSION_DENIED" and "permission denied"
    # depending on the transport, so compare with separators normalized.
    text = str(exc).lower().replace("_", " ")
    return any(marker.replace("_", " ") in text for marker in _FATAL_MARKERS)


@dataclass(slots=True)
class BrainCallbacks:
    """Hooks the pipeline supplies. All are called from the event loop."""

    on_audio: Callable[[bytes], None]
    on_text: Callable[[str], None] = lambda _text: None
    on_turn_start: Callable[[], None] = lambda: None
    on_turn_complete: Callable[[], None] = lambda: None
    on_interrupted: Callable[[], None] = lambda: None
    on_ready: Callable[[str], None] = lambda _model: None


class GeminiLiveBrain:
    """Owns the Live API websocket and turns prompts into speech."""

    def __init__(self, cfg: Config, callbacks: BrainCallbacks) -> None:
        self.cfg = cfg
        self.callbacks = callbacks
        self._client = genai.Client(api_key=cfg.gemini.api_key)
        self._outbox: asyncio.Queue[str] = asyncio.Queue(maxsize=8)
        self._stop = asyncio.Event()
        self._resumption_handle: str | None = None
        self._model: str = ""
        self.speaking = False
        self.connected = False
        self.turns_completed = 0
        self.fatal_error = ""

    # -- public API --------------------------------------------------------

    @property
    def model(self) -> str:
        return self._model

    @property
    def busy(self) -> bool:
        """True while the model is producing a turn; the director waits on this."""
        return self.speaking or not self._outbox.empty()

    def say(self, prompt: str) -> bool:
        """Queue a prompt. Returns False if the outbox is saturated."""
        try:
            self._outbox.put_nowait(prompt)
            return True
        except asyncio.QueueFull:
            log.warning("Brain outbox full; dropping prompt")
            return False

    def stop(self) -> None:
        self._stop.set()

    # -- session config ----------------------------------------------------

    def _live_config(self) -> types.LiveConnectConfig:
        gem = self.cfg.gemini
        kwargs: dict = {
            "response_modalities": RESPONSE_MODALITIES,
            "system_instruction": build_system_instruction(gem),
            "speech_config": types.SpeechConfig(
                voice_config=types.VoiceConfig(
                    prebuilt_voice_config=types.PrebuiltVoiceConfig(voice_name=gem.voice)
                ),
                language_code=gem.language_code,
            ),
            "output_audio_transcription": types.AudioTranscriptionConfig(),
            "session_resumption": types.SessionResumptionConfig(
                handle=self._resumption_handle
            ),
            # A stream runs for hours; without compression we would hit the
            # context limit and the session would be torn down.
            "context_window_compression": types.ContextWindowCompressionConfig(
                sliding_window=types.SlidingWindow()
            ),
            "temperature": gem.temperature,
        }
        # The SDK models safety_settings on LiveConnectConfig, but the
        # Developer API's setup message has no such field: sending it closes
        # the socket with 1007 'Unknown name "safetySettings" at setup' before
        # the API key is even validated, so every model in the fallback list
        # fails identically and the streamer never connects. Vertex AI does
        # accept it, so it goes out only there.
        if self._client.vertexai:
            kwargs["safety_settings"] = _safety_settings(
                self.cfg.safety.harm_block_threshold
            )
        if gem.affective_dialog:
            kwargs["enable_affective_dialog"] = True
        if gem.proactivity:
            kwargs["proactivity"] = types.ProactivityConfig(proactive_audio=True)
        return types.LiveConnectConfig(**kwargs)

    # -- main loop ---------------------------------------------------------

    async def run(self) -> None:
        """Keep a Live session up until stop() is called."""
        backoff = 1.0
        while not self._stop.is_set():
            try:
                await self._session_once()
                backoff = 1.0  # clean end (GoAway); reconnect immediately
            except asyncio.CancelledError:
                raise
            except BrainAuthError as exc:
                self.connected = False
                self.fatal_error = str(exc)
                log.error("%s", exc)
                self._stop.set()
                return
            except Exception as exc:
                self.connected = False
                log.error("Gemini Live session failed: %s", exc)
                log.info("Reconnecting in %.0fs", backoff)
                with contextlib.suppress(asyncio.TimeoutError):
                    await asyncio.wait_for(self._stop.wait(), timeout=backoff)
                backoff = min(backoff * 2, 30.0)

    async def _connect(self):
        """Open a session, falling through the model candidates."""
        models = list(self.cfg.models)
        # Once a model works, stick with it rather than re-probing every time.
        if self._model:
            models = [self._model] + [m for m in models if m != self._model]

        last_error: Exception | None = None
        for model in models:
            try:
                manager = self._client.aio.live.connect(
                    model=model, config=self._live_config()
                )
                session = await manager.__aenter__()
            except Exception as exc:
                last_error = exc
                if _is_fatal(exc):
                    # A rejected key fails identically on every model; there is
                    # no point walking the rest of the list.
                    raise BrainAuthError(
                        f"Gemini rejected the API key: {_short(exc)}\n"
                        "Check GEMINI_API_KEY in your .env "
                        "(get one at https://aistudio.google.com/apikey)."
                    ) from exc
                # Expected while probing preview model names; keep it quiet
                # after the first successful connection.
                log.log(
                    logging.DEBUG if self._model else logging.WARNING,
                    "Model %s unavailable: %s",
                    model,
                    _short(exc),
                )
                continue
            if self._model != model:
                log.info("Using Gemini Live model: %s", model)
            self._model = model
            return manager, session

        detail = f" Last error: {_short(last_error)}" if last_error else ""
        raise RuntimeError(
            f"No Gemini Live model could be reached. Tried: {', '.join(models)}.{detail}"
        )

    async def _session_once(self) -> None:
        manager, session = await self._connect()
        self.connected = True
        self.callbacks.on_ready(self._model)
        sender = asyncio.create_task(self._send_loop(session), name="brain-send")
        try:
            await self._receive_loop(session)
        finally:
            self.connected = False
            self.speaking = False
            sender.cancel()
            with contextlib.suppress(asyncio.CancelledError, Exception):
                await sender
            with contextlib.suppress(Exception):
                await manager.__aexit__(None, None, None)

    async def _send_loop(self, session) -> None:
        while True:
            prompt = await self._outbox.get()
            log.debug("-> %s", prompt.replace("\n", " | ")[:200])
            await session.send_client_content(
                turns=types.Content(role="user", parts=[types.Part(text=prompt)]),
                turn_complete=True,
            )

    async def _receive_loop(self, session) -> None:
        async for message in session.receive():
            if self._stop.is_set():
                return

            if message.session_resumption_update is not None:
                update = message.session_resumption_update
                if update.resumable and update.new_handle:
                    self._resumption_handle = update.new_handle

            if message.go_away is not None:
                # The server is about to close. Return cleanly so run()
                # reconnects at once using the resumption handle.
                log.info(
                    "Live session expiring in %s; reconnecting",
                    getattr(message.go_away, "time_left", "a moment"),
                )
                return

            content = message.server_content
            if content is None:
                continue

            if content.interrupted:
                self.speaking = False
                self.callbacks.on_interrupted()
                continue

            if content.model_turn is not None:
                for part in content.model_turn.parts or []:
                    blob = part.inline_data
                    if blob is not None and blob.data:
                        if not self.speaking:
                            self.speaking = True
                            self.callbacks.on_turn_start()
                        self.callbacks.on_audio(blob.data)
                    if part.text:
                        self.callbacks.on_text(part.text)

            if content.output_transcription is not None:
                text = content.output_transcription.text
                if text:
                    self.callbacks.on_text(text)

            if content.turn_complete:
                self.speaking = False
                self.turns_completed += 1
                self.callbacks.on_turn_complete()


def _short(exc: object, limit: int = 200) -> str:
    text = str(exc).replace("\n", " ")
    return text[:limit] + ("..." if len(text) > limit else "")
