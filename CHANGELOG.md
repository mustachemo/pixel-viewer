# Changelog

All notable changes to this project are documented here. The format follows
[Keep a Changelog](https://keepachangelog.com/en/1.1.0/), and versions follow
[Semantic Versioning](https://semver.org/).

## [Unreleased]

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
