"""Double-click to open the Cam Link EDID window (no console). Same as: python camlink-edid.py gui"""
import os
import sys

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))

from camlink_edid.gui import main  # noqa: E402

if __name__ == "__main__":
    sys.exit(main())
