"""EDID helpers for the Cam Link 4K Rev.2. Pure functions, no device access.

The tool only works with the EDID layout that this device ships with:
256 bytes, EDID 1.3, identity "EGA 0x0066", one CTA-861 extension, an
unused display descriptor in slot 2 and a single range-limits descriptor.
Anything else is rejected instead of guessed.
"""
from __future__ import annotations

import hashlib
from dataclasses import dataclass
from typing import List, Optional, Tuple

EDID_SIZE = 256
HEADER = bytes.fromhex("00ffffffffffff00")
# Manufacturer "EGA" + product code 0x0066. This is the identity inside the
# EDID data (the same for several Cam Link 4K revisions); it is NOT the USB ID.
IDENTITY = bytes.fromhex("14e16600")
EDID_VERSION = bytes.fromhex("0103")
DESCRIPTOR_OFFSETS = (54, 72, 90, 108)
SLOT2 = 72  # second 18-byte descriptor: unused in the factory EDID
EMPTY_DESCRIPTOR = bytes.fromhex("0000001000") + bytes(13)  # "dummy" descriptor, tag 0x10
RECEIVER_MAX_PIXEL_CLOCK_KHZ = 300_000  # declared by the factory EDID (range limits + HDMI block)

# The factory EDID contains no per-unit serial number (bytes 12-15 are zero),
# so these hashes are the same for every unit with the factory EDID.
FACTORY_SHA256 = "013d14fbdc69c143d68103d94172bff342f89c0ba461bbd4bc3de2fa9960d735"
FACTORY_WITH_QHD60_SHA256 = "b6d74bd55e58628d1b16a360753a37aa7abd4ffe38a8feb254144db0406f1f9b"


class EdidError(ValueError):
    """The EDID cannot be used safely."""


@dataclass(frozen=True)
class Timing:
    pixel_clock_khz: int
    h_active: int
    h_blank: int
    h_front: int
    h_sync: int
    v_active: int
    v_blank: int
    v_front: int
    v_sync: int
    width_mm: int
    height_mm: int
    flags: int

    @property
    def h_total(self) -> int:
        return self.h_active + self.h_blank

    @property
    def v_total(self) -> int:
        return self.v_active + self.v_blank

    @property
    def refresh_hz(self) -> float:
        return self.pixel_clock_khz * 1000 / (self.h_total * self.v_total)

    @property
    def h_freq_khz(self) -> float:
        return self.pixel_clock_khz / self.h_total

    @property
    def interlaced(self) -> bool:
        return bool(self.flags & 0x80)

    def describe(self) -> str:
        sync = ""
        if (self.flags >> 3) & 3 == 3:  # digital separate sync
            sync = ", sync H{}/V{}".format("+" if self.flags & 2 else "-", "+" if self.flags & 4 else "-")
        return "{}x{}{} @ {:.3f} Hz, {:.2f} MHz pixel clock{}".format(
            self.h_active, self.v_active, "i" if self.interlaced else "",
            self.refresh_hz, self.pixel_clock_khz / 1000, sync)


# 2560x1440 @ 59.95 Hz, CVT reduced-blanking totals 2720x1481, 241.50 MHz, H-/V-.
# Byte-identical to the descriptor verified with a PS5 on real hardware; the
# timing values come from the PS5-tested EverLive v1.3.0 profile (see README).
QHD60 = Timing(pixel_clock_khz=241_500, h_active=2560, h_blank=160, h_front=48, h_sync=32,
               v_active=1440, v_blank=41, v_front=3, v_sync=5,
               width_mm=597, height_mm=336, flags=0x18)


