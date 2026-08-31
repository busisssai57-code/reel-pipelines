"""Wires the pipeline together and supervises its tasks.

    TikTok chat -> Director -> Gemini Live -> SpeechPlayer -> audio device
                                                   |
                                                   +-------> VTube Studio
"""

from __future__ import annotations

import asyncio
import contextlib
import time

from bta.audio.player import SpeechPlayer
from bta.audio.sink import build_sink
from bta.avatar.vtube import VTubeStudioClient, VTubeStudioError
from bta.brain.gemini_live import BrainCallbacks, GeminiLiveBrain
from bta.config import Config
from bta.director import Director
from bta.events import ChatMessage
from bta.log import get_logger

log = get_logger("pipeline")

# Keep injecting a shut mouth for this long after speech ends, so the closing
# frames definitely land, before handing the model back to face tracking.
CLOSED_HOLD_SECONDS = 0.5


class Pipeline:
    """Owns every long-running task and shuts them all down together."""

    def __init__(self, cfg: Config, *, use_console_source: bool = False) -> None:
        self.cfg = cfg
        self.use_console_source = use_console_source

        self.director = Director(cfg.director, persona_name=cfg.gemini.persona_name)
        self.sink = build_sink(cfg.audio)
        self.player = SpeechPlayer(
            self.sink,
            frame_ms=cfg.audio.frame_ms,
            gain=cfg.audio.gain,
            lipsync_delay_ms=cfg.audio.lipsync_delay_ms,
        )
        self.brain = GeminiLiveBrain(cfg, self._callbacks())
        self.vts: VTubeStudioClient | None = (
            VTubeStudioClient(cfg.vtube) if cfg.vtube.enabled else None
        )
        self.source: object | None = None

        self._stop = asyncio.Event()
        self._tasks: list[asyncio.Task] = []
        self._transcript = ""
        self.started_at = time.monotonic()

    # -- brain callbacks ---------------------------------------------------

    def _callbacks(self) -> BrainCallbacks:
        return BrainCallbacks(
            on_audio=self.player.feed,
            on_text=self._on_text,
            on_turn_start=lambda: log.debug("Speaking..."),
            on_turn_complete=self._on_turn_complete,
            on_interrupted=self._on_interrupted,
            on_ready=lambda model: log.info("Brain ready on %s", model),
        )

    def _on_text(self, text: str) -> None:
        self._transcript += text

    def _on_turn_complete(self) -> None:
        line = " ".join(self._transcript.split())
        self._transcript = ""
        if line:
            log.info("%s: %s", self.cfg.gemini.persona_name, line)

    def _on_interrupted(self) -> None:
        self._transcript = ""
        self.player.interrupt()

    def _on_chat(self, message: ChatMessage) -> None:
        if self.director.accept(message):
            log.info("chat  %s", message.render())

    # -- tasks -------------------------------------------------------------

    async def _director_loop(self) -> None:
        """Feed the brain one turn at a time, only while it is idle."""
        while not self._stop.is_set():
            await asyncio.sleep(0.25)
            if self.brain.busy or not self.brain.connected:
                continue
            # Do not start a new turn while the previous one is still audible.
            if self.player.speaking or self.player.pending_seconds > 0.15:
                continue
            prompt = self.director.next_prompt()
            if prompt:
                self.brain.say(prompt)

    async def _avatar_loop(self) -> None:
        """Stream mouth values to VTube Studio, reconnecting if it goes away."""
        if self.vts is None:
            return
        interval = 1.0 / max(1, self.cfg.vtube.inject_fps)
        backoff = 2.0

        while not self._stop.is_set():
            try:
                if not self.vts.connected:
                    await self.vts.connect()
                    backoff = 2.0

                closed_since: float | None = None
                while not self._stop.is_set():
                    open_value = self.player.mouth_open
                    now = time.monotonic()

                    if open_value == 0.0:
                        if closed_since is None:
                            closed_since = now
                        elif now - closed_since > CLOSED_HOLD_SECONDS:
                            # The mouth has been shut for a while. Stop
                            # injecting so VTube Studio's own face tracking
                            # takes the model back over until we speak again.
                            await asyncio.sleep(interval)
                            continue
                    else:
                        closed_since = None

                    await self.vts.set_mouth(open_value, self.player.mouth_form)
                    await asyncio.sleep(interval)

            except asyncio.CancelledError:
                raise
            except (VTubeStudioError, OSError) as exc:
                await self.vts.close()
                if self.cfg.vtube.required:
                    log.error("VTube Studio unavailable and VTS_REQUIRED=true: %s", exc)
                    self._stop.set()
                    return
                log.warning("VTube Studio: %s — retrying in %.0fs", exc, backoff)
                await self._sleep(backoff)
                backoff = min(backoff * 2, 30.0)

    async def _status_loop(self, every: float = 60.0) -> None:
        while not self._stop.is_set():
            await self._sleep(every)
            if self._stop.is_set():
                return
            log.info(
                "status: up %.0fm | chat accepted %d rejected %d queued %d | "
                "turns %d | brain %s | vts %s",
                (time.monotonic() - self.started_at) / 60,
                self.director.accepted,
                self.director.rejected,
                self.director.pending,
                self.brain.turns_completed,
                "up" if self.brain.connected else "down",
                "up" if (self.vts and self.vts.connected) else "off",
            )

    async def _sleep(self, seconds: float) -> None:
        with contextlib.suppress(asyncio.TimeoutError):
            await asyncio.wait_for(self._stop.wait(), timeout=seconds)

    # -- lifecycle ---------------------------------------------------------

    def _build_source(self):
        if self.use_console_source:
            from bta.sources.console import ConsoleSource

            return ConsoleSource(self._on_chat)
        from bta.sources.tiktok import TikTokSource

        return TikTokSource(self.cfg.tiktok, self._on_chat)

    async def run(self) -> None:
        log.info("Starting BTA streamer as '%s'", self.cfg.gemini.persona_name)
        self.player.start()
        self.source = self._build_source()

        self._tasks = [
            asyncio.create_task(self.brain.run(), name="brain"),
            asyncio.create_task(self.source.run(), name="source"),
            asyncio.create_task(self._director_loop(), name="director"),
            asyncio.create_task(self._status_loop(), name="status"),
        ]
        if self.vts is not None:
            self._tasks.append(asyncio.create_task(self._avatar_loop(), name="avatar"))

        try:
            # If any task dies the stream is broken; surface it and shut down.
            done, _ = await asyncio.wait(
                self._tasks, return_when=asyncio.FIRST_COMPLETED
            )
            for task in done:
                if task.cancelled():
                    continue
                exc = task.exception()
                if exc is not None:
                    log.error("Task %s failed: %s", task.get_name(), exc)
                elif task.get_name() == "brain" and self.brain.fatal_error:
                    log.error("Cannot continue: %s", self.brain.fatal_error)
                else:
                    log.info("Task %s finished; shutting down", task.get_name())
        finally:
            await self.shutdown()

    async def shutdown(self) -> None:
        if self._stop.is_set():
            return
        log.info("Shutting down...")
        self._stop.set()
        self.brain.stop()

        source = self.source
        if source is not None and hasattr(source, "stop"):
            with contextlib.suppress(Exception):
                await source.stop()

        for task in self._tasks:
            task.cancel()
        for task in self._tasks:
            with contextlib.suppress(asyncio.CancelledError, Exception):
                await task
        self._tasks.clear()

        if self.vts is not None:
            with contextlib.suppress(Exception):
                await self.vts.set_mouth(0.0, 0.0)
                await self.vts.close()

        self.player.stop()
        log.info(
            "Stopped. %d turns spoken, %d chat messages used.",
            self.brain.turns_completed,
            self.director.accepted,
        )
