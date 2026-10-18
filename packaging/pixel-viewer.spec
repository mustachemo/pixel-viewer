# PyInstaller spec for a standalone Pixel Viewer.app.
# Build it with packaging/build_macos_app.py.

import sys
from pathlib import Path

from PyInstaller.utils.hooks import collect_all, copy_metadata

# PyInstaller sets SPECPATH to the directory that contains this file.
ROOT = Path(SPECPATH).resolve().parent
sys.path.insert(0, str(ROOT / "src"))

from pixel_viewer.install_desktop import _info_plist, _write_icns  # noqa: E402

icon_path = ROOT / "build" / "icon.icns"
icon_path.parent.mkdir(parents=True, exist_ok=True)
if not _write_icns(icon_path):
    raise SystemExit("Could not build the macOS icon. iconutil is required.")

datas = copy_metadata("pixel-viewer")
binaries = []
hiddenimports = []
# * OpenCV's libraries are not picked up by the import graph. Qt is: the PySide6 hook bundles the modules
# * this program imports, and collect_all("PySide6") would also ship Qt WebEngine, Qt 3D and the rest.
package_datas, package_binaries, package_hidden = collect_all("cv2")
datas += package_datas
binaries += package_binaries
hiddenimports += package_hidden

a = Analysis(
    [str(ROOT / "src" / "pixel_viewer" / "__main__.py")],
    pathex=[str(ROOT / "src")],
    binaries=binaries,
    datas=datas,
    hiddenimports=hiddenimports,
    excludes=["tkinter", "pytest"],
    noarchive=False,
)
pyz = PYZ(a.pure)

exe = EXE(
    pyz,
    a.scripts,
    [],
    exclude_binaries=True,
    name="pixel-viewer",
    debug=False,
    bootloader_ignore_signals=False,
    strip=False,
    upx=False,
    console=False,
    disable_windowed_traceback=False,
    argv_emulation=False,
    target_arch=None,
    codesign_identity=None,
    entitlements_file=None,
)
coll = COLLECT(
    exe,
    a.binaries,
    a.datas,
    strip=False,
    upx=False,
    name="pixel-viewer",
)
app = BUNDLE(
    coll,
    name="Pixel Viewer.app",
    icon=str(icon_path),
    bundle_identifier="com.mustachemo.pixelviewer",
    info_plist=_info_plist(),
)
