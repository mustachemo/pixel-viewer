"""Image decoding and folder browsing with background prefetch."""

# ================================== Imports ================================== #
# Standard Library
import re
from collections import OrderedDict
from collections.abc import Callable
from concurrent.futures import Future, ThreadPoolExecutor
from dataclasses import dataclass
from pathlib import Path

# Third-party
import cv2
import numpy as np

# ================================== Constants ================================ #
IMAGE_SUFFIXES = frozenset({".bmp", ".jpeg", ".jpg", ".png", ".tif", ".tiff"})
MAX_LABEL_COUNT = 64
LABEL_COLOR_STEP = 12
PREFETCH_RADIUS = 2
CACHE_SIZE = 2 * PREFETCH_RADIUS + 3
PREFETCH_WORKERS = 2

# * A fixed ID → color lookup (instead of normalizing each mask) keeps a part the same color on every frame.
_LABEL_PALETTE = cv2.applyColorMap(np.arange(256, dtype=np.uint8).reshape(256, 1), cv2.COLORMAP_TURBO).reshape(256, 3)


# ================================= Dataclasses =============================== #
@dataclass(frozen=True)
class LoadedImage:
    """A decoded image plus the buffers the viewer paints and labels.

    Attributes:
        path: Source file.
        values: Pixel values printed in each cell: H×W for single-channel images, H×W×3 (BGR) otherwise.
        gray_values: H×W luminance; the same array as ``values`` for single-channel images.
        color_display: Contiguous uint8 BGR buffer for the original view, or None for single-channel images.
        gray_display: Contiguous uint8 BGR buffer for the grayscale view; label masks use a fixed color palette.
        is_label_mask: True for single-channel images holding a handful of integer part IDs.
    """

    path: Path
    values: np.ndarray
    gray_values: np.ndarray
    color_display: np.ndarray | None
    gray_display: np.ndarray
    is_label_mask: bool

    @property
    def is_single_channel(self) -> bool:
        """True when each pixel has one value (grayscale images and label masks)."""
        return self.values.ndim == 2

    @property
    def size(self) -> tuple[int, int]:
        """Image (width, height) in pixels."""
        return self.values.shape[1], self.values.shape[0]


# ================================== Loading ================================== #
def _to_uint8(array: np.ndarray) -> np.ndarray:
    """Returns uint8 arrays unchanged and stretches any other dtype to 0-255 for display."""
    if array.dtype == np.uint8:
        return array
    return cv2.normalize(array, None, 0, 255, cv2.NORM_MINMAX, cv2.CV_8U)


def load_image(path: Path) -> LoadedImage:
    """Decodes an image file into the buffers the viewer needs.

    Alpha is dropped, and images whose B, G and R channels are identical (such as the dataset's part masks) are
    collapsed to one channel so each cell shows a single value.

    Args:
        path: Image file to decode.

    Returns:
        The decoded image and its display buffers.

    Raises:
        ValueError: If OpenCV cannot decode the file.
    """
    raw = cv2.imread(str(path), cv2.IMREAD_UNCHANGED)
    if raw is None:
        raise ValueError(f"Could not decode image: {path}")
    if raw.ndim == 3:
        bgr = raw[:, :, :3]
        is_replicated = (bgr[:, :, 0] == bgr[:, :, 1]).all() and (bgr[:, :, 1] == bgr[:, :, 2]).all()
        raw = np.ascontiguousarray(bgr[:, :, 0] if is_replicated else bgr)

    is_single_channel = raw.ndim == 2
    # * np.bincount is much faster than np.unique on multi-megapixel masks, which matters when browsing quickly.
    is_label_mask = (
        is_single_channel and raw.dtype.kind == "u" and np.count_nonzero(np.bincount(raw.ravel())) <= MAX_LABEL_COUNT
    )
    gray_values = raw if is_single_channel else cv2.cvtColor(raw, cv2.COLOR_BGR2GRAY)
    if is_label_mask:
        gray_display = _LABEL_PALETTE[(raw.astype(np.uint32) * LABEL_COLOR_STEP) % 256]
    else:
        gray_display = cv2.cvtColor(_to_uint8(gray_values), cv2.COLOR_GRAY2BGR)

    return LoadedImage(
        path=path,
        values=raw,
        gray_values=gray_values,
        color_display=None if is_single_channel else _to_uint8(raw),
        gray_display=gray_display,
        is_label_mask=is_label_mask,
    )


