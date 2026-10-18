"""Tests for the folder thumbwheel."""

# Third-party
from PySide6.QtCore import QPoint, QPointF, Qt
from PySide6.QtGui import QWheelEvent
from PySide6.QtWidgets import QApplication

# Local
from pixel_viewer.dial import FrameDial


def _scroll(dial: FrameDial, angle: int) -> None:
    """Sends one wheel event whose angle delta is ``angle`` (120 is one notch upward)."""
    local = QPointF(dial.width() / 2, dial.height() / 2)
    event = QWheelEvent(
        local,
        QPointF(dial.mapToGlobal(local.toPoint())),
        QPoint(0, 0),
        QPoint(0, angle),
        Qt.MouseButton.NoButton,
        Qt.KeyboardModifier.NoModifier,
        Qt.ScrollPhase.ScrollUpdate,
        False,
    )
    QApplication.sendEvent(dial, event)


def test_scroll_down_moves_to_the_next_image(qtbot) -> None:
    dial = FrameDial()
    qtbot.addWidget(dial)
    dial.resize(96, 400)
    dial.set_position(0, 5)
    chosen: list[int] = []
    dial.index_selected.connect(chosen.append)

    _scroll(dial, -120)

    assert chosen == [1]
    assert dial.index == 1


def test_drag_down_moves_one_image_per_detent(qtbot) -> None:
    dial = FrameDial()
    qtbot.addWidget(dial)
    dial.resize(96, 400)
    dial.show()
    dial.set_position(0, 5)

    qtbot.mousePress(dial, Qt.MouseButton.LeftButton, pos=QPoint(48, 200))
    qtbot.mouseMove(dial, QPoint(48, 212))
    qtbot.mouseRelease(dial, Qt.MouseButton.LeftButton, pos=QPoint(48, 212))

    assert dial.index == 2


def test_a_long_folder_can_be_crossed_in_one_drag(qtbot) -> None:
    dial = FrameDial()
    qtbot.addWidget(dial)
    dial.resize(96, 400)
    dial.show()
    dial.set_position(0, 500)

    qtbot.mousePress(dial, Qt.MouseButton.LeftButton, pos=QPoint(48, 52))
    qtbot.mouseMove(dial, QPoint(48, 52 + 336))

    assert dial.index == 499
