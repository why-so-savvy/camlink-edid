"""Windows transport for the Cam Link 4K Rev.2 control interface (HID, interface 7).

Uses only Windows system DLLs through ctypes. Listing devices sends nothing
to any device. The control interface is opened exclusively, so Camera Hub or
another program cannot talk to the card in the middle of our sequence.
"""
from __future__ import annotations

import ctypes
import re
import sys
import time
import uuid
from ctypes import wintypes
from typing import List, Tuple

from .devices import HID_INTERFACE

if sys.platform != "win32":  # pragma: no cover - imported lazily by the CLI
    raise ImportError("The device transport is only available on Windows")

GUID_DEVINTERFACE_HID = "4d1e55b2-f16f-11cf-88cb-001111000030"
GUID_DEVINTERFACE_USB_DEVICE = "a5dcbf10-6530-11d2-901f-00c04fb951ed"
REPORT_ID_OUT = 0x06
REPORT_ID_IN = 0x05
OUT_LENGTH = 255    # report 0x06: 254 data bytes + report ID, as used by the vendor software
IN_LENGTH = 2047    # GET_REPORT length used by the vendor software; 2048 is rejected by the card
USAGE_PAGE = 0xFFA0
GENERIC_READ_WRITE = 0x80000000 | 0x40000000
OPEN_EXISTING = 3
ERROR_ACCESS_DENIED = 5
ERROR_SHARING_VIOLATION = 32
CR_SUCCESS = 0
CR_BUFFER_SMALL = 0x1A
HIDP_STATUS_SUCCESS = 0x00110000

_hid = ctypes.WinDLL("hid.dll", use_last_error=True)
_k32 = ctypes.WinDLL("kernel32.dll", use_last_error=True)
_cfg = ctypes.WinDLL("cfgmgr32.dll")

_k32.CreateFileW.restype = wintypes.HANDLE
_k32.CreateFileW.argtypes = [wintypes.LPCWSTR, wintypes.DWORD, wintypes.DWORD, ctypes.c_void_p,
                             wintypes.DWORD, wintypes.DWORD, wintypes.HANDLE]
_k32.CloseHandle.argtypes = [wintypes.HANDLE]
_hid.HidD_SetOutputReport.restype = wintypes.BOOLEAN
_hid.HidD_SetOutputReport.argtypes = [wintypes.HANDLE, ctypes.c_void_p, wintypes.ULONG]
_hid.HidD_GetInputReport.restype = wintypes.BOOLEAN
_hid.HidD_GetInputReport.argtypes = [wintypes.HANDLE, ctypes.c_void_p, wintypes.ULONG]
_hid.HidD_GetPreparsedData.restype = wintypes.BOOLEAN
_hid.HidD_GetPreparsedData.argtypes = [wintypes.HANDLE, ctypes.POINTER(ctypes.c_void_p)]
_hid.HidD_FreePreparsedData.argtypes = [ctypes.c_void_p]
_hid.HidP_GetCaps.restype = ctypes.c_long
_INVALID_HANDLE = ctypes.c_void_p(-1).value


class DeviceError(Exception):
    """The card cannot be opened safely. Nothing was sent to it."""


class _HIDP_CAPS(ctypes.Structure):
    _fields_ = [("Usage", wintypes.USHORT), ("UsagePage", wintypes.USHORT),
                ("InputReportByteLength", wintypes.USHORT), ("OutputReportByteLength", wintypes.USHORT),
                ("FeatureReportByteLength", wintypes.USHORT), ("Reserved", wintypes.USHORT * 17),
                ("Counts", wintypes.USHORT * 10)]


def _guid(text: str):
    return (ctypes.c_ubyte * 16).from_buffer_copy(uuid.UUID(text).bytes_le)


def _interface_paths(guid_text: str) -> List[str]:
    guid = _guid(guid_text)
    for _ in range(5):  # the list can grow between the two calls
        size = wintypes.ULONG()
        if _cfg.CM_Get_Device_Interface_List_SizeW(ctypes.byref(size), guid, None, 0) != CR_SUCCESS:
            return []
        buf = ctypes.create_unicode_buffer(size.value)
        result = _cfg.CM_Get_Device_Interface_ListW(guid, None, buf, size.value, 0)
        if result == CR_SUCCESS:
            return [p for p in ctypes.wstring_at(ctypes.addressof(buf), size.value).split("\0") if p]
        if result != CR_BUFFER_SMALL:
            return []
    return []


