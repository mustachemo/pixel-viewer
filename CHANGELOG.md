# Changelog

All notable changes to this project are documented here. The format follows
[Keep a Changelog](https://keepachangelog.com/en/1.1.0/), and versions follow
[Semantic Versioning](https://semver.org/).

## [Unreleased]

### Added

- Export the open folder, or a frame range, as a looping GIF and/or an MP4 at a chosen frame rate
  (File → Export Animation, Ctrl+E).
- `pixel-viewer --install` adds a clickable macOS app in `~/Applications` or a Linux application-menu
  entry. The macOS app accepts images dropped on its icon or opened with Open With.
- A standalone `Pixel Viewer.app` can be dragged into Applications. Tagged releases attach
  `PixelViewer-macOS.zip`. Build it locally with `python packaging/build_macos_app.py`.
- Play through the open folder with Space, or the Play button. A slider sets the delay between images
  from 0.1 s to 5 s. Playback loops back to the first image.

### Changed

- Dark window chrome, a launch screen with Open buttons, and an application icon. Launching with no
  path shows that screen instead of a file dialog.
- Opening a folder with no supported images explains the problem on the launch screen. The window stays
  clickable, including when Pixel Viewer is started from a terminal.

## [0.1.0] - 2026-09-24

### Added

- Zoomable canvas with a pixel grid from 8× and per-pixel values from 24× (grayscale) or 32× (R, G, B).
- Color-coded R, G and B values, and black or white grayscale values chosen for contrast with each cell.
- Original / grayscale toggle, fit to window, and "find object" zoom to the non-background pixels.
- Label-mask detection: masks with replicated channels collapse to one channel, and each part ID gets a fixed color.
- Folder browsing with ← / →, Home and End, keeping zoom and position, with neighbouring images decoded in the
  background.
- Zoom with the scroll wheel, trackpad pinch or + / −, always around the pointer; pan by dragging or with W A S D.
- Native menus, toolbar, status bar (file, size, position in folder, mode, zoom, pixel under the pointer),
  shortcuts dialog, open dialogs and drag-and-drop.
- `pixel-viewer` command with `--gray` and `--version`.

[Unreleased]: https://github.com/mustachemo/pixel-viewer/compare/v0.1.0...HEAD
[0.1.0]: https://github.com/mustachemo/pixel-viewer/releases/tag/v0.1.0
