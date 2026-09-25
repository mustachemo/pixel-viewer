"""The zoomable image canvas that draws a pixel grid and per-pixel values."""

# ================================== Imports ================================== #
# Standard Library
import math

# Third-party
import numpy as np
from PySide6.QtCore import QEvent, QLineF, QPointF, QRect, QRectF, Qt, Signal
from PySide6.QtGui import (
    QColor,
    QCursor,
    QFont,
    QFontDatabase,
    QImage,
    QKeyEvent,
    QMouseEvent,
    QNativeGestureEvent,
    QPainter,
    QPainterPath,
    QPaintEvent,
    QPen,
    QPixmap,
    QResizeEvent,
    QWheelEvent,
)
from PySide6.QtWidgets import QWidget

# Local
from pixel_viewer.images import LoadedImage

# ================================== Constants ================================ #
ZOOM_STEPS = (1, 2, 3, 4, 6, 8, 12, 16, 24, 32, 48, 64, 96, 128)
GRID_MIN_ZOOM = 8
HOVER_MIN_ZOOM = 4
GRAY_TEXT_MIN_ZOOM = 24
RGB_TEXT_MIN_ZOOM = 32
CONTENT_THRESHOLD = 30
PAN_FRACTION = 0.25
WHEEL_UNITS_PER_STEP = 120
PINCH_PER_STEP = 0.12
MIN_FONT_PIXELS = 6
GLYPH_CACHE_LIMIT = 4096

BACKGROUND_COLOR = QColor(30, 30, 30)
GRID_COLOR = QColor(70, 70, 70)
HOVER_COLOR = QColor(255, 220, 0)
PLACEHOLDER_COLOR = QColor(150, 150, 150)
OUTLINE_COLOR = QColor(0, 0, 0, 220)
CHANNEL_TEXT_COLORS = (QColor(255, 70, 70), QColor(70, 230, 70), QColor(50, 160, 255))
DARK_TEXT_COLOR = QColor(0, 0, 0)
LIGHT_TEXT_COLOR = QColor(255, 255, 255)

WASD_PAN_DIRECTIONS = {
    int(Qt.Key.Key_W): (0, -1),
    int(Qt.Key.Key_A): (-1, 0),
    int(Qt.Key.Key_S): (0, 1),
    int(Qt.Key.Key_D): (1, 0),
}