def usb_ids() -> List[Tuple[int, int]]:
    """VID/PID of connected USB devices. Paths (which contain serial numbers) are not returned."""
    ids = set()
    for path in _interface_paths(GUID_DEVINTERFACE_USB_DEVICE):
        m = re.search(r"vid_([0-9a-f]{4})&pid_([0-9a-f]{4})", path, re.I)
        if m:
            ids.add((int(m.group(1), 16), int(m.group(2), 16)))
    return sorted(ids)


def _control_paths() -> List[str]:
    return [p for p in _interface_paths(GUID_DEVINTERFACE_HID) if HID_INTERFACE in p.lower()]


def control_interface_present() -> bool:
    return bool(_control_paths())


class HidTransport:
    def __init__(self, path: str):
        handle = _k32.CreateFileW(path, GENERIC_READ_WRITE, 0, None, OPEN_EXISTING, 0, None)
        if handle in (None, _INVALID_HANDLE):
            error = ctypes.get_last_error()
            if error == ERROR_SHARING_VIOLATION:
                raise DeviceError("Another program is using the Cam Link control interface. Close Camera Hub, "
                                  "Elgato Studio and 4K Capture Utility (also from the system tray) and retry.")
            if error == ERROR_ACCESS_DENIED:
                raise DeviceError("Windows denied access to the Cam Link control interface (error 5).")
            raise DeviceError("Cannot open the Cam Link control interface (Windows error {}).".format(error))
        self.handle = handle
        try:
            self._check_caps()
        except Exception:
            self.close()
            raise

    def _check_caps(self) -> None:
        pre = ctypes.c_void_p()
        if not _hid.HidD_GetPreparsedData(self.handle, ctypes.byref(pre)):
            raise DeviceError("Cannot read the HID description of the control interface.")
        try:
            caps = _HIDP_CAPS()
            status = _hid.HidP_GetCaps(pre, ctypes.byref(caps)) & 0xFFFFFFFF
        finally:
            _hid.HidD_FreePreparsedData(pre)
        if status != HIDP_STATUS_SUCCESS or caps.UsagePage != USAGE_PAGE:
            raise DeviceError("Unexpected HID interface (usage page 0x{:04X}); refusing to talk to it."
                              .format(caps.UsagePage))

    def exchange(self, payload: bytes) -> bytes:
        payload = bytes(payload)
        if len(payload) > OUT_LENGTH - 1:
            raise ValueError("payload too long")
        out = (ctypes.c_ubyte * OUT_LENGTH)(REPORT_ID_OUT, *payload)
        if not _hid.HidD_SetOutputReport(self.handle, out, OUT_LENGTH):
            raise OSError("sending the HID report failed (Windows error {})".format(ctypes.get_last_error()))
        reply = (ctypes.c_ubyte * IN_LENGTH)(REPORT_ID_IN)
        if not _hid.HidD_GetInputReport(self.handle, reply, IN_LENGTH):
            raise OSError("reading the HID report failed (Windows error {})".format(ctypes.get_last_error()))
        return bytes(reply)

    def close(self) -> None:
        if getattr(self, "handle", None) not in (None, _INVALID_HANDLE):
            _k32.CloseHandle(self.handle)
            self.handle = None

    def __enter__(self):
        return self

    def __exit__(self, *exc):
        self.close()


def open_card() -> HidTransport:
    paths = _control_paths()
    if not paths:
        raise DeviceError("No Cam Link 4K Rev.2 (USB 0FD9:007B) control interface found. "
                          "Run 'detect' to see what is connected.")
    if len(paths) > 1:
        raise DeviceError("More than one Cam Link 4K Rev.2 is connected. Connect only the one to change.")
    return HidTransport(paths[0])


def wait_for_replug(say, sleep=time.sleep, timeout_s: float = 180.0) -> bool:
    """Wait until the card disappears and comes back. Returns False on timeout."""
    deadline = time.monotonic() + timeout_s
    while control_interface_present():
        if time.monotonic() > deadline:
            return False
        sleep(0.5)
    say("  Unplugged. Wait 5 seconds, then plug it back in.")
    while not control_interface_present():
        if time.monotonic() > deadline:
            return False
        sleep(0.5)
    say("  Plugged in. Waiting for the card to start...")
    sleep(3.0)
    return True
