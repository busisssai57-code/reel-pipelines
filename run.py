#!/usr/bin/env python3
"""BTA — automated AI TikTok Live streamer.

    python run.py                 # go live against TIKTOK_HANDLE
    python run.py --console       # rehearse with typed chat, no TikTok needed
    python run.py --check         # preflight: verify config and connections
    python run.py --list-devices  # show audio output devices
"""

from __future__ import annotations

import argparse
import asyncio
import contextlib
import signal
import sys

from bta.config import ConfigError, load_config, normalize_handle
from bta.log import get_logger, setup_logging

log = get_logger("run")


def parse_args(argv: list[str] | None = None) -> argparse.Namespace:
    parser = argparse.ArgumentParser(
        prog="run.py", description="Automated AI TikTok Live streamer"
    )
    parser.add_argument(
        "--console",
        action="store_true",
        help="read chat from stdin instead of TikTok (for testing)",
    )
    parser.add_argument(
        "--check", action="store_true", help="run preflight checks and exit"
    )
    parser.add_argument(
        "--list-devices", action="store_true", help="list audio output devices and exit"
    )
    parser.add_argument("--handle", default="", help="override TIKTOK_HANDLE")
    parser.add_argument("--voice", default="", help="override GEMINI_VOICE")
    parser.add_argument("--env", default=".env", help="path to the .env file")
    parser.add_argument("--log-level", default="", help="DEBUG, INFO, WARNING, ERROR")
    parser.add_argument(
        "--no-vts", action="store_true", help="run without VTube Studio"
    )
    return parser.parse_args(argv)


def list_devices() -> int:
    try:
        from bta.audio.sink import DeviceSink

        print(DeviceSink.list_devices())
        return 0
    except Exception as exc:
        print(f"Could not list audio devices: {exc}", file=sys.stderr)
        print(
            "Install PortAudio (macOS: brew install portaudio, "
            "Debian/Ubuntu: sudo apt install libportaudio2) and `pip install sounddevice`.",
            file=sys.stderr,
        )
        return 1


async def _run(args: argparse.Namespace) -> int:
    from bta.pipeline import Pipeline

    cfg = load_config(args.env)
    if args.handle:
        cfg.tiktok.handle = normalize_handle(args.handle)
    if args.voice:
        cfg.gemini.voice = args.voice
    if args.no_vts:
        cfg.vtube.enabled = False
    if args.log_level:
        cfg.log_level = args.log_level.upper()
    setup_logging(cfg.log_level)

    try:
        cfg.validate(require_tiktok=not args.console)
    except ConfigError as exc:
        print(str(exc), file=sys.stderr)
        return 2

    pipeline = Pipeline(cfg, use_console_source=args.console)

    loop = asyncio.get_running_loop()
    for signal_name in ("SIGINT", "SIGTERM"):
        with contextlib.suppress(AttributeError, NotImplementedError):
            loop.add_signal_handler(
                getattr(signal, signal_name),
                lambda: asyncio.create_task(pipeline.shutdown()),
            )

    try:
        await pipeline.run()
    except KeyboardInterrupt:
        await pipeline.shutdown()
    return 0


def main(argv: list[str] | None = None) -> int:
    args = parse_args(argv)
    setup_logging(args.log_level or "INFO")

    if args.list_devices:
        return list_devices()

    if args.check:
        from tools.check import run_preflight

        return asyncio.run(
            run_preflight(
                args.env,
                console=args.console,
                no_vts=args.no_vts,
                handle=args.handle,
                voice=args.voice,
            )
        )

    try:
        return asyncio.run(_run(args))
    except KeyboardInterrupt:
        return 130


if __name__ == "__main__":
    sys.exit(main())
