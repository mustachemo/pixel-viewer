"""The timeline shown while a GIF or video is the current file."""

# ================================== Imports ================================== #
# Third-party
from PySide6.QtCore import Qt, Signal
from PySide6.QtWidgets import QHBoxLayout, QLabel, QPushButton, QSlider, QWidget

# Local
from pixel_viewer.media import MotionClip, format_clock


# ================================= Timeline ================================== #
class ClipBar(QWidget):
    """Play, pause and scrub controls for the clip that is open.

    Hidden for still images. Shows the elapsed time, the length, and which frame is on screen.

    Signals:
        pause_toggled: The user clicked Play or Pause.
        seeked: The user moved the timeline to a frame index.
    """

    pause_toggled = Signal()
    seeked = Signal(int)

    def __init__(self, parent: QWidget | None = None) -> None:
        """Builds a hidden bar.

        Args:
            parent: Owning widget.
        """
        super().__init__(parent)
        self.setObjectName("clip_bar")
        self.play_button = QPushButton("Play")
        self.play_button.setObjectName("clip_play")
        self.play_button.setFixedWidth(72)
        self.play_button.clicked.connect(self.pause_toggled.emit)

        self.elapsed_label = QLabel("0:00.0")
        self.elapsed_label.setObjectName("clip_elapsed")
        self.duration_label = QLabel("0:00.0")
        self.duration_label.setObjectName("clip_duration")
        self.frame_label = QLabel()
        self.frame_label.setObjectName("clip_frames")

        self.slider = QSlider(Qt.Orientation.Horizontal)
        self.slider.setObjectName("clip_position")
        self.slider.setAccessibleName("Position in the clip")
        self.slider.valueChanged.connect(self.seeked.emit)

        layout = QHBoxLayout(self)
        layout.setContentsMargins(10, 6, 10, 6)
        layout.setSpacing(10)
        layout.addWidget(self.play_button)
        layout.addWidget(self.elapsed_label)
        layout.addWidget(self.slider, 1)
        layout.addWidget(self.duration_label)
        layout.addWidget(self.frame_label)
        self.hide()

    def set_clip(self, clip: MotionClip | None) -> None:
        """Shows ``clip``'s length and position, or hides the bar when ``clip`` is None."""
        if clip is None:
            self.hide()
            return
        self.slider.blockSignals(True)
        self.slider.setRange(0, max(clip.frame_count - 1, 0))
        self.slider.setValue(clip.index)
        self.slider.setEnabled(clip.frame_count > 1)
        self.slider.blockSignals(False)
        self.play_button.setEnabled(clip.frame_count > 1)
        self.duration_label.setText(format_clock(clip.duration_ms))
        self.show_position(clip)
        self.show()

    def show_position(self, clip: MotionClip) -> None:
        """Updates the playhead without treating it as a user seek."""
        self.slider.blockSignals(True)
        self.slider.setValue(clip.index)
        self.slider.blockSignals(False)
        self.elapsed_label.setText(format_clock(clip.position_ms))
        self.duration_label.setText(format_clock(clip.duration_ms))
        self.frame_label.setText(f"{clip.index + 1} / {clip.frame_count}")

    def set_playing(self, playing: bool) -> None:
        """Labels the button for the state a click will move to."""
        self.play_button.setText("Pause" if playing else "Play")
