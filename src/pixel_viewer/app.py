"""Main window and command-line entry point."""

# ================================== Imports ================================== #
# Standard Library
import argparse
import sys
import threading
import traceback
from collections.abc import Callable, Sequence
from importlib.metadata import PackageNotFoundError, version
from pathlib import Path

# Third-party
from PySide6.QtCore import QEvent, QObject, QPointF, QSettings, Qt, QThread, QTimer, Signal
from PySide6.QtGui import (
    QAction,
    QActionGroup,
    QCloseEvent,
    QCursor,
    QDragEnterEvent,
    QDropEvent,
    QFileOpenEvent,
    QFont,
    QFontDatabase,
    QGuiApplication,
    QKeySequence,
)
from PySide6.QtWidgets import (
    QApplication,
    QCheckBox,
    QDialog,
    QDialogButtonBox,
    QFileDialog,
    QFormLayout,
    QHBoxLayout,
    QLabel,
    QLineEdit,
    QMainWindow,
    QMessageBox,
    QProgressDialog,
    QPushButton,
    QSlider,
    QSpinBox,
    QStyle,
    QVBoxLayout,
    QWidget,
)

# Local
from pixel_viewer.canvas import PixelCanvas
from pixel_viewer.clip_bar import ClipBar
from pixel_viewer.dial import FrameDial
from pixel_viewer.export import (
    DEFAULT_FPS,
    MAX_FPS,
    MIN_FPS,
    AnimationExport,
    ExportCancelled,
    ExportError,
    animation_destinations,
    export_gif,
    export_video,
)
from pixel_viewer.images import VIEWABLE_SUFFIXES, ImageFolder, is_motion
from pixel_viewer.install_desktop import install_launcher
from pixel_viewer.media import MotionClip
from pixel_viewer.theme import apply_theme, window_icon

# ================================== Constants ================================ #
APP_NAME = "Pixel Viewer"
WINDOW_SIZE = (1400, 1000)
STATUS_MESSAGE_MS = 6000
PLAYBACK_MIN_MS = 100
PLAYBACK_MAX_MS = 5000
PLAYBACK_DEFAULT_MS = 1000
PLAYBACK_STEP_MS = 100
IMAGE_FILTER = f"Images and video ({' '.join(f'*{suffix}' for suffix in sorted(VIEWABLE_SUFFIXES))})"
ANIMATION_FILTER = "GIF (*.gif);;MP4 video (*.mp4)"


