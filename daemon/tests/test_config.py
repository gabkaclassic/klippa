"""Тесты конфига: дефолты, парсинг, валидация, clamp, файловые операции."""

import pytest

from klippad.config import (
    Config,
    ConfigError,
    dump_toml,
    ensure_config_file,
    from_dict,
    load_config,
    parse_config,
    save_config,
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


# --- from_dict (путь D-Bus SetConfig) ------------------------------------------


def test_from_dict_overrides_and_clamps():
    c = from_dict({"max_entries": 0, "auto_paste": False, "future": "x"})
    assert c.max_entries == 1  # clamp
    assert c.auto_paste is False
    assert c.hotkey == "<Super>v"  # не задан — дефолт


def test_from_dict_wrong_type_raises():
    with pytest.raises(ConfigError):
        from_dict({"capture_images": 1})  # int вместо bool
    with pytest.raises(ConfigError):
        from_dict({"max_entries": True})  # bool не сходит за int


# --- dump_toml / save_config (запись из prefs.js) ------------------------------


def test_dump_toml_roundtrips_defaults():
    cfg = Config()
    assert parse_config(dump_toml(cfg)) == cfg


def test_dump_toml_roundtrips_custom():
    cfg = Config(
        hotkey="<Ctrl><Alt>v",
        max_entries=7,
        capture_images=False,
        max_image_mb=3,
        auto_paste=False,
        skip_secrets=False,
        expire_days=30,
    )
    assert parse_config(dump_toml(cfg)) == cfg


def test_dump_toml_escapes_hotkey_with_quotes():
    # экзотика, но строка не должна ломать TOML
    cfg = Config(hotkey='<Ctrl>"')
    assert parse_config(dump_toml(cfg)).hotkey == '<Ctrl>"'


def test_save_config_atomic_perms_and_roundtrip(tmp_path):
    p = tmp_path / "sub" / "config.toml"
    cfg = Config(max_entries=11, auto_paste=False)
    returned = save_config(cfg, p)
    assert returned == p
    assert p.exists()
    assert not (tmp_path / "sub" / "config.toml.tmp").exists()  # temp убран
    assert (p.stat().st_mode & 0o777) == 0o600
    assert load_config(p) == cfg


def test_save_config_overwrites(tmp_path):
    p = tmp_path / "config.toml"
    save_config(Config(max_entries=5), p)
    save_config(Config(max_entries=9), p)
    assert load_config(p).max_entries == 9
