"""Tests for image decoding, natural sorting and folder browsing."""

# Standard Library
from pathlib import Path

# Third-party
import cv2
import numpy as np
import pytest

# Local
from pixel_viewer.images import load_image, natural_sort_key


# ================================ natural_sort_key =========================== #
def test_natural_sort_orders_numbers_numerically() -> None:
    names = ["img_10.png", "img_2.png", "IMG_1.png", "img_100.png"]

    ordered = sorted((Path(name) for name in names), key=natural_sort_key)

    assert [path.name for path in ordered] == ["IMG_1.png", "img_2.png", "img_10.png", "img_100.png"]


# ================================== load_image =============================== #
def test_load_color_image_keeps_three_channels(tmp_path: Path) -> None:
    path = tmp_path / "color.png"
    pixels = np.zeros((3, 5, 3), dtype=np.uint8)
    pixels[1, 2] = (10, 20, 30)
    cv2.imwrite(str(path), pixels)

    image = load_image(path)

    assert image.values.shape == (3, 5, 3)
    assert tuple(image.values[1, 2]) == (10, 20, 30)
    assert not image.is_single_channel
    assert not image.is_label_mask
    assert image.size == (5, 3)
    assert image.color_display is not None and image.color_display.flags["C_CONTIGUOUS"]
    assert image.gray_values.shape == (3, 5)


def test_load_rgba_mask_collapses_to_label_ids(tmp_path: Path) -> None:
    path = tmp_path / "mask.png"
    ids = np.array([[0, 7, 7], [13, 20, 0]], dtype=np.uint8)
    rgba = np.dstack([ids, ids, ids, np.full_like(ids, 255)])
    cv2.imwrite(str(path), rgba)

    image = load_image(path)

    assert image.is_single_channel
    assert image.is_label_mask
    np.testing.assert_array_equal(image.values, ids)
    assert image.color_display is None
    assert image.gray_display.shape == (2, 3, 3)


def test_label_colors_are_stable_across_masks(tmp_path: Path) -> None:
    few_ids = np.array([[0, 7]], dtype=np.uint8)
    many_ids = np.array([[0, 7, 20, 13]], dtype=np.uint8)
    cv2.imwrite(str(tmp_path / "a.png"), few_ids)
    cv2.imwrite(str(tmp_path / "b.png"), many_ids)

    first, second = load_image(tmp_path / "a.png"), load_image(tmp_path / "b.png")

    np.testing.assert_array_equal(first.gray_display[0, 1], second.gray_display[0, 1])


def test_grayscale_photo_is_not_a_label_mask(tmp_path: Path) -> None:
    path = tmp_path / "gradient.png"
    cv2.imwrite(str(path), np.tile(np.arange(256, dtype=np.uint8), (4, 1)))

    image = load_image(path)

    assert image.is_single_channel
    assert not image.is_label_mask


def test_load_image_rejects_undecodable_file(tmp_path: Path) -> None:
    path = tmp_path / "broken.png"
    path.write_bytes(b"not a png")

    with pytest.raises(ValueError, match="Could not decode"):
        load_image(path)
