"""Шифрование содержимого записей (AES-256-GCM) и хранение ключа в gnome-keyring.

Класс `Cipher` принимает ключ напрямую и покрыт тестами (round-trip без keyring).
`get_or_create_key` обращается к libsecret (Secret) и проверяется вручную.
"""

from __future__ import annotations

import base64
import os

from cryptography.exceptions import InvalidTag
from cryptography.hazmat.primitives.ciphers.aead import AESGCM

KEY_BYTES = 32   # AES-256
NONCE_BYTES = 12  # рекомендованный размер nonce для GCM


class DecryptError(Exception):
    """Не удалось расшифровать (битые данные или неверный ключ)."""


class Cipher:
    """AES-256-GCM. Формат blob: nonce(12) || ciphertext+tag.

    Каждое значение шифруется уникальным случайным nonce; тег GCM обеспечивает
    целостность (порча байтов БД обнаруживается при расшифровке).
    """

    def __init__(self, key: bytes) -> None:
        if len(key) != KEY_BYTES:
            raise ValueError(f"ключ должен быть {KEY_BYTES} байт, получено {len(key)}")
        self._aes = AESGCM(key)

    def encrypt(self, plaintext: bytes) -> bytes:
        nonce = os.urandom(NONCE_BYTES)
        return nonce + self._aes.encrypt(nonce, plaintext, None)

    def decrypt(self, blob: bytes) -> bytes:
        if len(blob) <= NONCE_BYTES:
            raise DecryptError("слишком короткий blob")
        nonce, ct = blob[:NONCE_BYTES], blob[NONCE_BYTES:]
        try:
            return self._aes.decrypt(nonce, ct, None)
        except InvalidTag as exc:
            raise DecryptError("неверный тег GCM (битые данные или ключ)") from exc


def generate_key() -> bytes:
    """Случайный 256-битный ключ."""
    return os.urandom(KEY_BYTES)


# --- хранение ключа в gnome-keyring (libsecret) -----------------------------

_KEYRING_LABEL = "klippa clipboard encryption key"
_ATTRS = {"app": "klippa", "purpose": "history-encryption"}


def _schema():
    import gi

    gi.require_version("Secret", "1")
    from gi.repository import Secret

    return Secret, Secret.Schema.new(
        "org.klippa.Key",
        Secret.SchemaFlags.NONE,
        {
            "app": Secret.SchemaAttributeType.STRING,
            "purpose": Secret.SchemaAttributeType.STRING,
        },
    )


def get_or_create_key() -> bytes:
    """Достать ключ из gnome-keyring; при отсутствии — создать и сохранить.

    Ключ хранится base64-строкой в дефолтной коллекции (libsecret), а не рядом
    с БД. Импорт gi отложен, чтобы модуль импортировался в тестах без gi.
    """
    Secret, schema = _schema()

    stored = Secret.password_lookup_sync(schema, _ATTRS, None)
    if stored:
        try:
            key = base64.b64decode(stored)
        except (ValueError, TypeError):
            key = b""
        if len(key) == KEY_BYTES:
            return key
        # повреждённое значение — пересоздаём

    key = generate_key()
    Secret.password_store_sync(
        schema,
        _ATTRS,
        Secret.COLLECTION_DEFAULT,
        _KEYRING_LABEL,
        base64.b64encode(key).decode("ascii"),
        None,
    )
    return key


def make_cipher_from_keyring() -> Cipher:
    """Удобный конструктор: Cipher на ключе из gnome-keyring."""
    return Cipher(get_or_create_key())
