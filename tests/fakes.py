"""Test doubles: a synthetic EDID with the Cam Link layout and a simulated card.

The EDID is generated here (no vendor data). The simulated MCU follows the
behaviour verified on hardware and in the firmware analysis:
  * reads of 0xA0 return the staging buffer;
  * each 8-byte write lands in staging and is echoed as 00 <offset> <d0> <d1>;
  * a malformed frame (e.g. the old wrong header 09 0A) is answered with status 01;
  * when the write pointer reaches byte 256 the staging buffer is committed to
    flash, after a header-only check (bytes 0, 1, 6, 7), like the real MCU;
  * a power cycle (replug) reloads staging from flash.
"""
from __future__ import annotations

from camlink_edid import edid


def factory_like_edid() -> bytes:
    b = bytearray(256)
    b[0:8] = edid.HEADER
    b[8:12] = edid.IDENTITY
    b[16], b[17] = 1, 30                      # week 1, 2020
    b[18:20] = edid.EDID_VERSION
    b[20:25] = bytes([0x80, 0x50, 0x2D, 0x78, 0x0A])
    b[25:35] = bytes.fromhex("ee95a3544c99260f5054")
    b[38:54] = bytes([1, 1] * 8)
    b[54:72] = edid.encode_dtd(edid.Timing(297_000, 3840, 560, 176, 88, 2160, 90, 8, 10, 1600, 900, 0x1E))
    b[72:90] = edid.EMPTY_DESCRIPTOR
    b[90:108] = bytes.fromhex("000000fc00") + b"TEST CAPTURE\n"
    b[108:126] = bytes.fromhex("000000fd0019790c781e000a202020202020")
    b[126] = 1
    b[127] = -sum(b[:127]) % 256
    blocks = (bytes([0x43, 0x10, 0x04, 0x5F])            # video: VIC 16, 4, 95
              + bytes([0x23, 0x09, 0x07, 0x07])          # audio: LPCM
              + bytes([0x83, 0x01, 0x00, 0x00])          # speaker allocation
              + bytes([0x67, 0x03, 0x0C, 0x00, 0x10, 0x00, 0xB8, 0x3C]))  # HDMI VSDB, 300 MHz
    b[128:132] = bytes([0x02, 0x03, 4 + len(blocks), 0xF0])
    b[132:132 + len(blocks)] = blocks
    pos = 132 + len(blocks)
    b[pos:pos + 18] = edid.encode_dtd(edid.Timing(148_500, 1920, 280, 88, 44, 1080, 45, 4, 5, 160, 90, 0x1E))
    b[255] = -sum(b[128:255]) % 256
    return bytes(b)


def with_checksum(data: bytes) -> bytes:
    b = bytearray(data)
    b[127] = -sum(b[:127]) % 256
    b[255] = -sum(b[128:255]) % 256
    return bytes(b)


class FakeCard:
    """Simulated Cam Link 4K Rev.2 control interface (transport + MCU)."""

    def __init__(self, flash: bytes):
        self.flash = bytearray(flash)
        self.staging = bytearray(flash)
        self.commits = 0
        self.frames = []
        self.reject_write_at = None      # offset -> answer status 01
        self.raise_at = None             # offset -> transport error
        self.corrupt_readback_at = None  # offset -> staging differs from what was written
        self.flash_fails = False         # commit happens but the flash keeps old data
        self.after_commit_flip = None    # offset of a byte that changes right after commit
        self.unstable_reads = False

    # transport API -------------------------------------------------------
    def exchange(self, payload: bytes) -> bytes:
        p = bytes(payload)
        self.frames.append(p)
        if len(p) >= 6 and p[1] == 0x07 and p[0] == 6 and p[2] == 0xA0 and p[3] == 1:
            off, n = p[4], p[5]
            data = bytearray(self.staging[off:off + n])
            if self.unstable_reads and off == 0x40:
                data[0] ^= self.reads_toggle()
            return bytes([0]) + bytes(data) + bytes(16)
        if len(p) >= 5 and p[1] == 0x06 and p[2] == 0xA0 and p[0] == 4 + p[3] and p[3] == 9:
            off, data = p[4], p[5:13]
            if off == self.raise_at:
                raise OSError("simulated USB failure")
            if off == self.reject_write_at:
                return bytes([1, 0, 0xFF, 0xFF])
            self.staging[off:off + 8] = data
            if off == self.corrupt_readback_at:
                self.staging[off] ^= 0xFF
            if off + 8 == 256:
                self._commit()
            return bytes([0, off]) + data[:2] + bytes(16)
        return bytes([1, 0, 0xFF, 0xFF])  # unknown or malformed frame, like the real card

    def _commit(self) -> None:
        s = self.staging
        if s[0] == 0 and s[1] == 0xFF and s[6] == 0xFF and s[7] == 0:
            self.commits += 1
            if not self.flash_fails:
                self.flash[:] = s
            if self.after_commit_flip is not None:
                s[self.after_commit_flip] ^= 1

    _toggle = 0

    def reads_toggle(self) -> int:
        self._toggle ^= 1
        return self._toggle

    # helpers -------------------------------------------------------------
    def replug(self) -> None:
        self.staging = bytearray(self.flash)

    @property
    def write_frames(self):
        return [f for f in self.frames if len(f) > 1 and f[1] == 0x06]

    def __enter__(self):
        return self

    def __exit__(self, *exc):
        return False
