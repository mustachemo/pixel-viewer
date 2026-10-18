"""Install a clickable macOS app or a Linux application-menu entry."""

# ================================== Imports ================================== #
# Standard Library
import os
import plistlib
import shlex
import shutil
import subprocess
import sys
import tempfile
from importlib.metadata import PackageNotFoundError, version
from pathlib import Path

# Local
from pixel_viewer.icons import render_icon_png

# ================================== Constants ================================ #
APP_NAME = "Pixel Viewer"
BUNDLE_ID = "com.mustachemo.pixelviewer"
LINUX_DESKTOP_NAME = "pixel-viewer.desktop"
LINUX_ICON_SIZES = (16, 24, 32, 48, 64, 128, 256, 512)
# iconutil names. The @2x files are the doubled pixel size of the point size in the name.
_ICONSET = (
    ("icon_16x16.png", 16),
    ("icon_16x16@2x.png", 32),
    ("icon_32x32.png", 32),
    ("icon_32x32@2x.png", 64),
    ("icon_128x128.png", 128),
    ("icon_128x128@2x.png", 256),
    ("icon_256x256.png", 256),
    ("icon_256x256@2x.png", 512),
    ("icon_512x512.png", 512),
    ("icon_512x512@2x.png", 1024),
)
_IMAGE_TYPES = (
    "public.png",
    "public.jpeg",
    "public.tiff",
    "com.microsoft.bmp",
    "com.compuserve.gif",
    "public.mpeg-4",
    "public.movie",
)


# ================================== Installing =============================== #
def launcher_command() -> list[str]:
    """Returns the command the desktop launcher should run.

    Prefers the ``pixel-viewer`` script beside the interpreter that is running this command. That stays inside the
    virtual environment: resolving a symlink here would land on the base Python, which does not have the package.
    Falls back to ``python -m pixel_viewer`` when that script is not there.
    """
    sibling = Path(sys.executable).parent / "pixel-viewer"
    if _is_launcher(sibling):
        return [str(sibling)]
    if sys.argv and sys.argv[0]:
        invoked = Path(sys.argv[0])
        if not invoked.is_absolute():
            invoked = Path.cwd() / invoked
        if _is_launcher(invoked):
            return [str(invoked)]
    found = shutil.which("pixel-viewer")
    if found is not None and _is_launcher(Path(found)):
        return [str(Path(found).resolve())]
    return [sys.executable, "-m", "pixel_viewer"]


def _is_launcher(path: Path) -> bool:
    """True for an executable console script. Skips ``.py`` files, which are not standalone programs."""
    return path.is_file() and os.access(path, os.X_OK) and path.suffix != ".py"


def install_launcher(root: Path | None = None) -> Path:
    """Installs a clickable launcher for this operating system.

    Args:
        root: Folder that receives the app. Defaults to ``~/Applications`` on macOS and the XDG data directory
            on Linux. Tests pass a temporary directory.

    Returns:
        The ``.app`` bundle or the ``.desktop`` file that was written.

    Raises:
        OSError: If this operating system has no installer, or a file cannot be written.
    """
    if sys.platform == "darwin":
        return install_macos(root or Path.home() / "Applications")
    if sys.platform.startswith("linux"):
        data_home = os.environ.get("XDG_DATA_HOME")
        default = Path(data_home) if data_home else Path.home() / ".local" / "share"
        return install_linux(root or default)
    raise OSError(f"Pixel Viewer has no desktop installer for {sys.platform}.")


def install_macos(destination: Path, command: list[str] | None = None, register: bool = True) -> Path:
    """Writes ``Pixel Viewer.app`` into ``destination`` and registers it with Launch Services.

    Args:
        destination: Folder that will contain the bundle, created if needed.
        command: Program to exec. Defaults to :func:`launcher_command`.
        register: Tell Launch Services about the bundle. Tests skip this so a temporary app is not indexed.

    Returns:
        Path of the installed bundle.
    """
    destination.mkdir(parents=True, exist_ok=True)
    staging = destination / ".pixel-viewer-staging.app"
    if staging.exists():
        shutil.rmtree(staging)
    contents = staging / "Contents"
    macos_dir = contents / "MacOS"
    resources = contents / "Resources"
    macos_dir.mkdir(parents=True)
    resources.mkdir()
    (contents / "Info.plist").write_bytes(plistlib.dumps(_info_plist(), sort_keys=False))
    executable = macos_dir / "pixel-viewer"
    executable.write_text(_shell_script(command or launcher_command()), encoding="utf-8")
    executable.chmod(0o755)
    _write_icns(resources / "icon.icns")

    target = destination / f"{APP_NAME}.app"
    if target.exists():
        shutil.rmtree(target)
    staging.rename(target)
    if register:
        _register_macos(target)
    return target


