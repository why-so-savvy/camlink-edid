# Changelog

## 0.1.0 (2026-11-26)

First release.

- Commands: `detect`, `status`, `backup`, `decode`, `add`, `remove`, `restore`.
- Supports Cam Link 4K Rev.2 (USB `0FD9:007B`) on Windows only.
- Adds 2560x1440 @ 59.95 Hz (241.50 MHz) to the unused EDID slot 2. This is the same descriptor that was verified with a PS5 on real hardware.
- Safety: exclusive device access, strict EDID validation, verified backups, typed confirmation, chunk-by-chunk checks that stop before the final commit, full read-back, and a guided replug check.
