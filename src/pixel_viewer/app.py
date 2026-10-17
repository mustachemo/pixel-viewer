"""Main window and command-line entry point."""

# ================================== Imports ================================== #
# Standard Library
import argparse
import sys
import threading
import traceback
from collections.abc import Callable, Sequence
from importlib.metadata import version
from pathlib import Path

# Third-party
from PySide6.QtCore import QObject, QPointF, Qt, QThread, QTimer, Signal
from PySide6.QtGui import (
    QAction,
    QActionGroup,
    QCloseEvent,
    QCursor,
    QDragEnterEvent,
    QDropEvent,
    QFontDatabase,
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
    QSpinBox,
    QStyle,
    QVBoxLayout,
    QWidget,
)

# Local
from pixel_viewer.canvas import PixelCanvas
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
from pixel_viewer.images import IMAGE_SUFFIXES, ImageFolder

# ================================== Constants ================================ #
APP_NAME = "Pixel Viewer"
WINDOW_SIZE = (1400, 1000)
STATUS_MESSAGE_MS = 6000
IMAGE_FILTER = f"Images ({' '.join(f'*{suffix}' for suffix in sorted(IMAGE_SUFFIXES))})"
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

        layout = QVBoxLayout(self)
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


# ================================ Main Window ================================ #
class MainWindow(QMainWindow):
    """Viewer window: the pixel canvas plus native menus, a toolbar and a status bar."""

    def __init__(self, gray: bool = False) -> None:
        """Builds the window.

        Args:
            gray: Start in the grayscale view.
        """
        super().__init__()
        self._folder: ImageFolder | None = None
        self._export_thread: QThread | None = None
        self._export_worker: _AnimationExporter | None = None
        self._export_progress: QProgressDialog | None = None
        self._export_cancel: threading.Event | None = None
        self._exporting = False
        self._closing_progress = False
        self.canvas = PixelCanvas(self)
        self.canvas.set_gray(gray)
        self.setCentralWidget(self.canvas)
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
        go_menu.addActions([self.previous_action, self.next_action])
        go_menu.addSeparator()
        go_menu.addActions([self.first_action, self.last_action])
        help_menu = menu_bar.addMenu("&Help")
        help_menu.addAction(self.shortcuts_action)

        toolbar = self.addToolBar("Main")
        toolbar.setObjectName("main_toolbar")
        toolbar.setMovable(False)
        toolbar.setToolButtonStyle(Qt.ToolButtonStyle.ToolButtonTextBesideIcon)
        toolbar.addAction(self.open_action)
        toolbar.addSeparator()
        toolbar.addActions([self.previous_action, self.next_action])
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
            True if the path was opened; False after warning the user.
        """
        try:
            folder = ImageFolder(path)
        except (FileNotFoundError, ValueError, PermissionError) as error:
            QMessageBox.warning(self, f"Cannot Open {path.name or path}", str(error))
            return False
        if self._folder is not None:
            self._folder.close()
        self._folder = folder
        self._show_current(keep_view=False)
        return True

    def open_file_dialog(self) -> None:
        """Asks for an image file to open."""
        dialog = QFileDialog(self, "Open Image", str(self._dialog_folder()), IMAGE_FILTER)
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

    def _go_by(self, offset: int) -> None:
        """Steps ``offset`` images forward or back."""
        if self._folder is not None:
            self._go_to(self._folder.index + offset)

    def _show_current(self, keep_view: bool) -> None:
        """Loads the folder's selected image into the canvas and refreshes the window chrome."""
        assert self._folder is not None
        path = self._folder.current_path
        try:
            self.canvas.set_image(self._folder.current(), keep_view=keep_view)
        except ValueError as error:
            self.statusBar().showMessage(str(error), STATUS_MESSAGE_MS)
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
        self.export_action.setEnabled(not self._exporting)
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
            ("Home End", "First / last image"),
            ("Drag, W A S D", "Pan"),
            ("Scroll, pinch, + −", "Zoom at the pointer"),
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
        dialog = ExportDialog(self._folder.paths, self._folder.folder, self)
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
        if any(url.isLocalFile() for url in event.mimeData().urls()):
            event.acceptProposedAction()

    def dropEvent(self, event: QDropEvent) -> None:
        """Opens the first dropped file or folder."""
        local_paths = [Path(url.toLocalFile()) for url in event.mimeData().urls() if url.isLocalFile()]
        if local_paths:
            event.acceptProposedAction()
            self.open_path(local_paths[0])

    def closeEvent(self, event: QCloseEvent) -> None:
        """Stops background decoding and any export before the window closes."""
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
    parser.add_argument("path", nargs="?", type=Path, help="image file or folder to open (asks when omitted)")
    parser.add_argument("--gray", action="store_true", help="start in the grayscale view")
    parser.add_argument("--version", action="version", version=f"%(prog)s {version('pixel-viewer')}")
    args = parser.parse_args(argv)
    if args.path is not None and not args.path.expanduser().exists():
        parser.error(f"no such file or folder: {args.path}")

    app = QApplication(sys.argv[:1])
    app.setApplicationName("pixel-viewer")
    app.setApplicationDisplayName(APP_NAME)
    window = MainWindow(gray=args.gray)
    window.resize(*WINDOW_SIZE)
    window.show()
    window.raise_()
    window.activateWindow()
    if args.path is not None:
        window.open_path(args.path)
    else:
        # ! macOS ignores clicks on a file panel shown before the app is frontmost, which is common when it is
        # ! launched from a terminal, so wait for the app to become active before asking for a file.
        dialog_requested = False

        def open_dialog_when_active(state: Qt.ApplicationState) -> None:
            nonlocal dialog_requested
            if state == Qt.ApplicationState.ApplicationActive and not dialog_requested:
                dialog_requested = True
                window.open_file_dialog()

        app.applicationStateChanged.connect(open_dialog_when_active)
        QTimer.singleShot(0, lambda: open_dialog_when_active(app.applicationState()))
    return app.exec()


if __name__ == "__main__":
    sys.exit(main())
