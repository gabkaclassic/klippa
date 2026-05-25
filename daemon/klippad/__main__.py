"""Точка входа демона klippad: сборка компонентов и главный цикл GLib.

Поток запуска:
  конфиг → ключ из keyring → шифрованная БД → загрузка истории в Store →
  публикация D-Bus → слежение за конфигом → main loop (до SIGINT/SIGTERM).
"""

from __future__ import annotations

import signal
import sys

import gi

gi.require_version("GLib", "2.0")
from gi.repository import GLib  # noqa: E402

from .config import ConfigWatcher, default_config_path, ensure_config_file, load_config
from .crypto import make_cipher_from_keyring
from .db import Database, default_db_path
from .service import Daemon, push_hotkey_to_extension
from .store import Store

_EXPIRY_INTERVAL_SEC = 3600


def main() -> int:
    cfg_path = default_config_path()
    ensure_config_file(cfg_path)
    cfg = load_config(cfg_path)

    try:
        cipher = make_cipher_from_keyring()
    except Exception as exc:
        print(f"klippad: не удалось получить ключ из gnome-keyring: {exc}", file=sys.stderr)
        return 1

    db = Database(default_db_path(), cipher)
    store = Store(max_entries=cfg.max_entries)
    store.load(db.load())
    db.sync(store.list())  # согласовать БД, если загрузка что-то вытеснила

    daemon = Daemon(cfg, store, db)
    push_hotkey_to_extension(cfg.hotkey)  # best-effort: расширение может быть ещё не установлено
    daemon.start()

    watcher = ConfigWatcher(cfg_path, daemon.apply_config)
    watcher.start()

    loop = GLib.MainLoop()

    def _shutdown(*_args) -> bool:
        print("klippad: останавливаюсь…", flush=True)
        watcher.stop()
        daemon.stop()
        loop.quit()
        return GLib.SOURCE_REMOVE

    GLib.unix_signal_add(GLib.PRIORITY_DEFAULT, signal.SIGINT, _shutdown)
    GLib.unix_signal_add(GLib.PRIORITY_DEFAULT, signal.SIGTERM, _shutdown)

    # авто-истечение (DMN-012): no-op при expire_days=0
    daemon.run_expiry()
    GLib.timeout_add_seconds(_EXPIRY_INTERVAL_SEC, daemon.run_expiry)

    print(f"klippad {_version()}: запущен, history={len(store)}", flush=True)
    loop.run()
    return 0


def _version() -> str:
    from . import __version__

    return __version__


if __name__ == "__main__":
    raise SystemExit(main())
