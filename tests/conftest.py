"""Shared test setup."""

# Standard Library
import os

# * Render Qt widgets off-screen so tests run without a display (CI, SSH sessions, sandboxes).
os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")
