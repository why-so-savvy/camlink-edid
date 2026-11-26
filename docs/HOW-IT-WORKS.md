# How it works

This page describes the Cam Link 4K Rev.2 (USB `0FD9:007B`) as far as this project understands it, and marks how each statement is known:

- **[hardware]**: verified on a real card
- **[firmware]**: from static analysis of the official MCU firmware 23.05.09
- **[inferred]**: reasonable but not proven

## The parts involved

```
 HDMI source (PS5)                                   Windows PC
        |                                                |
        | HDMI (the source reads the EDID over DDC)      | USB 3
        v                                                v
 +----------------+    I2C     +-------------------------------+
 | HDMI receiver  | <--------- | MCU (Nuvoton M031/M032 class) |
 +----------------+  programs  |  - emulates an EDID EEPROM    |
        |            the EDID  |    at I2C address 0xA0        |
        v                      |  - keeps the EDID in its own  |
 +----------------+    I2C     |    flash memory               |
 | ITE SoC        | ---------> +-------------------------------+
 | (video + USB,  |  forwards our
 | "BASE" fw)     |  HID commands
 +----------------+
```

- The **SoC** handles video and USB and runs the "BASE" firmware. The tested unit has BASE 21.08.03. [hardware]
- The **MCU** holds the EDID and runs the "MCU" firmware. The tested unit has MCU 23.05.09. [hardware]
- The exact HDMI receiver chip is not confirmed. The BASE image contains an ITE `IT6802` sample EDID, but that does not prove the part number. [inferred]

## Control interface

USB interface 7 is a HID device with the vendor usage page `0xFFA0`. [hardware] Elgato's own software uses it, and so does this tool:

- **Command:** the host sends HID output report `0x06` (255 bytes, zero-padded) with `SET_REPORT`.
- **Reply:** the host fetches input report `0x05` with `GET_REPORT` and a 2047-byte buffer. The card rejects 2048. The reply starts with a status byte.

The tool uses exactly two commands, both for the EDID address `0xA0`:

| Purpose | Bytes after report ID `06` | Reply |
|---|---|---|
| Read 8 bytes | `06 07 A0 01 <offset> 08` | `00` + 8 data bytes |
| Write 8 bytes | `0D 06 A0 09 <offset> <8 data bytes>` | `00 <offset> <data0> <data1>` |

How to read the write frame: `0D` is the frame length (4 + 9). `06` is the command (write). `A0` is the I2C address. `09` is the byte count (1 offset byte + 8 data bytes). [hardware]

An early prototype swapped the length and command fields (`09 0A A0 09 ...`). The card answered every such chunk with status `01` and changed nothing. It is easy to mistake that for "the firmware blocks EDID writes". It was simply a malformed frame. The tool now treats any non-`00` status as a reason to stop at once. [hardware]

## Write sequence

The tool follows the same sequence as Elgato's software, with extra checks:

1. A warm-up read of offset 0.
2. For each of the 32 chunks: write 8 bytes, wait 10 ms, read the same 8 bytes back. The reply status must be `00`, the echo must match, and the read-back must equal what was written. Otherwise the tool stops **before sending the next chunk**.
3. Wait 0.5 s, then read all 256 bytes twice and compare them with the intended EDID.

## What the card does with the data [firmware]

- Reads of `0xA0` come from a **staging buffer** in the MCU's RAM. Writes go into the same buffer, which is why each chunk can be read back right away. [hardware + firmware]
- When the write pointer reaches **byte 256**, the MCU checks only header bytes 0, 1, 6 and 7. It then saves the data to its **flash**, copies it to the active buffer and re-programs the HDMI receiver.
- Because of this, a write that stops before the final chunk is never committed. After a power cycle (unplugging USB), the MCU reloads the stored EDID from flash.
- At start-up the MCU loads the EDID from flash. If the header there is invalid, it falls back to its built-in factory EDID.
- The card checks **no checksums**. A corrupt EDID with a valid header would be stored and offered to the source. This is why the tool validates everything itself.

These points come from analysing MCU firmware 23.05.09. The factory firmware 21.x was never published, so it could not be analysed.

## The EDID change

The factory EDID has an unused display descriptor (tag `0x10`, all zeros) in slot 2, at bytes 72-89. `add` replaces it with this detailed timing descriptor and updates the block checksum at byte 127:

```
56 5E 00 A0 A0 A0 29 50 30 20 35 00 55 50 21 00 00 18
```

| Bytes | Value | Meaning |
|---|---|---|
| `56 5E` | 0x5E56 = 24150 | Pixel clock 241.50 MHz |
| `00 A0 A0` | | 2560 active + 160 blanking = 2720 total (horizontal) |
| `A0 29 50` | | 1440 active + 41 blanking = 1481 total (vertical) |
| `30 20 35 00` | | H front porch 48, H sync 32, V front porch 3, V sync 5 |
| `55 50 21` | | Image size 597 x 336 mm (informational only) |
| `00 00` | | No border |
| `18` | | Digital separate sync, H-, V- |

That gives 241,500,000 / (2720 x 1481) = **59.95055 Hz** and a line rate of 88.8 kHz. Everything stays inside the limits the factory EDID already declares: vertical 25-121 Hz, horizontal 12-120 kHz, pixel clock up to 300 MHz, HDMI TMDS up to 300 MHz. So nothing else needs to change.

The preferred timing (descriptor 1, 3840x2160 @ 30 Hz) and every CTA-861 mode, audio block and HDMI block stay exactly as they were. `remove` writes the unused descriptor back, which restores the previous bytes exactly.

Known SHA-256 values (the factory EDID has no per-unit serial number, so they are the same on every unit):

| EDID | SHA-256 |
|---|---|
| Factory | `013d14fbdc69c143d68103d94172bff342f89c0ba461bbd4bc3de2fa9960d735` |
| Factory + `add` | `b6d74bd55e58628d1b16a360753a37aa7abd4ffe38a8feb254144db0406f1f9b` |

On the tested unit, the manufacture-week field had also been changed earlier, during a harmless test write. The 1440p descriptor bytes were identical. [hardware]

## Verification record (tested unit)

| Step | Result |
|---|---|
| Date-only test write, then USB replug | Change stored and still present after the replug [hardware] |
| 1440p descriptor write | Full read-back identical [hardware] |
| USB replug, then read | Identical [hardware] |
| PS5 1440p output test | Passed [hardware, owner report] |
| Capture application input | 2560x1440, 60.00 fps, no frame generation or upscaling [hardware, screenshot] |
| Windows restart | Still working [hardware, owner report] |
| Not yet verified | PS5 restart with a fixed 1440p setting; a frame-uniqueness analysis of a 60 fps recording |

## Why not RAM-only?

A temporary change that disappears on unplug would be safer to experiment with. On this firmware, though, the only known path into the EDID (`0xA0`) always commits to flash. Another internal route to the receiver exists in the MCU code, but how the host could reach it, and how it behaves during HDMI renegotiation, are unknown. The tool does not use it.
