"""Персистентность истории в зашифрованной SQLite-БД.

Содержимое каждой записи (`data`) шифруется через Cipher перед записью.
Метаданные (kind, ts, source_app, позиция) хранятся открыто; превью НЕ хранится
(производно от содержимого), а пересчитывается при загрузке, чтобы не утекало.

Синхронизация устроена примитивно и надёжно: `sync(entries)` приводит БД в
точное соответствие текущему порядку Store. История мала, поэтому O(N) на
мутацию дёшево, а перешифровка происходит только для новых записей.
"""

from __future__ import annotations

import os
import sqlite3
import sys
import time
from pathlib import Path

from .crypto import Cipher, DecryptError
from .store import IMAGE, TEXT, Entry, _text_preview

APP = "klippa"


class HistoryUnreadable(Exception):
    """БД существует, но ни одна запись не расшифровывается текущим ключом.

    Обычно — ключ в gnome-keyring не соответствует файлу истории (пересоздан,
    другой профиль). Сигнал наверх: отложить файл и стартовать с пустой историей,
    а не падать в краш-цикл.
    """

_SCHEMA = """
CREATE TABLE IF NOT EXISTS entries (
    id          INTEGER PRIMARY KEY,
    kind        TEXT    NOT NULL,
    data        BLOB    NOT NULL,   -- зашифровано Cipher
    source_app  TEXT    NOT NULL DEFAULT '',
    ts          INTEGER NOT NULL,
    pos         INTEGER NOT NULL    -- 0 = голова (самая свежая)
);
CREATE INDEX IF NOT EXISTS idx_entries_pos ON entries(pos);
"""


def default_db_path() -> Path:
    """$XDG_DATA_HOME/klippa/history.db (по умолчанию ~/.local/share/...)."""
    base = os.environ.get("XDG_DATA_HOME") or os.path.expanduser("~/.local/share")
    return Path(base) / APP / "history.db"


def _preview_for(kind: str, data: bytes) -> str:
    return _text_preview(data) if kind == TEXT else "[изображение]"


class Database:
    """Зашифрованное хранилище истории на SQLite."""

    def __init__(self, path: Path, cipher: Cipher) -> None:
        self._path = path
        self._cipher = cipher
        self._open()

    def _open(self) -> None:
        """Открыть (создав при необходимости) файл БД с правами 0600 и схемой."""
        self._path.parent.mkdir(parents=True, exist_ok=True, mode=0o700)
        # Файл создаём с правами 0600 ДО открытия соединения.
        if not self._path.exists():
            fd = os.open(str(self._path), os.O_CREAT | os.O_WRONLY, 0o600)
            os.close(fd)
        else:
            self._path.chmod(0o600)
        self._conn = sqlite3.connect(str(self._path))
        self._conn.executescript(_SCHEMA)
        self._conn.commit()

    def close(self) -> None:
        self._conn.close()

    def load(self) -> list[Entry]:
        """Прочитать записи в порядке MRU (голова первой), расшифровав содержимое.

        Битые/нечитаемые записи пропускаются (частичная порча не должна терять всю
        историю). Если не читается НИ ОДНА запись из непустой БД — ключ не подходит
        ко всему файлу: поднимаем HistoryUnreadable, чтобы вызвавший отложил файл и
        стартовал с пустой историей вместо краш-цикла.
        """
        rows = self._conn.execute(
            "SELECT id, kind, data, source_app, ts FROM entries ORDER BY pos ASC"
        ).fetchall()
        entries: list[Entry] = []
        failed = 0
        for entry_id, kind, blob, source_app, ts in rows:
            try:
                data = self._cipher.decrypt(bytes(blob))
            except DecryptError:
                failed += 1
                continue
            entries.append(
                Entry(
                    id=entry_id,
                    kind=kind,
                    data=data,
                    source_app=source_app,
                    ts=ts,
                    preview=_preview_for(kind, data),
                )
            )
        if failed and not entries:
            raise HistoryUnreadable(
                f"{failed} записей не расшифрованы текущим ключом из gnome-keyring"
            )
        if failed:
            print(
                f"klippad: пропущено {failed} нечитаемых записей из {len(rows)}",
                file=sys.stderr,
                flush=True,
            )
        return entries

    def quarantine(self) -> Path:
        """Отложить нечитаемый файл БД в сторону и открыть новую пустую.

        Данные не теряем (файл сохраняем с пометкой `.unreadable-<время>`), но
        демон стартует с чистой историей. Возвращает путь к сохранённому файлу.
        """
        self._conn.close()
        backup = self._path.with_name(
            f"{self._path.name}.unreadable-{time.strftime('%Y%m%d-%H%M%S')}"
        )
        self._path.rename(backup)
        self._open()
        return backup

    def sync(self, entries: list[Entry]) -> None:
        """Привести БД в точное соответствие списку (entries[0] — голова)."""
        cur = self._conn.cursor()
        existing = {row[0] for row in cur.execute("SELECT id FROM entries")}
        wanted = {e.id for e in entries}

        # удалить отсутствующие
        for stale_id in existing - wanted:
            cur.execute("DELETE FROM entries WHERE id = ?", (stale_id,))

        for pos, entry in enumerate(entries):
            if entry.id in existing:
                # содержимое неизменно — обновляем только позицию и ts (без перешифровки)
                cur.execute(
                    "UPDATE entries SET pos = ?, ts = ?, source_app = ? WHERE id = ?",
                    (pos, entry.ts, entry.source_app, entry.id),
                )
            else:
                cur.execute(
                    "INSERT INTO entries (id, kind, data, source_app, ts, pos) "
                    "VALUES (?, ?, ?, ?, ?, ?)",
                    (
                        entry.id,
                        entry.kind,
                        self._cipher.encrypt(entry.data),
                        entry.source_app,
                        entry.ts,
                        pos,
                    ),
                )
        self._conn.commit()

    def clear(self) -> None:
        self._conn.execute("DELETE FROM entries")
        self._conn.commit()
