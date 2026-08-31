from __future__ import annotations

import math
import struct
import sys
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parent.parent
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from bta.config import OUTPUT_SAMPLE_RATE  # noqa: E402


def tone(seconds: float, amplitude: float = 0.8, frequency: float = 140.0) -> bytes:
    """A steady 16-bit LE mono tone at the Live API's output rate."""
    frames = int(seconds * OUTPUT_SAMPLE_RATE)
    return b"".join(
        struct.pack(
            "<h",
            int(amplitude * 32767 * math.sin(2 * math.pi * frequency * i / OUTPUT_SAMPLE_RATE)),
        )
        for i in range(frames)
    )


def silence(seconds: float) -> bytes:
    return b"\x00\x00" * int(seconds * OUTPUT_SAMPLE_RATE)


@pytest.fixture
def token_file(tmp_path: Path) -> str:
    return str(tmp_path / "vts_token")
