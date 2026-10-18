"""Tests for the application icon."""

# Standard Library
from io import BytesIO

# Third-party
import pytest
from PIL import Image

# Local
from pixel_viewer.icons import render_icon, render_icon_png


def test_icon_is_a_square_png() -> None:
    image = Image.open(BytesIO(render_icon_png(128)))

    assert image.format == "PNG"
    assert image.size == (128, 128)
    assert image.mode == "RGBA"
    # The amber cell is near the top centre, so the mark is not a flat fill.
    assert image.getpixel((64, 40))[0] > 180


def test_icon_rejects_a_size_that_cannot_hold_the_grid() -> None:
    with pytest.raises(ValueError):
        render_icon(8)