# ============================== Export dialog ================================ #
class ExportDialog(QDialog):
    """Asks which frames to write, at what rate, and whether to make a GIF, a video, or both."""

    def __init__(self, paths: Sequence[Path], folder: Path, parent: QWidget | None = None) -> None:
        """Builds the dialog for the images in ``paths``.

        Args:
            paths: Frames in playback order.
            folder: Folder those frames live in. The save path starts here.
            parent: Owning window.
        """
        super().__init__(parent)
        self._paths = list(paths)
        self._folder = folder
        self.setWindowTitle("Export Animation")
        self.setWindowModality(Qt.WindowModality.WindowModal)

        self.summary_label = QLabel()
        self.from_spin = QSpinBox()
        self.to_spin = QSpinBox()
        count = max(len(self._paths), 1)
        for spin, name in ((self.from_spin, "First frame"), (self.to_spin, "Last frame")):
            spin.setRange(1, count)
            spin.setAccessibleName(name)
        self.from_spin.setValue(1)
        self.to_spin.setValue(count)
        self.from_spin.valueChanged.connect(self._sync_range)
        self.to_spin.valueChanged.connect(self._sync_range)

        self.fps_spin = QSpinBox()
        self.fps_spin.setRange(MIN_FPS, MAX_FPS)
        self.fps_spin.setValue(DEFAULT_FPS)
        self.fps_spin.setSuffix(" fps")
        self.fps_spin.setAccessibleName("Frames per second")

        self.gif_box = QCheckBox("GIF")
        self.video_box = QCheckBox("MP4 video")
        self.gif_box.setChecked(True)
        self.video_box.setChecked(True)
        self.gif_box.toggled.connect(self._refresh_preview)
        self.video_box.toggled.connect(self._refresh_preview)

        self.path_edit = QLineEdit(str(folder / folder.name))
        self.path_edit.setAccessibleName("Save as")
        self.path_edit.setMinimumWidth(360)
        self.path_edit.textChanged.connect(self._refresh_preview)
        browse = QPushButton("Browse…")
        browse.clicked.connect(self._browse)

        self.preview_label = QLabel()
        self.preview_label.setWordWrap(True)

        range_row = QWidget()
        range_layout = QHBoxLayout(range_row)
        range_layout.setContentsMargins(0, 0, 0, 0)
        range_layout.addWidget(self.from_spin)
        range_layout.addWidget(QLabel("to"))
        range_layout.addWidget(self.to_spin)
        range_layout.addStretch(1)

        format_row = QWidget()
        format_layout = QHBoxLayout(format_row)
        format_layout.setContentsMargins(0, 0, 0, 0)
        format_layout.addWidget(self.gif_box)
        format_layout.addWidget(self.video_box)
        format_layout.addStretch(1)

        save_row = QWidget()
        save_layout = QHBoxLayout(save_row)
        save_layout.setContentsMargins(0, 0, 0, 0)
        save_layout.addWidget(self.path_edit, 1)
        save_layout.addWidget(browse)

        form = QFormLayout()
        form.addRow("Images", self.summary_label)
        form.addRow("Frames", range_row)
        form.addRow("Frames per second", self.fps_spin)
        form.addRow("Format", format_row)
        form.addRow("Save as", save_row)

        buttons = QDialogButtonBox(QDialogButtonBox.StandardButton.Ok | QDialogButtonBox.StandardButton.Cancel)
        export_button = buttons.button(QDialogButtonBox.StandardButton.Ok)
        export_button.setText("Export")
        export_button.setDefault(True)
        buttons.accepted.connect(self.accept)
        buttons.rejected.connect(self.reject)

        self.preview_label.setObjectName("hint")
        layout = QVBoxLayout(self)
        layout.setContentsMargins(20, 20, 20, 16)
        layout.setSpacing(14)
        form.setHorizontalSpacing(16)
        form.setVerticalSpacing(12)
        layout.addLayout(form)
        layout.addWidget(self.preview_label)
        layout.addWidget(buttons)
        self._refresh_summary()
        self._refresh_preview()

    def settings(self) -> AnimationExport:
        """Returns the request described by the form.

        Raises:
            ExportError: If the form has no format, no file name, or nowhere to save.
        """
        text = self.path_edit.text().strip()
        if not text:
            raise ExportError("Choose where to save the animation.")
        gif_path, video_path = animation_destinations(
            self._base_path(), gif=self.gif_box.isChecked(), video=self.video_box.isChecked()
        )
        for path in (gif_path, video_path):
            if path is not None and not path.parent.is_dir():
                raise ExportError(f"No such folder: {path.parent}")
        selected = tuple(self._paths[self.from_spin.value() - 1 : self.to_spin.value()])
        return AnimationExport(selected, self.fps_spin.value(), gif_path, video_path)

    def accept(self) -> None:
        """Closes the dialog when the form is valid, and explains it in place when it is not."""
        try:
            self.settings()
        except ExportError as error:
            self.preview_label.setText(str(error))
            return
        super().accept()

    def _base_path(self) -> Path:
        """Save location. A chosen folder is used as the directory, with the folder's name as the file name."""
        base = Path(self.path_edit.text().strip()).expanduser()
        if base.is_dir():
            return base / base.name
        return base

    def _sync_range(self) -> None:
        """Keeps the first frame from landing after the last, then updates the summary."""
        if self.from_spin.value() > self.to_spin.value():
            if self.sender() is self.from_spin:
                self.to_spin.setValue(self.from_spin.value())
            else:
                self.from_spin.setValue(self.to_spin.value())
        self._refresh_summary()

    def _refresh_summary(self) -> None:
        """Describes the frames the spin boxes currently include."""
        selected = self._paths[self.from_spin.value() - 1 : self.to_spin.value()]
        if len(selected) <= 1:
            self.summary_label.setText(selected[0].name if selected else "No images")
            return
        self.summary_label.setText(f"{len(selected)} images, {selected[0].name} through {selected[-1].name}")

    def _refresh_preview(self) -> None:
        """Shows the file names that Export will write."""
        if not self.gif_box.isChecked() and not self.video_box.isChecked():
            self.preview_label.setText("Choose a GIF, a video, or both.")
            return
        text = self.path_edit.text().strip()
        if not text:
            self.preview_label.setText("Choose where to save the animation.")
            return
        try:
            gif_path, video_path = animation_destinations(
                self._base_path(), gif=self.gif_box.isChecked(), video=self.video_box.isChecked()
            )
        except ExportError as error:
            self.preview_label.setText(str(error))
            return
        names = [path.name for path in (gif_path, video_path) if path is not None]
        self.preview_label.setText("Saves " + " and ".join(names))

    def _browse(self) -> None:
        """Asks for a save path without taking over the event loop."""
        # ! Same constraint as the open dialogs: exec() on a native file panel can stop taking clicks on macOS.
        current = self._base_path()
        start = current.parent if current.parent.is_dir() else self._folder
        video_only = self.video_box.isChecked() and not self.gif_box.isChecked()
        dialog = QFileDialog(self, "Export Animation", str(start / current.name), ANIMATION_FILTER)
        dialog.setAcceptMode(QFileDialog.AcceptMode.AcceptSave)
        dialog.setFileMode(QFileDialog.FileMode.AnyFile)
        dialog.setOption(QFileDialog.Option.DontConfirmOverwrite, True)
        dialog.setDefaultSuffix("mp4" if video_only else "gif")
        dialog.selectNameFilter("MP4 video (*.mp4)" if video_only else "GIF (*.gif)")
        dialog.setAttribute(Qt.WidgetAttribute.WA_DeleteOnClose)
        dialog.fileSelected.connect(self.path_edit.setText)
        dialog.open()


class _AnimationExporter(QObject):
    """Writes an animation off the UI thread and reports progress back with signals."""

    progressed = Signal(str, int, int)
    succeeded = Signal(str)
    failed = Signal(str)

    def __init__(self, settings: AnimationExport, cancelled: Callable[[], bool]) -> None:
        super().__init__()
        self._settings = settings
        self._cancelled = cancelled

    def run(self) -> None:
        """Writes each requested file. Runs on the export thread."""
        jobs: list[tuple[str, Path]] = []
        if self._settings.gif_path is not None:
            jobs.append(("GIF", self._settings.gif_path))
        if self._settings.video_path is not None:
            jobs.append(("video", self._settings.video_path))
        frame_count = len(self._settings.paths)
        total = frame_count * len(jobs)
        written: list[str] = []
        notes: list[str] = []
        try:
            for job_index, (label, path) in enumerate(jobs):

                def on_frame(index: int, _count: int, job_index: int = job_index, label: str = label) -> None:
                    self.progressed.emit(f"Writing {label}…", job_index * frame_count + index, total)

                if label == "GIF":
                    export_gif(
                        self._settings.paths,
                        path,
                        self._settings.fps,
                        on_frame=on_frame,
                        cancelled=self._cancelled,
                    )
                else:
                    note = export_video(
                        self._settings.paths,
                        path,
                        self._settings.fps,
                        on_frame=on_frame,
                        cancelled=self._cancelled,
                    )
                    if note:
                        notes.append(note)
                written.append(path.name)
        except ExportCancelled:
            message = "Export cancelled."
            if written:
                message = f"{message} Saved {' and '.join(written)}."
            self.succeeded.emit(message)
            return
        except ExportError as error:
            suffix = f" Saved {' and '.join(written)}." if written else ""
            self.failed.emit(f"{error}{suffix}")
            return
        except Exception as error:  # noqa: BLE001 - keep the window alive and show whatever the encoder raised.
            traceback.print_exc()
            self.failed.emit(str(error) or "Could not export the animation.")
            return
        message = f"Saved {' and '.join(written)}"
        if notes:
            message = f"{message}. {' '.join(notes)}"
        self.succeeded.emit(message)


