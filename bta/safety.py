"""Content guarding for both directions of the conversation.

Two separate jobs:

* **Inbound** — drop bait before it ever reaches the model. Cheaper than
  relying on the model to refuse, and it keeps the provider's safety metrics
  clean. This is what stops a troll steering the stream.
* **Outbound** — watch what the model actually says. The Live API streams
  native audio, so there is no chance to review a full response before it
  starts playing. What we can do is watch the transcript as it arrives and cut
  playback the moment it goes wrong, which turns a sentence into a syllable.

The default term list is deliberately tight. Filtering every mild swear would
make the stream lifeless, and a boring bot is its own kind of failure — these
target the categories that actually get an API key revoked.

Operator-specific terms (slurs, competitor names, a streamer's own no-go list)
belong in a file via ``SAFETY_BLOCKLIST_FILE``, not in source control.
"""

from __future__ import annotations

import re
from dataclasses import dataclass
from pathlib import Path

from bta.log import get_logger

log = get_logger("safety")


# Attempts to reprogram the streamer. This is the actual attack: a viewer
# cannot make the model say something terrible by asking nicely, but they can
# try to convince it that the rules changed.
INJECTION_PATTERNS: tuple[re.Pattern[str], ...] = tuple(
    re.compile(pattern, re.IGNORECASE)
    for pattern in (
        r"\bignore\s+(all\s+|any\s+|your\s+|the\s+)*(previous|prior|above|earlier)\b",
        r"\bdisregard\s+(all\s+|any\s+|your\s+|the\s+)*(previous|prior|above|rules|instructions)\b",
        r"\bforget\s+(everything|all|your)\s+(you|instructions|rules|prompt)",
        r"\b(system|initial|original)\s+prompt\b",
        r"\breveal\s+(your|the)\s+(prompt|instructions|rules|system)",
        r"\brepeat\s+(your|the)\s+(prompt|instructions|system)",
        r"\bwhat\s+(are|were)\s+your\s+(instructions|rules|prompt)",
        r"\byou\s+are\s+now\b",
        r"\bfrom\s+now\s+on\s+you\b",
        r"\bpretend\s+(to\s+be|you\s+are|that\s+you)",
        r"\bact\s+as\s+(if\s+)?(a|an|the)?\s*\w*\s*(jailbroken|unfiltered|uncensored)",
        r"\b(dan|do\s+anything\s+now)\s+mode\b",
        r"\bdeveloper\s+mode\b",
        r"\bjailbr(eak|oken)\b",
        r"\bwithout\s+(any\s+)?(filters?|restrictions?|censorship|rules)",
        r"\bno\s+longer\s+bound\s+by\b",
        # Punctuation is stripped by _normalize before these run, so patterns
        # must not depend on it — "new instructions:" arrives as "new
        # instructions".
        r"\bnew\s+(instructions?|rules?|persona)\b",
        r"\byour\s+(real|true|actual)\s+(instructions|purpose|prompt)",
    )
)

# Category keywords, not a profanity list. Each is high-signal for the kind of
# content that gets a provider key pulled, and low false-positive in ordinary
# livestream chat.
DEFAULT_BLOCKED_TERMS: tuple[str, ...] = (
    # Self-harm baiting
    "kill yourself",
    "kys",
    "commit suicide",
    "how to kill myself",
    "end your life",
    # Sexual content
    "nudes",
    "nsfw",
    "porn",
    "sexually explicit",
    "send nudes",
    "onlyfans",
    # Violence and weapons instructions
    "how to make a bomb",
    "build a bomb",
    "make a pipe bomb",
    "how to make napalm",
    "3d printed gun",
    "ghost gun",
    "how to kill someone",
    # Illegal goods
    "how to make meth",
    "cook meth",
    "buy drugs",
    "child porn",
    "cp link",
    # Hate framing that is safe to name without writing slurs
    "heil hitler",
    "gas the",
    "white power",
    "racial slur",
)


@dataclass(frozen=True, slots=True)
class Verdict:
    """Why something was allowed or refused."""

    blocked: bool
    category: str = ""
    detail: str = ""

    @property
    def allowed(self) -> bool:
        return not self.blocked


ALLOWED = Verdict(blocked=False)


