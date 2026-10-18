"""Tests for the main window: folder browsing, status bar and error reporting."""

# Standard Library
from pathlib import Path

# Third-party
import cv2
import numpy as np
import pytest
from PIL import Image
from PySide6.QtCore import QPointF, Qt
from PySide6.QtWidgets import QDialog, QFileDialog, QLabel, QMessageBox, QPushButton, QToolBar

# Local
from pixel_viewer.app import ExportDialog, MainWindow, main


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
def test_empty_state_opens_the_file_dialog(window: MainWindow) -> None:
    button = window.findChild(QPushButton, "open_image_button")

    assert button is not None and button.isVisible()
    button.click()

    dialog = window.findChild(QFileDialog)
    assert dialog is not None and dialog.isVisible()


def test_empty_state_hides_once_an_image_is_open(window: MainWindow, frames: Path) -> None:
    window.open_path(frames)

    assert not window.empty_state.isVisible()


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
def test_unsupported_file_stays_on_the_launch_screen(window: MainWindow, tmp_path: Path) -> None:
    notes = tmp_path / "notes.txt"
    notes.write_text("x")

    assert not window.open_path(notes)

    error = window.findChild(QLabel, "empty_error")
    assert error is not None and error.isVisible()
    assert "Unsupported image type" in error.text()
    assert window.findChild(QMessageBox) is None
    assert window.findChild(QPushButton, "open_image_button").isEnabled()


def test_empty_folder_leaves_the_window_clickable(window: MainWindow, tmp_path: Path) -> None:
    assert not window.open_path(tmp_path)

    error = window.findChild(QLabel, "empty_error")
    assert error is not None and error.isVisible()
    assert "No supported images" in error.text()
    window.findChild(QPushButton, "open_image_button").click()

    dialog = window.findChild(QFileDialog)
    assert dialog is not None and dialog.isVisible()


def test_playback_advances_and_loops(window: MainWindow, frames: Path, qtbot) -> None:
    window.open_path(frames)
    window.speed_slider.setValue(100)
    assert window.speed_label.text() == "0.1 s"
    assert not window.play_action.isChecked()

    window.play_action.trigger()
    qtbot.waitUntil(lambda: window.canvas.image.path.name == "frame_2.png", timeout=2000)
    window._go_to(len(window._folder.paths) - 1)
    qtbot.waitUntil(lambda: window.canvas.image.path.name == "frame_1.png", timeout=2000)

    window.play_action.trigger()

    assert not window.play_timer.isActive()
    assert window.play_action.iconText() == "Play"


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


# ==================================== Export ================================= #
def test_export_stays_disabled_until_a_folder_is_open(window: MainWindow, frames: Path) -> None:
    menus = [action.menu() for action in window.menuBar().actions() if action.menu() is not None]

    toolbar = window.findChild(QToolBar, "main_toolbar")

    assert toolbar is not None
    assert window.export_action in toolbar.actions()
    assert not window.export_action.isEnabled()
    assert any(window.export_action in menu.actions() for menu in menus)

    window.open_path(frames)

    assert window.export_action.isEnabled()


def test_export_dialog_defaults_to_every_frame(window: MainWindow, frames: Path) -> None:
    window.open_path(frames)
    dialog = ExportDialog(window._folder.paths, window._folder.folder, window)

    settings = dialog.settings()

    assert [path.name for path in settings.paths] == ["frame_1.png", "frame_2.png", "frame_10.png"]
    assert settings.fps == 10
    assert settings.gif_path == frames / f"{frames.name}.gif"
    assert settings.video_path == frames / f"{frames.name}.mp4"
    assert "frame_1.png through frame_10.png" in dialog.summary_label.text()


def test_export_dialog_range_is_clamped_and_a_format_is_required(window: MainWindow, frames: Path) -> None:
    window.open_path(frames)
    dialog = ExportDialog(window._folder.paths, window._folder.folder, window)
    dialog.to_spin.setValue(1)

    assert [path.name for path in dialog.settings().paths] == ["frame_1.png"]

    dialog.gif_box.setChecked(False)
    dialog.video_box.setChecked(False)
    dialog.accept()

    assert dialog.result() != QDialog.DialogCode.Accepted
    assert "GIF" in dialog.preview_label.text()


def test_export_asks_before_replacing_a_file(window: MainWindow, frames: Path, mocker) -> None:
    window.open_path(frames)
    existing = frames / f"{frames.name}.gif"
    existing.write_bytes(b"old")

    def fake_exec(self: ExportDialog) -> QDialog.DialogCode:
        self.video_box.setChecked(False)
        return QDialog.DialogCode.Accepted

    mocker.patch.object(ExportDialog, "exec", fake_exec)
    question = mocker.patch.object(QMessageBox, "question", return_value=QMessageBox.StandardButton.No)

    window.export_action.trigger()

    question.assert_called_once()
    assert existing.name in question.call_args.args[2]
    assert existing.read_bytes() == b"old"
    assert window.export_action.isEnabled()


def test_export_animation_writes_the_chosen_frames(window: MainWindow, frames: Path, qtbot, mocker) -> None:
    window.open_path(frames)
    gif = frames / "seq.gif"
    video = frames / "seq.mp4"

    def fake_exec(self: ExportDialog) -> QDialog.DialogCode:
        self.path_edit.setText(str(frames / "seq"))
        self.to_spin.setValue(2)
        self.fps_spin.setValue(5)
        return QDialog.DialogCode.Accepted

    mocker.patch.object(ExportDialog, "exec", fake_exec)
    warning = mocker.patch.object(QMessageBox, "warning")

    window.export_action.trigger()
    qtbot.waitUntil(lambda: gif.exists() and video.exists() and window.export_action.isEnabled(), timeout=20000)

    assert warning.call_count == 0
    assert "seq.gif" in window.statusBar().currentMessage()
    assert "seq.mp4" in window.statusBar().currentMessage()
    with Image.open(gif) as image:
        assert image.n_frames == 2
        assert image.size == (400, 300)
        image.seek(0)
        assert image.info["duration"] == 200
    capture = cv2.VideoCapture(str(video))
    assert capture.get(cv2.CAP_PROP_FRAME_COUNT) == 2
    assert capture.get(cv2.CAP_PROP_FPS) == pytest.approx(5)
    capture.release()


def test_shortcuts_include_export(window: MainWindow, mocker) -> None:
    captured: dict[str, str] = {}

    def fake_exec(self: QMessageBox) -> int:
        captured["text"] = self.text()
        return 0

    mocker.patch.object(QMessageBox, "exec", fake_exec)

    window.show_shortcuts()

    assert "Export a GIF or video" in captured["text"]


def test_wasd_reaches_canvas_through_window(window: MainWindow, frames: Path, qtbot) -> None:
    window.open_path(frames)
    window.canvas.zoom_by_steps(3)
    before = window.canvas.screen_to_image(QPointF(0, 0))

    qtbot.keyClick(window.canvas, Qt.Key.Key_S)

    assert window.canvas.screen_to_image(QPointF(0, 0)).y() > before.y()
