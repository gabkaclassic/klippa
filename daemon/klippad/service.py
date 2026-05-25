"""D-Bus-сервис org.klippa.Daemon — оркестрация store + db + crypto + thumbs.

Это gi-слой (Gio D-Bus); проверяется интеграционным smoke-чеклистом. Вся
содержательная логика делегируется протестированному ядру.
"""

from __future__ import annotations

import json

import gi

gi.require_version("Gio", "2.0")
gi.require_version("GLib", "2.0")
from gi.repository import Gio, GLib  # noqa: E402

from . import thumbs
from .config import Config
from .db import Database
from .store import IMAGE, TEXT, Store

BUS_NAME = "org.klippa.Daemon"
OBJECT_PATH = "/org/klippa/Daemon"
IFACE = "org.klippa.Daemon1"

# Расширение хранит хоткей в этой схеме (DMN-010 синхронизирует сюда из конфига).
EXT_SCHEMA = "org.gnome.shell.extensions.klippa"
EXT_HOTKEY_KEY = "hotkey"

# Жёсткий потолок на размер текстовой записи (защита от мусора в истории).
MAX_TEXT_BYTES = 1024 * 1024

# Должно совпадать с docs/dbus-interface.xml (канонический контракт IPC-001).
_INTERFACE_XML = """
<node>
  <interface name="org.klippa.Daemon1">
    <method name="Capture">
      <arg name="kind" type="s" direction="in"/>
      <arg name="data" type="ay" direction="in"/>
      <arg name="source_app" type="s" direction="in"/>
      <arg name="ts" type="x" direction="in"/>
      <arg name="sensitive" type="b" direction="in"/>
    </method>
    <method name="GetHistory">
      <arg name="limit" type="u" direction="in"/>
      <arg name="json" type="s" direction="out"/>
    </method>
    <method name="GetThumbnail">
      <arg name="id" type="t" direction="in"/>
      <arg name="png" type="ay" direction="out"/>
    </method>
    <method name="GetContent">
      <arg name="id" type="t" direction="in"/>
      <arg name="kind" type="s" direction="out"/>
      <arg name="data" type="ay" direction="out"/>
    </method>
    <method name="Promote"><arg name="id" type="t" direction="in"/></method>
    <method name="Delete"><arg name="id" type="t" direction="in"/></method>
    <method name="Clear"/>
    <signal name="HistoryChanged"/>
  </interface>
</node>
"""


def _as_bytes(value) -> bytes:
    """Привести распакованный GVariant 'ay' (bytes или list[int]) к bytes."""
    return bytes(value)


def push_settings_to_extension(cfg: Config) -> bool:
    """Синхронизировать настройки в GSettings расширения (DMN-010).

    config.toml демона — единственный источник истины; сюда зеркалятся хоткей,
    лимит показа и авто-вставка. Без падения, если схема ещё не установлена.
    """
    accel = (cfg.hotkey or "").strip()
    if not accel:
        print("klippad: пустой hotkey — не синхронизирую", flush=True)
        return False
    source = Gio.SettingsSchemaSource.get_default()
    if source is None or source.lookup(EXT_SCHEMA, True) is None:
        # расширение ещё не установлено — нормально на раннем этапе
        return False
    settings = Gio.Settings.new(EXT_SCHEMA)
    settings.set_strv(EXT_HOTKEY_KEY, [accel])
    settings.set_int("popup-limit", cfg.max_entries)
    settings.set_boolean("auto-paste", cfg.auto_paste)
    return True


