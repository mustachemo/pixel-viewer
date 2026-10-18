"""A thumbwheel on the side of the window for scrubbing through a folder."""

# ================================== Imports ================================== #
# Standard Library
import math

# Third-party
from PySide6.QtCore import QPointF, QRect, QRectF, Qt, Signal
from PySide6.QtGui import (
    QColor,
    QFont,
    QFontDatabase,
    QMouseEvent,
    QPainter,
    QPainterPath,
    QPaintEvent,
    QPen,
    QWheelEvent,
)
from PySide6.QtWidgets import QWidget

# ================================== Constants ================================ #
DIAL_WIDTH = 96
TICK_SPACING = 16
WHEEL_UNITS_PER_IMAGE = 120
FINE_DRAG_PIXELS = 6
DRAG_START_PIXELS = 3

PANEL_COLOR = QColor(22, 25, 34)
EDGE_COLOR = QColor(42, 49, 66)
TRACK_COLOR = QColor(16, 18, 24)
TRACK_BORDER = QColor(52, 59, 76)
TICK_COLOR = QColor(92, 101, 120)
NEAR_TICK_COLOR = QColor(197, 206, 221)
ACCENT_COLOR = QColor(230, 179, 37)
INDEX_COLOR = QColor(242, 244, 248)
MUTED_COLOR = QColor(154, 163, 181)


