"""Configuration, loaded from the environment / .env file."""

from __future__ import annotations

import os
from dataclasses import dataclass, field
from pathlib import Path

from dotenv import load_dotenv

# Gemini Live model candidates, tried in order at connect time. The Live API is
# still preview and Google rotates the dated suffixes, so we fall through the
# list rather than hard-coding a single ID that can vanish overnight.
DEFAULT_MODEL_FALLBACKS = (
    "gemini-2.5-flash-native-audio-preview-12-2025",
    "gemini-live-2.5-flash-preview-native-audio-09-2025",
    "gemini-live-2.5-flash-preview",
    "gemini-live-2.5-flash",
    "gemini-2.0-flash-live-preview-04-09",
)

# Fixed by the Live API wire format, not user-tunable.
INPUT_SAMPLE_RATE = 16_000
OUTPUT_SAMPLE_RATE = 24_000
SAMPLE_WIDTH = 2  # 16-bit little-endian PCM
CHANNELS = 1


class ConfigError(RuntimeError):
    """Raised when required configuration is missing or malformed."""


def _get(name: str, default: str = "") -> str:
    return (os.environ.get(name) or default).strip()


def _get_bool(name: str, default: bool) -> bool:
    raw = _get(name)
    if not raw:
        return default
    return raw.lower() in ("1", "true", "yes", "on")


def _get_int(name: str, default: int) -> int:
    raw = _get(name)
    if not raw:
        return default
    try:
        return int(raw)
    except ValueError as exc:
        raise ConfigError(f"{name} must be an integer, got {raw!r}") from exc


def _get_float(name: str, default: float) -> float:
    raw = _get(name)
    if not raw:
        return default
    try:
        return float(raw)
    except ValueError as exc:
        raise ConfigError(f"{name} must be a number, got {raw!r}") from exc


def _get_pairs(name: str) -> list[tuple[str, str]]:
    """Parse `a:1,b:2` into pairs. Malformed entries are reported, not ignored."""
    pairs: list[tuple[str, str]] = []
    for entry in _get_list(name):
        key, separator, value = entry.partition(":")
        if not separator or not key.strip() or not value.strip():
            raise ConfigError(
                f"{name} entry {entry!r} must look like 'key:value' "
                f"(whole setting: comma-separated pairs)"
            )
        pairs.append((key.strip(), value.strip()))
    return pairs


def _get_int_map(name: str) -> dict[str, int]:
    result: dict[str, int] = {}
    for key, value in _get_pairs(name):
        try:
            result[key] = int(value)
        except ValueError as exc:
            raise ConfigError(f"{name} value for {key!r} must be a number, got {value!r}") from exc
    return result


def _get_str_map(name: str, *, lower_keys: bool = False) -> dict[str, str]:
    return {
        (key.lower() if lower_keys else key): value for key, value in _get_pairs(name)
    }


def _get_list(name: str, default: tuple[str, ...] = ()) -> tuple[str, ...]:
    raw = _get(name)
    if not raw:
        return default
    return tuple(part.strip() for part in raw.split(",") if part.strip())


@dataclass(slots=True)
class TikTokConfig:
    handle: str = ""
    session_id: str = ""
    reconnect_delay: float = 10.0
    # When the target is offline, keep polling instead of exiting.
    retry_when_offline: bool = True


@dataclass(slots=True)
class GeminiConfig:
    api_key: str = ""
    model: str = ""
    model_fallbacks: tuple[str, ...] = DEFAULT_MODEL_FALLBACKS
    voice: str = "Puck"
    language_code: str = "en-US"
    temperature: float = 1.0
    persona_name: str = "Nova"
    persona_file: str = ""
    persona_extra: str = ""
    # Native-audio-only features; harmless to leave off for half-cascade models.
    affective_dialog: bool = False
    proactivity: bool = False


@dataclass(slots=True)
class VTubeConfig:
    enabled: bool = True
    host: str = "127.0.0.1"
    port: int = 8001
    plugin_name: str = "BTA Streamer"
    plugin_developer: str = "BTA"
    token_file: str = ".vts_token"
    mouth_open_param: str = "MouthOpen"
    mouth_form_param: str = "MouthSmile"
    inject_fps: int = 60
    # Injecting with faceFound=false lets VTS keep using real tracking for
    # everything we do not explicitly set.
    face_found: bool = False
    weight: float = 1.0
    required: bool = False

    @property
    def url(self) -> str:
        return f"ws://{self.host}:{self.port}"


@dataclass(slots=True)
class AudioConfig:
    # "device" -> speakers/virtual cable, "wav" -> file, "null" -> discard.
    sink: str = "device"
    device: str = ""
    wav_path: str = "out/stream_audio.wav"
    frame_ms: int = 20
    gain: float = 1.0
    # Delays the mouth relative to the audio, to compensate for buffering in a
    # virtual cable / OBS. Raise it if the avatar's lips lead the voice.
    lipsync_delay_ms: int = 0


