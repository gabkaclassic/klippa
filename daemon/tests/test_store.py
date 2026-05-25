"""Тесты ядра хранилища: ring-buffer, dedup/MRU, promote/delete/clear, eviction."""

from klippad.store import IMAGE, TEXT, Entry, Store


def _txt(store: Store, s: str, **kw) -> Entry:
    return store.add(TEXT, s.encode("utf-8"), **kw)


def test_add_and_order_newest_first():
    s = Store(max_entries=10)
    _txt(s, "first")
    _txt(s, "second")
    previews = [e.preview for e in s.list()]
    assert previews == ["second", "first"]


def test_eviction_keeps_max_and_drops_oldest():
    s = Store(max_entries=3)
    for i in range(5):
        _txt(s, f"v{i}")
    assert len(s) == 3
    previews = [e.preview for e in s.list()]
    assert previews == ["v4", "v3", "v2"]  # v0, v1 вытеснены


def test_dedup_promotes_existing_without_duplicate():
    s = Store(max_entries=10)
    first = _txt(s, "dup")
    _txt(s, "other")
    again = _txt(s, "dup")
    assert again.id == first.id            # та же запись, не новая
    assert len(s) == 2                     # дубля нет
    assert s.list()[0].id == first.id      # поднята в голову


def test_dedup_updates_ts():
    s = Store(max_entries=10)
    e = _txt(s, "x", ts=1000)
    _txt(s, "x", ts=2000)
    assert e.ts == 2000


def test_promote_moves_to_front():
    s = Store(max_entries=10)
    a = _txt(s, "a")
    _txt(s, "b")
    _txt(s, "c")
    assert s.promote(a.id) is True
    assert s.list()[0].id == a.id
    assert s.promote(99999) is False


def test_delete():
    s = Store(max_entries=10)
    a = _txt(s, "a")
    _txt(s, "b")
    assert s.delete(a.id) is True
    assert s.get(a.id) is None
    assert len(s) == 1
    assert s.delete(a.id) is False         # повторное — уже нет


def test_clear():
    s = Store(max_entries=10)
    _txt(s, "a")
    _txt(s, "b")
    s.clear()
    assert len(s) == 0
    assert s.list() == []


def test_set_max_entries_trims_and_reports_evicted():
    s = Store(max_entries=10)
    ids = [_txt(s, f"v{i}").id for i in range(5)]
    evicted = s.set_max_entries(2)
    assert s.max_entries == 2
    assert len(s) == 2
    # вытеснены самые старые (v0, v1, v2)
    assert set(evicted) == {ids[0], ids[1], ids[2]}


def test_text_preview_single_line_collapsed_and_truncated():
    s = Store(max_entries=10)
    e = _txt(s, "  \n\n  hello   world  \nsecond line")
    assert e.preview == "hello world"
    long = _txt(s, "x" * 200)
    assert len(long.preview) == 80


def test_image_default_preview_and_has_image_meta():
    s = Store(max_entries=10)
    e = s.add(IMAGE, b"\x89PNG fake", preview="Изображение 4×4")
    assert e.kind == IMAGE
    meta = e.meta()
    assert meta["has_image"] is True
    assert meta["preview"] == "Изображение 4×4"


def test_image_and_text_with_same_bytes_are_not_deduped():
    s = Store(max_entries=10)
    s.add(TEXT, b"payload")
    s.add(IMAGE, b"payload")
    assert len(s) == 2  # дедуп учитывает kind


def test_load_replaces_and_sets_next_id_above_max():
    s = Store(max_entries=10)
    entries = [
        Entry(id=5, kind=TEXT, data=b"a", source_app="", ts=1, preview="a"),
        Entry(id=9, kind=TEXT, data=b"b", source_app="", ts=2, preview="b"),
    ]
    s.load(entries)
    assert len(s) == 2
    new = _txt(s, "c")
    assert new.id == 10  # next_id = max(id)+1


def test_expire_older_than():
    s = Store(max_entries=10)
    old = _txt(s, "old", ts=100)
    fresh = _txt(s, "fresh", ts=5000)
    removed = s.expire_older_than(1000)
    assert removed == [old.id]
    assert s.get(fresh.id) is not None


def test_invalid_kind_and_max():
    import pytest

    s = Store(max_entries=1)
    try:
        s.add("video", b"x")
        assert False, "ожидался ValueError"
    except ValueError:
        pass
    with pytest.raises(ValueError):
        Store(max_entries=0)
