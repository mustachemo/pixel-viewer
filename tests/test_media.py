"""Tests for GIF and video playback."""

# Standard Library
import threading
from pathlib import Path

# Third-party
import cv2
import numpy as np
import pytest
from PIL import Image

# Local
from pixel_viewer.images import ImageFolder
from pixel_viewer.media import MotionClip, format_clock


def _gif(path: Path, colors: list[tuple[int, int, int]], duration: int = 100) -> Path:
    """Writes a solid-color GIF with one frame per color."""
    frames = [Image.new("RGB", (8, 6), color) for color in colors]
    frames[0].save(
        path,
        save_all=True,
        append_images=frames[1:],
        duration=[duration] * len(frames),
        loop=0,
        disposal=2,
    )
    return path


def _video(path: Path, blues: list[int], fps: float = 10) -> Path:
    """Writes a short MP4 whose frames differ in the blue channel."""
    size = (32, 24)
    writer = None
    for codec in ("avc1", "mp4v"):
        candidate = cv2.VideoWriter(str(path), cv2.VideoWriter_fourcc(*codec), fps, size)
        if candidate.isOpened():
            writer = candidate
            break
        candidate.release()
    assert writer is not None
    for blue in blues:
        frame = np.zeros((size[1], size[0], 3), dtype=np.uint8)
        frame[:, :, 0] = blue
        writer.write(frame)
    writer.release()
    return path


def test_format_clock() -> None:
    assert format_clock(0) == "0:00.0"
    assert format_clock(1200) == "0:01.2"
    assert format_clock(63_000) == "1:03.0"


def test_gif_frames_keep_their_own_pixels(tmp_path: Path) -> None:
    path = _gif(tmp_path / "clip.gif", [(255, 0, 0), (0, 255, 0), (0, 0, 255)], duration=80)
    clip = MotionClip(path)
    try:
        assert clip.frame_count == 3
        assert clip.duration_ms == 240
        assert clip.delay_ms == 80
        assert clip.frame().values[0, 0].tolist() == [0, 0, 255]
        assert clip.step().values[0, 0].tolist() == [0, 255, 0]
        assert clip.seek(2).values[0, 0].tolist() == [255, 0, 0]
        assert clip.position_ms == 160
        assert format_clock(clip.duration_ms) == "0:00.2"
    finally:
        clip.close()


def test_gif_open_returns_after_the_first_frame(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    held: list[threading.Thread] = []
    original_start = threading.Thread.start
    started = False

    def hold(thread: threading.Thread) -> None:
        held.append(thread)

    monkeypatch.setattr(threading.Thread, "start", hold)
    path = _gif(tmp_path / "clip.gif", [(255, 0, 0), (0, 255, 0), (0, 0, 255)])
    clip = MotionClip(path)
    try:
        assert len(held) == 1
        assert not held[0].is_alive()
        assert clip.frame_count == 3
        assert clip.has_frame(0)
        assert not clip.has_frame(1)
        assert clip.frame().values[0, 0].tolist() == [0, 0, 255]
        assert clip.duration_ms == 300
        original_start(held[0])
        started = True
        clip.wait_until_decoded()
        assert clip.fully_decoded
        assert clip.seek(2).values[0, 0].tolist() == [255, 0, 0]
    finally:
        if held and not started:
            original_start(held[0])
        clip.close()


def test_video_reads_frames_in_order_and_loops(tmp_path: Path) -> None:
    path = _video(tmp_path / "clip.mp4", [0, 128, 255], fps=10)
    clip = MotionClip(path)
    try:
        assert clip.frame_count == 3
        first = int(clip.frame().values[0, 0, 0])
        second = int(clip.step().values[0, 0, 0])
        third = int(clip.step().values[0, 0, 0])
        assert first < second < third
        assert int(clip.step().values[0, 0, 0]) == first
        assert clip.duration_ms == 300
    finally:
        clip.close()


def test_unreadable_video_raises(tmp_path: Path) -> None:
    path = tmp_path / "broken.mp4"
    path.write_bytes(b"not a video")

    with pytest.raises(ValueError, match="Could not"):
        MotionClip(path)


def test_folder_lists_stills_and_clips_together(tmp_path: Path) -> None:
    cv2.imwrite(str(tmp_path / "b.png"), np.zeros((2, 2, 3), dtype=np.uint8))
    _gif(tmp_path / "a.gif", [(1, 2, 3)])
    (tmp_path / "c.mp4").write_bytes(b"not a video")

    folder = ImageFolder(tmp_path)
    try:
        assert [path.name for path in folder.paths] == ["a.gif", "b.png", "c.mp4"]
        assert [path.name for path in folder.still_paths()] == ["b.png"]
    finally:
        folder.close()
