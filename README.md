# camlink-edid

Add a **2560x1440 @ 60 Hz** mode to the EDID of an **Elgato Cam Link 4K Rev.2** (USB ID `0FD9:007B`), so that HDMI sources such as a PlayStation 5 offer 1440p to it.

> **Unofficial.** Not affiliated with, endorsed or supported by Elgato or Corsair.
> **Experimental:** verified on one unit so far. Read [Safety](#safety) before writing anything.

## Why this exists

The Cam Link 4K Rev.2 can capture 2560x1440 at 60 Hz: its HDMI receiver accepts up to 300 MHz, and 1440p60 needs 241.5 MHz. But its factory **EDID**, the list of modes the card announces to the HDMI source, has no 1440p entry. A PS5 therefore says the connected HDMI device does not support 1440p.

Tools like CRU only change what *Windows* believes about a display. They cannot change what the card tells a console.

This tool writes one extra timing (2560x1440 @ 59.95 Hz) into an **unused slot** of the EDID stored inside the card. On the tested unit the PS5 then passed its 1440p test, and the capture application received native 2560x1440 at 60 fps, with no upscaling.

## What changes and what does not

| | |
|---|---|
| **Changed** | One unused 18-byte descriptor slot of the EDID, plus its checksum byte |
| **Not changed** | Firmware, every existing mode (4K30, 1080p60, ...), audio, device identity |
| **Where** | The card's own persistent memory. It survives unplugging and reboots. No background software is needed |
| **Undo** | `remove` puts back the exact previous bytes. `restore` writes any saved backup |

Adding a mode does **not** raise the hardware limits: 1440p120 (about 500 MHz) and 4K60 (594 MHz) are impossible on this card, and the tool refuses such modes.

## Supported hardware

The tool goes by **USB ID only**, never by product name. Elgato now uses the name "Cam Link 4K MK.2" for a *newer* revision with a different USB ID, so a box labelled "MK.2" is not enough to know which one you have.

| USB ID | Device | Status |
|---|---|---|
| `0FD9:007B` | Cam Link 4K Rev.2 (older "MK.2") | ✅ **Supported.** Verified on 1 unit (firmware 21.08.03, MCU 23.05.09) |
| `0FD9:0085` | Cam Link 4K Rev.2 in USB 2 mode | Connect it to a USB 3 port |
| `0FD9:0066` / `0067` | Cam Link 4K, 1st generation | ❌ Different hardware |
| `0FD9:00A1` / `00A2` | Cam Link 4K Rev.3 | ❌ Protocol unknown |
| `0FD9:00F4` / `00F5` | Cam Link 4K Rev.4 (newer "MK.2") | ❌ Protocol unknown |
| `1CFA:0011` | Cam Link Pro | Elgato's software lists custom EDID support for it |

To find your USB ID, run `python camlink-edid.py detect`. Or open Device Manager, then Cameras > Cam Link 4K > Properties > Details > Hardware Ids.

**About firmware:** the tested unit had its MCU firmware updated from the factory 21.09.23 to 23.05.09 through Camera Hub *before* this tool was finished. It is **not known** whether the update is needed, because writing has not yet been tested on a factory 21.x MCU. This tool never updates firmware. If a card answers differently from the tested one, the tool stops at the first chunk, before anything is stored. Please [report your result](CONTRIBUTING.md#reporting-a-result) either way.

## Requirements

- Windows 10 or 11
- Python 3.9 or newer from [python.org](https://www.python.org/downloads/) (tick "Add python.exe to PATH" during setup)
- The Cam Link connected to a USB 3 port
- Elgato Camera Hub, Elgato Studio and 4K Capture Utility closed, including their tray icons

No other software and no installation are needed. The tool uses only Python's standard library.

## Quick start

Download this repository (Code > Download ZIP), extract it, open PowerShell in that folder and run:

```powershell
python camlink-edid.py detect          # which Cam Link is connected (no communication with it)
python camlink-edid.py status          # read-only: what the card announces right now
python camlink-edid.py add --dry-run   # read-only: show exactly what would change
python camlink-edid.py add             # make the change (guided, see below)
```

`add` walks you through every step:

1. It reads the EDID **twice** and continues only if both reads match and the EDID is recognised.
2. It saves a **backup** to `%USERPROFILE%\camlink-edid-backups`, then reads the file back from disk to verify it.
3. It asks you to **unplug the HDMI cable** (keep USB connected) and to type `WRITE`.
4. It writes 32 chunks of 8 bytes and **checks each chunk** before sending the next one.
5. It reads the whole EDID back and compares it byte for byte.
6. It asks you to **unplug and replug USB**, then reads the card again to confirm the change is stored.

Then connect HDMI. On a PS5, go to Settings > Screen and Video > Video Output > Resolution and choose 1440p (on the tested unit, *Automatic* also picked 1440p). In your capture application, select 2560x1440 at 60 fps.

## Commands

| Command | What it does | Writes to the card? |
|---|---|---|
| `detect` | Lists connected Cam Link devices and whether they are supported. Sends nothing to any device | No |
| `status [--save FILE]` | Reads the EDID and shows its state and modes | No |
| `backup` | Saves a timestamped copy of the card's EDID | No |
| `decode FILE` | Shows the contents of an EDID file. Works offline, on any OS | No |
| `add [--dry-run]` | Adds the 2560x1440 @ 60 Hz mode | **Yes**, after confirmation |
| `remove [--dry-run]` | Removes that mode again (exact inverse of `add`) | **Yes**, after confirmation |
| `restore FILE [--dry-run]` | Writes a saved EDID back | **Yes**, after confirmation |

Common options: `--backup-dir DIR` (where backups are kept) and `--no-replug-check` (skip the guided replug check). Exit codes: `0` success, `1` stopped before writing (card unchanged), `2` problem during or after a write (follow the printed steps).

## Safety

**How the tool protects your card**

- **Narrow scope.** It talks only to USB `0FD9:007B` and only to the EDID address. The code has no firmware, reset or mode commands at all.
- **Exclusive access.** It opens the card's control interface exclusively, so Camera Hub cannot interleave its own commands.
- **Two identical reads** are required before the data is trusted.
- **Strict validation before any write:** size, header, both checksums, Cam Link identity, layout, and every mode within the 300 MHz receiver limit and the declared range limits. This matters because the card itself checks only 4 header bytes and would accept a broken EDID.
- **Minimal change.** `add` and `remove` may only touch slot 2 and its checksum. An internal check refuses anything else.
- **Mandatory backup.** It is verified on disk and never overwritten.
- **Dry run and confirmation.** Use `--dry-run` to see the plan. Nothing is written unless you type `WRITE`.
- **Each chunk is checked** (status byte, echo, read-back) before the next one is sent. On the analysed firmware, the card stores the EDID in its memory **only after the last chunk**. A stop at any earlier point therefore leaves the stored EDID unchanged. A malformed frame, like the swapped header bytes that made an early prototype fail, is rejected by the card at the very first chunk, and the tool stops right there.
- **Ctrl+C is postponed** during the roughly one second of writing, so a write cannot be split in two.
- **Verification.** A full read-back follows the write, and a guided unplug/replug confirms the EDID was really stored.
- **No automatic retries**, ever.

**What it cannot protect against**

- Unplugging USB or losing power *during* the roughly one second of writing. Before the last chunk, the analysis says the stored EDID stays unchanged. During the last chunk, the result is unknown: use `status`, then `restore` if needed.
- Hardware or firmware versions nobody has tested yet.
- Elgato software replacing the EDID. A factory reset or firmware update *may* restore the factory EDID (untested). If it does, run `add` again.

## Undo

```powershell
python camlink-edid.py remove                 # exact inverse of add
python camlink-edid.py restore "<backup>.bin" # any backup from %USERPROFILE%\camlink-edid-backups
```

Both work over USB alone, even when there is no HDMI picture at all.

## Troubleshooting and details

- [docs/TROUBLESHOOTING.md](docs/TROUBLESHOOTING.md): error messages and what to do
- [docs/HOW-IT-WORKS.md](docs/HOW-IT-WORKS.md): the hardware, the protocol, the exact bytes, and what is verified versus inferred
- [docs/COMPATIBILITY.md](docs/COMPATIBILITY.md): tested setups and the revision list

## FAQ

**Does it work with an Xbox or a PC?** The new mode is a normal EDID entry, so other sources may offer 1440p60 too. Only the PS5 has been tested.

**Will the change survive reinstalling Windows or moving the card to another PC?** Yes. It is stored in the card.

**Do I need Camera Hub?** No, and it must be closed while the tool runs.

**Why 59.95 Hz and not exactly 60?** This is the exact timing that a PS5 has accepted on real hardware. It uses CVT reduced blanking at 241.50 MHz.

**Linux or macOS?** Only `decode` works there for now. Device access is Windows-only.

## Contributing

Results from other units, especially with factory firmware, are the most valuable contribution. See [CONTRIBUTING.md](CONTRIBUTING.md).

## Credits

- [schlarpc/elgato-cam-link-4k-firmware-re](https://github.com/schlarpc/elgato-cam-link-4k-firmware-re) for the documentation of the differences between Cam Link 4K revisions.
- [Everlite/EverLive v1.3.0](https://github.com/Everlite/EverLive/releases/tag/v1.3.0) for the PS5-tested 2560x1440 @ 59.95 Hz timing (tested there on a different capture card).

## Disclaimer

This software writes to the persistent memory of your device. It is provided "as is", without warranty of any kind (see [LICENSE](LICENSE)). Use it at your own risk. It may void your warranty.

Elgato and Cam Link are trademarks of Corsair Memory, Inc. PlayStation is a trademark of Sony Interactive Entertainment Inc. They are used here only to identify compatible hardware.

## License

[MIT](LICENSE) © 2026 why-so-savvy
