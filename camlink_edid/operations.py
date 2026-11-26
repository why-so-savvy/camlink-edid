"""Logic shared by every user interface: planning, backups, writing and verification.

The command line (cli.py) and the window (gui.py) are thin layers over this
module, so both run exactly the same safety checks.
"""
from __future__ import annotations

import json
import os
import sys
import time
from dataclasses import dataclass, field
from datetime import datetime
from pathlib import Path
from typing import Callable, List, Optional

from . import __version__, edid, protocol

DEFAULT_BACKUP_DIR = Path.home() / "camlink-edid-backups"


class Refused(Exception):
    """Stop before writing anything: the card is unchanged."""


class VerificationFailed(Exception):
    """The write went through but the card does not report the intended EDID."""

    def __init__(self, after: Optional[bytes], detail: str):
        self.after = after
        super().__init__(detail)


@dataclass
class Env:
    """Everything that touches the outside world, replaceable in tests."""
    open_card: Callable = None
    usb_ids: Callable = None
    wait_for_replug: Optional[Callable] = None
    input: Callable[[str], str] = input
    sleep: Callable[[float], None] = time.sleep
    say: Callable[[str], None] = field(default=lambda text="": print(text, flush=True))


def default_env() -> Env:
    env = Env()
    if sys.platform == "win32":
        from . import winhid

        env.open_card = winhid.open_card
        env.usb_ids = winhid.usb_ids
        env.wait_for_replug = lambda say, cancel=None: winhid.wait_for_replug(say, cancel=cancel)
    else:
        def unavailable(*_args, **_kwargs):
            raise Refused("Talking to the card is only implemented for Windows. "
                          "Offline commands (decode) work on any system.")
        env.open_card = env.usb_ids = unavailable
    return env


def device_errors() -> tuple:
    """Exceptions that mean 'the card could not be reached'."""
    if sys.platform == "win32":
        from .winhid import DeviceError
        return (DeviceError, protocol.ProtocolError, OSError)
    return (protocol.ProtocolError, OSError)


# ---------------------------------------------------------------- planning

@dataclass(frozen=True)
class Plan:
    label: str          # "add", "remove" or "restore"
    current: bytes      # what the card holds now
    target: bytes       # what will be written

    @property
    def nothing_to_do(self) -> bool:
        return self.current == self.target

    @property
    def changed(self) -> List[int]:
        return edid.changed_offsets(self.current, self.target)

    @property
    def title(self) -> str:
        return {"add": "Add 1440p60", "remove": "Remove 1440p60", "restore": "Restore backup"}[self.label]


def _finish(label: str, current: bytes, target: bytes) -> Plan:
    found = edid.problems(target)
    if found:  # defence in depth; the planners already check this
        raise Refused("The planned EDID failed validation: " + "; ".join(found))
    return Plan(label, bytes(current), bytes(target))


def plan_add(current: bytes) -> Plan:
    found = edid.problems(current)
    if found:
        raise Refused("The card's current EDID is not one this tool recognises ({}). If a write was "
                      "interrupted, unplug the USB cable for 5 seconds and try again; otherwise "
                      "restore a backup.".format("; ".join(found)))
    try:
        return _finish("add", current, edid.add_qhd60(current))
    except edid.EdidError as err:
        raise Refused(str(err)) from err


def plan_remove(current: bytes) -> Plan:
    if edid.problems(current):
        raise Refused("The card's current EDID is not one this tool recognises; restore a backup instead.")
    try:
        return _finish("remove", current, edid.remove_qhd60(current))
    except edid.EdidError as err:
        raise Refused(str(err)) from err


def load_restore_file(path) -> bytes:
    p = Path(path)
    if not p.is_file() or p.stat().st_size != edid.EDID_SIZE:
        raise Refused("{} is not a 256-byte EDID file".format(path))
    data = p.read_bytes()
    found = edid.problems(data)
    if found:
        raise Refused("{} cannot be written safely: {}".format(path, "; ".join(found)))
    return data


def plan_restore(current: bytes, data: bytes) -> Plan:
    # The current EDID may be broken; that is exactly when a restore is needed.
    return _finish("restore", current, data)


# ---------------------------------------------------------------- backups

def save_backup(data: bytes, directory: Path, label: str) -> Path:
    """Store a copy that is never overwritten, then read it back from disk to verify it."""
    directory = Path(directory)
    directory.mkdir(parents=True, exist_ok=True)
    stamp = datetime.now().strftime("%Y%m%d-%H%M%S")
    for n in range(1, 100):
        path = directory / "camlink-edid-{}-{}{}.bin".format(stamp, label, "" if n == 1 else "-{}".format(n))
        try:
            with open(path, "xb") as f:
                f.write(data)
                f.flush()
                os.fsync(f.fileno())
            break
        except FileExistsError:
            continue
    else:
        raise Refused("Could not create a unique backup file name in {}".format(directory))
    if path.read_bytes() != bytes(data):
        raise Refused("The backup file {} could not be verified on disk".format(path))
    meta = {"tool": "camlink-edid", "version": __version__, "created": datetime.now().isoformat(timespec="seconds"),
            "usb_id": "0FD9:007B", "label": label, "sha256": edid.sha256(data),
            "state": edid.classify(data), "problems": edid.problems(data)}
    path.with_suffix(".json").write_text(json.dumps(meta, indent=2) + "\n", encoding="utf-8")
    return path


def matching_backups(data: bytes, directory: Path) -> List[str]:
    directory = Path(directory)
    if not directory.is_dir():
        return []
    digest = edid.sha256(data)
    return sorted(p.name for p in directory.glob("*.bin")
                  if p.stat().st_size == edid.EDID_SIZE and edid.sha256(p.read_bytes()) == digest)


# ---------------------------------------------------------------- writing

def write_and_verify(card: protocol.Card, plan: Plan,
                     progress: Optional[Callable[[int], None]] = None) -> None:
    """Write chunk by chunk (stops on the first anomaly), then compare a full read-back.

    Raises protocol.WriteAborted or VerificationFailed. The caller must already
    hold a verified backup of plan.current.
    """
    card.write_edid(plan.target, progress)
    card.sleep(protocol.COMMIT_SETTLE_S)
    try:
        after = card.read_edid_stable()
    except device_errors() as err:
        raise VerificationFailed(None, "the write finished but the final read-back failed: {}".format(err)) from err
    if after != plan.target:
        raise VerificationFailed(after, "the card reports a different EDID than the one written (offsets {})"
                                 .format(ranges(edid.changed_offsets(after, plan.target))))


def aborted_explanation(err: protocol.WriteAborted) -> str:
    if err.may_be_stored:
        return "The last chunk was involved, so the card may have stored the new EDID."
    return ("The tool stopped before the last chunk. On the analysed firmware the card stores the "
            "EDID only after the last chunk, so the stored EDID should be unchanged.")


def recovery_steps(backup: Path, command: str = "python camlink-edid.py") -> List[str]:
    return ["Do not retry the write repeatedly.",
            "1. Unplug the Cam Link USB cable for 5 seconds and plug it back in.",
            "2. Check the state again ('{} status' or Refresh in the window).".format(command),
            "3. If the state is not what you expect, restore your backup:",
            "   {}".format(backup)]


def ranges(offsets: List[int]) -> str:
    if not offsets:
        return "none"
    parts, start, prev = [], offsets[0], offsets[0]
    for o in list(offsets[1:]) + [None]:
        if o is not None and o == prev + 1:
            prev = o
            continue
        parts.append(str(start) if start == prev else "{}-{}".format(start, prev))
        if o is not None:
            start = prev = o
    return ", ".join(parts)
