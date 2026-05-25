"""Генерация миниатюр изображений через GdkPixbuf (только в памяти, без диска).

gi-слой: проверяется тестом с pytest.importorskip и ручным smoke. На диск ничего
не пишется — миниатюры живут в памяти демона и отдаются по D-Bus.
"""

from __future__ import annotations

import gi

gi.require_version("GdkPixbuf", "2.0")
from gi.repository import GdkPixbuf  # noqa: E402

THUMB_MAX_DIM = 200  # px по большей стороне


def _load(png_bytes: bytes) -> "GdkPixbuf.Pixbuf":
    loader = GdkPixbuf.PixbufLoader.new_with_type("png")
    loader.write(png_bytes)
    loader.close()
    pixbuf = loader.get_pixbuf()
    if pixbuf is None:
        raise ValueError("не удалось декодировать PNG")
    return pixbuf


def image_size(png_bytes: bytes) -> tuple[int, int]:
    pixbuf = _load(png_bytes)
    return pixbuf.get_width(), pixbuf.get_height()


def make_thumbnail(png_bytes: bytes, max_dim: int = THUMB_MAX_DIM) -> bytes:
    """Уменьшить картинку до max_dim по большей стороне и вернуть PNG-байты."""
    pixbuf = _load(png_bytes)
    w, h = pixbuf.get_width(), pixbuf.get_height()
    longest = max(w, h)
    if longest > max_dim:
        scale = max_dim / longest
        pixbuf = pixbuf.scale_simple(
            max(1, round(w * scale)),
            max(1, round(h * scale)),
            GdkPixbuf.InterpType.BILINEAR,
        )
    ok, buffer = pixbuf.save_to_bufferv("png", [], [])
    if not ok:
        raise ValueError("не удалось сериализовать миниатюру")
    return bytes(buffer)


def preview_for_image(png_bytes: bytes) -> str:
    """Текстовое превью для записи-картинки: размеры или фолбэк."""
    try:
        w, h = image_size(png_bytes)
        return f"Изображение {w}×{h}"
    except Exception:
        return "[изображение]"
