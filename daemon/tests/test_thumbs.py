"""Тест миниатюр (пропускается, если gi/GdkPixbuf недоступны)."""

import pytest

gi = pytest.importorskip("gi")
gi.require_version("GdkPixbuf", "2.0")
from gi.repository import GdkPixbuf  # noqa: E402

from klippad import thumbs  # noqa: E402


def _make_png(w: int, h: int) -> bytes:
    pb = GdkPixbuf.Pixbuf.new(GdkPixbuf.Colorspace.RGB, True, 8, w, h)
    pb.fill(0xFF0000FF)
    ok, buf = pb.save_to_bufferv("png", [], [])
    assert ok
    return bytes(buf)


def test_image_size():
    png = _make_png(64, 48)
    assert thumbs.image_size(png) == (64, 48)


def test_thumbnail_downscales_large_image():
    png = _make_png(800, 400)
    thumb = thumbs.make_thumbnail(png, max_dim=200)
    w, h = thumbs.image_size(thumb)
    assert max(w, h) == 200
    assert (w, h) == (200, 100)  # пропорции сохранены


def test_thumbnail_keeps_small_image():
    png = _make_png(50, 50)
    thumb = thumbs.make_thumbnail(png, max_dim=200)
    assert thumbs.image_size(thumb) == (50, 50)


def test_preview_for_image():
    assert thumbs.preview_for_image(_make_png(120, 90)) == "Изображение 120×90"
    assert thumbs.preview_for_image(b"not a png") == "[изображение]"
