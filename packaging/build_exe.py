"""Build the Windows program (CamLinkEDID.exe) with PyInstaller.

The release workflow on GitHub runs exactly this script, so a local build and
the published file are made the same way.

Usage, from the repository root, with PyInstaller installed:
    python packaging/build_exe.py
Output:
    dist/CamLinkEDID.exe          the program (one file, no console window)
    dist/CamLinkEDID.exe.sha256   its SHA-256 checksum
"""
import hashlib
import re
import subprocess
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
NAME = "CamLinkEDID"

VERSION_INFO = """VSVersionInfo(
  ffi=FixedFileInfo(filevers={nums}, prodvers={nums}, mask=0x3f, flags=0x0, OS=0x40004,
                    fileType=0x1, subtype=0x0, date=(0, 0)),
  kids=[
    StringFileInfo([StringTable('040904B0', [
      StringStruct('CompanyName', 'why-so-savvy'),
      StringStruct('FileDescription', 'Cam Link EDID: add 1440p60 to a Cam Link 4K Rev.2 (unofficial)'),
      StringStruct('FileVersion', '{version}'),
      StringStruct('InternalName', '{name}'),
      StringStruct('LegalCopyright', 'MIT License, (c) 2026 why-so-savvy'),
      StringStruct('OriginalFilename', '{name}.exe'),
      StringStruct('ProductName', 'Cam Link EDID'),
      StringStruct('ProductVersion', '{version}')])]),
    VarFileInfo([VarStruct('Translation', [1033, 1200])])
  ]
)
"""


def version() -> str:
    text = (ROOT / "camlink_edid" / "__init__.py").read_text(encoding="utf-8")
    return re.search(r'__version__ = "([0-9]+\.[0-9]+\.[0-9]+)"', text).group(1)


def main() -> int:
    v = version()
    nums = tuple(int(x) for x in v.split(".")) + (0,)
    build = ROOT / "build"
    build.mkdir(exist_ok=True)
    info = build / "version_info.txt"
    info.write_text(VERSION_INFO.format(nums=nums, version=v, name=NAME), encoding="utf-8")
    assets = ROOT / "camlink_edid" / "assets"
    separator = ";" if sys.platform == "win32" else ":"
    command = [
        sys.executable, "-m", "PyInstaller", "--noconfirm", "--clean",
        "--onefile", "--windowed", "--noupx",
        "--name", NAME,
        "--icon", str(assets / "icon.ico"),
        "--version-file", str(info),
        "--add-data", "{}{}camlink_edid/assets".format(assets, separator),
        "--distpath", str(ROOT / "dist"),
        "--workpath", str(build / "pyinstaller"),
        "--specpath", str(build),
        str(ROOT / "camlink-edid-gui.pyw"),
    ]
    subprocess.run(command, check=True, cwd=ROOT)
    exe = ROOT / "dist" / (NAME + ".exe")
    digest = hashlib.sha256(exe.read_bytes()).hexdigest()
    # Unix line ending, so "sha256sum -c" works too (text mode on Windows would write CRLF).
    (ROOT / "dist" / (NAME + ".exe.sha256")).write_bytes("{}  {}.exe\n".format(digest, NAME).encode("ascii"))
    print("Built {} ({} KiB), version {}\nSHA-256 {}".format(exe, exe.stat().st_size // 1024, v, digest))
    return 0


if __name__ == "__main__":
    sys.exit(main())
