"""Preflight: verify configuration and every external connection.

Run this before going live — it is much cheaper to find a bad API key or a
closed VTube Studio API here than thirty seconds into a stream.

    python run.py --check
"""

from __future__ import annotations

import asyncio
import contextlib

from bta.config import Config, ConfigError, load_config
from bta.log import get_logger, setup_logging

log = get_logger("check")

PASS, FAIL, WARN = "PASS", "FAIL", "WARN"


class Report:
    def __init__(self) -> None:
        self.rows: list[tuple[str, str, str]] = []

    def add(self, status: str, name: str, detail: str = "") -> None:
        self.rows.append((status, name, detail))
        marker = {PASS: "  ok  ", FAIL: " FAIL ", WARN: " warn "}[status]
        print(f"[{marker}] {name}" + (f"\n           {detail}" if detail else ""))

    @property
    def failed(self) -> bool:
        return any(status == FAIL for status, _, _ in self.rows)


async def check_vtube(cfg: Config, report: Report) -> None:
    if not cfg.vtube.enabled:
        report.add(WARN, "VTube Studio", "disabled (VTS_ENABLED=false)")
        return

    from bta.avatar.vtube import VTubeStudioClient, VTubeStudioError

    client = VTubeStudioClient(cfg.vtube)
    try:
        await client.connect(timeout=8.0)
    except VTubeStudioError as exc:
        report.add(
            FAIL if cfg.vtube.required else WARN,
            f"VTube Studio at {cfg.vtube.url}",
            str(exc),
        )
        return

    try:
        model = client.model_name or "(no model loaded)"
        report.add(PASS, f"VTube Studio at {cfg.vtube.url}", f"model: {model}")

        parameters = await client.available_parameters()
        for label, name in (
            ("mouth open", cfg.vtube.mouth_open_param),
            ("mouth form", cfg.vtube.mouth_form_param),
        ):
            if not name:
                continue
            if name in parameters:
                report.add(PASS, f"VTS {label} parameter '{name}'")
            else:
                report.add(
                    WARN,
                    f"VTS {label} parameter '{name}' not found",
                    "Available: " + ", ".join(parameters[:12]),
                )

        # Visible proof the link works: open and close the avatar's mouth.
        print("           (watch the avatar — its mouth should move now)")
        for _ in range(2):
            for value in (0.0, 0.4, 0.9, 0.4, 0.0):
                await client.set_mouth(value, value * 0.5)
                await asyncio.sleep(0.08)
        report.add(PASS, "VTS parameter injection")
    finally:
        with contextlib.suppress(Exception):
            await client.close()


async def check_gemini(cfg: Config, report: Report) -> None:
    if not cfg.gemini.api_key:
        report.add(FAIL, "Gemini API key", "GEMINI_API_KEY is not set")
        return

    from google import genai
    from google.genai import types

    from bta.brain.gemini_live import GeminiLiveBrain, BrainCallbacks

    brain = GeminiLiveBrain(cfg, BrainCallbacks(on_audio=lambda _pcm: None))
    live_config = brain._live_config()
    client = genai.Client(api_key=cfg.gemini.api_key)

    errors: list[str] = []
    for model in cfg.models:
        try:
            async with client.aio.live.connect(model=model, config=live_config) as session:
                await session.send_client_content(
                    turns=types.Content(
                        role="user",
                        parts=[types.Part(text="Say the single word: ready.")],
                    ),
                    turn_complete=True,
                )
                audio_bytes = 0
                transcript = ""
                async for message in session.receive():
                    content = message.server_content
                    if content is None:
                        continue
                    if content.model_turn is not None:
                        for part in content.model_turn.parts or []:
                            if part.inline_data and part.inline_data.data:
                                audio_bytes += len(part.inline_data.data)
                    if content.output_transcription is not None:
                        transcript += content.output_transcription.text or ""
                    if content.turn_complete:
                        break

            if audio_bytes:
                report.add(
                    PASS,
                    f"Gemini Live model '{model}'",
                    f"received {audio_bytes} bytes of audio"
                    + (f" — said: {transcript.strip()}" if transcript.strip() else ""),
                )
            else:
                report.add(WARN, f"Gemini Live model '{model}'", "connected but sent no audio")
            return
        except Exception as exc:
            detail = str(exc).replace("\n", " ")[:160]
            errors.append(f"{model}: {detail}")
            log.debug("Model %s failed: %s", model, exc)

    report.add(
        FAIL,
        "Gemini Live API",
        "No model could be reached.\n           " + "\n           ".join(errors),
    )


