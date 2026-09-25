"""Tests for the main window: folder browsing, status bar and error reporting."""

# Standard Library
from pathlib import Path

# Third-party
import cv2
import numpy as np
import pytest
from PySide6.QtCore import QPointF, Qt
from PySide6.QtWidgets import QFileDialog, QMessageBox

# Local
from pixel_viewer.app import MainWindow, main


# ================================== Fixtures ================================= #
@pytest.fixture
def frames(tmp_path: Path) -> Path:
    """A folder of three same-size color frames."""
    for number in (1, 2, 10):
        pixels = np.zeros((300, 400, 3), dtype=np.uint8)
        pixels[:, :, 1] = number
        cv2.imwrite(str(tmp_path / f"frame_{number}.png"), pixels)
    return tmp_path


@pytest.fixture
def window(qtbot) -> MainWindow:
    """A shown 800×600 main window with no image."""
    main_window = MainWindow()
    qtbot.addWidget(main_window)
    main_window.resize(800, 600)
    main_window.show()
    return main_window


# =================================== Browsing ================================ #
def test_arrow_navigation_keeps_zoom_and_position(window: MainWindow, frames: Path) -> None:
    assert window.open_path(frames / "frame_1.png")
    window.canvas.zoom_by_steps(3, QPointF(50, 50))
    zoom = window.canvas.zoom
    centre = window.canvas.screen_to_image(QPointF(100, 100))

    window.next_action.trigger()

    assert window.canvas.image.path.name == "frame_2.png"
    assert window.canvas.zoom == zoom
    assert window.canvas.screen_to_image(QPointF(100, 100)) == centre
    assert window.position_label.text() == "2 / 3"


def test_navigation_stops_at_folder_bounds(window: MainWindow, frames: Path) -> None:
    window.open_path(frames)

    assert not window.previous_action.isEnabled()
    window.last_action.trigger()
    assert window.canvas.image.path.name == "frame_10.png"
    assert not window.next_action.isEnabled()
    assert window.previous_action.isEnabled()


def test_toggle_gray_updates_mode(window: MainWindow, frames: Path) -> None:
    window.open_path(frames)

    window.toggle_gray_action.trigger()

    assert window.canvas.is_gray
    assert window.gray_action.isChecked()
    assert window.mode_label.text() == "Grayscale"


def test_status_bar_tracks_cursor(window: MainWindow) -> None:
    window.canvas.cursor_moved.emit((12, 345))

    assert window.cursor_label.text() == "x    12  y   345"


def test_open_dialog_is_non_blocking_and_opens_selection(window: MainWindow, frames: Path) -> None:
    window.open_file_dialog()

    dialog = window.findChild(QFileDialog)
    assert dialog is not None and dialog.isVisible()
    dialog.fileSelected.emit(str(frames / "frame_2.png"))

    assert window.canvas.image.path.name == "frame_2.png"


# ==================================== Errors ================================= #
def test_unsupported_file_warns(window: MainWindow, tmp_path: Path, mocker) -> None:
    warning = mocker.patch.object(QMessageBox, "warning")
    notes = tmp_path / "notes.txt"
    notes.write_text("x")

    assert not window.open_path(notes)

    warning.assert_called_once()
    assert "Unsupported image type" in warning.call_args.args[2]


def test_undecodable_frame_reports_in_status_bar(window: MainWindow, frames: Path) -> None:
    (frames / "frame_5.png").write_bytes(b"broken")
    window.open_path(frames / "frame_2.png")

    window.next_action.trigger()

    assert "Could not decode" in window.statusBar().currentMessage()
    assert window.canvas.image.path.name == "frame_2.png"


def test_main_prints_version(capsys) -> None:
    with pytest.raises(SystemExit):
        main(["--version"])

    assert capsys.readouterr().out.startswith("pixel-viewer 0.")


def test_main_rejects_missing_path(tmp_path: Path) -> None:
    with pytest.raises(SystemExit):
        main([str(tmp_path / "missing.png")])


def test_wasd_reaches_canvas_through_window(window: MainWindow, frames: Path, qtbot) -> None:
    window.open_path(frames)
    window.canvas.zoom_by_steps(3)
    before = window.canvas.screen_to_image(QPointF(0, 0))

    qtbot.keyClick(window.canvas, Qt.Key.Key_S)

    assert window.canvas.screen_to_image(QPointF(0, 0)).y() > before.y()
