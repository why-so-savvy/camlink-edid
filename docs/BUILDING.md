# Building, testing and verifying

## Verify a download

Each release has `CamLinkEDID.exe` and `CamLinkEDID.exe.sha256`. To check that your file is the one GitHub built:

```powershell
Get-FileHash .\CamLinkEDID.exe -Algorithm SHA256   # must match the value in CamLinkEDID.exe.sha256
```

The release workflow also publishes a **build-provenance attestation**: a signed record that the file was built by this repository's workflow from a specific commit. With the [GitHub CLI](https://cli.github.com/):

```powershell
gh attestation verify .\CamLinkEDID.exe --repo why-so-savvy/camlink-edid
```

**Why Windows or antivirus software may warn:** the .exe is not signed with a paid code-signing certificate, and one-file Python apps (PyInstaller) are sometimes flagged by heuristics. The checks above show the file is genuine. Running from source (below) avoids the .exe entirely.

## Run from source

You need [Python 3.10+](https://www.python.org/downloads/) from python.org. The installer includes Tkinter by default. No other packages are needed.

```powershell
python camlink-edid-gui.pyw            # the window (or double-click the file)
python camlink-edid.py --help          # the command line
python camlink-edid.py status          # read-only check of the card
```

## Tests

```powershell
python -m unittest discover -s tests
```

The tests run against `tests/fakes.py`, a simulated card. It behaves like the real one: it answers malformed messages with status `01`, keeps writes in a staging buffer and stores them only after the last chunk. Window tests are skipped automatically where there is no display. The optional factory-EDID test runs only if `CAMLINK_EDID_FACTORY_DUMP` points to an EDID read from a real card.

GitHub runs the tests on Windows and Linux with Python 3.10 and 3.14 on every push.

## Build the .exe locally

```powershell
python -m venv .venv
.venv\Scripts\python -m pip install pyinstaller==6.22.3
.venv\Scripts\python packaging\build_exe.py
```

The result is `dist\CamLinkEDID.exe` and its `.sha256` file. The script embeds version information and does not use UPX compression, which often triggers antivirus false positives.

## Make a release

1. Update `__version__` in `camlink_edid/__init__.py`, `version` in `pyproject.toml`, and `CHANGELOG.md`.
2. Commit, then tag and push: `git tag v0.3.0`, then `git push origin main --tags`.
3. The [release workflow](../.github/workflows/release.yml) runs the tests, checks that the tag matches the version, builds the .exe, attests it and publishes the release.

## Project layout

| Path | What it is |
|---|---|
| `camlink_edid/edid.py` | EDID parsing, validation and the 1440p60 change. Pure functions |
| `camlink_edid/protocol.py` | The two HID messages (read and write 8 bytes) and the chunk-by-chunk write checks |
| `camlink_edid/operations.py` | Shared logic: planning, backups, writing, verification |
| `camlink_edid/winhid.py` | Windows USB/HID access (system DLLs through ctypes) |
| `camlink_edid/devices.py` | Known Cam Link USB IDs |
| `camlink_edid/gui.py`, `cli.py` | The window and the command line, both thin layers over `operations.py` |
| `packaging/` | The .exe build script and release notes |
| `tests/` | The simulated card and all tests |