def _dropped_paths(event: QDropEvent | QDragEnterEvent) -> list[Path]:
    """Local files carried by a drag, ignoring anything that is not a file URL."""
    return [Path(url.toLocalFile()) for url in event.mimeData().urls() if url.isLocalFile()]


# =============================== Empty state ================================= #
class EmptyState(QWidget):
    """Centered launch screen shown until an image is open."""

    def __init__(
        self,
        canvas: QWidget,
        on_open: Callable[[], object],
        on_open_folder: Callable[[], object],
        on_drop: Callable[[Path], object],
    ) -> None:
        """Builds the empty state as a child of ``canvas`` and keeps it filling that canvas.

        Args:
            canvas: Widget the empty state covers.
            on_open: Opens the image file dialog.
            on_open_folder: Opens the folder dialog.
            on_drop: Opens a path dropped onto the empty state.
        """
        super().__init__(canvas)
        self._on_drop = on_drop
        self.setObjectName("empty_state")
        self.setAcceptDrops(True)
        # * A plain QWidget ignores stylesheet backgrounds unless this is set, which let the canvas hint show through.
        self.setAttribute(Qt.WidgetAttribute.WA_StyledBackground, True)
        canvas.installEventFilter(self)

        mark = QLabel()
        mark.setPixmap(window_icon().pixmap(72, 72))
        mark.setAlignment(Qt.AlignmentFlag.AlignCenter)

        title = QLabel("Pixel Viewer")
        title.setObjectName("empty_title")
        title.setAlignment(Qt.AlignmentFlag.AlignCenter)

        subtitle = QLabel("Drop an image, a GIF, a video, or a folder to inspect every pixel.")
        subtitle.setObjectName("empty_subtitle")
        subtitle.setAlignment(Qt.AlignmentFlag.AlignCenter)
        subtitle.setWordWrap(True)

        self.error_label = QLabel()
        self.error_label.setObjectName("empty_error")
        self.error_label.setAlignment(Qt.AlignmentFlag.AlignCenter)
        self.error_label.setWordWrap(True)
        self.error_label.hide()

        open_button = QPushButton("Open image")
        open_button.setObjectName("open_image_button")
        open_button.setDefault(True)
        open_button.clicked.connect(on_open)
        folder_button = QPushButton("Open folder")
        folder_button.setObjectName("open_folder_button")
        folder_button.clicked.connect(on_open_folder)

        buttons = QWidget()
        button_row = QHBoxLayout(buttons)
        button_row.setContentsMargins(0, 0, 0, 0)
        button_row.setSpacing(10)
        button_row.addStretch(1)
        button_row.addWidget(open_button)
        button_row.addWidget(folder_button)
        button_row.addStretch(1)

        column = QVBoxLayout()
        column.setSpacing(10)
        column.setContentsMargins(32, 32, 32, 32)
        column.addStretch(1)
        column.addWidget(mark)
        column.addWidget(title)
        column.addWidget(subtitle)
        column.addWidget(self.error_label)
        column.addSpacing(8)
        column.addWidget(buttons)
        column.addStretch(1)

        title_font = QFont(title.font())
        title_font.setPointSize(22)
        title_font.setWeight(QFont.Weight.DemiBold)
        title.setFont(title_font)

        layout = QVBoxLayout(self)
        layout.setContentsMargins(0, 0, 0, 0)
        layout.addLayout(column)
        self._fill()

    def show_message(self, message: str | None) -> None:
        """Shows an open error on the launch screen, or clears it when ``message`` is None."""
        if message:
            self.error_label.setText(message)
            self.error_label.show()
            return
        self.error_label.clear()
        self.error_label.hide()

    def eventFilter(self, watched: QObject, event: QEvent) -> bool:
        """Resizes with the canvas. Other events are left to the canvas."""
        if watched is self.parent() and event.type() == QEvent.Type.Resize:
            self._fill()
        return super().eventFilter(watched, event)

    def dragEnterEvent(self, event: QDragEnterEvent) -> None:
        """Accepts dragged local files and folders."""
        if _dropped_paths(event):
            event.acceptProposedAction()

    def dropEvent(self, event: QDropEvent) -> None:
        """Opens the first dropped file or folder."""
        paths = _dropped_paths(event)
        if paths:
            event.acceptProposedAction()
            self._on_drop(paths[0])

    def _fill(self) -> None:
        """Covers the whole canvas."""
        parent = self.parentWidget()
        if parent is not None:
            self.setGeometry(parent.rect())
            self.raise_()


