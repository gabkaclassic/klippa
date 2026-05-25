"""Модель записи и кольцевой буфер истории буфера обмена.

Чистый Python без зависимостей от gi — полностью покрывается unit-тестами.
Порядок хранения: индекс 0 — самая свежая запись (MRU-голова).
"""

from __future__ import annotations

import hashlib
import time
from dataclasses import dataclass, field

TEXT = "text"
IMAGE = "image"

_PREVIEW_LEN = 80


def _content_hash(kind: str, data: bytes) -> str:
    """Хеш содержимого для дедупликации (kind + байты)."""
    h = hashlib.sha256()
    h.update(kind.encode("utf-8"))
    h.update(b"\x00")
    h.update(data)
    return h.hexdigest()


def _text_preview(data: bytes) -> str:
    """Однострочное превью текста: первая непустая строка, схлопнутые пробелы."""
    text = data.decode("utf-8", "replace")
    for line in text.splitlines():
        stripped = " ".join(line.split())
        if stripped:
            return stripped[:_PREVIEW_LEN]
    # текст из одних пробелов/переводов строк
    collapsed = " ".join(text.split())
    return collapsed[:_PREVIEW_LEN]


@dataclass
class Entry:
    """Одна запись истории."""

    id: int
    kind: str
    data: bytes
    source_app: str
    ts: int
    preview: str
    content_hash: str = field(default="")

    def __post_init__(self) -> None:
        if not self.content_hash:
            self.content_hash = _content_hash(self.kind, self.data)

    def meta(self) -> dict:
        """Лёгкие метаданные для GetHistory (без тяжёлых данных)."""
        return {
            "id": self.id,
            "kind": self.kind,
            "preview": self.preview,
            "has_image": self.kind == IMAGE,
            "ts": self.ts,
        }


class Store:
    """Кольцевой буфер с дедупликацией и MRU-порядком.

    Повторное добавление существующего содержимого не создаёт дубль, а поднимает
    запись в голову (MRU) и обновляет ts. При переполнении вытесняется хвост
    (самая старая запись).
    """

    def __init__(self, max_entries: int = 50) -> None:
        if max_entries < 1:
            raise ValueError("max_entries должно быть >= 1")
        self._max = max_entries
        self._entries: list[Entry] = []          # [0] — самая свежая
        self._by_id: dict[int, Entry] = {}
        self._by_hash: dict[str, Entry] = {}
        self._next_id = 1

    # --- запись -------------------------------------------------------------

    def add(
        self,
        kind: str,
        data: bytes,
        source_app: str = "",
        ts: int | None = None,
        preview: str | None = None,
    ) -> Entry:
        """Добавить запись или поднять существующую (dedup/MRU). Возвращает запись."""
        if kind not in (TEXT, IMAGE):
            raise ValueError(f"неизвестный kind: {kind!r}")
        ts = int(time.time()) if ts is None else int(ts)
        chash = _content_hash(kind, data)

        existing = self._by_hash.get(chash)
        if existing is not None:
            existing.ts = ts
            existing.source_app = source_app or existing.source_app
            self._move_to_front(existing)
            return existing

        if preview is None:
            preview = _text_preview(data) if kind == TEXT else "[изображение]"
        entry = Entry(
            id=self._next_id,
            kind=kind,
            data=data,
            source_app=source_app,
            ts=ts,
            preview=preview,
            content_hash=chash,
        )
        self._next_id += 1
        self._entries.insert(0, entry)
        self._by_id[entry.id] = entry
        self._by_hash[chash] = entry
        self._evict()
        return entry

    def load(self, entries: list[Entry]) -> None:
        """Загрузить записи из персистентного слоя (порядок: свежие первыми)."""
        self.clear()
        for entry in entries:
            self._entries.append(entry)
            self._by_id[entry.id] = entry
            self._by_hash[entry.content_hash] = entry
            self._next_id = max(self._next_id, entry.id + 1)
        self._evict()

    # --- чтение -------------------------------------------------------------

    def list(self, limit: int = 0) -> list[Entry]:
        """Записи, свежие первыми. limit=0 — все."""
        if limit <= 0:
            return list(self._entries)
        return self._entries[:limit]

    def get(self, entry_id: int) -> Entry | None:
        return self._by_id.get(entry_id)

    def __len__(self) -> int:
        return len(self._entries)

    # --- мутации ------------------------------------------------------------

    def promote(self, entry_id: int) -> bool:
        """Поднять запись в голову (MRU). True, если запись существовала."""
        entry = self._by_id.get(entry_id)
        if entry is None:
            return False
        self._move_to_front(entry)
        return True

    def delete(self, entry_id: int) -> bool:
        """Удалить запись. True, если она существовала."""
        entry = self._by_id.pop(entry_id, None)
        if entry is None:
            return False
        self._by_hash.pop(entry.content_hash, None)
        self._entries.remove(entry)
        return True

    def clear(self) -> None:
        self._entries.clear()
        self._by_id.clear()
        self._by_hash.clear()

    def expire_older_than(self, cutoff_ts: int) -> list[int]:
        """Удалить записи старше cutoff_ts. Возвращает id удалённых (для синка БД)."""
        stale = [e.id for e in self._entries if e.ts < cutoff_ts]
        for entry_id in stale:
            self.delete(entry_id)
        return stale

    # --- конфигурация -------------------------------------------------------

    @property
    def max_entries(self) -> int:
        return self._max

    def set_max_entries(self, n: int) -> list[int]:
        """Сменить ёмкость. Возвращает id вытесненных записей (для синка БД)."""
        if n < 1:
            raise ValueError("max_entries должно быть >= 1")
        self._max = n
        return self._evict()

    # --- внутреннее ---------------------------------------------------------

    def _move_to_front(self, entry: Entry) -> None:
        self._entries.remove(entry)
        self._entries.insert(0, entry)

    def _evict(self) -> list[int]:
        """Вытеснить хвост сверх ёмкости. Возвращает id вытесненных."""
        evicted: list[int] = []
        while len(self._entries) > self._max:
            old = self._entries.pop()
            self._by_id.pop(old.id, None)
            self._by_hash.pop(old.content_hash, None)
            evicted.append(old.id)
        return evicted
