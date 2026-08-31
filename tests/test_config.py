"""Configuration loading and validation."""

from __future__ import annotations

import pytest

from bta.config import Config, ConfigError, load_config, normalize_handle


@pytest.fixture(autouse=True)
def clean_env(monkeypatch):
    for name in list(__import__("os").environ):
        if name.startswith(
            ("TIKTOK_", "GEMINI_", "VTS_", "AUDIO_", "DIRECTOR_", "PERSONA_", "LOG_")
        ):
            monkeypatch.delenv(name, raising=False)
    monkeypatch.delenv("GOOGLE_API_KEY", raising=False)


@pytest.mark.parametrize(
    "raw,expected",
    [
        ("@handle", "@handle"),
        ("handle", "@handle"),
        ("  @handle  ", "@handle"),
        ("https://www.tiktok.com/@handle/live", "@handle"),
        ("tiktok.com/@handle", "@handle"),
        ("", ""),
        ("@", ""),
    ],
)
def test_normalize_handle(raw, expected):
    assert normalize_handle(raw) == expected


def test_load_config_reads_env(monkeypatch):
    monkeypatch.setenv("GEMINI_API_KEY", "key-123")
    monkeypatch.setenv("TIKTOK_HANDLE", "someone")
    monkeypatch.setenv("GEMINI_VOICE", "Charon")
    monkeypatch.setenv("VTS_PORT", "9001")
    monkeypatch.setenv("VTS_ENABLED", "false")
    monkeypatch.setenv("AUDIO_GAIN", "0.5")
    monkeypatch.setenv("DIRECTOR_BLOCKED_WORDS", "foo, BAR ,baz")

    cfg = load_config(env_file=None)
    assert cfg.gemini.api_key == "key-123"
    assert cfg.tiktok.handle == "@someone"
    assert cfg.gemini.voice == "Charon"
    assert cfg.vtube.port == 9001
    assert cfg.vtube.enabled is False
    assert cfg.audio.gain == 0.5
    assert cfg.director.blocked_words == ("foo", "bar", "baz")


def test_google_api_key_is_accepted_as_a_fallback(monkeypatch):
    monkeypatch.setenv("GOOGLE_API_KEY", "fallback-key")
    assert load_config(env_file=None).gemini.api_key == "fallback-key"


def test_env_file_is_loaded(tmp_path, monkeypatch):
    env = tmp_path / ".env"
    env.write_text("GEMINI_API_KEY=from-file\nTIKTOK_HANDLE=@fromfile\n")
    cfg = load_config(env_file=str(env))
    assert cfg.gemini.api_key == "from-file"
    assert cfg.tiktok.handle == "@fromfile"


def test_real_env_beats_the_env_file(tmp_path, monkeypatch):
    env = tmp_path / ".env"
    env.write_text("GEMINI_API_KEY=from-file\n")
    monkeypatch.setenv("GEMINI_API_KEY", "from-environment")
    assert load_config(env_file=str(env)).gemini.api_key == "from-environment"


def test_bad_integer_is_reported(monkeypatch):
    monkeypatch.setenv("VTS_PORT", "not-a-number")
    with pytest.raises(ConfigError, match="VTS_PORT"):
        load_config(env_file=None)


def test_validate_reports_every_problem_at_once():
    cfg = Config()
    cfg.audio.sink = "bogus"
    with pytest.raises(ConfigError) as info:
        cfg.validate()
    message = str(info.value)
    assert "GEMINI_API_KEY" in message
    assert "TIKTOK_HANDLE" in message
    assert "AUDIO_SINK" in message


def test_validate_passes_with_the_minimum():
    cfg = Config()
    cfg.gemini.api_key = "k"
    cfg.tiktok.handle = "@h"
    cfg.validate()


def test_console_mode_does_not_require_a_handle():
    cfg = Config()
    cfg.gemini.api_key = "k"
    cfg.validate(require_tiktok=False)


def test_model_list_puts_the_explicit_model_first():
    cfg = Config()
    cfg.gemini.model = "my-preferred-model"
    models = cfg.models
    assert models[0] == "my-preferred-model"
    assert len(models) == len(set(models)), "model list should be deduplicated"


def test_model_list_without_an_override_uses_fallbacks():
    assert len(Config().models) >= 2


def test_persona_file_is_appended(tmp_path, monkeypatch):
    persona = tmp_path / "persona.txt"
    persona.write_text("You love talking about synthesizers.")
    monkeypatch.setenv("PERSONA_FILE", str(persona))
    cfg = load_config(env_file=None)
    assert "synthesizers" in cfg.gemini.persona_extra


def test_commerce_maps_are_parsed(monkeypatch):
    monkeypatch.setenv("COMMERCE_ENABLED", "true")
    monkeypatch.setenv("COMMERCE_STOCK", "tee-blk-l:40, mug:12")
    monkeypatch.setenv("COMMERCE_PRICES", "tee-blk-l:2500")
    monkeypatch.setenv("COMMERCE_GIFT_SKUS", "Galaxy:tee-blk-l")
    monkeypatch.setenv("COMMERCE_SKU_NAMES", "tee-blk-l:black tee")

    commerce = load_config(env_file=None).commerce
    assert commerce.enabled
    assert commerce.stock == {"tee-blk-l": 40, "mug": 12}
    assert commerce.prices == {"tee-blk-l": 2500}
    # Gift names are matched case-insensitively, so keys are normalized.
    assert commerce.gift_skus == {"galaxy": "tee-blk-l"}
    assert commerce.sku_names == {"tee-blk-l": "black tee"}


def test_commerce_is_off_by_default():
    assert Config().commerce.enabled is False


def test_holds_are_kept_on_session_end_by_default():
    """Releasing a buyer's unit because a stream dropped must be opt-in."""
    assert Config().commerce.release_holds_on_end is False


@pytest.mark.parametrize("raw", ["tee-blk-l", "tee-blk-l:", ":40", "tee-blk-l:40,mug"])
def test_malformed_pair_settings_are_reported(raw, monkeypatch):
    monkeypatch.setenv("COMMERCE_STOCK", raw)
    with pytest.raises(ConfigError, match="COMMERCE_STOCK"):
        load_config(env_file=None)


def test_non_numeric_stock_is_reported(monkeypatch):
    monkeypatch.setenv("COMMERCE_STOCK", "tee-blk-l:lots")
    with pytest.raises(ConfigError, match="must be a number"):
        load_config(env_file=None)


def test_vtube_url_is_built_from_host_and_port():
    cfg = Config()
    cfg.vtube.host, cfg.vtube.port = "10.0.0.5", 9000
    assert cfg.vtube.url == "ws://10.0.0.5:9000"
