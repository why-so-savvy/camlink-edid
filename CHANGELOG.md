# Changelog

## 0.2.0 (2026-11-26)

- New window (Tkinter, no extra dependencies). Open it by double-clicking `camlink-edid-gui.pyw` or with `python camlink-edid.py gui`.
  - Shows the modes the card offers to the console and whether 1440p60 is among them.
  - Add, remove, back up and restore through a three-step guide: Check, Write, Confirm.
  - Write to card stays disabled until the HDMI cable is confirmed unplugged.
  - Shows chunk-by-chunk progress, and the window cannot be closed while writing.
  - Detects the USB replug and re-reads the card to confirm the change is stored.
- Before writing, the window re-reads the card and stops if the EDID changed since it was shown.
- The logic shared by the command line and the window now lives in `operations.py`, so both run identical checks.
- The replug wait can be cancelled ("Skip this check").
- Tested on real hardware: the `remove` / `add` round trip (see docs/COMPATIBILITY.md).

## 0.1.0 (2026-11-26)

First release.

- Commands: `detect`, `status`, `backup`, `decode`, `add`, `remove`, `restore`.
- Supports Cam Link 4K Rev.2 (USB `0FD9:007B`) on Windows only.
- Adds 2560x1440 @ 59.95 Hz (241.50 MHz) to the unused EDID slot 2. This is the same descriptor that was verified with a PS5 on real hardware.
- Safety: exclusive device access, strict EDID validation, verified backups, typed confirmation, chunk-by-chunk checks that stop before the final commit, full read-back, and a guided replug check.
