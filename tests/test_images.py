"""Tests for image decoding, natural sorting and folder browsing."""

# Standard Library
from pathlib import Path

# Third-party
import cv2
import numpy as np
import pytest

# Local
from pixel_viewer import images
from pixel_viewer.images import CACHE_SIZE, PREFETCH_RADIUS, ImageFolder, load_image, natural_sort_key


# ================================== Fixtures ================================= #
@pytest.fixture
def image_folder(tmp_path: Path) -> Path:
    """A folder with numbered PNGs in non-natural name order, plus a non-image file."""
    for number in (10, 2, 1, 33, 3):
        pixels = np.full((4, 6, 3), number, dtype=np.uint8)
        pixels[0, 0] = (number, 0, 255)
        cv2.imwrite(str(tmp_path / f"img_{number}.png"), pixels)
    (tmp_path / "notes.txt").write_text("not an image")
    (tmp_path / ".img_0.png").write_bytes(b"hidden macOS metadata")
    return tmp_path


class CountingLoader:
    """Loader stand-in that records every path it decodes."""

    def __init__(self) -> None:
        self.calls: list[Path] = []

    def __call__(self, path: Path) -> images.LoadedImage:
        self.calls.append(path)
        return load_image(path)


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


# ================================= ImageFolder =============================== #
def test_folder_lists_only_images_in_natural_order(image_folder: Path) -> None:
    folder = ImageFolder(image_folder / "img_3.png")

    try:
        assert [path.name for path in folder.paths] == [
            "img_1.png",
            "img_2.png",
            "img_3.png",
            "img_10.png",
            "img_33.png",
        ]
        assert folder.current_path.name == "img_3.png"
    finally:
        folder.close()


def test_opening_a_folder_starts_at_first_image(image_folder: Path) -> None:
    folder = ImageFolder(image_folder)

    try:
        assert folder.index == 0
    finally:
        folder.close()


def test_move_to_clamps_and_reports_changes(image_folder: Path) -> None:
    folder = ImageFolder(image_folder)

    try:
        assert not folder.move_to(-1)
        assert folder.move_to(99)
        assert folder.current_path.name == "img_33.png"
        assert not folder.move_to(folder.index + 1)
    finally:
        folder.close()


def test_current_decodes_once_and_prefetches_neighbours(image_folder: Path) -> None:
    loader = CountingLoader()
    folder = ImageFolder(image_folder / "img_3.png", loader=loader)

    try:
        first = folder.current()
        again = folder.current()
        folder._executor.shutdown(wait=True)

        assert first is again
        assert loader.calls.count(image_folder.resolve() / "img_3.png") == 1
        assert {path.name for path in loader.calls} == {
            "img_1.png",
            "img_2.png",
            "img_3.png",
            "img_10.png",
            "img_33.png",
        }
    finally:
        folder.close()


def test_cache_never_exceeds_limit(image_folder: Path) -> None:
    for number in range(40, 40 + CACHE_SIZE + PREFETCH_RADIUS * 2):
        cv2.imwrite(str(image_folder / f"img_{number}.png"), np.zeros((2, 2, 3), dtype=np.uint8))
    folder = ImageFolder(image_folder)

    try:
        for index in range(len(folder.paths)):
            folder.move_to(index)
            folder.current()
            assert len(folder._cache) <= CACHE_SIZE
            assert folder.current_path in folder._cache
    finally:
        folder.close()


def test_folder_errors(tmp_path: Path) -> None:
    (tmp_path / "notes.txt").write_text("x")

    with pytest.raises(FileNotFoundError, match="No such file"):
        ImageFolder(tmp_path / "missing.png")
    with pytest.raises(FileNotFoundError, match="No supported images"):
        ImageFolder(tmp_path)
    with pytest.raises(ValueError, match="Unsupported image type"):
        ImageFolder(tmp_path / "notes.txt")


def test_undecodable_current_image_raises_and_can_retry(image_folder: Path) -> None:
    (image_folder / "img_0.png").write_bytes(b"broken")
    folder = ImageFolder(image_folder / "img_0.png")

    try:
        with pytest.raises(ValueError):
            folder.current()
        assert folder.current_path not in folder._cache
    finally:
        folder.close()