def install_linux(destination: Path, command: list[str] | None = None) -> Path:
    """Writes a ``.desktop`` file and icons under an XDG data directory.

    Args:
        destination: XDG data directory, usually ``~/.local/share``.
        command: Program the menu entry runs. Defaults to :func:`launcher_command`.

    Returns:
        Path of the desktop file.
    """
    applications = destination / "applications"
    applications.mkdir(parents=True, exist_ok=True)
    desktop = applications / LINUX_DESKTOP_NAME
    desktop.write_text(_desktop_entry(command or launcher_command()), encoding="utf-8")
    for size in LINUX_ICON_SIZES:
        icon_dir = destination / "icons" / "hicolor" / f"{size}x{size}" / "apps"
        icon_dir.mkdir(parents=True, exist_ok=True)
        (icon_dir / "pixel-viewer.png").write_bytes(render_icon_png(size))
    updater = shutil.which("update-desktop-database")
    if updater is not None:
        subprocess.run([updater, str(applications)], check=False, stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)
    return desktop


# ================================== Contents ================================= #
def _app_version() -> str:
    """Package version, or ``0.0.0`` when the package metadata is not installed."""
    try:
        return version("pixel-viewer")
    except PackageNotFoundError:
        return "0.0.0"


def _info_plist() -> dict[str, object]:
    """Info.plist fields for the macOS bundle."""
    app_version = _app_version()
    return {
        "CFBundleName": APP_NAME,
        "CFBundleDisplayName": APP_NAME,
        "CFBundleIdentifier": BUNDLE_ID,
        "CFBundleVersion": app_version,
        "CFBundleShortVersionString": app_version,
        "CFBundlePackageType": "APPL",
        "CFBundleSignature": "????",
        "CFBundleExecutable": "pixel-viewer",
        "CFBundleIconFile": "icon",
        "CFBundleInfoDictionaryVersion": "6.0",
        "LSMinimumSystemVersion": "12.0",
        "LSApplicationCategoryType": "public.app-category.photography",
        "NSHighResolutionCapable": True,
        "NSSupportsAutomaticGraphicsSwitching": True,
        "LSMultipleInstancesProhibited": True,
        "CFBundleDocumentTypes": [
            {
                "CFBundleTypeName": "Image",
                "CFBundleTypeRole": "Viewer",
                "LSHandlerRank": "Alternate",
                "LSItemContentTypes": list(_IMAGE_TYPES),
            }
        ],
    }


def _shell_script(command: list[str]) -> str:
    """macOS bundle executable. Launch Services runs it directly, so no terminal window appears."""
    quoted = " ".join(shlex.quote(part) for part in command)
    return f"""#!/bin/sh
# Pixel Viewer.app launcher. Recreate it with: pixel-viewer --install
cd "$HOME" || exit 1
exec {quoted} "$@"
"""


def _desktop_entry(command: list[str]) -> str:
    """XDG desktop entry. ``Terminal=false`` keeps the app off a terminal when it is clicked."""
    executable = " ".join(shlex.quote(part) for part in command)
    return f"""[Desktop Entry]
Version=1.0
Type=Application
Name={APP_NAME}
GenericName=Pixel Image Viewer
Comment=Zoom into an image and read every pixel value
Exec={executable} %F
Icon=pixel-viewer
Terminal=false
Categories=Graphics;2DGraphics;Viewer;
MimeType=image/png;image/jpeg;image/tiff;image/bmp;image/gif;video/mp4;video/quicktime;video/webm;video/x-msvideo;
Keywords=pixel;image;mask;zoom;
StartupNotify=true
StartupWMClass=pixel-viewer
"""


def _write_icns(destination: Path) -> bool:
    """Builds an ``.icns`` with ``iconutil``. Returns False when that tool is not on the machine."""
    iconutil = shutil.which("iconutil")
    if iconutil is None:
        return False
    with tempfile.TemporaryDirectory(prefix="pixel-viewer-iconset-") as temporary:
        iconset = Path(temporary) / "PixelViewer.iconset"
        iconset.mkdir()
        for name, size in _ICONSET:
            (iconset / name).write_bytes(render_icon_png(size))
        result = subprocess.run([iconutil, "-c", "icns", str(iconset), "-o", str(destination)], check=False)
    return result.returncode == 0 and destination.is_file()


def _register_macos(bundle: Path) -> None:
    """Tells Launch Services about the new bundle so Spotlight and Open With can see it."""
    registrar = Path(
        "/System/Library/Frameworks/CoreServices.framework/Frameworks/LaunchServices.framework/Support/lsregister"
    )
    if registrar.is_file():
        subprocess.run(
            [str(registrar), "-f", str(bundle)],
            check=False,
            stdout=subprocess.DEVNULL,
            stderr=subprocess.DEVNULL,
        )
