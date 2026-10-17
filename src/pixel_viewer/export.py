"""Write a sequence of images to a looping GIF and/or an MP4 video."""

# ================================== Imports ================================== #
# Standard Library
from collections.abc import Callable, Iterator, Sequence
from pathlib import Path

# Third-party
import cv2
import numpy as np
from PIL import Image

# Local
from pixel_viewer.images import load_image

# ================================== Constants ================================ #
MIN_FPS = 1
MAX_FPS = 60
DEFAULT_FPS = 10
_VIDEO_CODECS = ("avc1", "mp4v")

FrameCallback = Callable[[int, int], None]
CancelCallback = Callable[[], bool]


# ================================= Exceptions ================================ #
class ExportError(Exception):
    """The animation could not be written."""


class ExportCancelled(ExportError):
    """The user cancelled the export. A partial file is removed; existing files are left as they were."""


# ================================= Dataclasses =============================== #
class AnimationExport:
    """One request to write images, in order, as a GIF, a video, or both.

    Attributes:
        paths: Frames in playback order.
        fps: Frames per second, from 1 to 60.
        gif_path: GIF to write, or None to skip it.
        video_path: MP4 to write, or None to skip it.
    """

    def __init__(
        self,
        paths: tuple[Path, ...],
        fps: int,
        gif_path: Path | None = None,
        video_path: Path | None = None,
    ) -> None:
        if not paths:
            raise ExportError("No images to export.")
        if not MIN_FPS <= fps <= MAX_FPS:
            raise ExportError(f"Frames per second must be between {MIN_FPS} and {MAX_FPS}.")
        if gif_path is None and video_path is None:
            raise ExportError("Choose a GIF, a video, or both.")
        self.paths = paths
        self.fps = fps
        self.gif_path = gif_path
        self.video_path = video_path


# ================================== Writing ================================== #
def animation_destinations(base: Path, *, gif: bool, video: bool) -> tuple[Path | None, Path | None]:
    """Returns the GIF and MP4 paths for a save location.

    A trailing ``.gif`` or ``.mp4`` is replaced. Any other dot in the name is kept, so ``my.dataset``
    becomes ``my.dataset.gif`` rather than ``my.gif``.

    Args:
        base: File path the user chose, with or without an animation suffix.
        gif: Write a GIF.
        video: Write an MP4.

    Returns:
        ``(gif_path, video_path)``. Either entry is None when that format is off.

    Raises:
        ExportError: If neither format is selected, or the file name is empty.
    """
    if not gif and not video:
        raise ExportError("Choose a GIF, a video, or both.")
    name = base.name
    for suffix in (".gif", ".mp4"):
        if name.lower().endswith(suffix):
            name = name[: -len(suffix)]
            break
    if not name or name in {".", ".."}:
        raise ExportError("Choose a file name for the animation.")
    stem = base.with_name(name)
    return (stem.with_name(name + ".gif") if gif else None, stem.with_name(name + ".mp4") if video else None)


def export_gif(
    paths: Sequence[Path],
    destination: Path,
    fps: int,
    on_frame: FrameCallback | None = None,
    cancelled: CancelCallback | None = None,
) -> None:
    """Writes ``paths`` to a looping GIF at ``fps``.

    GIF delays step by 10 ms, so 24 fps is stored as 40 ms and plays at 25 fps.

    Args:
        paths: Frames in playback order.
        destination: ``.gif`` file to create or replace.
        fps: Frames per second, from 1 to 60.
        on_frame: Called with the 1-based frame index and the frame count after each frame is prepared.
        cancelled: Polled between frames. When it returns true, the export stops and ``destination`` is unchanged.

    Raises:
        ExportError: If the frames cannot be written.
        ExportCancelled: If ``cancelled`` reports that the user cancelled.
    """
    _check_request(paths, fps, destination, ".gif")

    def write(temporary: Path) -> None:
        _encode_gif(temporary, paths, fps, on_frame, cancelled)

    _write_atomically(destination, write)


def export_video(
    paths: Sequence[Path],
    destination: Path,
    fps: int,
    on_frame: FrameCallback | None = None,
    cancelled: CancelCallback | None = None,
) -> str | None:
    """Writes ``paths`` to an MP4 at ``fps``.

    Uses H.264 when the machine has that encoder, otherwise MPEG-4. Odd widths or heights gain one repeated
    row or column, because those encoders store even dimensions and would otherwise crop a pixel.

    Args:
        paths: Frames in playback order.
        destination: ``.mp4`` file to create or replace.
        fps: Frames per second, from 1 to 60.
        on_frame: Called with the 1-based frame index and the frame count after each frame is written.
        cancelled: Polled between frames. When it returns true, the export stops and ``destination`` is unchanged.

    Returns:
        A note when the video was padded to even dimensions, otherwise None.

    Raises:
        ExportError: If the frames cannot be written.
        ExportCancelled: If ``cancelled`` reports that the user cancelled.
    """
    _check_request(paths, fps, destination, ".mp4")
    note: str | None = None

    def write(temporary: Path) -> None:
        nonlocal note
        note = _encode_video(temporary, paths, fps, on_frame, cancelled)

    _write_atomically(destination, write)
    return note


