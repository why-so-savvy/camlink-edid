# Contributing

Thank you for helping. This tool writes to people's hardware, so the bar is **evidence first**.

## Reporting a result

Results, good or bad, are the most useful contribution. Open an issue using the "Device report" template and include:

- the USB ID shown at the top of the app and the text from its **Activity** box, or the output of `python camlink-edid.py detect` and `python camlink-edid.py status` (none of these contain serial numbers);
- the BASE and MCU firmware shown in Camera Hub;
- what you ran, the full output, and the exit code;
- the source (PS5, Xbox, PC, ...) and what it offered after the change;
- whether the change survived a USB replug.

Do **not** attach USB captures (`.pcap`), logs from Elgato software or raw device paths. They can contain your device's serial number.

## Adding support for another revision

[docs/AI-ASSISTED-RESEARCH.md](docs/AI-ASSISTED-RESEARCH.md) describes a safe way to collect the evidence, with or without an AI assistant.
Support for a new USB ID is only added when there is evidence for all of the following:

1. **Read-only first.** The EDID can be read through a documented, observed command. Collect this by capturing the traffic of Elgato's own software with your own device. Never test unknown commands on a device.
2. **Write path.** The exact frame format and reply are confirmed from the vendor software's own traffic, and so is the point at which the device commits to persistent memory.
3. **Recovery.** A tested way to put the original EDID back.
4. **A hardware result** from at least one unit, with a replug check.

Each revision gets its own explicit entry in `camlink_edid/devices.py` and its own tests. Never relax the `0FD9:007B` checks to make another device "just try".

## Code rules

Setup, tests and the .exe build are described in [docs/BUILDING.md](docs/BUILDING.md).

- Use the Python standard library only, so there is nothing to trust beyond Python itself. PyInstaller is used only to package releases.
- Put shared logic in `operations.py`. The window (`gui.py`) and the command line (`cli.py`) must stay thin layers over it.
- The protocol module may only build frames for the EDID address. Do not add generic I2C, firmware, reset or mode commands.
- Every safety check needs a test in `tests/`, against the simulated card in `tests/fakes.py`.
- Run the tests before opening a pull request:

  ```powershell
  python -m unittest discover -s tests
  ```

## What must never be committed

- Elgato firmware, applications, DLLs or other binaries
- EDID dumps from real devices (`*.bin` is git-ignored on purpose)
- USB captures, logs or anything containing serial numbers
