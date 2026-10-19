"""A scroll wheel on the side of the window for moving through a folder."""

# ================================== Imports ================================== #
# Standard Library
import math

# Third-party
from PySide6.QtCore import QEasingCurve, QPointF, QRect, QRectF, Qt, QVariantAnimation, Signal
from PySide6.QtGui import (
    QColor,
    QFont,
    QFontDatabase,
    QLinearGradient,
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
RIDGE_SPACING = 9.0
WHEEL_UNITS_PER_IMAGE = 120
FINE_DRAG_PIXELS = 6
DRAG_START_PIXELS = 3
ROLL_MS = 130

PANEL_COLOR = QColor(22, 25, 34)
EDGE_COLOR = QColor(42, 49, 66)
ACCENT_COLOR = QColor(230, 179, 37)
INDEX_COLOR = QColor(242, 244, 248)
MUTED_COLOR = QColor(154, 163, 181)


# =================================== Dial ==================================== #
class FrameDial(QWidget):
    """Knurled scroll wheel. Rolling or dragging it moves through the open folder.

    Stills, GIFs and videos are one list. A short folder moves one file every few pixels of drag. A long folder
    maps the height of the wheel onto the whole folder, so one drag can reach any file. One wheel notch is one file.

    Signals:
        index_selected: The file index the user rolled to.
    """

    index_selected = Signal(int)

    def __init__(self, parent: QWidget | None = None) -> None:
        """Creates an empty wheel.

        Args:
            parent: Owning widget.
        """
        super().__init__(parent)
        self.setObjectName("frame_dial")
        self.setFixedWidth(DIAL_WIDTH)
        self.setFocusPolicy(Qt.FocusPolicy.NoFocus)
        self.setMouseTracking(True)
        self.setAttribute(Qt.WidgetAttribute.WA_OpaquePaintEvent)
        self.setAccessibleName("Folder scroll wheel")
        self.setToolTip("Scroll or drag to move through images, GIFs and videos")

        self._index = 0
        self._count = 0
        self._label = ""
        self._offset = 0.0
        self._wheel_accumulator = 0.0
        self._drag_origin_y: float | None = None
        self._drag_origin_index = 0
        self._animation = QVariantAnimation(self)
        self._animation.setDuration(ROLL_MS)
        self._animation.setEasingCurve(QEasingCurve.Type.OutCubic)
        self._animation.valueChanged.connect(self._on_roll)

    # -------------------------------- State ---------------------------------- #
    @property
    def index(self) -> int:
        """Selected file index, or 0 when the folder is empty."""
        return self._index

    @property
    def count(self) -> int:
        """Number of files the wheel can reach."""
        return self._count

    @property
    def label(self) -> str:
        """Name of the file currently on the wheel."""
        return self._label

    def set_position(self, index: int, count: int, label: str = "") -> None:
        """Shows ``index`` within a folder of ``count`` files without emitting ``index_selected``.

        A one-file step rolls the wheel into the next detent. A jump, or a new folder, lands immediately.
        A drag in progress keeps the wheel under the pointer.

        Args:
            index: Selected position, clamped to the folder.
            count: Number of files. Zero draws an idle wheel.
            label: File name shown under the wheel.
        """
        count_changed = count != self._count
        self._count = max(count, 0)
        self._label = label
        last = max(self._count - 1, 0)
        index = min(max(index, 0), last)
        self._index = index
        if self._drag_origin_y is not None:
            self.update()
            return
        distance = abs(self._offset - index)
        if count_changed or distance > 1.01:
            self._animation.stop()
            self._offset = float(index)
        elif distance > 0.01:
            self._animate_to(float(index))
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
        """The capsule the ridges roll inside."""
        top = 56.0
        bottom = 36.0
        return QRectF(26, top, 46, max(self.height() - top - bottom, 48))

    def _pixels_per_image(self) -> float:
        """Drag distance that advances one file. Long folders use the whole wheel as the range."""
        span = max(self._count - 1, 1)
        travel = max(self._track().height(), 1.0)
        if span * FINE_DRAG_PIXELS <= travel:
            return float(FINE_DRAG_PIXELS)
        return travel / span

    def _animate_to(self, target: float) -> None:
        """Rolls the ridges from where they are to ``target``."""
        self._animation.stop()
        self._animation.setStartValue(self._offset)
        self._animation.setEndValue(target)
        self._animation.start()

    def _on_roll(self, value: object) -> None:
        """Applies one frame of a detent animation."""
        if self._drag_origin_y is not None:
            return
        self._offset = float(value)  # type: ignore[arg-type]
        self.update()

    # -------------------------------- Paint ---------------------------------- #
    def paintEvent(self, event: QPaintEvent) -> None:
        """Draws the housing, the knurled wheel and the file it is resting on."""
        del event
        painter = QPainter(self)
        painter.setRenderHint(QPainter.RenderHint.Antialiasing)
        painter.fillRect(self.rect(), PANEL_COLOR)
        painter.fillRect(0, 0, 1, self.height(), EDGE_COLOR)
        self._draw_heading(painter)
        track = self._track()
        self._draw_wheel(painter, track)
        self._draw_pointer(painter, track)
        self._draw_label(painter, track)

    def _draw_heading(self, painter: QPainter) -> None:
        """Draws the 1-based index and the folder size above the wheel."""
        index_font = QFont(QFontDatabase.systemFont(QFontDatabase.SystemFont.GeneralFont))
        index_font.setPixelSize(18)
        index_font.setWeight(QFont.Weight.DemiBold)
        painter.setFont(index_font)
        painter.setPen(INDEX_COLOR if self._count else MUTED_COLOR)
        number = "–" if self._count == 0 else str(self._index + 1)
        painter.drawText(QRect(0, 6, self.width(), 22), Qt.AlignmentFlag.AlignCenter, number)

        total_font = QFont(QFontDatabase.systemFont(QFontDatabase.SystemFont.GeneralFont))
        total_font.setPixelSize(11)
        painter.setFont(total_font)
        painter.setPen(MUTED_COLOR)
        total = "empty" if self._count == 0 else f"of {self._count}"
        painter.drawText(QRect(0, 28, self.width(), 16), Qt.AlignmentFlag.AlignCenter, total)

    def _draw_wheel(self, painter: QPainter, track: QRectF) -> None:
        """Draws a cylinder whose ridges sit on the current roll position."""
        radius = track.width() / 2
        clip = QPainterPath()
        clip.addRoundedRect(track, radius, radius)
        painter.save()
        painter.setClipPath(clip)

        body = QLinearGradient(track.topLeft(), track.topRight())
        body.setColorAt(0.0, QColor(8, 9, 14))
        body.setColorAt(0.16, QColor(26, 30, 40))
        body.setColorAt(0.46, QColor(58, 66, 84))
        body.setColorAt(0.54, QColor(86, 96, 116))
        body.setColorAt(0.84, QColor(30, 34, 46))
        body.setColorAt(1.0, QColor(10, 12, 18))
        painter.fillRect(track, body)
        self._draw_ridges(painter, track)

        shine = QLinearGradient(track.topLeft(), track.topRight())
        shine.setColorAt(0.0, QColor(255, 255, 255, 0))
        shine.setColorAt(0.46, QColor(255, 255, 255, 10))
        shine.setColorAt(0.54, QColor(255, 255, 255, 28))
        shine.setColorAt(0.70, QColor(255, 255, 255, 0))
        shine.setColorAt(1.0, QColor(0, 0, 0, 40))
        painter.fillRect(track, shine)

        fade = QLinearGradient(track.topLeft(), track.bottomLeft())
        fade.setColorAt(0.0, QColor(8, 9, 14, 230))
        fade.setColorAt(0.16, QColor(8, 9, 14, 0))
        fade.setColorAt(0.84, QColor(8, 9, 14, 0))
        fade.setColorAt(1.0, QColor(8, 9, 14, 230))
        painter.fillRect(track, fade)
        painter.restore()

        painter.setPen(QPen(QColor(72, 80, 98), 1))
        painter.setBrush(Qt.BrushStyle.NoBrush)
        painter.drawRoundedRect(track, radius, radius)

    def _draw_ridges(self, painter: QPainter, track: QRectF) -> None:
        """Draws the rubber grooves, shifted by the fractional part of the roll."""
        phase = math.modf(self._offset)[0] * RIDGE_SPACING
        center_y = track.center().y()
        left = track.left() + 5
        right = track.right() - 5
        y = track.top() - RIDGE_SPACING + phase
        while y < track.bottom() + RIDGE_SPACING:
            distance = abs(y - center_y)
            nearest = distance < RIDGE_SPACING * 0.5
            fade = max(0.0, 1.0 - (distance / (track.height() / 2)) ** 1.3)
            alpha = int(220 * fade)
            if nearest and self._count > 1:
                groove = QColor(ACCENT_COLOR)
                groove.setAlpha(min(alpha + 40, 255))
                highlight = QColor(255, 214, 120, min(alpha, 180))
                thickness = 2.6
            else:
                groove = QColor(6, 7, 10, alpha)
                highlight = QColor(170, 180, 198, alpha // 3)
                thickness = 2.0
            painter.setPen(QPen(groove, thickness, Qt.PenStyle.SolidLine, Qt.PenCapStyle.FlatCap))
            painter.drawLine(QPointF(left, y), QPointF(right, y))
            painter.setPen(QPen(highlight, 1, Qt.PenStyle.SolidLine, Qt.PenCapStyle.FlatCap))
            painter.drawLine(QPointF(left, y + 2.2), QPointF(right, y + 2.2))
            y += RIDGE_SPACING

    def _draw_pointer(self, painter: QPainter, track: QRectF) -> None:
        """Draws the fixed notch the wheel turns under."""
        center_y = track.center().y()
        pointer = QPainterPath()
        pointer.moveTo(track.left() - 8, center_y)
        pointer.lineTo(track.left() + 1, center_y - 5)
        pointer.lineTo(track.left() + 1, center_y + 5)
        pointer.closeSubpath()
        painter.setPen(Qt.PenStyle.NoPen)
        painter.setBrush(ACCENT_COLOR if self._count > 1 else MUTED_COLOR)
        painter.drawPath(pointer)

    def _draw_label(self, painter: QPainter, track: QRectF) -> None:
        """Draws the current file name, keeping the extension visible when it is shortened."""
        if not self._label:
            return
        font = QFont(QFontDatabase.systemFont(QFontDatabase.SystemFont.GeneralFont))
        font.setPixelSize(10)
        painter.setFont(font)
        painter.setPen(MUTED_COLOR)
        rect = QRect(6, int(track.bottom()) + 8, self.width() - 12, 18)
        text = painter.fontMetrics().elidedText(self._label, Qt.TextElideMode.ElideMiddle, rect.width())
        painter.drawText(rect, Qt.AlignmentFlag.AlignCenter, text)

    # -------------------------------- Input ---------------------------------- #
    def wheelEvent(self, event: QWheelEvent) -> None:
        """Steps one file per wheel notch. Scroll down moves to a later file."""
        event.accept()
        if self._count < 2 or event.phase() == Qt.ScrollPhase.ScrollMomentum:
            return
        delta = event.angleDelta().y() or event.angleDelta().x()
        # * Keep the wheel matched to the platform: a downward scroll always moves to a later file.
        if event.inverted():
            delta = -delta
        self._wheel_accumulator += delta
        if abs(self._wheel_accumulator) < WHEEL_UNITS_PER_IMAGE:
            return
        steps = int(self._wheel_accumulator / WHEEL_UNITS_PER_IMAGE)
        self._wheel_accumulator -= steps * WHEEL_UNITS_PER_IMAGE
        self._select(self._index - steps)

    def mousePressEvent(self, event: QMouseEvent) -> None:
        """Starts a drag that rolls the wheel with the pointer."""
        if event.button() == Qt.MouseButton.LeftButton and self._count >= 2:
            self._animation.stop()
            self._offset = float(self._index)
            self._drag_origin_y = event.position().y()
            self._drag_origin_index = self._index
            self.setCursor(Qt.CursorShape.ClosedHandCursor)
            event.accept()
            return
        super().mousePressEvent(event)

    def mouseMoveEvent(self, event: QMouseEvent) -> None:
        """Rolls by the drag distance. A small movement is ignored so a click does not change files."""
        if self._drag_origin_y is None:
            return
        delta = event.position().y() - self._drag_origin_y
        if abs(delta) < DRAG_START_PIXELS:
            return
        raw = self._drag_origin_index + delta / self._pixels_per_image()
        limit = float(max(self._count - 1, 0))
        self._offset = min(max(raw, 0.0), limit)
        steps = math.trunc(delta / self._pixels_per_image())
        self._select(self._drag_origin_index + steps)
        self.update()

    def mouseReleaseEvent(self, event: QMouseEvent) -> None:
        """Lets the wheel settle into the detent it landed on."""
        if event.button() == Qt.MouseButton.LeftButton and self._drag_origin_y is not None:
            self._drag_origin_y = None
            self.unsetCursor()
            self._animate_to(float(self._index))
            event.accept()
            return
        super().mouseReleaseEvent(event)