@dataclass(slots=True)
class DirectorConfig:
    """Chat selection and pacing."""

    max_batch: int = 4
    max_message_chars: int = 180
    queue_size: int = 500
    user_cooldown: float = 8.0
    dedupe_window: float = 60.0
    idle_prompt_after: float = 45.0
    idle_prompts: tuple[str, ...] = ()
    blocked_words: tuple[str, ...] = ()
    strip_urls: bool = True
    greet_gifts: bool = True
    greet_follows: bool = True


@dataclass(slots=True)
class CommerceConfig:
    """Product fulfillment tied to live activity."""

    enabled: bool = False
    session_id: str = ""
    # sku -> starting on-hand count.
    stock: dict[str, int] = field(default_factory=dict)
    # sku -> price in cents, used for revenue reporting only.
    prices: dict[str, int] = field(default_factory=dict)
    # sku -> human name, for what the streamer says out loud.
    sku_names: dict[str, str] = field(default_factory=dict)
    # Lowercased TikTok gift name -> sku. Empty means gifts never place
    # orders; a SKU is never inferred from a gift we were not told about.
    gift_skus: dict[str, str] = field(default_factory=dict)
    # A gift is already paid for, so there is no later payment step to wait
    # on. Off would leave that unit reserved forever.
    auto_fulfill_gifts: bool = True
    # Whether a broadcast ending releases held stock, or the buyer keeps
    # their unit. Genuinely a policy call, so it is explicit.
    release_holds_on_end: bool = False
    announce_orders: bool = True

    def problems(self) -> list[str]:
        """Configuration errors that would only surface mid-stream otherwise.

        A gift mapped to a SKU that inventory has never heard of is the
        expensive one: the viewer spends real money, the order is rejected as
        UnknownSku, and they are deliberately told nothing (it is an operator
        fault, not a stock-out). Catching it at startup is the difference
        between a typo and a bad stream.
        """
        if not self.enabled:
            return []

        found: list[str] = []
        for gift_name, sku in sorted(self.gift_skus.items()):
            if sku not in self.stock:
                found.append(
                    f"COMMERCE_GIFT_SKUS maps gift {gift_name!r} to sku {sku!r}, "
                    f"which is not in COMMERCE_STOCK"
                    + (f" (known: {', '.join(sorted(self.stock))})" if self.stock else "")
                )
        for sku, count in sorted(self.stock.items()):
            if count < 0:
                found.append(f"COMMERCE_STOCK for {sku!r} cannot be negative ({count})")
        return found

    def unnamed_skus(self) -> list[str]:
        """Stock SKUs with no spoken name. Not fatal, but they get read aloud."""
        return sorted(sku for sku in self.stock if sku not in self.sku_names)


@dataclass(slots=True)
class Config:
    tiktok: TikTokConfig = field(default_factory=TikTokConfig)
    gemini: GeminiConfig = field(default_factory=GeminiConfig)
    vtube: VTubeConfig = field(default_factory=VTubeConfig)
    audio: AudioConfig = field(default_factory=AudioConfig)
    director: DirectorConfig = field(default_factory=DirectorConfig)
    commerce: CommerceConfig = field(default_factory=CommerceConfig)
    log_level: str = "INFO"

    @property
    def models(self) -> tuple[str, ...]:
        """Model IDs to try, in order, de-duplicated."""
        ordered = ([self.gemini.model] if self.gemini.model else []) + list(
            self.gemini.model_fallbacks
        )
        seen: dict[str, None] = {}
        for model in ordered:
            if model:
                seen.setdefault(model, None)
        return tuple(seen)

    def validate(self, *, require_tiktok: bool = True) -> None:
        """Raise ConfigError listing everything that is missing at once."""
        problems: list[str] = []
        if not self.gemini.api_key:
            problems.append("GEMINI_API_KEY is not set (get one at aistudio.google.com)")
        if require_tiktok and not self.tiktok.handle:
            problems.append("TIKTOK_HANDLE is not set (e.g. @yourhandle)")
        if self.audio.sink not in ("device", "wav", "null"):
            problems.append(f"AUDIO_SINK must be device|wav|null, got {self.audio.sink!r}")
        if not 5 <= self.audio.frame_ms <= 100:
            problems.append("AUDIO_FRAME_MS must be between 5 and 100")
        if not 1 <= self.vtube.inject_fps <= 120:
            problems.append("VTS_INJECT_FPS must be between 1 and 120")
        problems.extend(self.commerce.problems())
        if problems:
            raise ConfigError(
                "Configuration problems:\n"
                + "\n".join(f"  - {p}" for p in problems)
                + "\n\nCopy .env.example to .env and fill it in."
            )


def normalize_handle(handle: str) -> str:
    """TikTokLive wants a leading '@'; accept a bare handle or a full URL."""
    handle = handle.strip()
    if not handle:
        return ""
    if "tiktok.com/" in handle:
        tail = handle.split("tiktok.com/", 1)[1]
        handle = tail.split("/", 1)[0]
    handle = handle.lstrip("@").strip()
    return f"@{handle}" if handle else ""


