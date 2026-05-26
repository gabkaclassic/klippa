"""Конфигурация демона: TOML + hot-reload.

Парсинг (`parse_config`) изолирован от gi и покрыт тестами. Слежение за файлом
(`ConfigWatcher`) использует Gio.FileMonitor и проверяется вручную.
"""

from __future__ import annotations

import json
import os
import tomllib
from dataclasses import asdict, dataclass
from pathlib import Path

APP = "klippa"


class ConfigError(ValueError):
    """Некорректный конфиг (битый TOML или неверные типы значений)."""


@dataclass
class Config:
    """Значения конфигурации с дефолтами (PRD §7)."""

    hotkey: str = "<Super>v"        # любая GTK-комбинация-акселератор
    max_entries: int = 50           # длина истории; сверх — вытеснение старого
    capture_images: bool = True     # ловить ли image/* (вкл. скриншоты)
    max_image_mb: int = 10          # картинки крупнее — отбрасывать
    auto_paste: bool = True         # авто-Ctrl+V в прежнее окно по выбору
    skip_secrets: bool = True       # не хранить помеченное менеджерами паролей
    expire_days: int = 0            # авто-истечение записей; 0 — выключено


# Шаблон файла по умолчанию (с комментариями — tomllib только читает).
DEFAULT_TOML = """\
# Конфигурация klippa. Меняется на лету (демон следит за файлом).

hotkey         = "<Super>v"   # любая комбинация, например "<Ctrl><Alt>v"
max_entries    = 50           # сколько последних записей хранить
capture_images = true         # ловить изображения и скриншоты из буфера
max_image_mb   = 10           # картинки крупнее этого — игнорировать
auto_paste     = true         # вставлять выбранное Ctrl+V автоматически
skip_secrets   = true         # пропускать помеченное менеджерами паролей
expire_days    = 0            # удалять записи старше N дней (0 — не удалять)
"""

_BOOL = (bool,)
_INT = (int,)
_STR = (str,)
# карта поле → допустимые типы (bool — подтип int, поэтому проверяем строго)
_SCHEMA: dict[str, tuple[type, ...]] = {
    "hotkey": _STR,
    "max_entries": _INT,
    "capture_images": _BOOL,
    "max_image_mb": _INT,
    "auto_paste": _BOOL,
    "skip_secrets": _BOOL,
    "expire_days": _INT,
}


def default_config_path() -> Path:
    """$XDG_CONFIG_HOME/klippa/config.toml (по умолчанию ~/.config/...)."""
    base = os.environ.get("XDG_CONFIG_HOME") or os.path.expanduser("~/.config")
    return Path(base) / APP / "config.toml"


def from_dict(raw: dict) -> Config:
    """Собрать Config из словаря (TOML или JSON по D-Bus). Неизвестные ключи игнорируются.

    Поднимает ConfigError при неверном типе известного ключа.
    """
    cfg = Config()
    for key, value in raw.items():
        if key not in _SCHEMA:
            continue  # неизвестный ключ — молча пропускаем (forward-compat)
        allowed = _SCHEMA[key]
        # bool — подкласс int: отсекаем перепутанные типы строго
        if allowed is _INT and isinstance(value, bool):
            raise ConfigError(f"{key}: ожидалось целое, получено булево")
        if allowed is _BOOL and not isinstance(value, bool):
            raise ConfigError(f"{key}: ожидалось булево")
        if not isinstance(value, allowed):
            raise ConfigError(f"{key}: неверный тип {type(value).__name__}")
        setattr(cfg, key, value)

    _clamp(cfg)
    return cfg


def parse_config(data: str) -> Config:
    """Разобрать TOML-строку в Config. Неизвестные ключи игнорируются.

    Поднимает ConfigError при битом TOML или неверном типе известного ключа.
    """
    try:
        raw = tomllib.loads(data)
    except tomllib.TOMLDecodeError as exc:
        raise ConfigError(f"битый TOML: {exc}") from exc
    return from_dict(raw)


def _clamp(cfg: Config) -> None:
    """Привести значения к допустимым границам."""
    if cfg.max_entries < 1:
        cfg.max_entries = 1
    if cfg.max_image_mb < 1:
        cfg.max_image_mb = 1
    if cfg.expire_days < 0:
        cfg.expire_days = 0


