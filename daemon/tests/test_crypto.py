"""Тесты AES-256-GCM (с инъекцией ключа, без обращения к keyring)."""

import pytest

from klippad.crypto import (
    KEY_BYTES,
    Cipher,
    DecryptError,
    generate_key,
)


def test_roundtrip():
    c = Cipher(generate_key())
    for payload in [b"", b"hello", b"\x00\xff\x10binary", "Кириллица".encode("utf-8")]:
        assert c.decrypt(c.encrypt(payload)) == payload


def test_ciphertext_differs_each_time_unique_nonce():
    c = Cipher(generate_key())
    a = c.encrypt(b"same")
    b = c.encrypt(b"same")
    assert a != b                       # разные nonce → разный blob
    assert c.decrypt(a) == c.decrypt(b) == b"same"


def test_ciphertext_is_not_plaintext():
    c = Cipher(generate_key())
    blob = c.encrypt(b"secret-token-123")
    assert b"secret-token-123" not in blob


def test_wrong_key_fails():
    blob = Cipher(generate_key()).encrypt(b"payload")
    with pytest.raises(DecryptError):
        Cipher(generate_key()).decrypt(blob)


def test_tampered_blob_detected():
    c = Cipher(generate_key())
    blob = bytearray(c.encrypt(b"payload"))
    blob[-1] ^= 0x01                    # порча тега/шифртекста
    with pytest.raises(DecryptError):
        c.decrypt(bytes(blob))


def test_too_short_blob():
    c = Cipher(generate_key())
    with pytest.raises(DecryptError):
        c.decrypt(b"short")


def test_invalid_key_length():
    with pytest.raises(ValueError):
        Cipher(b"too-short")
    assert len(generate_key()) == KEY_BYTES