# ================================ Main Window ================================ #
class MainWindow(QMainWindow):
    """Viewer window: the pixel canvas plus native menus, a toolbar and a status bar."""

    def __init__(self, gray: bool = False) -> None:
        """Builds the window.

        Args:
            gray: Start in the grayscale view.
        """
        super().__init__()
        app = QApplication.instance()
        if isinstance(app, QApplication):
            apply_theme(app)
        self.setWindowIcon(window_icon())
        self._folder: ImageFolder | None = None
        self._export_thread: QThread | None = None
        self._export_worker: _AnimationExporter | None = None
        self._export_progress: QProgressDialog | None = None
        self._export_cancel: threading.Event | None = None
        self._exporting = False
        self._closing_progress = False
        self.canvas = PixelCanvas(self)
        self.canvas.set_gray(gray)
        self.empty_state = EmptyState(self.canvas, self.open_file_dialog, self.open_folder_dialog, self.open_path)
        self.dial = FrameDial()
        self.dial.hide()
        self.dial.index_selected.connect(self._scrub_to)
        self.clip_bar = ClipBar()
        self.clip_bar.pause_toggled.connect(self._on_space)
        self.clip_bar.seeked.connect(self._seek_clip)
        stage = QWidget()
        stage_layout = QVBoxLayout(stage)
        stage_layout.setContentsMargins(0, 0, 0, 0)
        stage_layout.setSpacing(0)
        row = QHBoxLayout()
        row.setContentsMargins(0, 0, 0, 0)
        row.setSpacing(0)
        row.addWidget(self.canvas, 1)
        row.addWidget(self.dial)
        stage_layout.addLayout(row, 1)
        stage_layout.addWidget(self.clip_bar)
        self.setCentralWidget(stage)
        self.setAcceptDrops(True)
        self.setUnifiedTitleAndToolBarOnMac(True)
        self.setWindowTitle(APP_NAME)

        # ------------------------------- Actions ------------------------------ #
        style = self.style()
        self.open_action = self._action("&Open…", [QKeySequence.StandardKey.Open], self.open_file_dialog)
        self.open_action.setIcon(style.standardIcon(QStyle.StandardPixmap.SP_DialogOpenButton))
        self.open_folder_action = self._action("Open &Folder…", ["Ctrl+Shift+O"], self.open_folder_dialog)
        self.export_action = self._action("Export &Animation…", ["Ctrl+E"], self.export_animation)
        self.export_action.setIcon(style.standardIcon(QStyle.StandardPixmap.SP_DialogSaveButton))
        self.export_action.setEnabled(False)
        self.quit_action = self._action("&Quit", [QKeySequence.StandardKey.Quit, "Q"], self.close)

        self.original_action = self._action("&Original", [], lambda: self.canvas.set_gray(False), checkable=True)
        self.gray_action = self._action("&Grayscale", [], lambda: self.canvas.set_gray(True), checkable=True)
        mode_group = QActionGroup(self)
        mode_group.addAction(self.original_action)
        mode_group.addAction(self.gray_action)
        (self.gray_action if gray else self.original_action).setChecked(True)
        self.toggle_gray_action = self._action("&Toggle Grayscale", ["G"], self._toggle_gray)
        self.zoom_in_action = self._action(
            "Zoom &In", ["+", "=", QKeySequence.StandardKey.ZoomIn], lambda: self._zoom(1)
        )
        self.zoom_out_action = self._action(
            "Zoom O&ut", ["-", QKeySequence.StandardKey.ZoomOut], lambda: self._zoom(-1)
        )
        self.fit_action = self._action("&Fit to Window", ["R", "Ctrl+0"], self.canvas.reset_view)
        self.find_action = self._action("Find O&bject", ["C"], self.canvas.find_object)

        self.previous_action = self._action("&Previous Image", ["Left"], lambda: self._go_by(-1))
        self.previous_action.setIcon(style.standardIcon(QStyle.StandardPixmap.SP_ArrowBack))
        self.next_action = self._action("&Next Image", ["Right"], lambda: self._go_by(1))
        self.next_action.setIcon(style.standardIcon(QStyle.StandardPixmap.SP_ArrowForward))
        self.play_action = self._action("&Play", [], self._toggle_play, checkable=True)
        self.play_action.setEnabled(False)
        self.play_timer = QTimer(self)
        self.play_timer.timeout.connect(self._play_next)
        self._clip: MotionClip | None = None
        self._clip_seek_target: int | None = None
        self._clip_timer = QTimer(self)
        self._clip_timer.timeout.connect(self._advance_clip)
        self._clip_ready_timer = QTimer(self)
        self._clip_ready_timer.setInterval(20)
        self._clip_ready_timer.timeout.connect(self._on_clip_ready)
        self.space_action = self._action("Pause or Play", ["Space"], self._on_space)
        self.first_action = self._action("&First Image", ["Home"], lambda: self._go_to(0))
        self.last_action = self._action("&Last Image", ["End"], lambda: self._go_to(sys.maxsize))
        self.shortcuts_action = self._action("&Keyboard Shortcuts", ["H", "?"], self.show_shortcuts)

        # -------------------------------- Menus ------------------------------- #
        menu_bar = self.menuBar()
        file_menu = menu_bar.addMenu("&File")
        file_menu.addActions([self.open_action, self.open_folder_action])
        file_menu.addSeparator()
        file_menu.addAction(self.export_action)
        file_menu.addSeparator()
        file_menu.addAction(self.quit_action)
        view_menu = menu_bar.addMenu("&View")
        view_menu.addActions([self.original_action, self.gray_action, self.toggle_gray_action])
        view_menu.addSeparator()
        view_menu.addActions([self.zoom_in_action, self.zoom_out_action, self.fit_action, self.find_action])
        go_menu = menu_bar.addMenu("&Go")
        go_menu.addActions([self.previous_action, self.next_action, self.play_action])
        go_menu.addSeparator()
        go_menu.addActions([self.first_action, self.last_action])
        help_menu = menu_bar.addMenu("&Help")
        help_menu.addAction(self.shortcuts_action)

        self.previous_action.setIconText("Previous")
        self.next_action.setIconText("Next")
        self.play_action.setIconText("Play")
        self.gray_action.setIconText("Gray")
        self.zoom_in_action.setIconText("+")
        self.zoom_out_action.setIconText("−")
        self.fit_action.setIconText("Fit")
        self.find_action.setIconText("Find")
        self.export_action.setIconText("Export")

        toolbar = self.addToolBar("Main")
        toolbar.setObjectName("main_toolbar")
        toolbar.setMovable(False)
        toolbar.setToolButtonStyle(Qt.ToolButtonStyle.ToolButtonTextBesideIcon)
        toolbar.addAction(self.open_action)
        toolbar.addSeparator()
        toolbar.addActions([self.previous_action, self.next_action, self.play_action])
        toolbar.addWidget(self._playback_controls())
        toolbar.addSeparator()
        toolbar.addActions([self.original_action, self.gray_action])
        toolbar.addSeparator()
        toolbar.addActions([self.zoom_out_action, self.zoom_in_action, self.fit_action, self.find_action])
        toolbar.addSeparator()
        toolbar.addAction(self.export_action)

        # ------------------------------ Status bar ---------------------------- #
        self.file_label = QLabel()
        self.position_label = QLabel()
        self.mode_label = QLabel()
        self.zoom_label = QLabel()
        self.cursor_label = QLabel()
        fixed_font = QFontDatabase.systemFont(QFontDatabase.SystemFont.FixedFont)
        for label in (self.position_label, self.zoom_label, self.cursor_label):
            label.setFont(fixed_font)
        self.cursor_label.setMinimumWidth(self.cursor_label.fontMetrics().horizontalAdvance("x 00000  y 00000") + 8)
        status_bar = self.statusBar()
        status_bar.addWidget(self.file_label, 1)
        for label in (self.position_label, self.mode_label, self.zoom_label, self.cursor_label):
            status_bar.addPermanentWidget(label)

        self.canvas.cursor_moved.connect(self._show_cursor)
        self.canvas.view_changed.connect(self._update_status)
        self._show_cursor(None)
        self._update_status()
        if not self._restore_geometry():
            self.resize(*WINDOW_SIZE)
        self.canvas.setFocus()

    def _action(
        self,
        text: str,
        shortcuts: Sequence[str | QKeySequence.StandardKey],
        slot: Callable[[], object],
        checkable: bool = False,
    ) -> QAction:
        """Creates a window-wide action with one or more shortcuts."""
        action = QAction(text, self)
        action.setShortcuts([QKeySequence(shortcut) for shortcut in shortcuts])
        action.setCheckable(checkable)
        action.triggered.connect(slot)
        self.addAction(action)
        return action

    # -------------------------------- Opening -------------------------------- #
    def open_path(self, path: Path) -> bool:
        """Opens an image, or the first image of a folder, and makes its folder browsable.

        Args:
            path: Image file or folder.

        Returns:
            True if the path was opened; False after explaining the error on the window.
        """
        try:
            folder = ImageFolder(path)
        except (FileNotFoundError, ValueError, PermissionError) as error:
            # ! A modal QMessageBox here uses a nested event loop. Launched from a terminal, macOS then delivers
            # ! clicks to neither the dialog nor the window, so the error stays on the launch screen instead.
            self._report_open_error(str(error))
            return False
        if self._folder is not None:
            self._folder.close()
        self._folder = folder
        self._show_current(keep_view=False)
        return True

    def open_file_dialog(self) -> None:
        """Asks for an image file to open."""
        dialog = QFileDialog(self, "Open", str(self._dialog_folder()), IMAGE_FILTER)
        dialog.setFileMode(QFileDialog.FileMode.ExistingFile)
        self._show_open_dialog(dialog)

    def open_folder_dialog(self) -> None:
        """Asks for a folder and opens its first image."""
        dialog = QFileDialog(self, "Open Folder", str(self._dialog_folder()))
        dialog.setFileMode(QFileDialog.FileMode.Directory)
        dialog.setOption(QFileDialog.Option.ShowDirsOnly)
        self._show_open_dialog(dialog)

    def _show_open_dialog(self, dialog: QFileDialog) -> None:
        """Shows an open dialog as a window-modal sheet and opens whatever the user picks."""
        # ! Use open(), not exec() or the static getOpenFileName(): those spin a nested event loop, and on macOS the
        # ! native panel can then stop responding to clicks.
        dialog.setAttribute(Qt.WidgetAttribute.WA_DeleteOnClose)
        dialog.fileSelected.connect(lambda name: self.open_path(Path(name)))
        dialog.open()

    def _dialog_folder(self) -> Path:
        """Folder the open dialogs start in: the current image's folder, or the home folder."""
        return self._folder.folder if self._folder is not None else Path.home()

    # ------------------------------- Browsing -------------------------------- #
    def _go_to(self, index: int) -> None:
        """Shows the image at ``index`` (clamped), keeping the current zoom and position."""
        if self._folder is not None and self._folder.move_to(index):
            self._show_current(keep_view=True)

    def _scrub_to(self, index: int) -> None:
        """Moves to ``index`` from the dial and stops playback so the wheel is not fighting the timer."""
        if self.play_action.isChecked():
            self.play_action.setChecked(False)
        self._go_to(index)

    def _go_by(self, offset: int) -> None:
        """Steps ``offset`` images forward or back."""
        if self._folder is not None:
            self._go_to(self._folder.index + offset)

    def _report_open_error(self, message: str) -> None:
        """Explains a failed open without a modal dialog, so the Open buttons stay clickable."""
        self.empty_state.show_message(message)
        self.statusBar().showMessage(message, STATUS_MESSAGE_MS)

    def _playback_controls(self) -> QWidget:
        """Slider for how long each image stays on screen while Play is running."""
        self.speed_slider = QSlider(Qt.Orientation.Horizontal)
        self.speed_slider.setObjectName("playback_speed")
        self.speed_slider.setRange(PLAYBACK_MIN_MS, PLAYBACK_MAX_MS)
        self.speed_slider.setSingleStep(PLAYBACK_STEP_MS)
        self.speed_slider.setPageStep(PLAYBACK_STEP_MS * 5)
        self.speed_slider.setValue(PLAYBACK_DEFAULT_MS)
        self.speed_slider.setFixedWidth(140)
        self.speed_slider.setAccessibleName("Time between images")
        self.speed_slider.valueChanged.connect(self._set_playback_interval)
        self.speed_label = QLabel(self._format_interval(PLAYBACK_DEFAULT_MS))
        self.speed_label.setObjectName("playback_interval")
        self.speed_label.setMinimumWidth(self.speed_label.fontMetrics().horizontalAdvance("5.0 s") + 8)

        controls = QWidget()
        layout = QHBoxLayout(controls)
        layout.setContentsMargins(4, 0, 4, 0)
        layout.setSpacing(8)
        layout.addWidget(self.speed_slider)
        layout.addWidget(self.speed_label)
        return controls

    def _toggle_play(self, playing: bool) -> None:
        """Starts or stops automatic advance. ``playing`` is the action's new checked state."""
        self.play_action.setIconText("Pause" if playing else "Play")
        self.play_action.setText("&Pause" if playing else "&Play")
        if playing:
            self.play_timer.start(self.speed_slider.value())
        else:
            self.play_timer.stop()

    def _on_space(self, _checked: bool = False) -> None:
        """Pauses the open GIF or video. With a still image showing, Space runs the folder slideshow."""
        if self._clip is not None and self._clip.frame_count > 1:
            playing = not self._clip_timer.isActive()
            if not playing and self.play_action.isChecked():
                self.play_action.trigger()
            self._set_clip_playing(playing)
            return
        self.play_action.trigger()

    def _set_clip_playing(self, playing: bool) -> None:
        """Starts or stops the open clip. A paused frame stays on the canvas, so zoom and pixel values still work."""
        if self._clip is None or self._clip.frame_count < 2:
            playing = False
        if playing:
            self._clip_timer.start(self._clip.delay_ms if self._clip is not None else 0)
        else:
            self._clip_timer.stop()
        self.clip_bar.set_playing(playing)

    def _advance_clip(self) -> None:
        """Shows the next frame of the open clip, keeping the current zoom and position.

        If that frame is still being decoded, tries again shortly instead of freezing the window.
        """
        if self._clip is None:
            self._clip_timer.stop()
            return
        if self._clip.error is not None:
            self._set_clip_playing(False)
            self.statusBar().showMessage(self._clip.error, STATUS_MESSAGE_MS)
            return
        next_index = (self._clip.index + 1) % self._clip.frame_count
        if not self._clip.has_frame(next_index):
            self._clip_timer.start(20)
            return
        try:
            frame = self._clip.step()
        except ValueError as error:
            self._set_clip_playing(False)
            self.statusBar().showMessage(str(error), STATUS_MESSAGE_MS)
            return
        self.canvas.set_image(frame, keep_view=True)
        self.clip_bar.show_position(self._clip)
        self._clip_timer.setInterval(self._clip.delay_ms)

    def _seek_clip(self, index: int) -> None:
        """Pauses on the frame the timeline landed on. A frame still decoding shows up as soon as it is ready."""
        if self._clip is None:
            return
        index = min(max(index, 0), self._clip.frame_count - 1)
        if index == self._clip.index:
            self._clip_seek_target = None
            return
        self._set_clip_playing(False)
        if not self._clip.has_frame(index):
            self._clip_seek_target = index
            self._clip_ready_timer.start()
            return
        self._clip_seek_target = None
        self._show_sought_frame(index)

    def _on_clip_ready(self) -> None:
        """Shows a scrubbed frame once it has been composited, and refreshes the length when decoding finishes."""
        clip = self._clip
        if clip is None:
            self._clip_ready_timer.stop()
            return
        if clip.error is not None and (self._clip_seek_target is None or not clip.has_frame(self._clip_seek_target)):
            self._clip_ready_timer.stop()
            self._set_clip_playing(False)
            self.statusBar().showMessage(clip.error, STATUS_MESSAGE_MS)
            return
        target = self._clip_seek_target
        if target is not None and clip.has_frame(target):
            self._clip_seek_target = None
            self._show_sought_frame(target)
        if clip.fully_decoded and self._clip_seek_target is None:
            self.clip_bar.show_position(clip)
            self._clip_ready_timer.stop()

    def _show_sought_frame(self, index: int) -> None:
        """Shows frame ``index`` of the open clip, which is already composited."""
        if self._clip is None:
            return
        try:
            frame = self._clip.seek(index)
        except ValueError as error:
            self.statusBar().showMessage(str(error), STATUS_MESSAGE_MS)
            return
        self.canvas.set_image(frame, keep_view=True)
        self.clip_bar.show_position(self._clip)

    def _close_clip(self) -> None:
        """Stops playback and releases the decoder."""
        self._clip_timer.stop()
        self._clip_ready_timer.stop()
        self._clip_seek_target = None
        self.clip_bar.set_playing(False)
        self.clip_bar.set_clip(None)
        if self._clip is not None:
            self._clip.close()
            self._clip = None

    def _play_next(self) -> None:
        """Shows the next image, returning to the first after the last."""
        if self._folder is None or len(self._folder.paths) < 2:
            self.play_action.setChecked(False)
            return
        next_index = self._folder.index + 1
        if next_index >= len(self._folder.paths):
            next_index = 0
        self._go_to(next_index)

    def _set_playback_interval(self, milliseconds: int) -> None:
        """Snaps the slider to a tenth of a second and applies it to a running slideshow."""
        snapped = max(PLAYBACK_MIN_MS, min(PLAYBACK_MAX_MS, round(milliseconds / PLAYBACK_STEP_MS) * PLAYBACK_STEP_MS))
        if snapped != milliseconds:
            self.speed_slider.setValue(snapped)
            return
        self.speed_label.setText(self._format_interval(snapped))
        self.play_timer.setInterval(snapped)

    @staticmethod
    def _format_interval(milliseconds: int) -> str:
        """Formats a delay as seconds with one decimal, for example ``1.0 s``."""
        return f"{milliseconds / 1000:.1f} s"

    def _show_current(self, keep_view: bool) -> None:
        """Loads the folder's selected image into the canvas and refreshes the window chrome."""
        assert self._folder is not None
        path = self._folder.current_path
        self._close_clip()
        try:
            if is_motion(path):
                clip = MotionClip(path)
                self.canvas.set_image(clip.frame(), keep_view=keep_view)
                self._clip = clip
                self.clip_bar.set_clip(clip)
                self._set_clip_playing(clip.frame_count > 1)
                if not clip.fully_decoded:
                    self._clip_ready_timer.start()
            else:
                self.canvas.set_image(self._folder.current(), keep_view=keep_view)
        except ValueError as error:
            self.statusBar().showMessage(str(error), STATUS_MESSAGE_MS)
        else:
            self.empty_state.show_message(None)
        # * Qt adds the app name itself (and on macOS a proxy icon for the file), so the title is just the file.
        self.setWindowFilePath(str(path))
        self.setWindowTitle(path.name)

        index, count = self._folder.index, len(self._folder.paths)
        for action, enabled in (
            (self.previous_action, index > 0),
            (self.first_action, index > 0),
            (self.next_action, index < count - 1),
            (self.last_action, index < count - 1),
        ):
            action.setEnabled(enabled)
        self.export_action.setEnabled(bool(self._folder.still_paths()) and not self._exporting)
        self.play_action.setEnabled(count >= 2)
        if count < 2 and self.play_action.isChecked():
            self.play_action.setChecked(False)
        self.dial.set_position(index, count, path.name)
        self.dial.setVisible(count > 0)
        self.empty_state.setVisible(self.canvas.image is None)
        self._update_status()

    # ------------------------------- View ------------------------------------ #
    def _toggle_gray(self) -> None:
        """Switches between the original and grayscale views."""
        (self.original_action if self.gray_action.isChecked() else self.gray_action).trigger()

    def _zoom(self, steps: int) -> None:
        """Zooms around the pointer when it is over the canvas, otherwise around the centre."""
        anchor: QPointF | None = None
        if self.canvas.underMouse():
            anchor = self.canvas.mapFromGlobal(QCursor.pos()).toPointF()
        self.canvas.zoom_by_steps(steps, anchor)

    def show_shortcuts(self) -> None:
        """Shows a table of keyboard and mouse controls."""
        open_keys = self.open_action.shortcut().toString(QKeySequence.SequenceFormat.NativeText)
        export_keys = self.export_action.shortcut().toString(QKeySequence.SequenceFormat.NativeText)
        quit_keys = self.quit_action.shortcuts()[0].toString(QKeySequence.SequenceFormat.NativeText)
        rows = [
            ("← →", "Previous / next image in the folder"),
            ("Space", "Pause a GIF or video, or play through the folder"),
            ("Home End", "First / last image"),
            ("Drag, W A S D", "Pan"),
            ("Scroll, pinch, + −", "Zoom at the pointer"),
            ("Scroll or drag the wheel", "Move through images, GIFs and videos"),
            ("G", "Toggle original / grayscale"),
            ("C", "Find object"),
            ("R", "Fit to window"),
            ("H, ?", "Show this help"),
            (open_keys, "Open an image"),
            (export_keys, "Export a GIF or video"),
            (f"Q, {quit_keys}", "Quit"),
        ]
        table_rows = "".join(
            f"<tr><td style='padding:2px 16px 2px 0'><b>{keys}</b></td><td>{action}</td></tr>" for keys, action in rows
        )
        dialog = QMessageBox(self)
        dialog.setWindowTitle("Keyboard Shortcuts")
        dialog.setTextFormat(Qt.TextFormat.RichText)
        dialog.setText(f"<table>{table_rows}</table>")
        dialog.exec()

    # ------------------------------ Status bar ------------------------------- #
    def _show_cursor(self, pixel: tuple[int, int] | None) -> None:
        """Shows the image pixel under the pointer."""
        self.cursor_label.setText("x     –  y     –" if pixel is None else f"x {pixel[0]:>5}  y {pixel[1]:>5}")

    def _update_status(self) -> None:
        """Refreshes the file, position, mode and zoom labels."""
        image = self.canvas.image
        if self._folder is None or image is None:
            for label in (self.file_label, self.position_label, self.mode_label, self.zoom_label):
                label.clear()
            return

        count = len(self._folder.paths)
        width, height = image.size
        self.file_label.setText(f"{image.path.name}  ·  {width} × {height}")
        self.position_label.setText(f"{self._folder.index + 1:>{len(str(count))}} / {count}")
        if image.is_label_mask:
            mode = "Label mask"
        else:
            mode = "Grayscale" if self.canvas.is_gray else "Original"
        if self._clip is not None:
            kind = "GIF" if self._clip.path.suffix.lower() == ".gif" else "Video"
            mode = f"{kind} · {mode}"
        self.mode_label.setText(mode)
        zoom = self.canvas.zoom
        self.zoom_label.setText(f"Fit {zoom:.0%}" if self.canvas.is_fit else f"{zoom:g}×")
        for action in (self.original_action, self.gray_action, self.toggle_gray_action):
            action.setEnabled(not image.is_single_channel)

    # -------------------------------- Export --------------------------------- #
    def export_animation(self) -> None:
        """Asks how to turn the open folder into a GIF and/or a video, then writes it."""
        if self._folder is None or self._exporting:
            return
        stills = self._folder.still_paths()
        if not stills:
            return
        dialog = ExportDialog(stills, self._folder.folder, self)
        if dialog.exec() != QDialog.DialogCode.Accepted:
            return
        try:
            settings = dialog.settings()
        except ExportError as error:
            QMessageBox.warning(self, "Cannot Export", str(error))
            return
        existing = [
            path.name for path in (settings.gif_path, settings.video_path) if path is not None and path.exists()
        ]
        if existing:
            names = " and ".join(existing)
            answer = QMessageBox.question(
                self,
                "Replace Existing File",
                f"{names} already exists. Replace it?",
                QMessageBox.StandardButton.Yes | QMessageBox.StandardButton.No,
                QMessageBox.StandardButton.No,
            )
            if answer != QMessageBox.StandardButton.Yes:
                return
        self._start_export(settings)

    def _start_export(self, settings: AnimationExport) -> None:
        """Writes ``settings`` on a background thread and shows progress on this window."""
        self._exporting = True
        self.export_action.setEnabled(False)
        cancel = threading.Event()
        self._export_cancel = cancel
        # * Move the worker onto the thread before connecting it, so run() executes there rather than on the UI thread.
        worker = _AnimationExporter(settings, cancel.is_set)
        thread = QThread()
        worker.moveToThread(thread)
        thread.started.connect(worker.run)
        worker.progressed.connect(self._on_export_progress)
        worker.succeeded.connect(thread.quit)
        worker.failed.connect(thread.quit)
        worker.succeeded.connect(self._show_export_message)
        worker.failed.connect(self._show_export_error)
        thread.finished.connect(self._clear_export_job)
        self._export_worker = worker
        self._export_thread = thread

        progress = QProgressDialog("Preparing…", "Cancel", 0, len(settings.paths), self)
        progress.setWindowTitle("Export Animation")
        progress.setWindowModality(Qt.WindowModality.WindowModal)
        progress.setMinimumDuration(0)
        progress.setAutoClose(False)
        progress.setAutoReset(False)
        progress.setValue(0)
        progress.canceled.connect(self._cancel_export)
        self._export_progress = progress
        progress.show()
        thread.start()

    def _on_export_progress(self, label: str, current: int, total: int) -> None:
        """Advances the progress dialog. Late updates after Cancel are ignored."""
        if self._export_cancel is not None and self._export_cancel.is_set():
            return
        progress = self._export_progress
        if progress is None:
            return
        progress.setMaximum(total)
        progress.setLabelText(label)
        progress.setValue(min(current, total))

    def _cancel_export(self) -> None:
        """Asks the writer to stop after the frame it is on."""
        if self._closing_progress or self._export_cancel is None:
            return
        self._export_cancel.set()
        if self._export_progress is not None:
            self._export_progress.setLabelText("Cancelling…")

    def _show_export_message(self, message: str) -> None:
        """Closes the progress dialog and reports a finished or cancelled export."""
        self._close_progress()
        self.statusBar().showMessage(message, STATUS_MESSAGE_MS)

    def _show_export_error(self, message: str) -> None:
        """Closes the progress dialog and explains why the export stopped."""
        self._close_progress()
        QMessageBox.warning(self, "Cannot Export", message)

    def _close_progress(self) -> None:
        """Closes the progress dialog without treating that close as a cancel request."""
        progress = self._export_progress
        if progress is None:
            return
        self._closing_progress = True
        self._export_progress = None
        progress.close()
        self._closing_progress = False

    def _clear_export_job(self) -> None:
        """Drops the finished export thread and turns the menu item back on."""
        self._exporting = False
        thread = self._export_thread
        worker = self._export_worker
        self._export_thread = None
        self._export_worker = None
        self._export_cancel = None
        self._close_progress()
        if thread is not None:
            thread.deleteLater()
        if worker is not None:
            worker.deleteLater()
        if self._folder is not None:
            self.export_action.setEnabled(True)

    # ----------------------------- Window events ----------------------------- #
    def dragEnterEvent(self, event: QDragEnterEvent) -> None:
        """Accepts dragged local files and folders."""
        if _dropped_paths(event):
            event.acceptProposedAction()

    def dropEvent(self, event: QDropEvent) -> None:
        """Opens the first dropped file or folder."""
        paths = _dropped_paths(event)
        if paths:
            event.acceptProposedAction()
            self.open_path(paths[0])

    def _restore_geometry(self) -> bool:
        """Restores the last window size when a display is attached.

        Returns:
            True if a saved size was applied. Off-screen tests skip this and keep the size the test sets.
        """
        if QGuiApplication.platformName() == "offscreen":
            return False
        geometry = QSettings("com.mustachemo.pixelviewer", "pixel-viewer").value("geometry")
        if geometry is None:
            return False
        self.restoreGeometry(geometry)
        return True

    def _save_geometry(self) -> None:
        """Remembers the window size for the next launch."""
        if QGuiApplication.platformName() == "offscreen":
            return
        QSettings("com.mustachemo.pixelviewer", "pixel-viewer").setValue("geometry", self.saveGeometry())

    def closeEvent(self, event: QCloseEvent) -> None:
        """Stops background decoding and any export before the window closes."""
        self.play_timer.stop()
        self._close_clip()
        self._save_geometry()
        if self._export_cancel is not None:
            self._export_cancel.set()
        thread = self._export_thread
        if thread is not None and thread.isRunning():
            thread.quit()
            thread.wait(5000)
        if self._folder is not None:
            self._folder.close()
        super().closeEvent(event)


