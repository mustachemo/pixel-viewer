"""Main window and command-line entry point."""

# ================================== Imports ================================== #
# Standard Library
import argparse
import sys
from collections.abc import Callable, Sequence
from importlib.metadata import version
from pathlib import Path

# Third-party
from PySide6.QtCore import QPointF, Qt, QTimer
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
from PySide6.QtWidgets import QApplication, QFileDialog, QLabel, QMainWindow, QMessageBox, QStyle

# Local
from pixel_viewer.canvas import PixelCanvas
from pixel_viewer.images import IMAGE_SUFFIXES, ImageFolder

# ================================== Constants ================================ #
APP_NAME = "Pixel Viewer"
WINDOW_SIZE = (1400, 1000)
STATUS_MESSAGE_MS = 6000
IMAGE_FILTER = f"Images ({' '.join(f'*{suffix}' for suffix in sorted(IMAGE_SUFFIXES))})"


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
        """Stops background decoding before the window closes."""
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
