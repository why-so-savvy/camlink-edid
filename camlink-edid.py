#!/usr/bin/env python3
"""Run without installing:  python camlink-edid.py <command>

Commands: detect, status, backup, decode, add, remove, restore. Use --help on any command.
"""
import os
import sys

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))

from camlink_edid.cli import main  # noqa: E402

if __name__ == "__main__":
    sys.exit(main())