class Daemon:
    """Владеет историей и публикует её по D-Bus."""

    def __init__(self, config: Config, store: Store, db: Database) -> None:
        self._cfg = config
        self._store = store
        self._db = db
        self._thumbs: dict[int, bytes] = {}  # id → PNG-миниатюра (память)
        self._conn: Gio.DBusConnection | None = None
        self._owner_id = 0
        self._reg_id = 0

    # --- жизненный цикл -----------------------------------------------------

    def start(self) -> None:
        self._owner_id = Gio.bus_own_name(
            Gio.BusType.SESSION,
            BUS_NAME,
            Gio.BusNameOwnerFlags.NONE,
            self._on_bus_acquired,
            None,
            self._on_name_lost,
        )

    def stop(self) -> None:
        if self._conn is not None and self._reg_id:
            self._conn.unregister_object(self._reg_id)
        if self._owner_id:
            Gio.bus_unown_name(self._owner_id)
        self._db.close()

    def _on_bus_acquired(self, conn: Gio.DBusConnection, _name: str) -> None:
        self._conn = conn
        node = Gio.DBusNodeInfo.new_for_xml(_INTERFACE_XML)
        self._reg_id = conn.register_object(
            OBJECT_PATH, node.interfaces[0], self._on_method_call, None, None
        )

    def _on_name_lost(self, _conn, _name) -> None:
        print(f"klippad: не удалось получить имя {BUS_NAME} (уже занято?)", flush=True)

    # --- применение конфига -------------------------------------------------

    def apply_config(self, cfg: Config) -> None:
        """Вызывается ConfigWatcher при изменении config.toml."""
        self._cfg = cfg
        evicted = self._store.set_max_entries(cfg.max_entries)
        for entry_id in evicted:
            self._thumbs.pop(entry_id, None)
        if evicted:
            self._db.sync(self._store.list())
        push_settings_to_extension(cfg)
        self._emit_changed()

    # --- диспетчер D-Bus ----------------------------------------------------

    def _on_method_call(
        self, _conn, _sender, _path, _iface, method, params, invocation
    ) -> None:
        try:
            handler = getattr(self, f"_m_{method}", None)
            if handler is None:
                invocation.return_dbus_error(
                    f"{IFACE}.Error.UnknownMethod", f"нет метода {method}"
                )
                return
            handler(params, invocation)
        except Exception as exc:  # защита: ошибка метода не должна ронять демон
            print(f"klippad: ошибка в {method}: {exc!r}", flush=True)
            invocation.return_dbus_error(f"{IFACE}.Error.Failed", str(exc))

    # --- методы -------------------------------------------------------------

    def _m_Capture(self, params, invocation) -> None:
        kind, raw, source_app, ts, sensitive = params.unpack()
        data = _as_bytes(raw)
        invocation.return_value(None)  # быстрый ответ; обработка ниже

        if sensitive and self._cfg.skip_secrets:
            return
        preview = None
        if kind == TEXT:
            if not data or not data.decode("utf-8", "replace").strip():
                return
            if len(data) > MAX_TEXT_BYTES:
                return
        elif kind == IMAGE:
            if not self._cfg.capture_images:
                return
            if len(data) > self._cfg.max_image_mb * 1024 * 1024:
                return
            preview = thumbs.preview_for_image(data)
        else:
            return

        existed = self._store.find(kind, data) is not None
        entry = self._store.add(kind, data, source_app or "", int(ts), preview)
        if kind == IMAGE and not existed:
            try:
                self._thumbs[entry.id] = thumbs.make_thumbnail(data)
            except Exception as exc:
                print(f"klippad: миниатюра не создана: {exc}", flush=True)

        self._db.sync(self._store.list())
        self._prune_thumbs()
        self._emit_changed()

    def _m_GetHistory(self, params, invocation) -> None:
        (limit,) = params.unpack()
        meta = [e.meta() for e in self._store.list(limit)]
        payload = json.dumps(meta, ensure_ascii=False)
        invocation.return_value(GLib.Variant("(s)", (payload,)))

    def _m_GetThumbnail(self, params, invocation) -> None:
        (entry_id,) = params.unpack()
        png = self._thumbs.get(entry_id)
        if png is None:
            entry = self._store.get(entry_id)
            if entry is not None and entry.kind == IMAGE:
                try:
                    png = thumbs.make_thumbnail(entry.data)
                    self._thumbs[entry_id] = png
                except Exception:
                    png = b""
            else:
                png = b""
        invocation.return_value(GLib.Variant("(ay)", (png,)))

    def _m_GetContent(self, params, invocation) -> None:
        (entry_id,) = params.unpack()
        entry = self._store.get(entry_id)
        if entry is None:
            invocation.return_dbus_error(f"{IFACE}.Error.NotFound", "нет записи")
            return
        invocation.return_value(GLib.Variant("(say)", (entry.kind, entry.data)))

    def _m_Promote(self, params, invocation) -> None:
        (entry_id,) = params.unpack()
        if self._store.promote(entry_id):
            self._db.sync(self._store.list())
            self._emit_changed()
        invocation.return_value(None)

    def _m_Delete(self, params, invocation) -> None:
        (entry_id,) = params.unpack()
        if self._store.delete(entry_id):
            self._thumbs.pop(entry_id, None)
            self._db.sync(self._store.list())
            self._emit_changed()
        invocation.return_value(None)

    def _m_Clear(self, _params, invocation) -> None:
        self._store.clear()
        self._thumbs.clear()
        self._db.clear()
        self._emit_changed()
        invocation.return_value(None)

    # --- авто-истечение (DMN-012) ------------------------------------------

    def run_expiry(self) -> bool:
        """Удалить записи старше expire_days. No-op при 0. Возвращает SOURCE_CONTINUE."""
        days = self._cfg.expire_days
        if days > 0:
            import time

            cutoff = int(time.time()) - days * 86400
            removed = self._store.expire_older_than(cutoff)
            for entry_id in removed:
                self._thumbs.pop(entry_id, None)
            if removed:
                self._db.sync(self._store.list())
                self._emit_changed()
        return GLib.SOURCE_CONTINUE

    # --- вспомогательное ----------------------------------------------------

    def _prune_thumbs(self) -> None:
        live = {e.id for e in self._store.list()}
        for stale in [i for i in self._thumbs if i not in live]:
            self._thumbs.pop(stale, None)

    def _emit_changed(self) -> None:
        if self._conn is not None:
            self._conn.emit_signal(
                None, OBJECT_PATH, IFACE, "HistoryChanged", None
            )