def load_config(env_file: str | os.PathLike[str] | None = ".env") -> Config:
    """Read .env (if present) and build a Config. Real env vars win over .env."""
    if env_file is not None:
        path = Path(env_file)
        if path.is_file():
            load_dotenv(path, override=False)

    persona_file = _get("PERSONA_FILE")
    persona_extra = _get("PERSONA_EXTRA")
    if persona_file and Path(persona_file).is_file():
        persona_extra = (
            Path(persona_file).read_text(encoding="utf-8").strip() + "\n" + persona_extra
        ).strip()

    return Config(
        tiktok=TikTokConfig(
            handle=normalize_handle(_get("TIKTOK_HANDLE")),
            session_id=_get("TIKTOK_SESSION_ID"),
            reconnect_delay=_get_float("TIKTOK_RECONNECT_DELAY", 10.0),
            retry_when_offline=_get_bool("TIKTOK_RETRY_WHEN_OFFLINE", True),
        ),
        gemini=GeminiConfig(
            api_key=_get("GEMINI_API_KEY") or _get("GOOGLE_API_KEY"),
            model=_get("GEMINI_MODEL"),
            model_fallbacks=_get_list("GEMINI_MODEL_FALLBACKS", DEFAULT_MODEL_FALLBACKS),
            voice=_get("GEMINI_VOICE", "Puck"),
            language_code=_get("GEMINI_LANGUAGE", "en-US"),
            temperature=_get_float("GEMINI_TEMPERATURE", 1.0),
            persona_name=_get("PERSONA_NAME", "Nova"),
            persona_file=persona_file,
            persona_extra=persona_extra,
            affective_dialog=_get_bool("GEMINI_AFFECTIVE_DIALOG", False),
            proactivity=_get_bool("GEMINI_PROACTIVITY", False),
        ),
        vtube=VTubeConfig(
            enabled=_get_bool("VTS_ENABLED", True),
            host=_get("VTS_HOST", "127.0.0.1"),
            port=_get_int("VTS_PORT", 8001),
            plugin_name=_get("VTS_PLUGIN_NAME", "BTA Streamer"),
            plugin_developer=_get("VTS_PLUGIN_DEVELOPER", "BTA"),
            token_file=_get("VTS_TOKEN_FILE", ".vts_token"),
            mouth_open_param=_get("VTS_MOUTH_OPEN_PARAM", "MouthOpen"),
            mouth_form_param=_get("VTS_MOUTH_FORM_PARAM", "MouthSmile"),
            inject_fps=_get_int("VTS_INJECT_FPS", 60),
            face_found=_get_bool("VTS_FACE_FOUND", False),
            weight=_get_float("VTS_WEIGHT", 1.0),
            required=_get_bool("VTS_REQUIRED", False),
        ),
        audio=AudioConfig(
            sink=_get("AUDIO_SINK", "device").lower(),
            device=_get("AUDIO_DEVICE"),
            wav_path=_get("AUDIO_WAV_PATH", "out/stream_audio.wav"),
            frame_ms=_get_int("AUDIO_FRAME_MS", 20),
            gain=_get_float("AUDIO_GAIN", 1.0),
            lipsync_delay_ms=_get_int("AUDIO_LIPSYNC_DELAY_MS", 0),
        ),
        director=DirectorConfig(
            max_batch=_get_int("DIRECTOR_MAX_BATCH", 4),
            max_message_chars=_get_int("DIRECTOR_MAX_MESSAGE_CHARS", 180),
            queue_size=_get_int("DIRECTOR_QUEUE_SIZE", 500),
            user_cooldown=_get_float("DIRECTOR_USER_COOLDOWN", 8.0),
            dedupe_window=_get_float("DIRECTOR_DEDUPE_WINDOW", 60.0),
            idle_prompt_after=_get_float("DIRECTOR_IDLE_PROMPT_AFTER", 45.0),
            idle_prompts=_get_list("DIRECTOR_IDLE_PROMPTS"),
            blocked_words=tuple(w.lower() for w in _get_list("DIRECTOR_BLOCKED_WORDS")),
            strip_urls=_get_bool("DIRECTOR_STRIP_URLS", True),
            greet_gifts=_get_bool("DIRECTOR_GREET_GIFTS", True),
            greet_follows=_get_bool("DIRECTOR_GREET_FOLLOWS", True),
        ),
        commerce=CommerceConfig(
            enabled=_get_bool("COMMERCE_ENABLED", False),
            session_id=_get("COMMERCE_SESSION_ID"),
            stock=_get_int_map("COMMERCE_STOCK"),
            prices=_get_int_map("COMMERCE_PRICES"),
            sku_names=_get_str_map("COMMERCE_SKU_NAMES"),
            gift_skus=_get_str_map("COMMERCE_GIFT_SKUS", lower_keys=True),
            auto_fulfill_gifts=_get_bool("COMMERCE_AUTO_FULFILL_GIFTS", True),
            release_holds_on_end=_get_bool("COMMERCE_RELEASE_HOLDS_ON_END", False),
            announce_orders=_get_bool("COMMERCE_ANNOUNCE_ORDERS", True),
        ),
        log_level=_get("LOG_LEVEL", "INFO").upper(),
    )
