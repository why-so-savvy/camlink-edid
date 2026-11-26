# Safety and security

This tool writes to the memory of a capture card, so safety problems are taken seriously.

## Please report

- Anything that could write unexpected data, leave a card unusable, or skip a safety check: a backup, a validation step, the chunk-by-chunk checks or the confirmation.
- A release file whose checksum or [attestation](docs/BUILDING.md#verify-a-download) does not match.

Report privately through GitHub's **Security > Report a vulnerability** on this repository. For problems that cannot harm other users, a normal issue is fine.

Please include what you ran, the full output from the **Activity** box or the terminal, and your card's USB ID and firmware.
Do not include USB captures or logs from Elgato's software: they can contain your card's serial number.

## Supported versions

Only the latest release receives fixes.
