"""Playback of one GIF or video. Each frame is a normal image, so zoom and pixel values keep working."""

# ================================== Imports ================================== #
# Standard Library
import threading
from pathlib import Path

# Third-party
import cv2
import numpy as np
from PIL import Image

# Local
from pixel_viewer.images import LoadedImage, loaded_from_array

# ================================== Constants ================================ #
_MIN_FRAME_MS = 20
_FALLBACK_FPS = 30.0


# ================================== Timing =================================== #
def format_clock(milliseconds: int) -> str:
    """Formats a position as ``m:ss.t``, for example ``0:01.2`` or ``1:03.0``."""
    milliseconds = max(int(milliseconds), 0)
    minutes, remainder = divmod(milliseconds, 60_000)
    seconds, millis = divmod(remainder, 1000)
    return f"{minutes}:{seconds:02d}.{millis // 100}"


# =================================== Clip ==================================== #
class MotionClip:
    """One GIF or video, opened for frame-by-frame playback.

    A GIF shows its first frame immediately. Later frames are composited in the background, in order, because a
    frame can depend on the ones before it. Videos stay on disk and are read as the playhead moves.
    """

    def __init__(self, path: Path) -> None:
        """Opens ``path``.

        Args:
            path: A GIF or a video file.

        Raises:
            ValueError: If the file has no readable frames.
        """
        self.path = path
        self.index = 0
        self._frames: list[np.ndarray | None] | None = None
        self._loaded: list[LoadedImage | None] = []
        self._durations: list[int] = []
        self._ready = 0
        self._error: str | None = None
        self._lock = threading.Lock()
        self._ready_cv = threading.Condition(self._lock)
        self._stop = threading.Event()
        self._thread: threading.Thread | None = None
        self._source: Image.Image | None = None
        self._canvas: Image.Image | None = None
        self._capture: cv2.VideoCapture | None = None
        self._next_read = 0
        self.fps = _FALLBACK_FPS
        if path.suffix.lower() == ".gif":
            self._open_gif(path)
        else:
            self._open_video(path)

    @property
    def frame_count(self) -> int:
        """Number of frames."""
        if self._frames is not None:
            return len(self._frames)
        assert self._capture is not None
        return int(self._capture.get(cv2.CAP_PROP_FRAME_COUNT))

    @property
    def fully_decoded(self) -> bool:
        """True when every GIF frame is composited. Videos are read on demand, so they are always ready."""
        if self._frames is None:
            return True
        with self._lock:
            return self._ready >= len(self._frames)

    @property
    def error(self) -> str | None:
        """Why decoding stopped, if a later frame could not be read."""
        with self._lock:
            return self._error

    @property
    def delay_ms(self) -> int:
        """How long the current frame should stay on screen."""
        if self._durations:
            return self._durations[self.index] or self._durations[0] or _MIN_FRAME_MS
        return max(_MIN_FRAME_MS, round(1000 / self.fps))

    @property
    def position_ms(self) -> int:
        """Start time of the current frame."""
        if self._durations:
            return sum(self._frame_delays(self.index))
        return round(self.index * 1000 / self.fps)

    @property
    def duration_ms(self) -> int:
        """Length of the whole clip. Frames still decoding use the first frame's delay."""
        if self._durations:
            return sum(self._frame_delays(len(self._durations)))
        return round(self.frame_count * 1000 / self.fps)

    def has_frame(self, index: int) -> bool:
        """True when ``index`` can be shown without waiting. GIF frames become ready in order."""
        if self._frames is None:
            return 0 <= index < self.frame_count
        with self._lock:
            return 0 <= index < len(self._frames) and index < self._ready

    def frame(self) -> LoadedImage:
        """Returns the current frame as an image the canvas can zoom into."""
        if self._frames is not None:
            self._wait_for(self.index)
            loaded = self._loaded[self.index]
            assert loaded is not None
            return loaded
        assert self._capture is not None
        if self._next_read != self.index:
            self._capture.set(cv2.CAP_PROP_POS_FRAMES, self.index)
        ok, decoded = self._capture.read()
        if not ok or decoded is None:
            raise ValueError(f"Could not read frame {self.index + 1} of {self.path.name}.")
        self._next_read = self.index + 1
        return loaded_from_array(self.path, decoded, detect_mask=False)

    def seek(self, index: int) -> LoadedImage:
        """Moves the playhead to ``index`` and returns that frame."""
        self.index = min(max(index, 0), self.frame_count - 1)
        return self.frame()

    def step(self) -> LoadedImage:
        """Advances one frame, wrapping to the start after the last, and returns the new frame."""
        self.index = (self.index + 1) % self.frame_count
        return self.frame()

    def close(self) -> None:
        """Stops background decoding and releases the decoder. Safe to call more than once."""
        self._stop.set()
        with self._lock:
            self._ready_cv.notify_all()
        thread = self._thread
        if thread is not None and thread.is_alive() and threading.current_thread() is not thread:
            thread.join(timeout=2)
        if self._capture is not None:
            self._capture.release()
            self._capture = None
        # * Leave the decoder's image alone if a frame is still being composited.
        if self._source is not None and (thread is None or not thread.is_alive()):
            self._source.close()
            self._source = None
        self._thread = None

    def wait_until_decoded(self, timeout: float = 5) -> None:
        """Blocks until background GIF decoding finishes. Used by tests."""
        thread = self._thread
        if thread is not None and thread.is_alive():
            thread.join(timeout)
        if self.error is not None:
            raise ValueError(self.error)

    def _frame_delays(self, count: int) -> list[int]:
        """Delays for the first ``count`` frames. Unknown ones reuse the first frame's delay."""
        first = self._durations[0] or _MIN_FRAME_MS
        return [value or first for value in self._durations[:count]]

    def _wait_for(self, index: int) -> None:
        """Blocks until GIF frame ``index`` is composited."""
        with self._lock:
            while index >= self._ready and self._error is None and not self._stop.is_set():
                self._ready_cv.wait(timeout=0.05)
            if index < self._ready:
                return
            if self._error is not None:
                raise ValueError(self._error)
        raise ValueError(f"Could not read frame {index + 1} of {self.path.name}.")

    def _open_gif(self, path: Path) -> None:
        """Composites the first frame, then decodes the rest without blocking the window."""
        try:
            image = Image.open(path)
        except (OSError, ValueError) as error:
            raise ValueError(f"Could not open {path.name}.") from error
        frame_count = int(getattr(image, "n_frames", 1) or 1)
        if frame_count < 1:
            image.close()
            raise ValueError(f"Could not read frames from {path.name}.")
        self._source = image
        self._canvas = Image.new("RGBA", image.size, (0, 0, 0, 255))
        self._frames = [None] * frame_count
        self._loaded = [None] * frame_count
        self._durations = [0] * frame_count
        try:
            bgr, duration = self._composite_gif_frame(0)
        except (OSError, ValueError) as error:
            image.close()
            self._source = None
            raise ValueError(f"Could not read frames from {path.name}.") from error
        self._publish_gif_frame(0, bgr, duration)
        self.fps = 1000 / duration
        if frame_count > 1:
            self._thread = threading.Thread(
                target=self._decode_remaining_gif_frames, name="pixel-viewer-gif", daemon=True
            )
            self._thread.start()

    def _decode_remaining_gif_frames(self) -> None:
        """Composites frames after the first. Runs off the UI thread."""
        assert self._frames is not None
        for index in range(1, len(self._frames)):
            if self._stop.is_set():
                return
            try:
                bgr, duration = self._composite_gif_frame(index)
            except (OSError, ValueError):
                with self._lock:
                    self._error = f"Could not read frame {index + 1} of {self.path.name}."
                    self._ready_cv.notify_all()
                return
            self._publish_gif_frame(index, bgr, duration)

    def _composite_gif_frame(self, index: int) -> tuple[np.ndarray, int]:
        """Paints GIF frame ``index`` onto the running canvas and returns BGR pixels plus its delay."""
        assert self._source is not None and self._canvas is not None
        self._source.seek(index)
        duration = max(_MIN_FRAME_MS, int(self._source.info.get("duration") or 100))
        disposal = int(getattr(self._source, "disposal_method", 0) or 0)
        snapshot = self._canvas.copy() if disposal == 3 else None
        frame = self._source.convert("RGBA")
        self._canvas.paste(frame, (0, 0), frame)
        rgba = np.ascontiguousarray(np.asarray(self._canvas))
        bgr = cv2.cvtColor(rgba, cv2.COLOR_RGBA2BGR)
        if disposal == 2:
            self._canvas = Image.new("RGBA", self._source.size, (0, 0, 0, 255))
        elif snapshot is not None:
            self._canvas = snapshot
        return bgr, duration

    def _publish_gif_frame(self, index: int, bgr: np.ndarray, duration: int) -> None:
        """Stores one composited frame and wakes anyone waiting for it."""
        loaded = loaded_from_array(self.path, bgr, detect_mask=False)
        with self._lock:
            assert self._frames is not None
            self._frames[index] = bgr
            self._durations[index] = duration
            self._loaded[index] = loaded
            self._ready = index + 1
            self._ready_cv.notify_all()

    def _open_video(self, path: Path) -> None:
        """Opens a video and checks that it reports at least one frame."""
        capture = cv2.VideoCapture(str(path))
        if not capture.isOpened():
            capture.release()
            raise ValueError(f"Could not open {path.name}.")
        count = int(capture.get(cv2.CAP_PROP_FRAME_COUNT) or 0)
        fps = float(capture.get(cv2.CAP_PROP_FPS) or 0)
        if count < 1:
            capture.release()
            raise ValueError(f"Could not read frames from {path.name}.")
        self._capture = capture
        self.fps = fps if fps > 0 else _FALLBACK_FPS
