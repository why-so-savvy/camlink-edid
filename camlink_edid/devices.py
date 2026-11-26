"""Known Cam Link USB IDs. The tool decides by USB ID only, never by product name.

Source: device-capability manifests shipped with Elgato 4K Capture Utility
1.7.16 and Elgato Studio 2.0. Note that Elgato Studio calls the newer
Rev.4 (0FD9:00F4) "Cam Link 4K MK.2" and the supported 0FD9:007B
"Rev.2, previous Cam Link 4K MK.2": a box labelled "MK.2" is not enough.
"""
from __future__ import annotations

from dataclasses import dataclass
from typing import Optional

ELGATO_VID = 0x0FD9
SUPPORTED_PID = 0x007B
HID_INTERFACE = "vid_0fd9&pid_007b&mi_07"

SUPPORTED, USB2_MODE, UNSUPPORTED, VENDOR_FEATURE = "supported", "usb2", "unsupported", "vendor"


@dataclass(frozen=True)
class KnownDevice:
    vid: int
    pid: int
    name: str
    support: str
    note: str

    @property
    def usb_id(self) -> str:
        return "{:04X}:{:04X}".format(self.vid, self.pid)


_DIFFERENT = "different hardware; its protocol is unknown to this tool"
_USB2 = "running in USB 2 mode; connect it to a USB 3 port"

KNOWN = [
    KnownDevice(0x0FD9, 0x0061, "Cam Link (HD)", UNSUPPORTED, _DIFFERENT),
    KnownDevice(0x0FD9, 0x0062, "Cam Link (HD), USB 2 mode", UNSUPPORTED, _DIFFERENT),
    KnownDevice(0x0FD9, 0x0066, "Cam Link 4K, 1st generation", UNSUPPORTED, _DIFFERENT),
    KnownDevice(0x0FD9, 0x0067, "Cam Link 4K, 1st generation, USB 2 mode", UNSUPPORTED, _DIFFERENT),
    KnownDevice(0x0FD9, 0x007B, "Cam Link 4K Rev.2 (sold as \"MK.2\")", SUPPORTED, "supported"),
    KnownDevice(0x0FD9, 0x0085, "Cam Link 4K Rev.2, USB 2 mode", USB2_MODE, _USB2),
    KnownDevice(0x0FD9, 0x00A1, "Cam Link 4K Rev.3", UNSUPPORTED, _DIFFERENT),
    KnownDevice(0x0FD9, 0x00A2, "Cam Link 4K Rev.3, USB 2 mode", UNSUPPORTED, _DIFFERENT),
    KnownDevice(0x0FD9, 0x00F4, "Cam Link 4K Rev.4 (newer \"MK.2\")", UNSUPPORTED, _DIFFERENT),
    KnownDevice(0x0FD9, 0x00F5, "Cam Link 4K Rev.4, USB 2 mode", UNSUPPORTED, _DIFFERENT),
    KnownDevice(0x1CFA, 0x0011, "Cam Link Pro", VENDOR_FEATURE,
                "Elgato's own software lists custom EDID support for this model"),
]


def lookup(vid: int, pid: int) -> Optional[KnownDevice]:
    for device in KNOWN:
        if device.vid == vid and device.pid == pid:
            return device
    if vid == ELGATO_VID:
        return KnownDevice(vid, pid, "Elgato device (not a Cam Link 4K Rev.2)", UNSUPPORTED,
                           "not supported by this tool")
    return None
