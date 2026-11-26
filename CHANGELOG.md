# Changelog

## 0.3.0 (2026-11-26)

- **One-file Windows app, `CamLinkEDID.exe`:** no Python needed.
  - GitHub builds it from the tagged source, publishes a SHA-256 checksum and attaches a build-provenance attestation.
  - Version information is embedded and UPX compression is not used, to reduce antivirus false positives.
- An app icon, plus a **Help** link to the step-by-step guide.
- Unexpected errors now appear in the Activity box instead of vanishing (the .exe has no console).
- Plainer wording in the window for people new to EDID.
- Documentation rewritten:
  - a step-by-step README tutorial with screenshots, and plain-language explanations of what changes and where;
  - a guide for owners of other revisions on [researching their card with an AI assistant](docs/AI-ASSISTED-RESEARCH.md), with a rules template;
  - [troubleshooting](docs/TROUBLESHOOTING.md) for every message;
  - [building and verifying](docs/BUILDING.md);
  - [the project story](docs/PROJECT-STORY.md);
  - a security policy and issue templates.

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