def load_config(path: Path | None = None) -> Config:
    """Прочитать конфиг из файла. Отсутствующий файл → дефолты."""
    path = path or default_config_path()
    if not path.exists():
        return Config()
    return parse_config(path.read_text(encoding="utf-8"))


def ensure_config_file(path: Path | None = None) -> Path:
    """Создать конфиг с дефолтами, если его нет. Каталог — с правами 0700."""
    path = path or default_config_path()
    if not path.exists():
        path.parent.mkdir(parents=True, exist_ok=True, mode=0o700)
        path.write_text(DEFAULT_TOML, encoding="utf-8")
        path.chmod(0o600)
    return path


def as_dict(cfg: Config) -> dict:
    return asdict(cfg)


def dump_toml(cfg: Config) -> str:
    """Сериализовать Config в комментированный TOML (как DEFAULT_TOML, но со значениями).

    Используется при записи конфига из prefs.js (через D-Bus SetConfig): файл
    остаётся человекочитаемым, с пояснениями. Парсится обратно в тот же Config.
    """

    def s(value: str) -> str:  # basic-строка TOML == JSON-строка для наших значений
        return json.dumps(value, ensure_ascii=False)

    def b(value: bool) -> str:
        return "true" if value else "false"

    return (
        "# Конфигурация klippa. Меняется на лету (демон следит за файлом).\n"
        "\n"
        f"hotkey         = {s(cfg.hotkey)}   # любая комбинация, например \"<Ctrl><Alt>v\"\n"
        f"max_entries    = {cfg.max_entries}           # сколько последних записей хранить\n"
        f"capture_images = {b(cfg.capture_images)}         # ловить изображения и скриншоты из буфера\n"
        f"max_image_mb   = {cfg.max_image_mb}           # картинки крупнее этого — игнорировать\n"
        f"auto_paste     = {b(cfg.auto_paste)}         # вставлять выбранное Ctrl+V автоматически\n"
        f"skip_secrets   = {b(cfg.skip_secrets)}         # пропускать помеченное менеджерами паролей\n"
        f"expire_days    = {cfg.expire_days}            # удалять записи старше N дней (0 — не удалять)\n"
    )


def save_config(cfg: Config, path: Path | None = None) -> Path:
    """Атомарно записать конфиг (temp + rename), права 0600. Каталог — 0700.

    Атомарность важна: частично записанный файл при чтении на старте дал бы
    ConfigError. rename меняет inode, поэтому ConfigWatcher свою же запись может
    не увидеть — вызывающий (SetConfig) применяет конфиг напрямую.
    """
    path = path or default_config_path()
    path.parent.mkdir(parents=True, exist_ok=True, mode=0o700)
    tmp = path.with_name(path.name + ".tmp")
    tmp.write_text(dump_toml(cfg), encoding="utf-8")
    tmp.chmod(0o600)
    os.replace(tmp, path)
    return path


class ConfigWatcher:
    """Следит за config.toml через Gio.FileMonitor и зовёт callback при изменении.

    Импорт gi отложен в метод, чтобы модуль оставался импортируемым без gi
    (для unit-тестов ядра)."""

    def __init__(self, path: Path, on_change) -> None:
        self._path = path
        self._on_change = on_change
        self._monitor = None

    def start(self) -> Config:
        """Создать файл при отсутствии, запустить слежение, вернуть текущий конфиг."""
        import gi

        gi.require_version("Gio", "2.0")
        from gi.repository import Gio

        ensure_config_file(self._path)
        gfile = Gio.File.new_for_path(str(self._path))
        self._monitor = gfile.monitor_file(Gio.FileMonitorFlags.NONE, None)
        self._monitor.connect("changed", self._on_fs_event)
        return load_config(self._path)

    def stop(self) -> None:
        if self._monitor is not None:
            self._monitor.cancel()
            self._monitor = None

    def _on_fs_event(self, _monitor, _f, _other, event_type) -> None:
        import gi

        gi.require_version("Gio", "2.0")
        from gi.repository import Gio

        if event_type not in (
            Gio.FileMonitorEvent.CHANGES_DONE_HINT,
            Gio.FileMonitorEvent.CREATED,
        ):
            return
        try:
            cfg = load_config(self._path)
        except ConfigError as exc:
            # битый конфиг не должен ронять демон — логируем, оставляем прежний
            print(f"klippad: игнорирую битый конфиг: {exc}", flush=True)
            return
        self._on_change(cfg)
