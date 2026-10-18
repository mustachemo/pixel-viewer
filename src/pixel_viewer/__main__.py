"""`python -m pixel_viewer` entry point, used by the desktop launcher."""

# ================================== Imports ================================== #
# Standard Library
import sys

# Local
from pixel_viewer.app import main

if __name__ == "__main__":
    sys.exit(main())
