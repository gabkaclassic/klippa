"""Тесты конфига: дефолты, парсинг, валидация, clamp, файловые операции."""

import pytest

from klippad.config import (
    Config,
    ConfigError,
    ensure_config_file,
    load_config,
    parse_config,
)


def test_defaults():
    c = Config()
    assert c.hotkey == "<Super>v"
    assert c.max_entries == 50
    assert c.capture_images is True
    assert c.auto_paste is True
    assert c.skip_secrets is True
    assert c.expire_days == 0


def test_parse_overrides_known_keys():
    c = parse_config(
        'hotkey = "<Ctrl><Alt>v"\n'
        "max_entries = 100\n"
        "capture_images = false\n"
        "auto_paste = false\n"
    )
    assert c.hotkey == "<Ctrl><Alt>v"
    assert c.max_entries == 100
    assert c.capture_images is False
    assert c.auto_paste is False
    assert c.skip_secrets is True  # не задано — дефолт


def test_unknown_keys_ignored():
    c = parse_config('future_flag = 123\nhotkey = "<Super>c"\n')
    assert c.hotkey == "<Super>c"


def test_malformed_toml_raises():
    with pytest.raises(ConfigError):
        parse_config("this is = = not toml")


def test_wrong_type_raises():
    with pytest.raises(ConfigError):
        parse_config('max_entries = "many"')
    with pytest.raises(ConfigError):
        parse_config("capture_images = 1")  # int вместо bool


def test_bool_not_accepted_as_int():
    # true в TOML не должно сойти за max_entries
    with pytest.raises(ConfigError):
        parse_config("max_entries = true")


def test_clamp_bounds():
    c = parse_config("max_entries = 0\nmax_image_mb = 0\nexpire_days = -5\n")
    assert c.max_entries == 1
    assert c.max_image_mb == 1
    assert c.expire_days == 0


def test_load_missing_file_returns_defaults(tmp_path):
    c = load_config(tmp_path / "nope.toml")
    assert c == Config()


def test_load_existing_file(tmp_path):
    p = tmp_path / "config.toml"
    p.write_text('max_entries = 7\n', encoding="utf-8")
    assert load_config(p).max_entries == 7


def test_ensure_config_file_creates_with_defaults_and_perms(tmp_path):
    p = tmp_path / "sub" / "config.toml"
    ensure_config_file(p)
    assert p.exists()
    # дефолтный файл должен парситься в дефолтный Config
    assert load_config(p) == Config()
    assert (p.stat().st_mode & 0o777) == 0o600


def test_ensure_config_file_idempotent(tmp_path):
    p = tmp_path / "config.toml"
    p.write_text("max_entries = 3\n", encoding="utf-8")
    ensure_config_file(p)  # не должен перезаписать существующий
    assert load_config(p).max_entries == 3