async def check_tiktok(cfg: Config, report: Report, *, console: bool) -> None:
    if console:
        report.add(WARN, "TikTok", "skipped (--console mode)")
        return
    if not cfg.tiktok.handle:
        report.add(FAIL, "TikTok handle", "TIKTOK_HANDLE is not set")
        return

    from bta.sources.tiktok import TikTokSource

    source = TikTokSource(cfg.tiktok, lambda _message: None)
    try:
        # Call the client directly rather than TikTokSource.is_live(), which
        # deliberately swallows errors so the run loop can keep retrying. Here
        # we need to tell "offline" apart from "cannot reach TikTok at all".
        live = await asyncio.wait_for(source.client.is_live(), timeout=25.0)
    except asyncio.TimeoutError:
        report.add(FAIL, f"TikTok {cfg.tiktok.handle}", "timed out reaching TikTok")
        return
    except Exception as exc:
        report.add(
            FAIL,
            f"TikTok {cfg.tiktok.handle}",
            f"could not reach TikTok: {type(exc).__name__}: {str(exc)[:120]}\n"
            "           Check your internet connection, VPN, or whether the "
            "handle exists.",
        )
        return
    if live:
        report.add(PASS, f"TikTok {cfg.tiktok.handle}", "is live right now")
    else:
        report.add(
            WARN,
            f"TikTok {cfg.tiktok.handle}",
            "not live — the streamer will wait and connect when it goes live",
        )


def check_commerce(cfg: Config, report: Report) -> None:
    if not cfg.commerce.enabled:
        return
    commerce = cfg.commerce

    if not commerce.stock:
        report.add(
            WARN, "Commerce", "enabled but COMMERCE_STOCK is empty — nothing can sell"
        )
        return

    total = sum(commerce.stock.values())
    report.add(
        PASS,
        "Commerce stock",
        f"{len(commerce.stock)} sku(s), {total} unit(s): "
        + ", ".join(f"{sku} x{count}" for sku, count in sorted(commerce.stock.items())),
    )

    # Variants live in the sku string, so show the operator exactly which
    # fully-specified product each gift claims.
    if commerce.gift_skus:
        report.add(
            PASS,
            "Commerce gift mapping",
            "; ".join(
                f"{gift} -> {sku}" for gift, sku in sorted(commerce.gift_skus.items())
            ),
        )
    else:
        report.add(
            WARN,
            "Commerce gift mapping",
            "no COMMERCE_GIFT_SKUS set — gifts will never place an order",
        )

    unnamed = commerce.unnamed_skus()
    if unnamed and commerce.announce_orders:
        report.add(
            WARN,
            "Commerce spoken names",
            f"no COMMERCE_SKU_NAMES for: {', '.join(unnamed)} — these get read "
            "out as-is on stream",
        )

    if not commerce.auto_fulfill_gifts:
        report.add(
            WARN,
            "Commerce fulfillment",
            "COMMERCE_AUTO_FULFILL_GIFTS is off — gift orders stay RESERVED and "
            "something must fulfil or cancel them, or stock is held forever",
        )
    report.add(
        PASS,
        "Commerce end-of-stream policy",
        "held stock is released when the broadcast ends"
        if commerce.release_holds_on_end
        else "buyers keep reserved stock after the broadcast ends",
    )


def check_audio(cfg: Config, report: Report) -> None:
    from bta.audio.sink import build_sink

    sink = build_sink(cfg.audio)
    try:
        if sink.name == "device":
            report.add(PASS, "Audio output", f"device sink ({cfg.audio.device or 'default'})")
        elif cfg.audio.sink == "device":
            report.add(
                WARN,
                "Audio output",
                f"requested a device but fell back to '{sink.name}' — "
                "viewers will not hear anything. Check `python run.py --list-devices`.",
            )
        else:
            report.add(PASS, "Audio output", f"{sink.name} sink")
    finally:
        sink.close()


async def run_preflight(
    env_file: str = ".env",
    *,
    console: bool = False,
    no_vts: bool = False,
    handle: str = "",
    voice: str = "",
) -> int:
    """Check the same configuration `run.py` would actually use."""
    try:
        cfg = load_config(env_file)
    except ConfigError as exc:
        print(str(exc))
        return 2

    # Mirror the command-line overrides, so --check reflects the real run.
    if handle:
        from bta.config import normalize_handle

        cfg.tiktok.handle = normalize_handle(handle)
    if voice:
        cfg.gemini.voice = voice
    if no_vts:
        cfg.vtube.enabled = False
    setup_logging(cfg.log_level)

    print("\nBTA preflight\n" + "=" * 60)
    report = Report()

    try:
        cfg.validate(require_tiktok=not console)
        report.add(PASS, "Configuration")
    except ConfigError as exc:
        report.add(FAIL, "Configuration", str(exc))

    check_audio(cfg, report)
    check_commerce(cfg, report)
    await check_tiktok(cfg, report, console=console)
    await check_vtube(cfg, report)
    if cfg.gemini.api_key:
        await check_gemini(cfg, report)

    print("=" * 60)
    if report.failed:
        print("Preflight FAILED — fix the items above before going live.\n")
        return 1
    print("Preflight passed. You are ready to stream.\n")
    return 0


if __name__ == "__main__":
    import sys

    sys.exit(asyncio.run(run_preflight()))