def encode_dtd(t: Timing) -> bytes:
    """Encode an 18-byte EDID detailed timing descriptor."""
    limits = [(t.pixel_clock_khz // 10, 1, 0xFFFF), (t.h_active, 1, 0xFFF), (t.h_blank, 1, 0xFFF),
              (t.v_active, 1, 0xFFF), (t.v_blank, 1, 0xFFF), (t.h_front, 0, 0x3FF),
              (t.h_sync, 0, 0x3FF), (t.v_front, 0, 0x3F), (t.v_sync, 0, 0x3F),
              (t.width_mm, 0, 0xFFF), (t.height_mm, 0, 0xFFF), (t.flags, 0, 0xFF)]
    if t.pixel_clock_khz % 10 or any(not lo <= v <= hi for v, lo, hi in limits):
        raise EdidError("Timing value out of range for a detailed timing descriptor")
    pc = t.pixel_clock_khz // 10
    return bytes([
        pc & 0xFF, pc >> 8,
        t.h_active & 0xFF, t.h_blank & 0xFF, (t.h_active >> 8) << 4 | t.h_blank >> 8,
        t.v_active & 0xFF, t.v_blank & 0xFF, (t.v_active >> 8) << 4 | t.v_blank >> 8,
        t.h_front & 0xFF, t.h_sync & 0xFF, (t.v_front & 0xF) << 4 | (t.v_sync & 0xF),
        (t.h_front >> 8) << 6 | (t.h_sync >> 8) << 4 | (t.v_front >> 4) << 2 | t.v_sync >> 4,
        t.width_mm & 0xFF, t.height_mm & 0xFF, (t.width_mm >> 8) << 4 | t.height_mm >> 8,
        0, 0, t.flags,
    ])


def decode_dtd(d: bytes) -> Optional[Timing]:
    """Decode an 18-byte descriptor; None if it is a display descriptor, not a timing."""
    if len(d) != 18:
        raise EdidError("A descriptor must be 18 bytes")
    pc = d[0] | d[1] << 8
    if pc == 0:
        return None
    return Timing(
        pixel_clock_khz=pc * 10,
        h_active=d[2] | (d[4] >> 4) << 8, h_blank=d[3] | (d[4] & 0xF) << 8,
        v_active=d[5] | (d[7] >> 4) << 8, v_blank=d[6] | (d[7] & 0xF) << 8,
        h_front=d[8] | (d[11] >> 6) << 8, h_sync=d[9] | ((d[11] >> 4) & 3) << 8,
        v_front=(d[10] >> 4) | ((d[11] >> 2) & 3) << 4, v_sync=(d[10] & 0xF) | (d[11] & 3) << 4,
        width_mm=d[12] | (d[14] >> 4) << 8, height_mm=d[13] | (d[14] & 0xF) << 8,
        flags=d[17])


QHD60_DTD = encode_dtd(QHD60)


@dataclass(frozen=True)
class RangeLimits:
    v_min_hz: int
    v_max_hz: int
    h_min_khz: int
    h_max_khz: int
    max_pixel_clock_khz: int


def sha256(data: bytes) -> str:
    return hashlib.sha256(bytes(data)).hexdigest()


def block_checksum_ok(e: bytes, block: int) -> bool:
    return sum(e[block * 128:(block + 1) * 128]) % 256 == 0


def _fix_block0_checksum(buf: bytearray) -> None:
    buf[127] = -sum(buf[:127]) % 256


def changed_offsets(a: bytes, b: bytes) -> List[int]:
    return [i for i in range(min(len(a), len(b))) if a[i] != b[i]]


def range_limits(e: bytes) -> RangeLimits:
    found = [e[o:o + 18] for o in DESCRIPTOR_OFFSETS if e[o:o + 5] == bytes.fromhex("000000fd00")]
    if len(found) != 1:
        raise EdidError("Expected exactly one EDID 1.3 range-limits descriptor")
    d = found[0]
    return RangeLimits(d[5], d[6], d[7], d[8], d[9] * 10_000)


def cta_data_blocks(e: bytes) -> List[Tuple[int, bytes]]:
    """Return (tag, payload) for each CTA-861 data block in the extension."""
    dtd_start = e[130]
    if not 4 <= dtd_start <= 127:
        raise EdidError("Unsupported CTA extension layout")
    blocks, pos, end = [], 132, 128 + dtd_start
    while pos < end:
        tag, count = e[pos] >> 5, e[pos] & 31
        if pos + 1 + count > end:
            raise EdidError("CTA data block runs past its declared end")
        blocks.append((tag, bytes(e[pos + 1:pos + 1 + count])))
        pos += 1 + count
    return blocks


def cta_timings(e: bytes) -> List[Timing]:
    out, pos = [], 128 + e[130]
    while pos + 18 <= 255:
        t = decode_dtd(e[pos:pos + 18])
        if t is None:
            break
        out.append(t)
        pos += 18
    return out


def hdmi_max_tmds_khz(e: bytes) -> Optional[int]:
    for tag, payload in cta_data_blocks(e):
        if tag == 3 and payload[:3] == bytes.fromhex("030c00"):
            return payload[6] * 5_000 if len(payload) >= 7 and payload[6] else None
    return None


def _has_hdmi_block(e: bytes) -> bool:
    return any(tag == 3 and p[:3] == bytes.fromhex("030c00") for tag, p in cta_data_blocks(e))


def problems(e: bytes) -> List[str]:
    """Every reason why this EDID must not be written to the card. Empty = OK."""
    e = bytes(e)
    if len(e) != EDID_SIZE:
        return ["size is {} bytes, expected 256".format(len(e))]
    out = []
    if e[:8] != HEADER:
        out.append("invalid EDID header")
    for block in (0, 1):
        if not block_checksum_ok(e, block):
            out.append("checksum of block {} is wrong".format(block))
    if e[8:12] != IDENTITY:
        out.append("EDID identity is not 'EGA 0x0066' (not a Cam Link 4K EDID)")
    if e[18:20] != EDID_VERSION:
        out.append("EDID version is not 1.3")
    if e[126] != 1 or e[128:130] != bytes([2, 3]):
        out.append("expected exactly one CTA-861 revision 3 extension block")
    if out:
        return out
    if decode_dtd(e[54:72]) is None:
        out.append("the first descriptor (preferred timing) is missing")
    try:
        limits = range_limits(e)
        cta_data_blocks(e)
        if not _has_hdmi_block(e):
            out.append("HDMI vendor-specific data block is missing")
        tmds = hdmi_max_tmds_khz(e)
    except EdidError as err:
        return out + [str(err)]
    ceiling = min(limits.max_pixel_clock_khz, tmds or RECEIVER_MAX_PIXEL_CLOCK_KHZ,
                  RECEIVER_MAX_PIXEL_CLOCK_KHZ)
    timings = [t for t in (decode_dtd(e[o:o + 18]) for o in DESCRIPTOR_OFFSETS) if t] + cta_timings(e)
    for t in timings:
        if t.h_blank == 0 or t.v_blank == 0 or t.h_front + t.h_sync > t.h_blank or t.v_front + t.v_sync > t.v_blank:
            out.append("timing {} has an impossible blanking layout".format(t.describe()))
        elif t.pixel_clock_khz > ceiling:
            out.append("timing {} exceeds the {} MHz limit of the receiver".format(t.describe(), ceiling // 1000))
        elif not (limits.v_min_hz - 0.5 <= t.refresh_hz <= limits.v_max_hz + 0.5
                  and limits.h_min_khz - 0.5 <= t.h_freq_khz <= limits.h_max_khz + 0.5):
            out.append("timing {} is outside the declared range limits".format(t.describe()))
    return out


def check(e: bytes) -> None:
    found = problems(e)
    if found:
        raise EdidError("; ".join(found))


FACTORY_LAYOUT, QHD60_PRESENT, UNKNOWN = "factory-layout", "qhd60", "unknown"


def classify(e: bytes) -> str:
    """factory-layout: slot 2 unused; qhd60: this tool's mode present; unknown: anything else."""
    if problems(e):
        return UNKNOWN
    slot = bytes(e[SLOT2:SLOT2 + 18])
    if slot == EMPTY_DESCRIPTOR:
        return FACTORY_LAYOUT
    if slot == QHD60_DTD:
        return QHD60_PRESENT
    return UNKNOWN


def state_text(e: bytes) -> str:
    state = classify(e)
    digest = sha256(e)
    if state == FACTORY_LAYOUT:
        text = "no 1440p mode (slot 2 unused)"
        if digest == FACTORY_SHA256:
            text += ", identical to the factory EDID"
    elif state == QHD60_PRESENT:
        text = "1440p60 mode present ({})".format(QHD60.describe())
        if digest == FACTORY_WITH_QHD60_SHA256:
            text += ", identical to factory EDID + this tool's change"
    elif problems(e):
        text = "INVALID or unrecognised EDID"
    else:
        text = "valid Cam Link EDID with a different custom descriptor in slot 2"
    return text


def _verify_change(old: bytes, new: bytes) -> bytes:
    allowed = set(range(SLOT2, SLOT2 + 18)) | {127}
    if not set(changed_offsets(old, new)) <= allowed:
        raise EdidError("Internal safety check failed: change outside slot 2 and its checksum")
    check(new)
    return bytes(new)


def add_qhd60(e: bytes) -> bytes:
    """Put the 1440p60 descriptor into the unused slot 2. Nothing else changes."""
    check(e)
    state = classify(e)
    if state == QHD60_PRESENT:
        return bytes(e)
    if state != FACTORY_LAYOUT:
        raise EdidError("Slot 2 already holds a different descriptor; refusing to overwrite it")
    new = bytearray(e)
    new[SLOT2:SLOT2 + 18] = QHD60_DTD
    _fix_block0_checksum(new)
    return _verify_change(e, new)


def remove_qhd60(e: bytes) -> bytes:
    """Exact inverse of add_qhd60: slot 2 goes back to the factory 'unused' descriptor."""
    check(e)
    state = classify(e)
    if state == FACTORY_LAYOUT:
        return bytes(e)
    if state != QHD60_PRESENT:
        raise EdidError("Slot 2 does not hold this tool's 1440p60 descriptor; use 'restore' instead")
    new = bytearray(e)
    new[SLOT2:SLOT2 + 18] = EMPTY_DESCRIPTOR
    _fix_block0_checksum(new)
    return _verify_change(e, new)


_VIC = {1: "640x480p60", 2: "720x480p60 4:3", 3: "720x480p60 16:9", 4: "1280x720p60",
        5: "1920x1080i60", 16: "1920x1080p60", 17: "720x576p50 4:3", 18: "720x576p50 16:9",
        19: "1280x720p50", 20: "1920x1080i50", 31: "1920x1080p50", 32: "1920x1080p24",
        33: "1920x1080p25", 34: "1920x1080p30", 60: "1280x720p24", 61: "1280x720p25",
        62: "1280x720p30", 63: "1920x1080p120", 64: "1920x1080p100", 93: "3840x2160p24",
        94: "3840x2160p25", 95: "3840x2160p30", 97: "3840x2160p60"}


def _vic_mode(name: str) -> Tuple[int, int, int, bool]:
    size, rest = name.split(" ")[0].split("x")[0], name.split(" ")[0].split("x")[1]
    interlaced = "i" in rest
    height, rate = rest.replace("i", "p").split("p")
    return int(size), int(height), int(rate), interlaced


@dataclass(frozen=True)
class Mode:
    width: int
    height: int
    refresh_hz: int
    interlaced: bool
    preferred: bool = False


def offered_modes(e: bytes) -> List[Mode]:
    """Video modes a source sees: the detailed timings plus the CTA-861 video codes.

    (PC-only standard/established timings are left out on purpose.)
    """
    e = bytes(e)
    if len(e) != EDID_SIZE or e[:8] != HEADER:
        return []
    found = {}
    for n, o in enumerate(DESCRIPTOR_OFFSETS):
        t = decode_dtd(e[o:o + 18])
        if t:
            m = Mode(t.h_active, t.v_active * (2 if t.interlaced else 1), round(t.refresh_hz), t.interlaced, n == 0)
            found[(m.width, m.height, m.refresh_hz, m.interlaced)] = m
    try:
        blocks = cta_data_blocks(e) if e[126] and e[128] == 2 else []
        timings = cta_timings(e) if blocks else []
    except EdidError:
        blocks, timings = [], []
    for tag, payload in blocks:
        if tag != 2:
            continue
        for b in payload:
            vic = (b & 0x7F) if 129 <= b <= 192 else b
            if vic in _VIC:
                w, h, r, i = _vic_mode(_VIC[vic])
                found.setdefault((w, h, r, i), Mode(w, h, r, i))
    for t in timings:
        found.setdefault((t.h_active, t.v_active, round(t.refresh_hz), t.interlaced),
                         Mode(t.h_active, t.v_active, round(t.refresh_hz), t.interlaced))
    return sorted(found.values(), key=lambda m: (-m.width * m.height, m.interlaced, -m.refresh_hz))


def describe(e: bytes) -> List[str]:
    """Human-readable summary of the modes and fields that matter here."""
    e = bytes(e)
    lines = ["SHA-256: " + sha256(e)]
    if len(e) != EDID_SIZE or e[:8] != HEADER:
        return lines + ["Not a 256-byte EDID"]
    lines.append("Identity: {}{}{} product 0x{:04X}, week {}, year {}, EDID {}.{}".format(
        chr(64 + (e[8] >> 2 & 31)), chr(64 + ((e[8] & 3) << 3 | e[9] >> 5)), chr(64 + (e[9] & 31)),
        e[10] | e[11] << 8, e[16], 1990 + e[17], e[18], e[19]))
    lines.append("Checksums: block 0 {}, block 1 {}".format(
        "OK" if block_checksum_ok(e, 0) else "WRONG", "OK" if block_checksum_ok(e, 1) else "WRONG"))
    for n, o in enumerate(DESCRIPTOR_OFFSETS, 1):
        d = e[o:o + 18]
        t = decode_dtd(d)
        if t:
            text = "timing " + t.describe() + (" (preferred)" if n == 1 else "")
        elif d[3] == 0xFC:
            text = "name '{}'".format(d[5:18].split(b"\n")[0].decode("ascii", "replace").strip())
        elif d[3] == 0xFD:
            text = "range limits V {}-{} Hz, H {}-{} kHz, max {} MHz".format(d[5], d[6], d[7], d[8], d[9] * 10)
        elif d == EMPTY_DESCRIPTOR:
            text = "unused"
        else:
            text = "descriptor tag 0x{:02X}".format(d[3])
        lines.append("Descriptor {}: {}".format(n, text))
    if e[126] and e[128] == 2:
        try:
            for tag, p in cta_data_blocks(e):
                if tag == 2:
                    vics = [(b & 0x7F) if 129 <= b <= 192 else b for b in p]
                    lines.append("CTA video: " + ", ".join(_VIC.get(v, "VIC{}".format(v)) for v in vics))
                elif tag == 1:
                    lines.append("CTA audio: {} format block(s)".format(len(p) // 3))
            tmds = hdmi_max_tmds_khz(e)
            if tmds:
                lines.append("HDMI max TMDS clock: {} MHz".format(tmds // 1000))
            for t in cta_timings(e):
                lines.append("CTA timing: " + t.describe())
        except EdidError as err:
            lines.append("CTA extension: " + str(err))
    return lines
