"""Tests for the canvas view model: zoom levels, anchoring, clamping, and painting."""

# Standard Library
from collections.abc import Callable
from pathlib import Path

# Third-party
import cv2
import numpy as np
import pytest
from PySide6.QtCore import QPointF

# Local
from pixel_viewer.canvas import PixelCanvas
from pixel_viewer.images import LoadedImage, load_image

CANVAS_SIZE = (800, 600)


# ================================== Fixtures ================================= #
@pytest.fixture
def canvas(qtbot) -> PixelCanvas:
    """An 800×600 canvas with no image."""
    widget = PixelCanvas()
    qtbot.addWidget(widget)
    widget.resize(*CANVAS_SIZE)
    return widget


@pytest.fixture
def make_image(tmp_path: Path) -> Callable[[np.ndarray], LoadedImage]:
    """Writes an array to a PNG and loads it back the way the app does."""

    def make(pixels: np.ndarray) -> LoadedImage:
        path = tmp_path / f"image_{len(list(tmp_path.iterdir()))}.png"
        cv2.imwrite(str(path), pixels)
        return load_image(path)

    return make


def color_image(width: int, height: int) -> np.ndarray:
    """A BGR gradient, so neighbouring pixels differ."""
    pixels = np.zeros((height, width, 3), dtype=np.uint8)
    pixels[:, :, 0] = np.arange(width, dtype=np.uint32)[None, :] % 256
    pixels[:, :, 2] = np.arange(height, dtype=np.uint32)[:, None] % 256
    return pixels


# ================================== View state =============================== #
def test_new_image_fits_and_centres(canvas: PixelCanvas, make_image) -> None:
    canvas.set_image(make_image(color_image(400, 300)))

    assert canvas.is_fit
    assert canvas.zoom == pytest.approx(2.0)
    assert canvas.screen_to_image(QPointF(400, 300)) == QPointF(200, 150)


def test_zoom_keeps_point_under_anchor(canvas: PixelCanvas, make_image) -> None:
    canvas.set_image(make_image(color_image(800, 600)))
    anchor = QPointF(123, 321)
    before = canvas.screen_to_image(anchor)

    canvas.zoom_by_steps(3, anchor)

    after = canvas.screen_to_image(anchor)
    assert canvas.zoom == 4
    assert abs(after.x() - before.x()) <= 0.5 / canvas.zoom
    assert abs(after.y() - before.y()) <= 0.5 / canvas.zoom


def test_zoom_out_returns_to_fit(canvas: PixelCanvas, make_image) -> None:
    canvas.set_image(make_image(color_image(1600, 1200)))
    canvas.zoom_by_steps(2)

    canvas.zoom_by_steps(-10)

    assert canvas.is_fit
    assert canvas.zoom == pytest.approx(0.5)


def test_pan_is_clamped_to_image(canvas: PixelCanvas, make_image) -> None:
    canvas.set_image(make_image(color_image(800, 600)))
    canvas.zoom_by_steps(1)

    for _ in range(20):
        canvas.pan_by_fraction(-1, -1)

    assert canvas.pixel_at(QPointF(0, 0)) == (0, 0)


def test_pixel_at_outside_image_is_none(canvas: PixelCanvas, make_image) -> None:
    canvas.set_image(make_image(color_image(400, 400)))

    assert canvas.pixel_at(QPointF(10, 300)) is None
    assert canvas.pixel_at(QPointF(401, 301)) == (200, 200)


def test_keep_view_preserves_zoom_and_centre(canvas: PixelCanvas, make_image) -> None:
    canvas.set_image(make_image(color_image(800, 600)))
    canvas.zoom_by_steps(4, QPointF(100, 100))
    zoom, centre = canvas.zoom, canvas.screen_to_image(QPointF(400, 300))

    canvas.set_image(make_image(color_image(800, 600)), keep_view=True)

    assert canvas.zoom == zoom
    assert canvas.screen_to_image(QPointF(400, 300)) == centre

    canvas.set_image(make_image(color_image(800, 600)))
    assert canvas.is_fit


def test_single_channel_images_are_always_gray(canvas: PixelCanvas, make_image) -> None:
    canvas.set_image(make_image(np.array([[0, 7], [13, 0]], dtype=np.uint8)))

    canvas.set_gray(False)

    assert canvas.is_gray


# =================================== Painting ================================ #
def test_paints_placeholder_without_image(canvas: PixelCanvas) -> None:
    assert not canvas.grab().isNull()
