# Compatibility

## Tested setups

| # | USB ID | BASE firmware | MCU firmware | Source | Result | Persistence | Reporter |
|---|---|---|---|---|---|---|---|
| 1 | `0FD9:007B` | 21.08.03 | 23.05.09 (updated from factory 21.09.23) | PS5, Automatic resolution | 1440p test passed. Capture input 2560x1440 @ 60.00 fps | Survived a USB replug (verified by reading the card) and a Windows restart | why-so-savvy |
| 1b | same unit | 21.08.03 | 23.05.09 | PS5 | **Tool v0.1.0 round trip:** `remove`, then `add`. Every chunk passed its checks, full read-back matched, and each result survived a USB replug. PS5 1440p at about 60 fps confirmed afterwards | Both states read back after a replug | why-so-savvy |

**Wanted:** results from `0FD9:007B` units on factory firmware, especially MCU 21.x, and any `remove` or `restore` round trip. See [CONTRIBUTING.md](../CONTRIBUTING.md#reporting-a-result).

You can see your firmware version in Elgato Camera Hub: open the device settings (the sliders icon). The version is shown as `BASE (MCU: x)`. Close Camera Hub completely before running this tool.

## The Cam Link family by USB ID

This list comes from the device-capability manifests shipped with Elgato 4K Capture Utility 1.7.16 and Elgato Studio 2.0.

| USB 3 ID | USB 2 ID | Name used by Elgato | Firmware parts | This tool |
|---|---|---|---|---|
| `0FD9:0061` | `0FD9:0062` | Cam Link (HD) | MCU + FPGA | Not supported |
| `0FD9:0066` | `0FD9:0067` | Cam Link 4K | MCU + FPGA | Not supported (different hardware) |
| `0FD9:007B` | `0FD9:0085` | Cam Link 4K MK.2, later renamed "Rev.2" | MCU + BASE | **Supported** (USB 3 mode) |
| `0FD9:00A1` | `0FD9:00A2` | Cam Link 4K Rev.3 | MCU + BASE | Not supported (protocol unknown) |
| `0FD9:00F4` | `0FD9:00F5` | Cam Link 4K MK.2 / "Rev.4" | unknown | Not supported (protocol unknown) |
| `1CFA:0011` | | Cam Link Pro | MCU | Not needed: Elgato software lists custom EDID support |

Note that the EDID identity "EGA 0x0066" is shared by several revisions. It says nothing about the USB ID, which is why the tool checks both.
