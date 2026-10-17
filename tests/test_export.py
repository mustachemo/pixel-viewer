"""Tests for GIF and MP4 export."""

# Standard Library
from pathlib import Path

# Third-party
import cv2
import numpy as np
import pytest
from PIL import Image

# Local
from pixel_viewer.export import (
    MAX_FPS,
    MIN_FPS,
    AnimationExport,
    ExportCancelled,
    ExportError,
    animation_destinations,
    export_gif,
    export_video,
)


# ================================== Helpers ================================== #
def _solid(folder: Path, name: str, bgr: tuple[int, int, int], size: tuple[int, int] = (4, 6)) -> Path:
    """Writes a flat BGR image. ``size`` is (height, width)."""
    height, width = size
    pixels = np.zeros((height, width, 3), dtype=np.uint8)
    pixels[:] = bgr
    path = folder / name
    cv2.imwrite(str(path), pixels)
    return path


def _gif_info(path: Path) -> tuple[list[tuple[int, int, int]], list[int], object, tuple[int, int]]:
    """Returns corner RGB pixels, per-frame delays in ms, the loop count and the image size."""
    pixels: list[tuple[int, int, int]] = []
    durations: list[int] = []
    with Image.open(path) as image:
        loop = image.info.get("loop")
        size = image.size
        for index in range(image.n_frames):
            image.seek(index)
            pixel = image.convert("RGB").getpixel((0, 0))
            pixels.append((int(pixel[0]), int(pixel[1]), int(pixel[2])))
            durations.append(int(image.info.get("duration", 0)))
    return pixels, durations, loop, size


def _video_info(path: Path) -> tuple[int, tuple[int, int, int] | None, float]:
    """Returns the frame count, the last frame's shape and the container frame rate."""
    capture = cv2.VideoCapture(str(path))
    fps = capture.get(cv2.CAP_PROP_FPS)
    count = 0
    shape: tuple[int, int, int] | None = None
    while True:
        ok, frame = capture.read()
        if not ok:
            break
        count += 1
        shape = frame.shape
    capture.release()
    return count, shape, fps


# ================================== Destinations ============================= #
def test_animation_destinations_keep_dots_in_the_name(tmp_path: Path) -> None:
    gif, video = animation_destinations(tmp_path / "my.dataset", gif=True, video=True)

    assert gif == tmp_path / "my.dataset.gif"
    assert video == tmp_path / "my.dataset.mp4"


def test_animation_destinations_replace_a_single_suffix(tmp_path: Path) -> None:
    gif, video = animation_destinations(tmp_path / "clip.mp4", gif=True, video=False)

    assert gif == tmp_path / "clip.gif"
    assert video is None


def test_animation_export_rejects_an_empty_selection() -> None:
    with pytest.raises(ExportError, match="No images"):
        AnimationExport((), 10, gif_path=Path("clip.gif"))


def test_animation_export_rejects_a_rate_outside_the_range() -> None:
    with pytest.raises(ExportError, match=f"between {MIN_FPS} and {MAX_FPS}"):
        AnimationExport((Path("frame.png"),), 0, gif_path=Path("clip.gif"))


def test_animation_export_requires_a_format() -> None:
    with pytest.raises(ExportError, match="GIF"):
        AnimationExport((Path("frame.png"),), 10)


def test_animation_destinations_reject_a_bare_suffix(tmp_path: Path) -> None:
    with pytest.raises(ExportError, match="file name"):
        animation_destinations(tmp_path / ".gif", gif=True, video=False)


# ===================================== GIF =================================== #
def test_gif_keeps_path_order_rate_and_loops(tmp_path: Path) -> None:
    paths = [
        _solid(tmp_path, "red.png", (0, 0, 255)),
        _solid(tmp_path, "green.png", (0, 255, 0)),
        _solid(tmp_path, "blue.png", (255, 0, 0)),
    ]

    export_gif(list(reversed(paths)), tmp_path / "clip.gif", 24)

    pixels, durations, loop, size = _gif_info(tmp_path / "clip.gif")
    assert size == (6, 4)
    assert loop == 0
    assert durations == [40, 40, 40]
    assert pixels[0][2] > 250 and pixels[0][0] < 5
    assert pixels[1][1] > 250 and pixels[1][0] < 5
    assert pixels[2][0] > 250 and pixels[2][1] < 5


def test_single_frame_gif(tmp_path: Path) -> None:
    path = _solid(tmp_path, "only.png", (0, 0, 255))

    export_gif([path], tmp_path / "only.gif", 10)

    _pixels, durations, loop, size = _gif_info(tmp_path / "only.gif")
    assert size == (6, 4)
    assert durations == [100]
    assert loop == 0


def test_label_mask_gif_uses_the_viewer_colors(tmp_path: Path) -> None:
    mask = np.full((4, 6), 7, dtype=np.uint8)
    path = tmp_path / "mask.png"
    cv2.imwrite(str(path), mask)

    export_gif([path], tmp_path / "mask.gif", 10)

    pixels, _durations, _loop, _size = _gif_info(tmp_path / "mask.gif")
    red, green, blue = pixels[0]
    assert max(red, green, blue) - min(red, green, blue) > 20


def test_sixteen_bit_gif_exports(tmp_path: Path) -> None:
    path = tmp_path / "wide.png"
    cv2.imwrite(str(path), np.full((4, 6), 1000, dtype=np.uint16))

    export_gif([path], tmp_path / "wide.gif", 10)

    _pixels, _durations, _loop, size = _gif_info(tmp_path / "wide.gif")
    assert size == (6, 4)


