"""Dark theme shared by the window, dialogs and menus."""

# ================================== Imports ================================== #
# Third-party
from PySide6.QtCore import Qt
from PySide6.QtGui import QColor, QFont, QIcon, QPalette, QPixmap
from PySide6.QtWidgets import QApplication

# Local
from pixel_viewer.icons import render_icon_png

# ================================== Constants ================================ #
_THEME_PROPERTY = "pixel_viewer_theme"

# * One stylesheet for every widget, so dialogs opened later match the window.
STYLESHEET = """
QMainWindow, QDialog {
    background: #12141a;
    color: #f2f4f8;
}
QWidget#empty_state {
    background: #12141a;
}
QLabel {
    color: #f2f4f8;
    background: transparent;
}
QLabel#empty_title {
    font-size: 28px;
    font-weight: 600;
    color: #f7f8fb;
}
QLabel#empty_subtitle, QLabel#hint {
    color: #9aa3b5;
    font-size: 13px;
}
QLabel#empty_subtitle {
    font-size: 14px;
}
QLabel#empty_error {
    color: #ffb0a4;
    font-size: 14px;
}
QSlider::groove:horizontal {
    height: 4px;
    background: #343b4c;
    border-radius: 2px;
}
QSlider::sub-page:horizontal {
    background: #e6b325;
    border-radius: 2px;
}
QSlider::handle:horizontal {
    width: 14px;
    height: 14px;
    margin: -6px 0;
    background: #f2f4f8;
    border: 2px solid #e6b325;
    border-radius: 7px;
}
QMenuBar {
    background: #12141a;
    color: #f2f4f8;
    spacing: 2px;
    padding: 2px 6px;
}
QMenuBar::item {
    background: transparent;
    padding: 6px 10px;
    border-radius: 6px;
}
QMenuBar::item:selected {
    background: #2a3142;
}
QMenu {
    background: #1c212c;
    color: #f2f4f8;
    border: 1px solid #343b4c;
    border-radius: 10px;
    padding: 6px;
}
QMenu::item {
    padding: 6px 28px 6px 16px;
    border-radius: 6px;
}
QMenu::item:selected {
    background: #2a3142;
}
QMenu::separator {
    height: 1px;
    background: #343b4c;
    margin: 6px 8px;
}
QToolBar#main_toolbar {
    background: #181b24;
    border: none;
    border-bottom: 1px solid #2a3142;
    spacing: 4px;
    padding: 6px 10px;
}
QToolBar::separator {
    background: #343b4c;
    width: 1px;
    margin: 6px 8px;
}
QToolButton {
    background: transparent;
    color: #f2f4f8;
    border: 1px solid transparent;
    border-radius: 8px;
    padding: 6px 10px;
}
QToolButton:hover {
    background: #2a3142;
}
QToolButton:pressed {
    background: #343c52;
}
QToolButton:checked {
    background: #3a321c;
    color: #f6d78a;
    border-color: #6d5b30;
}
QToolButton:disabled {
    color: #5c6578;
}
QStatusBar {
    background: #181b24;
    color: #b7c0d0;
    border-top: 1px solid #2a3142;
}
QStatusBar::item {
    border: none;
}
QStatusBar QLabel {
    color: #c5cedd;
    padding: 0 8px;
}
QPushButton {
    background: #2a3142;
    color: #f2f4f8;
    border: 1px solid #3d465c;
    border-radius: 8px;
    padding: 8px 16px;
    min-height: 18px;
}
QPushButton:hover {
    background: #343c52;
}
QPushButton:pressed {
    background: #3d465c;
}
QPushButton:disabled {
    color: #6a7386;
    background: #222733;
    border-color: #2e3546;
}
QPushButton#primary, QPushButton:default {
    background: #e6b325;
    color: #1a1404;
    border: none;
    font-weight: 600;
}
QPushButton#primary:hover, QPushButton:default:hover {
    background: #f0c44a;
}
QLineEdit, QSpinBox, QComboBox {
    background: #1a1e28;
    color: #f2f4f8;
    border: 1px solid #343b4c;
    border-radius: 8px;
    padding: 6px 8px;
    selection-background-color: #e6b325;
    selection-color: #1a1404;
    min-height: 20px;
}
QLineEdit:focus, QSpinBox:focus, QComboBox:focus {
    border-color: #e6b325;
}
QCheckBox {
    spacing: 8px;
    color: #f2f4f8;
}
QProgressBar {
    background: #1a1e28;
    border: 1px solid #343b4c;
    border-radius: 6px;
    text-align: center;
    color: #f2f4f8;
    min-height: 16px;
}
QProgressBar::chunk {
    background: #e6b325;
    border-radius: 5px;
}
QMessageBox {
    background: #161922;
}
QScrollBar:vertical, QScrollBar:horizontal {
    background: transparent;
    border: none;
    margin: 0;
}
QScrollBar:vertical { width: 10px; }
QScrollBar:horizontal { height: 10px; }
QScrollBar::handle:vertical, QScrollBar::handle:horizontal {
    background: #3d465c;
    border-radius: 4px;
    min-height: 24px;
    min-width: 24px;
}
QScrollBar::add-line, QScrollBar::sub-line {
    width: 0;
    height: 0;
}
"""


# ================================== Applying ================================= #
def apply_theme(app: QApplication) -> None:
    """Applies the dark palette, stylesheet and window icon. Safe to call more than once."""
    if app.property(_THEME_PROPERTY):
        return
    app.setProperty(_THEME_PROPERTY, True)
    app.setStyle("Fusion")
    app.styleHints().setColorScheme(Qt.ColorScheme.Dark)
    font = app.font()
    font.setPointSize(13)
    font.setWeight(QFont.Weight.Normal)
    app.setFont(font)

    palette = app.palette()
    palette.setColor(QPalette.ColorRole.Window, QColor("#12141a"))
    palette.setColor(QPalette.ColorRole.WindowText, QColor("#f2f4f8"))
    palette.setColor(QPalette.ColorRole.Base, QColor("#1a1e28"))
    palette.setColor(QPalette.ColorRole.AlternateBase, QColor("#222733"))
    palette.setColor(QPalette.ColorRole.Text, QColor("#f2f4f8"))
    palette.setColor(QPalette.ColorRole.Button, QColor("#2a3142"))
    palette.setColor(QPalette.ColorRole.ButtonText, QColor("#f2f4f8"))
    palette.setColor(QPalette.ColorRole.Highlight, QColor("#e6b325"))
    palette.setColor(QPalette.ColorRole.HighlightedText, QColor("#1a1404"))
    palette.setColor(QPalette.ColorRole.PlaceholderText, QColor("#8b93a7"))
    palette.setColor(QPalette.ColorRole.ToolTipBase, QColor("#222733"))
    palette.setColor(QPalette.ColorRole.ToolTipText, QColor("#f2f4f8"))
    palette.setColor(QPalette.ColorRole.Link, QColor("#e6b325"))
    app.setPalette(palette)
    app.setStyleSheet(STYLESHEET)
    app.setWindowIcon(window_icon())


def window_icon() -> QIcon:
    """Returns the application icon at the sizes the dock and taskbar request."""
    icon = QIcon()
    for size in (16, 32, 48, 64, 128, 256):
        pixmap = QPixmap()
        pixmap.loadFromData(render_icon_png(size), "PNG")
        icon.addPixmap(pixmap)
    return icon
