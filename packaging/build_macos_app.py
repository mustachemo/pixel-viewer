"""Build a standalone Pixel Viewer.app that can be dragged into Applications.

The bundle contains Python, Qt and the image libraries, so another Mac does not need this checkout or a terminal.
"""

# ================================== Imports ================================== #
# Standard Library
import argparse
import shutil
import subprocess
import sys
from pathlib import Path

# ================================== Constants ================================ #
ROOT = Path(__file__).resolve().parents[1]
APP_NAME = "Pixel Viewer.app"


def main() -> int:
    """Builds the app, a zip of it, and optionally copies it to ~/Applications."""
    parser = argparse.ArgumentParser(description="Build a standalone macOS Pixel Viewer.app.")
    parser.add_argument(
        "--install", action="store_true", help="replace ~/Applications/Pixel Viewer.app with this build"
    )
    args = parser.parse_args()
    if sys.platform != "darwin":
        print("The macOS app has to be built on a Mac.", file=sys.stderr)
        return 1

    dist = ROOT / "dist" / "macos"
    work = ROOT / "build" / "pyinstaller"
    dist.mkdir(parents=True, exist_ok=True)
    subprocess.run(
        [
            sys.executable,
            "-m",
            "PyInstaller",
            "--noconfirm",
            "--clean",
            "--distpath",
            str(dist),
            "--workpath",
            str(work),
            str(ROOT / "packaging" / "pixel-viewer.spec"),
        ],
        cwd=ROOT,
        check=True,
    )
    app = dist / APP_NAME
    # * Ad-hoc signature lets this Mac open the bundle. Other Macs still need Right Click → Open the first time,
    # * because the app is not signed with an Apple Developer ID.
    subprocess.run(["codesign", "--force", "--deep", "--sign", "-", str(app)], check=True)

    zip_path = ROOT / "dist" / "PixelViewer-macOS.zip"
    zip_path.unlink(missing_ok=True)
    shutil.make_archive(str(zip_path.with_suffix("")), "zip", dist, APP_NAME)
    print(f"Built {app}")
    print(f"Zip {zip_path}")

    if args.install:
        destination = Path.home() / "Applications" / APP_NAME
        if destination.exists():
            shutil.rmtree(destination)
        shutil.copytree(app, destination, symlinks=True)
        print(f"Installed {destination}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