def natural_sort_key(path: Path) -> list[int | str]:
    """Sort key that orders numbered files as people expect: ``img_2`` before ``img_10``."""
    return [int(part) if part.isdigit() else part.lower() for part in re.split(r"(\d+)", path.name)]


# ================================ Folder Browsing ============================ #
class ImageFolder:
    """The images in one folder in natural order, with the current image's neighbours decoded in the background."""

    def __init__(self, start: Path, loader: Callable[[Path], LoadedImage] = load_image) -> None:
        """Lists the folder containing ``start``, or ``start`` itself when it is a folder.

        Args:
            start: An image file to open, or a folder to open at its first image.
            loader: Decodes one file; injectable for tests.

        Raises:
            FileNotFoundError: If ``start`` does not exist or its folder has no supported images.
            ValueError: If ``start`` is a file with an unsupported extension.
        """
        start = start.expanduser().resolve()
        if not start.exists():
            raise FileNotFoundError(f"No such file or folder: {start}")
        if start.is_file() and start.suffix.lower() not in IMAGE_SUFFIXES:
            supported = ", ".join(sorted(IMAGE_SUFFIXES))
            raise ValueError(f"Unsupported image type '{start.suffix}'. Supported: {supported}")

        self.folder = start if start.is_dir() else start.parent
        self.paths = sorted(
            (
                path
                for path in self.folder.iterdir()
                if path.is_file() and not path.name.startswith(".") and path.suffix.lower() in IMAGE_SUFFIXES
            ),
            key=natural_sort_key,
        )
        if not self.paths:
            raise FileNotFoundError(f"No supported images in {self.folder}")
        self.index = self.paths.index(start) if start.is_file() else 0

        self._loader = loader
        self._executor = ThreadPoolExecutor(max_workers=PREFETCH_WORKERS, thread_name_prefix="pixel-viewer-prefetch")
        self._cache: OrderedDict[Path, Future[LoadedImage]] = OrderedDict()

    @property
    def current_path(self) -> Path:
        """Path of the selected image."""
        return self.paths[self.index]

    def move_to(self, index: int) -> bool:
        """Selects the image at ``index``, clamped to the folder.

        Args:
            index: Position in ``paths``; values past either end select the first or last image.

        Returns:
            True if the selection changed.
        """
        clamped = min(max(index, 0), len(self.paths) - 1)
        changed = clamped != self.index
        self.index = clamped
        return changed

    def current(self) -> LoadedImage:
        """Returns the selected image, waiting for it to decode if needed, and prefetches its neighbours.

        Returns:
            The decoded image at ``index``.

        Raises:
            ValueError: If the file cannot be decoded.
        """
        path = self.current_path
        try:
            image = self._request(path).result()
        except ValueError:
            self._cache.pop(path, None)
            raise

        for distance in range(1, PREFETCH_RADIUS + 1):
            for neighbour in (self.index + distance, self.index - distance):
                if 0 <= neighbour < len(self.paths):
                    self._request(self.paths[neighbour])
        # * Mark the current image most recently used so eviction never drops what is on screen.
        self._cache.move_to_end(path)
        return image

    def close(self) -> None:
        """Stops background decoding and cancels pending prefetches."""
        self._executor.shutdown(wait=False, cancel_futures=True)

    def _request(self, path: Path) -> Future[LoadedImage]:
        """Returns the decode for ``path``, scheduling it if needed and evicting the least recently used entry."""
        if path in self._cache:
            self._cache.move_to_end(path)
            return self._cache[path]
        future = self._executor.submit(self._loader, path)
        self._cache[path] = future
        while len(self._cache) > CACHE_SIZE:
            _, evicted = self._cache.popitem(last=False)
            evicted.cancel()
        return future