# =================================== Dial ==================================== #
class FrameDial(QWidget):
    """Vertical thumbwheel. Scrolling or dragging it selects an image in the open folder.

    A short folder moves one image every few pixels of drag. A long folder maps the height of the wheel onto the
    whole folder, so one drag can reach any frame. The scroll wheel always steps one image per notch.

    Signals:
        index_selected: The image index the user scrubbed to.
    """

    index_selected = Signal(int)

    def __init__(self, parent: QWidget | None = None) -> None:
        """Creates an empty dial.

        Args:
            parent: Owning widget.
        """
        super().__init__(parent)
        self.setObjectName("frame_dial")
        self.setFixedWidth(DIAL_WIDTH)
        self.setFocusPolicy(Qt.FocusPolicy.NoFocus)
        self.setMouseTracking(True)
        self.setAttribute(Qt.WidgetAttribute.WA_OpaquePaintEvent)
        self.setAccessibleName("Frame dial")
        self.setToolTip("Scroll or drag to move through the folder")

        self._index = 0
        self._count = 0
        self._wheel_accumulator = 0.0
        self._drag_origin_y: float | None = None
        self._drag_origin_index = 0

    # -------------------------------- State ---------------------------------- #
    @property
    def index(self) -> int:
        """Selected image index, or 0 when the folder is empty."""
        return self._index

    @property
    def count(self) -> int:
        """Number of images the dial can reach."""
        return self._count

    def set_position(self, index: int, count: int) -> None:
        """Shows ``index`` within a folder of ``count`` images without emitting ``index_selected``.

        Args:
            index: Selected position, clamped to the folder.
            count: Number of images. Zero hides the meaningful markings.
        """
        self._count = max(count, 0)
        last = max(self._count - 1, 0)
        self._index = min(max(index, 0), last)
        self.update()

    def _select(self, index: int) -> None:
        """Clamps ``index`` and tells the window when the selection changed."""
        if self._count < 2:
            return
        clamped = min(max(index, 0), self._count - 1)
        if clamped == self._index:
            return
        self._index = clamped
        self.update()
        self.index_selected.emit(clamped)

    def _track(self) -> QRectF:
        """Rounded column the tick marks live in."""
        return QRectF(30, 52, 36, max(self.height() - 64, 36))

    def _pixels_per_image(self) -> float:
        """Drag distance that advances one image. Long folders use the whole wheel as the range."""
        span = max(self._count - 1, 1)
        travel = max(self._track().height(), 1.0)
        if span * FINE_DRAG_PIXELS <= travel:
            return float(FINE_DRAG_PIXELS)
        return travel / span

    # -------------------------------- Paint ---------------------------------- #
    def paintEvent(self, event: QPaintEvent) -> None:
        """Draws the wheel, the fixed pointer and the current position."""
        del event
        painter = QPainter(self)
        painter.setRenderHint(QPainter.RenderHint.Antialiasing)
        painter.fillRect(self.rect(), PANEL_COLOR)
        painter.fillRect(0, 0, 1, self.height(), EDGE_COLOR)
        self._draw_heading(painter)
        track = self._track()
        self._draw_track(painter, track)
        if self._count > 0:
            self._draw_ticks(painter, track)
            self._draw_pointer(painter, track)
            self._draw_position_pip(painter)

    def _draw_heading(self, painter: QPainter) -> None:
        """Draws the 1-based index and the folder size above the wheel."""
        index_font = QFont(QFontDatabase.systemFont(QFontDatabase.SystemFont.GeneralFont))
        index_font.setPixelSize(18)
        index_font.setWeight(QFont.Weight.DemiBold)
        painter.setFont(index_font)
        painter.setPen(INDEX_COLOR if self._count else MUTED_COLOR)
        number = "–" if self._count == 0 else str(self._index + 1)
        painter.drawText(QRect(0, 4, self.width(), 24), Qt.AlignmentFlag.AlignCenter, number)

        total_font = QFont(QFontDatabase.systemFont(QFontDatabase.SystemFont.GeneralFont))
        total_font.setPixelSize(11)
        painter.setFont(total_font)
        painter.setPen(MUTED_COLOR)
        total = "no images" if self._count == 0 else f"of {self._count}"
        painter.drawText(QRect(0, 26, self.width(), 16), Qt.AlignmentFlag.AlignCenter, total)

    def _draw_track(self, painter: QPainter, track: QRectF) -> None:
        """Draws the recessed column the wheel sits in."""
        painter.setPen(QPen(TRACK_BORDER, 1))
        painter.setBrush(TRACK_COLOR)
        painter.drawRoundedRect(track, 18, 18)

    def _draw_ticks(self, painter: QPainter, track: QRectF) -> None:
        """Draws a tick per nearby image, with the selected image on the pointer."""
        painter.save()
        painter.setClipRect(track.adjusted(3, 10, -3, -10))
        center_y = track.center().y()
        mid_x = track.center().x()
        reach = int(track.height() / 2 / TICK_SPACING) + 1
        for offset in range(-reach, reach + 1):
            image_index = self._index + offset
            if not 0 <= image_index < self._count:
                continue
            y = center_y + offset * TICK_SPACING
            distance = abs(offset)
            if distance == 0:
                color, half, thickness = ACCENT_COLOR, 13.0, 2.4
            elif distance < 3:
                color, half, thickness = NEAR_TICK_COLOR, 10.0, 1.6
            else:
                fade = max(50, 210 - distance * 16)
                color, half, thickness = QColor(TICK_COLOR), 7.0, 1.2
                color.setAlpha(fade)
            pen = QPen(color, thickness, Qt.PenStyle.SolidLine, Qt.PenCapStyle.RoundCap)
            painter.setPen(pen)
            painter.drawLine(QPointF(mid_x - half, y), QPointF(mid_x + half, y))
        painter.restore()

    def _draw_pointer(self, painter: QPainter, track: QRectF) -> None:
        """Draws the fixed mark the wheel turns under."""
        center_y = track.center().y()
        pointer = QPainterPath()
        pointer.moveTo(track.left() - 7, center_y)
        pointer.lineTo(track.left() - 1, center_y - 5)
        pointer.lineTo(track.left() - 1, center_y + 5)
        pointer.closeSubpath()
        painter.setPen(Qt.PenStyle.NoPen)
        painter.setBrush(ACCENT_COLOR)
        painter.drawPath(pointer)

    def _draw_position_pip(self, painter: QPainter) -> None:
        """Draws where the selected image sits in the whole folder."""
        track = self._track()
        gutter_x = track.right() + 10
        painter.setPen(Qt.PenStyle.NoPen)
        painter.setBrush(QColor(52, 59, 76))
        painter.drawRoundedRect(QRectF(gutter_x - 1.5, track.top(), 3, track.height()), 1.5, 1.5)
        if self._count < 2:
            return
        fraction = self._index / (self._count - 1)
        pip_y = track.top() + fraction * track.height()
        painter.setBrush(ACCENT_COLOR)
        painter.drawRoundedRect(QRectF(gutter_x - 2.5, pip_y - 7, 5, 14), 2, 2)

    # -------------------------------- Input ---------------------------------- #
    def wheelEvent(self, event: QWheelEvent) -> None:
        """Steps one image per wheel notch. Scroll down moves to a later image."""
        event.accept()
        if self._count < 2 or event.phase() == Qt.ScrollPhase.ScrollMomentum:
            return
        delta = event.angleDelta().y() or event.angleDelta().x()
        # * Keep the dial matched to the platform: a downward scroll always moves to a later image.
        if event.inverted():
            delta = -delta
        self._wheel_accumulator += delta
        if abs(self._wheel_accumulator) < WHEEL_UNITS_PER_IMAGE:
            return
        steps = int(self._wheel_accumulator / WHEEL_UNITS_PER_IMAGE)
        self._wheel_accumulator -= steps * WHEEL_UNITS_PER_IMAGE
        self._select(self._index - steps)

    def mousePressEvent(self, event: QMouseEvent) -> None:
        """Starts a drag-to-scrub."""
        if event.button() == Qt.MouseButton.LeftButton and self._count >= 2:
            self._drag_origin_y = event.position().y()
            self._drag_origin_index = self._index
            self.setCursor(Qt.CursorShape.ClosedHandCursor)
            event.accept()
            return
        super().mousePressEvent(event)

    def mouseMoveEvent(self, event: QMouseEvent) -> None:
        """Scrubs by the drag distance. A small movement is ignored so a click does not change frames."""
        if self._drag_origin_y is None:
            return
        delta = event.position().y() - self._drag_origin_y
        if abs(delta) < DRAG_START_PIXELS:
            return
        steps = math.trunc(delta / self._pixels_per_image())
        self._select(self._drag_origin_index + steps)

    def mouseReleaseEvent(self, event: QMouseEvent) -> None:
        """Ends a drag-to-scrub."""
        if event.button() == Qt.MouseButton.LeftButton and self._drag_origin_y is not None:
            self._drag_origin_y = None
            self.unsetCursor()
            event.accept()
            return
        super().mouseReleaseEvent(event)
