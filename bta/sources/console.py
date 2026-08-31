"""Type chat messages by hand instead of pulling them from TikTok.

Lets you rehearse the whole brain -> audio -> avatar path without being live.
Input format is either `text` or `user: text`; prefix with `!gift`, `!follow`
or `!share` to simulate those events.
"""

from __future__ import annotations

import asyncio
import sys
from typing import Callable

from bta.events import ChatMessage, Priority
from bta.log import get_logger

log = get_logger("source.console")

Emit = Callable[[ChatMessage], None]

_KINDS = {
    "!gift": ("gift", Priority.GIFT),
    "!follow": ("follow", Priority.FOLLOW),
    "!share": ("share", Priority.SHARE),
}


def parse_line(line: str, default_user: str = "TestViewer") -> ChatMessage | None:
    line = line.strip()
    if not line:
        return None

    kind, priority = "chat", Priority.CHAT
    for token, (event_kind, event_priority) in _KINDS.items():
        if line.lower().startswith(token):
            kind, priority = event_kind, event_priority
            line = line[len(token) :].strip()
            break

    user = default_user
    if ":" in line:
        candidate, _, rest = line.partition(":")
        # Only treat it as a name if it looks like one, not a stray colon.
        if candidate and len(candidate) <= 30 and " " not in candidate.strip():
            user, line = candidate.strip(), rest.strip()

    if kind == "chat" and not line:
        return None
    if kind == "chat" and "?" in line:
        priority = Priority.QUESTION
    return ChatMessage(user=user, text=line, kind=kind, priority=priority)


class ConsoleSource:
    """Reads stdin on a worker thread and emits ChatMessages."""

    def __init__(self, emit: Emit, default_user: str = "TestViewer") -> None:
        self.emit = emit
        self.default_user = default_user
        self.connected = True
        self._stop = asyncio.Event()

    async def run(self) -> None:
        loop = asyncio.get_running_loop()
        print(
            "\nConsole chat is live. Type a message and press Enter.\n"
            "  alice: what game is this?      -> a normal chat message\n"
            "  !gift bob: sent 5x Rose        -> a gift\n"
            "  Ctrl-D to stop.\n",
            file=sys.stderr,
        )
        while not self._stop.is_set():
            try:
                line = await loop.run_in_executor(None, sys.stdin.readline)
            except Exception:
                return
            if not line:  # EOF
                log.info("Console input closed")
                return
            message = parse_line(line, self.default_user)
            if message is not None:
                self.emit(message)

    async def stop(self) -> None:
        self._stop.set()
