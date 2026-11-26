"""HID protocol of the Cam Link 4K Rev.2 (USB 0FD9:007B, interface 7, usage page 0xFFA0).

Pure logic: the transport is injected, so every safety check can be tested
without hardware. Only two frame types exist in this module, both for the
EDID address 0xA0. Nothing else (firmware, modes, other I2C addresses) can be
sent through it.

Frame layout (after HID report ID 0x06, padded to 255 bytes):
  read 8 bytes : 06 07 A0 01 <offset> 08            -> reply: 00 <8 data bytes>
  write 8 bytes: 0D 06 A0 09 <offset> <8 data bytes> -> reply: 00 <offset> <data0> <data1>
                 |  |  |  |
                 |  |  |  +- byte count: 1 offset byte + 8 data bytes
                 |  |  +---- I2C address of the EDID (emulated EEPROM in the MCU)
                 |  +------- command 06 = write (07 = read)
                 +---------- frame length = 4 + byte count

The write sequence mirrors the vendor's own (32 x [write 8 bytes, 10 ms,
read the same 8 bytes back]). Each chunk is checked before the next is sent.
On the analysed firmware (MCU 23.05.09) the card stores the EDID in flash only
when the write pointer reaches byte 256, i.e. after the last chunk, so any
abort before the last chunk leaves the stored EDID untouched.
"""
from __future__ import annotations

import time
from typing import Callable, Optional

EDID_ADDRESS = 0xA0
CMD_WRITE = 0x06
CMD_READ = 0x07
CHUNK = 8
EDID_SIZE = 256
WRITE_SETTLE_S = 0.010   # vendor software waits 10 ms after each chunk
READ_GAP_S = 0.002
COMMIT_SETTLE_S = 0.5    # pause before the final read-back
LAST_CHUNK = EDID_SIZE - CHUNK


class ProtocolError(Exception):
    """The card did not answer as expected. Raised before any write starts, or during reads."""


class WriteAborted(Exception):
    """A write was stopped by a safety check."""

    def __init__(self, offset: int, reason: str):
        self.offset = offset
        self.reason = reason
        # The last chunk triggers the commit to flash, so only then may it have happened.
        self.may_be_stored = offset >= LAST_CHUNK
        super().__init__("write stopped at offset 0x{:02X}: {}".format(offset, reason))


def read_frame(offset: int) -> bytes:
    if not (0 <= offset <= LAST_CHUNK and offset % CHUNK == 0):
        raise ValueError("offset must be a multiple of 8 within the EDID")
    return bytes([0x06, CMD_READ, EDID_ADDRESS, 0x01, offset, CHUNK])


def write_frame(offset: int, data: bytes) -> bytes:
    data = bytes(data)
    if not (0 <= offset <= LAST_CHUNK and offset % CHUNK == 0 and len(data) == CHUNK):
        raise ValueError("a write frame carries exactly 8 bytes at an 8-byte aligned offset")
    count = 1 + len(data)
    return bytes([4 + count, CMD_WRITE, EDID_ADDRESS, count, offset]) + data


class Card:
    """EDID access on one opened card. `transport.exchange(payload) -> reply bytes`."""

    def __init__(self, transport, sleep: Callable[[float], None] = time.sleep):
        self.transport = transport
        self.sleep = sleep

    def read_chunk(self, offset: int) -> bytes:
        reply = bytes(self.transport.exchange(read_frame(offset)))
        if len(reply) < 1 + CHUNK or reply[0] != 0x00:
            raise ProtocolError("unexpected reply to a read at offset 0x{:02X}: {}".format(
                offset, reply[:1 + CHUNK].hex(" ")))
        return reply[1:1 + CHUNK]

    def read_edid(self) -> bytes:
        out = bytearray()
        for offset in range(0, EDID_SIZE, CHUNK):
            out += self.read_chunk(offset)
            self.sleep(READ_GAP_S)
        return bytes(out)

    def read_edid_stable(self) -> bytes:
        """Read twice; refuse to trust the data unless both reads agree."""
        first = self.read_edid()
        second = self.read_edid()
        if first != second:
            raise ProtocolError("two consecutive reads of the EDID differ; the connection is not stable")
        return first

    def write_edid(self, target: bytes, progress: Optional[Callable[[int], None]] = None) -> None:
        target = bytes(target)
        if len(target) != EDID_SIZE:
            raise ValueError("the EDID must be exactly 256 bytes")
        self.read_chunk(0)  # warm-up read, as the vendor software does
        for offset in range(0, EDID_SIZE, CHUNK):
            chunk = target[offset:offset + CHUNK]
            try:
                reply = bytes(self.transport.exchange(write_frame(offset, chunk)))
            except Exception as err:  # transport failure mid-write
                raise WriteAborted(offset, "communication error: {}".format(err)) from err
            expected = bytes([0x00, offset]) + chunk[:2]
            if reply[:4] != expected:
                raise WriteAborted(offset, "the card rejected the chunk (reply {}, expected {})".format(
                    reply[:4].hex(" "), expected.hex(" ")))
            self.sleep(WRITE_SETTLE_S)
            try:
                back = self.read_chunk(offset)
            except Exception as err:
                raise WriteAborted(offset, "could not read the chunk back: {}".format(err)) from err
            if back != chunk:
                raise WriteAborted(offset, "read-back {} differs from written {}".format(
                    back.hex(" "), chunk.hex(" ")))
            if progress:
                progress(offset)
