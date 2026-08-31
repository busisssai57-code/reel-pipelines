"""Logging setup shared by every module."""

from __future__ import annotations

import logging
import os
import sys

_CONFIGURED = False

# Libraries that are chatty at DEBUG/INFO and drown out our own lines.
_NOISY = ("websockets", "httpx", "httpcore", "google_genai", "TikTokLive", "asyncio")


class _ColorFormatter(logging.Formatter):
    COLORS = {
        "DEBUG": "\033[36m",
        "INFO": "\033[32m",
        "WARNING": "\033[33m",
        "ERROR": "\033[31m",
        "CRITICAL": "\033[1;31m",
    }
    RESET = "\033[0m"

    def __init__(self, fmt: str, color: bool) -> None:
        super().__init__(fmt, datefmt="%H:%M:%S")
        self.color = color

    def format(self, record: logging.LogRecord) -> str:
        out = super().format(record)
        if self.color:
            tint = self.COLORS.get(record.levelname)
            if tint:
                return f"{tint}{out}{self.RESET}"
        return out


def setup_logging(level: str = "INFO") -> None:
    """Configure root logging once. Safe to call repeatedly."""
    global _CONFIGURED
    if _CONFIGURED:
        return
    _CONFIGURED = True

    color = sys.stderr.isatty() and os.environ.get("NO_COLOR") is None
    handler = logging.StreamHandler(sys.stderr)
    handler.setFormatter(
        _ColorFormatter("%(asctime)s %(levelname)-7s %(name)-18s %(message)s", color)
    )

    root = logging.getLogger()
    root.handlers[:] = [handler]
    root.setLevel(getattr(logging, level.upper(), logging.INFO))

    for name in _NOISY:
        logging.getLogger(name).setLevel(logging.WARNING)


def get_logger(name: str) -> logging.Logger:
    return logging.getLogger(name)