# ==================================== Video ================================== #
def test_video_falls_back_when_h264_is_unavailable(tmp_path: Path, mocker) -> None:
    path = _solid(tmp_path, "frame.png", (0, 0, 255), size=(8, 8))
    real_writer = cv2.VideoWriter
    attempts: list[int] = []

    def open_writer(filename: str, fourcc: int, fps: float, size: tuple[int, int]) -> cv2.VideoWriter:
        attempts.append(fourcc)
        if len(attempts) == 1:
            unavailable = real_writer(filename, fourcc, fps, (0, 0))
            unavailable.release()
            return unavailable
        return real_writer(filename, fourcc, fps, size)

    mocker.patch("pixel_viewer.export.cv2.VideoWriter", side_effect=open_writer)

    export_video([path], tmp_path / "clip.mp4", 10)

    assert len(attempts) == 2
    count, shape, fps = _video_info(tmp_path / "clip.mp4")
    assert count == 1
    assert shape == (8, 8, 3)
    assert fps == pytest.approx(10)


def test_video_keeps_path_order_and_rate(tmp_path: Path) -> None:
    paths = [
        _solid(tmp_path, "red.png", (0, 0, 255), size=(8, 8)),
        _solid(tmp_path, "green.png", (0, 255, 0), size=(8, 8)),
    ]

    note = export_video(paths, tmp_path / "clip.mp4", 10)

    count, shape, fps = _video_info(tmp_path / "clip.mp4")
    assert note is None
    assert count == 2
    assert shape == (8, 8, 3)
    assert fps == pytest.approx(10)


def test_odd_frame_stays_exact_in_gif_and_is_padded_in_video(tmp_path: Path) -> None:
    path = _solid(tmp_path, "odd.png", (20, 40, 60), size=(7, 5))

    export_gif([path], tmp_path / "odd.gif", 10)
    note = export_video([path], tmp_path / "odd.mp4", 10)

    _pixels, _durations, _loop, size = _gif_info(tmp_path / "odd.gif")
    count, shape, _fps = _video_info(tmp_path / "odd.mp4")
    assert size == (5, 7)
    assert count == 1
    assert shape == (8, 6, 3)
    assert note is not None
    assert "6 × 8" in note
    assert "5 × 7" in note


# ==================================== Errors ================================= #
def test_size_mismatch_keeps_the_existing_file(tmp_path: Path) -> None:
    first = _solid(tmp_path, "a.png", (0, 0, 255))
    second = _solid(tmp_path, "b.png", (0, 255, 0), size=(8, 8))
    destination = tmp_path / "clip.gif"
    destination.write_bytes(b"keep")

    with pytest.raises(ExportError, match="same size"):
        export_gif([first, second], destination, 10)

    assert destination.read_bytes() == b"keep"
    assert list(tmp_path.glob(".*partial*")) == []


def test_undecodable_image_raises(tmp_path: Path) -> None:
    good = _solid(tmp_path, "a.png", (0, 0, 255))
    bad = tmp_path / "bad.png"
    bad.write_bytes(b"not a png")

    with pytest.raises(ExportError, match="Could not decode"):
        export_gif([good, bad], tmp_path / "clip.gif", 10)


def test_cancel_leaves_the_existing_gif_in_place(tmp_path: Path) -> None:
    paths = [
        _solid(tmp_path, "a.png", (0, 0, 255)),
        _solid(tmp_path, "b.png", (0, 255, 0)),
    ]
    destination = tmp_path / "clip.gif"
    destination.write_bytes(b"old")
    seen: list[int] = []

    def on_frame(index: int, _count: int) -> None:
        seen.append(index)

    with pytest.raises(ExportCancelled):
        export_gif(paths, destination, 10, on_frame=on_frame, cancelled=lambda: len(seen) >= 1)

    assert destination.read_bytes() == b"old"
    assert list(tmp_path.glob(".*partial*")) == []


def test_wrong_suffix_and_missing_folder_raise(tmp_path: Path) -> None:
    path = _solid(tmp_path, "a.png", (0, 0, 255))

    with pytest.raises(ExportError, match=r"\.mp4"):
        export_video([path], tmp_path / "clip.avi", 10)
    with pytest.raises(ExportError, match="No such folder"):
        export_gif([path], tmp_path / "missing" / "clip.gif", 10)


def test_empty_export_raises(tmp_path: Path) -> None:
    with pytest.raises(ExportError, match="No images"):
        export_gif([], tmp_path / "clip.gif", 10)


def test_fps_outside_the_dialog_range_raises(tmp_path: Path) -> None:
    path = _solid(tmp_path, "a.png", (0, 0, 255))

    with pytest.raises(ExportError, match=f"between {MIN_FPS} and {MAX_FPS}"):
        export_gif([path], tmp_path / "clip.gif", 0)


def test_cancel_leaves_the_existing_video_in_place(tmp_path: Path) -> None:
    paths = [
        _solid(tmp_path, "a.png", (0, 0, 255), size=(8, 8)),
        _solid(tmp_path, "b.png", (0, 255, 0), size=(8, 8)),
    ]
    destination = tmp_path / "clip.mp4"
    destination.write_bytes(b"old")
    seen: list[int] = []

    def on_frame(index: int, _count: int) -> None:
        seen.append(index)

    with pytest.raises(ExportCancelled):
        export_video(paths, destination, 10, on_frame=on_frame, cancelled=lambda: len(seen) >= 1)

    assert destination.read_bytes() == b"old"
    assert list(tmp_path.glob(".*partial*")) == []