# ================================== Canvas =================================== #
class PixelCanvas(QWidget):
    """Paints one image at discrete zoom levels, with a pixel grid and value labels when zoomed in.

    The view is described by a zoom factor and the image coordinate shown at the widget's centre. "Fit" is a
    special zoom level that shows the whole image; every other level is a whole number so pixel cells land on
    whole screen points and the grid stays crisp.

    Signals:
        cursor_moved: The image pixel ``(x, y)`` under the pointer, or None when it leaves the image.
        view_changed: Emitted after the zoom or the visible region changes.
    """

    cursor_moved = Signal(object)
    view_changed = Signal()

    def __init__(self, parent: QWidget | None = None) -> None:
        """Creates an empty canvas.

        Args:
            parent: Owning widget.
        """
        super().__init__(parent)
        self.setFocusPolicy(Qt.FocusPolicy.StrongFocus)
        self.setMouseTracking(True)
        # * Every paint covers its whole rect, so Qt can skip clearing the background first.
        self.setAttribute(Qt.WidgetAttribute.WA_OpaquePaintEvent)

        self._image: LoadedImage | None = None
        self._color_qimage: QImage | None = None
        self._gray_qimage: QImage | None = None
        self._prefer_gray = False
        self._is_fit = True
        self._step_zoom = 1.0
        self._center = QPointF()
        self._hover: tuple[int, int] | None = None
        self._drag_last: QPointF | None = None
        self._wheel_accumulator = 0.0
        self._pinch_accumulator = 0.0
        self._glyph_cache: dict[tuple[str, int, bool, int, float], QPixmap] = {}
        self._value_font = QFontDatabase.systemFont(QFontDatabase.SystemFont.FixedFont)
        self._value_font.setWeight(QFont.Weight.DemiBold)

    # ------------------------------ View state ------------------------------- #
    @property
    def image(self) -> LoadedImage | None:
        """The image being shown, if any."""
        return self._image

    @property
    def is_fit(self) -> bool:
        """True while the whole image is scaled to fit the widget."""
        return self._is_fit

    @property
    def zoom(self) -> float:
        """Screen points per image pixel."""
        if self._image is None:
            return 1.0
        if self._is_fit:
            image_width, image_height = self._image.size
            return max(min(self.width() / image_width, self.height() / image_height), 1e-6)
        return self._step_zoom

    @property
    def is_gray(self) -> bool:
        """True when showing the grayscale view; single-channel images are always shown this way."""
        return self._prefer_gray or (self._image is not None and self._image.is_single_channel)

    def set_gray(self, gray: bool) -> None:
        """Chooses the grayscale (one value per cell) or original (R, G, B values) view.

        Args:
            gray: Show grayscale when True. Ignored for single-channel images, which have no color view.
        """
        self._prefer_gray = gray
        self.update()
        self.view_changed.emit()

    def set_image(self, image: LoadedImage, keep_view: bool = False) -> None:
        """Shows a new image.

        Args:
            image: The image to show.
            keep_view: Keep the current zoom and centre (used when stepping through a folder of same-size frames);
                otherwise fit the new image to the widget.
        """
        had_image = self._image is not None
        self._image = image
        # * QImage wraps the numpy buffers without copying; the LoadedImage held above keeps them alive.
        width, height = image.size
        if image.color_display is not None:
            self._color_qimage = QImage(
                image.color_display.data, width, height, image.color_display.strides[0], QImage.Format.Format_BGR888
            )
        else:
            self._color_qimage = None
        self._gray_qimage = QImage(
            image.gray_display.data, width, height, image.gray_display.strides[0], QImage.Format.Format_BGR888
        )

        if keep_view and had_image:
            self._clamp_center()
        else:
            self._is_fit = True
            self._center = QPointF(width / 2, height / 2)
        self._hover = self.pixel_at(self.mapFromGlobal(QCursor.pos()).toPointF()) if self.underMouse() else None
        self.update()
        self.view_changed.emit()
        self.cursor_moved.emit(self._hover)

    def reset_view(self) -> None:
        """Fits the whole image to the widget."""
        if self._image is None:
            return
        width, height = self._image.size
        self._is_fit = True
        self._center = QPointF(width / 2, height / 2)
        self._after_view_change()

    def zoom_by_steps(self, steps: int, anchor: QPointF | None = None) -> None:
        """Moves ``steps`` zoom levels in (positive) or out (negative), keeping the point under ``anchor`` still.

        Args:
            steps: Number of zoom levels to move.
            anchor: Widget position to zoom around; defaults to the widget centre.
        """
        if self._image is None or steps == 0:
            return
        fit_zoom = self._fit_zoom()
        levels = [fit_zoom, *(step for step in ZOOM_STEPS if step > fit_zoom * (1 + 1e-9))]
        current = self.zoom
        if steps > 0:
            higher = [index for index, level in enumerate(levels) if level > current * (1 + 1e-9)]
            target_index = min(higher[0] + steps - 1, len(levels) - 1) if higher else len(levels) - 1
        else:
            lower = [index for index, level in enumerate(levels) if level < current * (1 - 1e-9)]
            target_index = max(lower[-1] + steps + 1, 0) if lower else 0

        anchor = anchor if anchor is not None else QPointF(self.width() / 2, self.height() / 2)
        image_point = self.screen_to_image(anchor)
        self._is_fit = target_index == 0
        self._step_zoom = levels[target_index]
        widget_center = QPointF(self.width() / 2, self.height() / 2)
        self._center = image_point - (anchor - widget_center) / self.zoom
        self._after_view_change()

    def pan_by_fraction(self, dx: float, dy: float) -> None:
        """Moves the view by a fraction of the widget size.

        Args:
            dx: Horizontal fraction of the widget width; positive moves the view right.
            dy: Vertical fraction of the widget height; positive moves the view down.
        """
        if self._image is None:
            return
        self._center += QPointF(dx * self.width(), dy * self.height()) / self.zoom
        self._after_view_change()

    def find_object(self) -> None:
        """Zooms to the largest level that shows all non-background pixels, centred on them."""
        if self._image is None:
            return
        image = self._image
        content = image.values > 0 if image.is_label_mask else image.gray_values > CONTENT_THRESHOLD
        columns, rows = np.flatnonzero(content.any(axis=0)), np.flatnonzero(content.any(axis=1))
        if columns.size == 0:
            return

        box_width, box_height = columns[-1] - columns[0] + 1, rows[-1] - rows[0] + 1
        fit_zoom = self._fit_zoom()
        fitting = [
            step
            for step in ZOOM_STEPS
            if step > fit_zoom and box_width * step <= self.width() and box_height * step <= self.height()
        ]
        self._is_fit = not fitting
        self._step_zoom = float(fitting[-1]) if fitting else 1.0
        self._center = QPointF((columns[0] + columns[-1] + 1) / 2, (rows[0] + rows[-1] + 1) / 2)
        self._after_view_change()

    # ------------------------------ Coordinates ------------------------------ #
    def screen_to_image(self, point: QPointF) -> QPointF:
        """Converts a widget position to continuous image coordinates (pixel ``(x, y)`` spans ``[x, x + 1)``)."""
        return (point - self._origin()) / self.zoom

    def image_to_screen(self, point: QPointF) -> QPointF:
        """Converts continuous image coordinates to a widget position."""
        return self._origin() + point * self.zoom

    def pixel_at(self, point: QPointF) -> tuple[int, int] | None:
        """Returns the image pixel under a widget position, or None outside the image."""
        if self._image is None:
            return None
        image_point = self.screen_to_image(point)
        x, y = math.floor(image_point.x()), math.floor(image_point.y())
        width, height = self._image.size
        return (x, y) if 0 <= x < width and 0 <= y < height else None

    def _fit_zoom(self) -> float:
        """Zoom factor that fits the whole image in the widget."""
        assert self._image is not None
        width, height = self._image.size
        return max(min(self.width() / width, self.height() / height), 1e-6)

    def _origin(self) -> QPointF:
        """Widget position of the image's top-left corner."""
        origin = QPointF(self.width() / 2, self.height() / 2) - self._center * self.zoom
        # * Snapping to whole points puts every cell edge on a whole point, so the grid never blurs or wobbles.
        return origin if self._is_fit else QPointF(round(origin.x()), round(origin.y()))

    def _clamp_center(self) -> None:
        """Keeps the view inside the image, centring any axis where the scaled image is smaller than the widget."""
        if self._image is None:
            return
        zoom = self.zoom
        clamped = []
        for center, image_extent, widget_extent in (
            (self._center.x(), self._image.size[0], self.width()),
            (self._center.y(), self._image.size[1], self.height()),
        ):
            half_view = widget_extent / (2 * zoom)
            if 2 * half_view >= image_extent:
                clamped.append(image_extent / 2)
            else:
                clamped.append(min(max(center, half_view), image_extent - half_view))
        self._center = QPointF(*clamped)

    def _after_view_change(self) -> None:
        """Clamps the view, refreshes the hover pixel and repaints."""
        self._clamp_center()
        self.update()
        self.view_changed.emit()
        if self.underMouse():
            self._set_hover(self.pixel_at(self.mapFromGlobal(QCursor.pos()).toPointF()))

    # ------------------------------- Painting -------------------------------- #
    def paintEvent(self, event: QPaintEvent) -> None:
        """Draws the part of the image, grid and values inside the dirty rect."""
        painter = QPainter(self)
        dirty = event.rect()
        painter.fillRect(dirty, BACKGROUND_COLOR)
        if self._image is None:
            painter.setPen(PLACEHOLDER_COLOR)
            painter.drawText(self.rect(), Qt.AlignmentFlag.AlignCenter, "Open an image or drop one here")
            return

        zoom, origin = self.zoom, self._origin()
        width, height = self._image.size
        # Visible pixel range [x0, x1) × [y0, y1), limited to the dirty rect so hover updates stay cheap.
        x0 = max(0, math.floor((dirty.left() - origin.x()) / zoom))
        y0 = max(0, math.floor((dirty.top() - origin.y()) / zoom))
        x1 = min(width, math.ceil((dirty.right() + 1 - origin.x()) / zoom))
        y1 = min(height, math.ceil((dirty.bottom() + 1 - origin.y()) / zoom))
        if x0 >= x1 or y0 >= y1:
            return

        qimage = self._gray_qimage if self.is_gray or self._color_qimage is None else self._color_qimage
        target = QRectF(origin.x() + x0 * zoom, origin.y() + y0 * zoom, (x1 - x0) * zoom, (y1 - y0) * zoom)
        # * Nearest-neighbour when magnifying so each pixel is a flat square; smooth only when shrinking.
        painter.setRenderHint(QPainter.RenderHint.SmoothPixmapTransform, zoom < 1)
        painter.drawImage(target, qimage, QRectF(x0, y0, x1 - x0, y1 - y0))

        if zoom >= GRID_MIN_ZOOM:
            grid_pen = QPen(GRID_COLOR)
            grid_pen.setCosmetic(True)
            painter.setPen(grid_pen)
            vertical = [
                QLineF(target.left() + i * zoom, target.top(), target.left() + i * zoom, target.bottom())
                for i in range(x1 - x0 + 1)
            ]
            horizontal = [
                QLineF(target.left(), target.top() + j * zoom, target.right(), target.top() + j * zoom)
                for j in range(y1 - y0 + 1)
            ]
            painter.drawLines(vertical + horizontal)

        if zoom >= (GRAY_TEXT_MIN_ZOOM if self.is_gray else RGB_TEXT_MIN_ZOOM):
            self._draw_values(painter, zoom, origin, (x0, y0, x1, y1))

        if self._hover is not None and zoom >= HOVER_MIN_ZOOM:
            hover_pen = QPen(HOVER_COLOR, 2)
            hover_pen.setCosmetic(True)
            painter.setPen(hover_pen)
            painter.setBrush(Qt.BrushStyle.NoBrush)
            painter.drawRect(self._cell_rect(*self._hover).adjusted(1, 1, -1, -1))

    def _draw_values(self, painter: QPainter, zoom: float, origin: QPointF, bounds: tuple[int, int, int, int]) -> None:
        """Draws each visible pixel's value(s) centred in its cell.

        Args:
            painter: Active painter on this widget.
            zoom: Screen points per image pixel.
            origin: Widget position of the image's top-left corner.
            bounds: Visible pixel range ``(x0, y0, x1, y1)``, end-exclusive.
        """
        assert self._image is not None
        x0, y0, x1, y1 = bounds
        dpr = self.devicePixelRatioF()
        if self.is_gray:
            values = self._image.gray_values[y0:y1, x0:x1]
            display = self._image.gray_display[y0:y1, x0:x1].astype(np.float32)
            # Rec. 601 luma of the painted color (BGR order) picks black text on light cells, white on dark.
            is_light = display @ np.array([0.114, 0.587, 0.299], dtype=np.float32) > 127
            font_pixels = self._font_pixels(zoom, self._max_digits(), line_count=1)
            for row in range(y1 - y0):
                for column in range(x1 - x0):
                    color = DARK_TEXT_COLOR if is_light[row, column] else LIGHT_TEXT_COLOR
                    glyph = self._glyph(_format_value(values[row, column]), color, False, font_pixels, dpr)
                    center = origin + QPointF((x0 + column + 0.5) * zoom, (y0 + row + 0.5) * zoom)
                    _draw_centered(painter, glyph, center, dpr)
            return

        values = self._image.values[y0:y1, x0:x1]
        font_pixels = self._font_pixels(zoom, self._max_digits(), line_count=3)
        for row in range(y1 - y0):
            for column in range(x1 - x0):
                blue, green, red = values[row, column]
                for line, (value, color) in enumerate(zip((red, green, blue), CHANNEL_TEXT_COLORS, strict=True)):
                    glyph = self._glyph(_format_value(value), color, True, font_pixels, dpr)
                    center = origin + QPointF((x0 + column + 0.5) * zoom, (y0 + row + (line + 0.5) / 3) * zoom)
                    _draw_centered(painter, glyph, center, dpr)

    def _max_digits(self) -> int:
        """Widest value label the image can produce, so the font size does not change from cell to cell."""
        assert self._image is not None
        values = self._image.values
        if values.dtype.kind == "f":
            return 5
        if self._image.is_label_mask:
            # * Masks have few IDs, so size for at least two digits to make them easy to read.
            return max(2, len(str(int(values.max()))))
        return len(str(np.iinfo(values.dtype).max))

    @staticmethod
    def _font_pixels(zoom: float, digit_count: int, line_count: int) -> int:
        """Largest font pixel size that fits ``line_count`` lines of ``digit_count`` digits in a cell."""
        # Monospace digits are about 0.6 em wide; digit-only lines need about 1.05 em including spacing.
        usable = zoom * 0.9
        return max(MIN_FONT_PIXELS, int(min(usable / (digit_count * 0.62), usable / (line_count * 1.05))))

    def _glyph(self, text: str, color: QColor, outlined: bool, font_pixels: int, dpr: float) -> QPixmap:
        """Returns a cached, device-pixel-ratio-aware pixmap of ``text``."""
        key = (text, color.rgba(), outlined, font_pixels, dpr)
        if (cached := self._glyph_cache.get(key)) is not None:
            return cached
        if len(self._glyph_cache) >= GLYPH_CACHE_LIMIT:
            self._glyph_cache.clear()

        font = QFont(self._value_font)
        font.setPixelSize(font_pixels)
        path = QPainterPath()
        path.addText(0, 0, font, text)
        outline_width = max(2.0, font_pixels / 5) if outlined else 0.0
        bounds = path.boundingRect().adjusted(-outline_width, -outline_width, outline_width, outline_width)
        pixmap = QPixmap(max(1, math.ceil(bounds.width() * dpr)), max(1, math.ceil(bounds.height() * dpr)))
        pixmap.setDevicePixelRatio(dpr)
        pixmap.fill(Qt.GlobalColor.transparent)

        glyph_painter = QPainter(pixmap)
        glyph_painter.setRenderHint(QPainter.RenderHint.Antialiasing)
        glyph_painter.translate(-bounds.topLeft())
        if outlined:
            outline_pen = QPen(OUTLINE_COLOR, outline_width)
            outline_pen.setJoinStyle(Qt.PenJoinStyle.RoundJoin)
            glyph_painter.strokePath(path, outline_pen)
        glyph_painter.fillPath(path, color)
        glyph_painter.end()

        self._glyph_cache[key] = pixmap
        return pixmap

    def _cell_rect(self, x: int, y: int) -> QRect:
        """Widget rect covering image pixel ``(x, y)``, padded so outline updates repaint cleanly."""
        top_left = self.image_to_screen(QPointF(x, y))
        return QRectF(top_left.x(), top_left.y(), self.zoom, self.zoom).toAlignedRect()

    def _set_hover(self, pixel: tuple[int, int] | None) -> None:
        """Moves the hover outline, repainting only the old and new cells."""
        if pixel == self._hover:
            return
        for cell in (self._hover, pixel):
            if cell is not None and self.zoom >= HOVER_MIN_ZOOM:
                self.update(self._cell_rect(*cell).adjusted(-2, -2, 2, 2))
        self._hover = pixel
        self.cursor_moved.emit(pixel)

    # --------------------------------- Input --------------------------------- #
    def event(self, event: QEvent) -> bool:
        """Handles the trackpad pinch gesture (macOS and Wayland); other events go to the default handlers."""
        if (
            event.type() == QEvent.Type.NativeGesture
            and isinstance(event, QNativeGestureEvent)
            and event.gestureType() == Qt.NativeGestureType.ZoomNativeGesture
        ):
            self._pinch_accumulator += event.value()
            if abs(self._pinch_accumulator) >= PINCH_PER_STEP:
                direction = 1 if self._pinch_accumulator > 0 else -1
                self._pinch_accumulator = 0.0
                self.zoom_by_steps(direction, event.position())
            return True
        return super().event(event)

    def wheelEvent(self, event: QWheelEvent) -> None:
        """Zooms around the pointer, one level per notch or per equivalent trackpad scroll distance."""
        event.accept()
        # * Trackpad momentum after the fingers lift would keep zooming long after the user stopped.
        if event.phase() == Qt.ScrollPhase.ScrollMomentum:
            return
        delta = event.angleDelta().y() or event.angleDelta().x()
        # * Undo macOS "natural scrolling" so wheel-away always zooms in, whatever the system setting.
        if event.inverted():
            delta = -delta
        self._wheel_accumulator += delta
        if abs(self._wheel_accumulator) < WHEEL_UNITS_PER_STEP:
            return
        direction = 1 if self._wheel_accumulator > 0 else -1
        # Cap at one level per event and drop any backlog, so a fast flick cannot overshoot several levels.
        self._wheel_accumulator = 0.0
        self.zoom_by_steps(direction, event.position())

    def mousePressEvent(self, event: QMouseEvent) -> None:
        """Starts a drag-to-pan with the left button."""
        if event.button() == Qt.MouseButton.LeftButton and self._image is not None:
            self._drag_last = event.position()
            self.setCursor(Qt.CursorShape.ClosedHandCursor)
            event.accept()
            return
        super().mousePressEvent(event)

    def mouseMoveEvent(self, event: QMouseEvent) -> None:
        """Pans while dragging and tracks the pixel under the pointer."""
        if self._drag_last is not None:
            delta = event.position() - self._drag_last
            self._drag_last = event.position()
            self._center -= delta / self.zoom
            self._after_view_change()
        self._set_hover(self.pixel_at(event.position()))

    def mouseReleaseEvent(self, event: QMouseEvent) -> None:
        """Ends a drag-to-pan."""
        if event.button() == Qt.MouseButton.LeftButton and self._drag_last is not None:
            self._drag_last = None
            self.unsetCursor()
            event.accept()
            return
        super().mouseReleaseEvent(event)

    def keyPressEvent(self, event: QKeyEvent) -> None:
        """Pans with W, A, S and D; other keys go to the window's shortcuts."""
        direction = WASD_PAN_DIRECTIONS.get(event.key())
        unmodified = event.modifiers() in (Qt.KeyboardModifier.NoModifier, Qt.KeyboardModifier.KeypadModifier)
        if direction is None or not unmodified:
            super().keyPressEvent(event)
            return
        self.pan_by_fraction(direction[0] * PAN_FRACTION, direction[1] * PAN_FRACTION)

    def resizeEvent(self, event: QResizeEvent) -> None:
        """Keeps the view inside the image when the window size changes."""
        super().resizeEvent(event)
        self._clamp_center()
        self.view_changed.emit()

    def leaveEvent(self, event: QEvent) -> None:
        """Clears the hover outline when the pointer leaves the canvas."""
        super().leaveEvent(event)
        self._set_hover(None)


# ================================== Drawing ================================== #
def _format_value(value: np.generic) -> str:
    """Formats a pixel value compactly: integers as-is, floats to three significant digits."""
    return f"{value:.3g}" if isinstance(value, np.floating) else str(int(value))


def _draw_centered(painter: QPainter, glyph: QPixmap, center: QPointF, dpr: float) -> None:
    """Draws ``glyph`` centred on ``center``, in logical (device-independent) points."""
    painter.drawPixmap(QPointF(center.x() - glyph.width() / (2 * dpr), center.y() - glyph.height() / (2 * dpr)), glyph)