def iter_display_frames(paths: Sequence[Path]) -> Iterator[np.ndarray]:
    """Yields uint8 BGR frames in ``paths`` order, as the viewer paints them.

    Color images keep their color. Grayscale images and label masks use the buffer the canvas shows, so a mask
    keeps the same part colors as the window.

    Args:
        paths: Image files.

    Yields:
        A contiguous H×W×3 uint8 BGR frame.

    Raises:
        ExportError: If a file cannot be decoded, or a frame's size differs from the first frame.
    """
    expected: tuple[int, int] | None = None
    first_name = ""
    for path in paths:
        try:
            image = load_image(path)
        except ValueError as error:
            raise ExportError(str(error)) from error
        source = image.color_display if image.color_display is not None else image.gray_display
        frame = np.ascontiguousarray(source)
        size = (frame.shape[1], frame.shape[0])
        if expected is None:
            expected = size
            first_name = path.name
        elif size != expected:
            raise ExportError(
                f"{path.name} is {size[0]} × {size[1]}, but {first_name} is {expected[0]} × {expected[1]}. "
                "Every frame has to be the same size."
            )
        yield frame


# ================================= Internals ================================= #
def _check_request(paths: Sequence[Path], fps: int, destination: Path, suffix: str) -> None:
    """Checks the frame list, the rate and the destination suffix before any file is touched."""
    if not paths:
        raise ExportError("No images to export.")
    if not MIN_FPS <= fps <= MAX_FPS:
        raise ExportError(f"Frames per second must be between {MIN_FPS} and {MAX_FPS}.")
    if destination.suffix.lower() != suffix:
        kind = "GIF" if suffix == ".gif" else "Video"
        raise ExportError(f"{kind} files have to end in {suffix}, not '{destination.name}'.")


def _check_cancelled(cancelled: CancelCallback | None) -> None:
    """Stops the export when the user has asked to cancel."""
    if cancelled is not None and cancelled():
        raise ExportCancelled("Export cancelled.")


def _write_atomically(destination: Path, write: Callable[[Path], None]) -> None:
    """Runs ``write`` on a temporary file, then replaces ``destination``.

    A failure or cancellation deletes the temporary file and leaves an existing destination untouched.
    """
    if not destination.parent.is_dir():
        raise ExportError(f"No such folder: {destination.parent}")
    temporary = destination.with_name(f".{destination.stem}.partial{destination.suffix}")
    try:
        write(temporary)
    except Exception:
        temporary.unlink(missing_ok=True)
        raise
    temporary.replace(destination)


def _to_pil(frame: np.ndarray) -> Image.Image:
    """Converts a BGR display frame to an RGB Pillow image."""
    return Image.fromarray(cv2.cvtColor(frame, cv2.COLOR_BGR2RGB))


def _encode_gif(
    temporary: Path,
    paths: Sequence[Path],
    fps: int,
    on_frame: FrameCallback | None,
    cancelled: CancelCallback | None,
) -> None:
    """Writes one GIF frame at a time so a long sequence is not held in memory twice."""
    # * GIF stores the delay in hundredths of a second. 24 fps becomes 40 ms, which plays at 25 fps.
    duration = max(10, round(1000 / fps / 10) * 10)
    frames = iter_display_frames(paths)
    first = next(frames)
    count = len(paths)

    def rest() -> Iterator[Image.Image]:
        index = 1
        for frame in frames:
            _check_cancelled(cancelled)
            index += 1
            if on_frame is not None:
                on_frame(index, count)
            yield _to_pil(frame)

    _check_cancelled(cancelled)
    if on_frame is not None:
        on_frame(1, count)
    _to_pil(first).save(
        temporary,
        format="GIF",
        save_all=True,
        append_images=rest(),
        duration=duration,
        loop=0,
        disposal=2,
    )


def _pad_even(frame: np.ndarray) -> np.ndarray:
    """Repeats the last row and column until both sides are even."""
    height, width = frame.shape[:2]
    pad_bottom = height % 2
    pad_right = width % 2
    if not pad_bottom and not pad_right:
        return frame
    # * H.264 dimensions have to be even. Repeating the edge keeps every pixel; cropping would drop one.
    return cv2.copyMakeBorder(frame, 0, pad_bottom, 0, pad_right, cv2.BORDER_REPLICATE)


def _open_writer(path: Path, fps: float, size: tuple[int, int]) -> cv2.VideoWriter:
    """Opens an MP4 writer, preferring H.264 and falling back to MPEG-4."""
    for codec in _VIDEO_CODECS:
        writer = cv2.VideoWriter(str(path), cv2.VideoWriter_fourcc(*codec), fps, size)
        if writer.isOpened():
            return writer
        writer.release()
    raise ExportError(f"Could not create the video file {path.name}. No H.264 or MPEG-4 encoder is available.")


def _encode_video(
    temporary: Path,
    paths: Sequence[Path],
    fps: int,
    on_frame: FrameCallback | None,
    cancelled: CancelCallback | None,
) -> str | None:
    """Writes every frame into ``temporary`` and reports when even-dimension padding was needed."""
    frames = iter_display_frames(paths)
    first = next(frames)
    original = (first.shape[1], first.shape[0])
    padded = _pad_even(first)
    size = (padded.shape[1], padded.shape[0])
    writer = _open_writer(temporary, float(fps), size)
    count = len(paths)
    try:
        _check_cancelled(cancelled)
        if not writer.write(padded):
            raise ExportError("Could not write a video frame.")
        index = 1
        if on_frame is not None:
            on_frame(index, count)
        for frame in frames:
            _check_cancelled(cancelled)
            if not writer.write(_pad_even(frame)):
                raise ExportError("Could not write a video frame.")
            index += 1
            if on_frame is not None:
                on_frame(index, count)
    finally:
        writer.release()
    if size == original:
        return None
    return (
        f"The video is {size[0]} × {size[1]} because the encoder needs even dimensions; "
        f"the images are {original[0]} × {original[1]}."
    )
