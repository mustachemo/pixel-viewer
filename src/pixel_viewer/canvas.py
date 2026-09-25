"""The zoomable image canvas that draws a pixel grid and per-pixel values."""

# ================================== Imports ================================== #
# Standard Library
import math

# Third-party
from PySide6.QtCore import QEvent, QPointF, QRect, QRectF, Qt, Signal
from PySide6.QtGui import (
    QColor,
    QCursor,
    QImage,
    QMouseEvent,
    QPainter,
    QPaintEvent,
    QPen,
    QResizeEvent,
)
from PySide6.QtWidgets import QWidget

# Local
from pixel_viewer.images import LoadedImage

# ================================== Constants ================================ #
ZOOM_STEPS = (1, 2, 3, 4, 6, 8, 12, 16, 24, 32, 48, 64, 96, 128)
HOVER_MIN_ZOOM = 4

BACKGROUND_COLOR = QColor(30, 30, 30)
HOVER_COLOR = QColor(255, 220, 0)
PLACEHOLDER_COLOR = QColor(150, 150, 150)


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
        """Draws the part of the image inside the dirty rect."""
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

        if self._hover is not None and zoom >= HOVER_MIN_ZOOM:
            hover_pen = QPen(HOVER_COLOR, 2)
            hover_pen.setCosmetic(True)
            painter.setPen(hover_pen)
            painter.setBrush(Qt.BrushStyle.NoBrush)
            painter.drawRect(self._cell_rect(*self._hover).adjusted(1, 1, -1, -1))

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
    def mouseMoveEvent(self, event: QMouseEvent) -> None:
        """Tracks the pixel under the pointer."""
        self._set_hover(self.pixel_at(event.position()))

    def resizeEvent(self, event: QResizeEvent) -> None:
        """Keeps the view inside the image when the window size changes."""
        super().resizeEvent(event)
        self._clamp_center()
        self.view_changed.emit()

    def leaveEvent(self, event: QEvent) -> None:
        """Clears the hover outline when the pointer leaves the canvas."""
        super().leaveEvent(event)
        self._set_hover(None)
