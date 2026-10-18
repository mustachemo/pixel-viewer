"""Tests for the macOS app bundle and the Linux desktop entry."""

# Standard Library
import plistlib
import shutil
import stat
import sys
from pathlib import Path

# Third-party
import pytest

# Local
from pixel_viewer.app import main
from pixel_viewer.install_desktop import install_linux, install_macos, launcher_command


def test_launcher_uses_the_script_beside_the_interpreter(monkeypatch: pytest.MonkeyPatch, tmp_path: Path) -> None:
    bin_dir = tmp_path / "bin"
    bin_dir.mkdir()
    python = bin_dir / "python"
    python.write_text("#!/bin/sh\n")
    python.chmod(0o755)
    script = bin_dir / "pixel-viewer"
    script.write_text("#!/bin/sh\n")
    script.chmod(0o755)
    monkeypatch.setattr(sys, "executable", str(python))

    assert launcher_command() == [str(script)]


def test_macos_bundle_is_a_clickable_app(tmp_path: Path) -> None:
    bundle = install_macos(tmp_path, command=["/opt/pixel-viewer"], register=False)

    executable = bundle / "Contents" / "MacOS" / "pixel-viewer"
    script = executable.read_text()
    info = plistlib.loads((bundle / "Contents" / "Info.plist").read_bytes())

    assert bundle.name == "Pixel Viewer.app"
    assert executable.stat().st_mode & stat.S_IXUSR
    assert "/opt/pixel-viewer" in script
    assert script.startswith("#!/bin/sh")
    assert info["CFBundleIdentifier"] == "com.mustachemo.pixelviewer"
    assert info["CFBundleExecutable"] == "pixel-viewer"
    assert info["NSHighResolutionCapable"] is True
    assert "public.png" in info["CFBundleDocumentTypes"][0]["LSItemContentTypes"]
    if shutil.which("iconutil"):
        icon = bundle / "Contents" / "Resources" / "icon.icns"
        assert icon.is_file() and icon.stat().st_size > 0


def test_linux_desktop_entry_launches_without_a_terminal(tmp_path: Path) -> None:
    desktop = install_linux(tmp_path, command=["/opt/pixel viewer/pixel-viewer"])
    text = desktop.read_text()

    assert desktop == tmp_path / "applications" / "pixel-viewer.desktop"
    assert "Terminal=false" in text
    assert "Exec='/opt/pixel viewer/pixel-viewer' %F" in text
    assert "image/png" in text
    icon = tmp_path / "icons" / "hicolor" / "256x256" / "apps" / "pixel-viewer.png"
    assert icon.is_file() and icon.read_bytes().startswith(b"\x89PNG")


def test_install_flag_reports_the_launcher(
    monkeypatch: pytest.MonkeyPatch, capsys: pytest.CaptureFixture[str], tmp_path: Path
) -> None:
    target = tmp_path / "Pixel Viewer.app"
    monkeypatch.setattr("pixel_viewer.app.install_launcher", lambda: target)

    assert main(["--install"]) == 0
    assert str(target) in capsys.readouterr().out


def test_install_flag_reports_a_failure(monkeypatch: pytest.MonkeyPatch, capsys: pytest.CaptureFixture[str]) -> None:
    def fail() -> Path:
        raise OSError("disk full")

    monkeypatch.setattr("pixel_viewer.app.install_launcher", fail)

    assert main(["--install"]) == 1
    assert "disk full" in capsys.readouterr().err