# ================================ Entry Point ================================ #
def _package_version() -> str:
    """Installed package version. A frozen app without metadata still launches."""
    try:
        return version("pixel-viewer")
    except PackageNotFoundError:
        return "0.0.0"


class PixelViewerApplication(QApplication):
    """QApplication that accepts images opened from Finder or the file manager while the app is running."""

    def __init__(self, argv: list[str]) -> None:
        super().__init__(argv)
        self.open_file: Callable[[Path], object] | None = None

    def event(self, event: QEvent) -> bool:
        """Opens a file delivered by the operating system, such as Open With on macOS."""
        if event.type() == QEvent.Type.FileOpen and isinstance(event, QFileOpenEvent) and self.open_file is not None:
            self.open_file(Path(event.file()))
            return True
        return super().event(event)


def main(argv: Sequence[str] | None = None) -> int:
    """Runs the viewer.

    Args:
        argv: Command-line arguments, excluding the program name; defaults to ``sys.argv[1:]``.

    Returns:
        The Qt event loop's exit code.
    """
    parser = argparse.ArgumentParser(
        prog="pixel-viewer",
        description="Zoomable image viewer that shows per-pixel values. Use ← → to step through the folder.",
    )
    parser.add_argument("path", nargs="*", type=Path, help="image file or folder to open")
    parser.add_argument("--gray", action="store_true", help="start in the grayscale view")
    parser.add_argument(
        "--install",
        action="store_true",
        help="install a clickable app in ~/Applications (macOS) or the application menu (Linux)",
    )
    parser.add_argument("--version", action="version", version=f"%(prog)s {_package_version()}")
    args = parser.parse_args(argv)
    if args.install:
        try:
            installed = install_launcher()
        except OSError as error:
            print(f"Could not install {APP_NAME}: {error}", file=sys.stderr)
            return 1
        print(f"Installed {installed}")
        return 0

    paths = [path.expanduser() for path in args.path]
    missing = [path for path in paths if not path.exists()]
    if missing:
        parser.error(f"no such file or folder: {missing[0]}")

    app = PixelViewerApplication(sys.argv[:1])
    app.setApplicationName("pixel-viewer")
    app.setApplicationDisplayName(APP_NAME)
    app.setOrganizationDomain("com.mustachemo")
    app.setDesktopFileName("pixel-viewer")
    apply_theme(app)
    window = MainWindow(gray=args.gray)
    app.open_file = window.open_path
    window.show()
    window.raise_()
    window.activateWindow()
    if paths:
        window.open_path(paths[0])
    return app.exec()


if __name__ == "__main__":
    sys.exit(main())
