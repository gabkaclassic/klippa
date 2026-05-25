"""Тесты персистентности: шифрованная БД, восстановление порядка, права, очистка."""

from klippad.crypto import Cipher, generate_key
from klippad.db import Database
from klippad.store import IMAGE, TEXT, Store


def _store_with(texts):
    s = Store(max_entries=50)
    for t in texts:
        s.add(TEXT, t.encode("utf-8"))
    return s


def _fixed_cipher():
    # фиксированный ключ — детерминизм между «перезапусками» в одном тесте
    return Cipher(b"k" * 32)


def test_sync_and_reload_preserves_order(tmp_path):
    key = generate_key()
    db = Database(tmp_path / "h.db", Cipher(key))
    s = _store_with(["a", "b", "c"])      # порядок MRU: c, b, a
    db.sync(s.list())
    db.close()

    db2 = Database(tmp_path / "h.db", Cipher(key))
    loaded = db2.load()
    assert [e.preview for e in loaded] == ["c", "b", "a"]
    db2.close()


def test_reload_into_store_restores_mru(tmp_path):
    c = _fixed_cipher()
    db = Database(tmp_path / "h.db", c)
    s = _store_with(["x", "y", "z"])
    s.promote(s.list()[-1].id)            # поднять самую старую (x) в голову
    db.sync(s.list())
    db.close()

    db2 = Database(tmp_path / "h.db", _fixed_cipher())
    s2 = Store(max_entries=50)
    s2.load(db2.load())
    assert [e.preview for e in s2.list()] == ["x", "z", "y"]
    db2.close()


def test_blob_on_disk_is_encrypted(tmp_path):
    db = Database(tmp_path / "h.db", _fixed_cipher())
    db.sync(_store_with(["super-secret-value"]).list())
    db.close()
    raw = (tmp_path / "h.db").read_bytes()
    assert b"super-secret-value" not in raw


def test_db_file_permissions_0600(tmp_path):
    p = tmp_path / "h.db"
    Database(p, _fixed_cipher()).close()
    assert (p.stat().st_mode & 0o777) == 0o600


def test_clear_empties_db(tmp_path):
    c = _fixed_cipher()
    db = Database(tmp_path / "h.db", c)
    db.sync(_store_with(["a", "b"]).list())
    db.clear()
    db.close()
    db2 = Database(tmp_path / "h.db", _fixed_cipher())
    assert db2.load() == []
    db2.close()


def test_sync_deletes_removed_entries(tmp_path):
    c = _fixed_cipher()
    db = Database(tmp_path / "h.db", c)
    s = _store_with(["a", "b", "c"])
    db.sync(s.list())
    # удалить b из стора и пересинхронить
    target = next(e for e in s.list() if e.preview == "b")
    s.delete(target.id)
    db.sync(s.list())
    db.close()

    db2 = Database(tmp_path / "h.db", _fixed_cipher())
    assert sorted(e.preview for e in db2.load()) == ["a", "c"]
    db2.close()


def test_image_entry_roundtrip(tmp_path):
    c = _fixed_cipher()
    db = Database(tmp_path / "h.db", c)
    s = Store(max_entries=50)
    png = b"\x89PNG\r\n\x1a\n fake image bytes"
    s.add(IMAGE, png, preview="Изображение 4×4")
    db.sync(s.list())
    db.close()

    db2 = Database(tmp_path / "h.db", _fixed_cipher())
    loaded = db2.load()
    assert len(loaded) == 1
    assert loaded[0].kind == IMAGE
    assert loaded[0].data == png          # содержимое восстановлено побайтово
    db2.close()