def load_blocklist_file(path: str) -> tuple[str, ...]:
    """Read extra terms, one per line. `#` comments and blanks are skipped."""
    if not path:
        return ()
    file = Path(path)
    if not file.is_file():
        log.warning("SAFETY_BLOCKLIST_FILE %s does not exist; ignoring", path)
        return ()
    terms = []
    for line in file.read_text(encoding="utf-8").splitlines():
        line = line.split("#", 1)[0].strip().lower()
        if line:
            terms.append(line)
    log.info("Loaded %d extra blocklist term(s) from %s", len(terms), path)
    return tuple(terms)


class ContentGuard:
    """Decides what reaches the model, and what the audience is allowed to hear."""

    def __init__(
        self,
        *,
        extra_terms: tuple[str, ...] = (),
        use_defaults: bool = True,
        block_injection: bool = True,
        guard_output: bool = True,
    ) -> None:
        terms = set(extra_terms)
        if use_defaults:
            terms.update(DEFAULT_BLOCKED_TERMS)
        self.terms = tuple(sorted(term.lower() for term in terms if term))
        self._matchers = tuple(_build_matcher(term) for term in self.terms)
        self.block_injection = block_injection
        self.guard_output = guard_output

        self.inbound_blocked = 0
        self.injection_attempts = 0
        self.outbound_blocked = 0

    # -- inbound -----------------------------------------------------------

    def check_inbound(self, text: str) -> Verdict:
        """Judge a viewer message before it is sent to the model."""
        lowered = _normalize(text)
        if not lowered:
            return ALLOWED

        if self.block_injection:
            for pattern in INJECTION_PATTERNS:
                if pattern.search(lowered):
                    self.injection_attempts += 1
                    self.inbound_blocked += 1
                    return Verdict(True, "injection", pattern.pattern)

        for term, matches in zip(self.terms, self._matchers):
            if matches(lowered):
                self.inbound_blocked += 1
                return Verdict(True, "blocked_term", term)
        return ALLOWED

    # -- outbound ----------------------------------------------------------

    def check_outbound(self, text: str) -> Verdict:
        """Judge what the streamer is saying, as the transcript arrives.

        Only the term list applies here: an injection pattern is something a
        viewer writes, and matching it against our own speech would cut the
        stream for saying "ignore the previous question".
        """
        if not self.guard_output:
            return ALLOWED
        lowered = _normalize(text)
        for term, matches in zip(self.terms, self._matchers):
            if matches(lowered):
                self.outbound_blocked += 1
                return Verdict(True, "blocked_term", term)
        return ALLOWED


# Short tokens like "kys" and "porn" fire inside ordinary words if matched as
# bare substrings, so they need a leading word boundary. Long ones are also
# checked with spaces removed, to catch "s e n d  n u d e s" — but only when
# they are long enough that an accidental collision is implausible ("lucky
# sale" de-spaces to "luckysale", which contains "kys").
_BOUNDARY_MAX_LENGTH = 5
_DESPACED_MIN_LENGTH = 8


# Three or more single-letter "words" in a row is spelling-out, not writing.
# Gluing them catches "k y s" without touching "lucky sale", which is what a
# blanket de-space would break.
_SPELLED_OUT = re.compile(r"\b(?:\w\s+){2,}\w\b")


def _normalize(text: str) -> str:
    """Fold the easy evasions: punctuation, stretched letters, spelling-out.

    Not a defence against a determined adversary — it just stops `p.o.r.n`,
    `kyyyys` and `k y s` walking straight through a substring check.
    """
    lowered = text.lower()
    collapsed = re.sub(r"[^a-z0-9\s]+", "", lowered)
    # Collapse a stretched run to a single letter. No blocklist term contains
    # an intentional triple, so this cannot hide one.
    collapsed = re.sub(r"(.)\1{2,}", r"\1", collapsed)
    collapsed = re.sub(r"\s+", " ", collapsed).strip()
    return _SPELLED_OUT.sub(lambda m: m.group(0).replace(" ", ""), collapsed)


def _build_matcher(term: str):
    """Precompile how one term is looked for in normalized text."""
    stripped = term.replace(" ", "")

    if len(stripped) <= _BOUNDARY_MAX_LENGTH:
        # A leading boundary still catches "pornography" while skipping words
        # that merely contain the letters.
        pattern = re.compile(rf"\b{re.escape(term)}")
        return lambda text: pattern.search(text) is not None

    if len(stripped) >= _DESPACED_MIN_LENGTH:
        return lambda text: term in text or stripped in text.replace(" ", "")

    return lambda text: term in text
