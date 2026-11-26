"""Command line interface.

Exit codes:
  0  success (or nothing to do)
  1  refused or failed BEFORE anything was written: the card is unchanged
  2  a problem happened during or after a write: follow the printed steps
"""
from __future__ import annotations

import argparse
import contextlib
import json
import os
import signal
import sys
import threading
import time
from dataclasses import dataclass, field
from datetime import datetime
from pathlib import Path
from typing import Callable, List, Optional

from . import __version__, devices, edid, protocol

OK, REFUSED, WRITE_PROBLEM = 0, 1, 2
CONFIRM_WORD = "WRITE"
DEFAULT_BACKUP_DIR = Path.home() / "camlink-edid-backups"


class Refused(Exception):
    """Stop before writing anything."""


@dataclass
class Env:
    """Everything that touches the outside world, replaceable in tests."""
    open_card: Callable = None
    usb_ids: Callable = None
    wait_for_replug: Optional[Callable] = None
    input: Callable[[str], str] = input
    sleep: Callable[[float], None] = time.sleep
    say: Callable[[str], None] = field(default=lambda text="": print(text, flush=True))


def _default_env() -> Env:
    env = Env()
    if sys.platform == "win32":
        from . import winhid

        def open_card():
            return winhid.open_card()

        env.open_card = open_card
        env.usb_ids = winhid.usb_ids
        env.wait_for_replug = lambda say: winhid.wait_for_replug(say)
    else:
        def unavailable(*_):
            raise Refused("Talking to the card is only implemented for Windows. "
                          "Offline commands (decode) work on any system.")
        env.open_card = env.usb_ids = unavailable
    return env


def _device_errors():
    if sys.platform == "win32":
        from .winhid import DeviceError
        return (DeviceError, protocol.ProtocolError, OSError)
    return (protocol.ProtocolError, OSError)


@contextlib.contextmanager
def _defer_interrupts(say):
    """Ctrl+C during the ~1 s write is postponed, so it cannot split the write in two."""
    if threading.current_thread() is not threading.main_thread():
        yield
        return
    pending = []
    names = [n for n in ("SIGINT", "SIGBREAK") if hasattr(signal, n)]
    previous = {n: signal.signal(getattr(signal, n), lambda s, f: pending.append(s)) for n in names}
    try:
        yield
    finally:
        for n, handler in previous.items():
            signal.signal(getattr(signal, n), handler)
        if pending:
            say("(Ctrl+C was postponed until the write finished.)")


def save_backup(data: bytes, directory: Path, label: str) -> Path:
    """Store a copy that is never overwritten, then read it back from disk to verify it."""
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


def _matching_backups(data: bytes, directory: Path) -> List[str]:
    if not directory.is_dir():
        return []
    digest = edid.sha256(data)
    return sorted(p.name for p in directory.glob("*.bin") if p.stat().st_size == 256 and edid.sha256(p.read_bytes()) == digest)


def _print_edid(env: Env, data: bytes) -> None:
    for line in edid.describe(data):
        env.say("  " + line)


# ---------------------------------------------------------------- read-only commands

def cmd_detect(args, env: Env) -> int:
    ids = env.usb_ids()
    found = [(vid, pid, devices.lookup(vid, pid)) for vid, pid in ids]
    found = [f for f in found if f[2] is not None]
    if not found:
        env.say("No Elgato Cam Link device found on USB.")
        return REFUSED
    for vid, pid, info in found:
        env.say("{}  {}  -> {}".format(info.usb_id, info.name, info.note))
    supported = [f for f in found if f[2].support == devices.SUPPORTED]
    if len(supported) == 1:
        env.say("\nNext: python camlink-edid.py status   (read-only)")
        return OK
    if len(supported) > 1:
        env.say("\nMore than one supported card is connected. Connect only the one you want to change.")
    return REFUSED


def _read_current(env: Env, transport) -> bytes:
    card = protocol.Card(transport, sleep=env.sleep)
    return card.read_edid_stable()


def cmd_status(args, env: Env) -> int:
    with env.open_card() as transport:
        data = _read_current(env, transport)
    env.say("Cam Link 4K Rev.2 (USB 0FD9:007B): EDID read twice, both reads identical.")
    env.say("State: " + edid.state_text(data))
    for name in _matching_backups(data, args.backup_dir):
        env.say("Same as backup: " + name)
    _print_edid(env, data)
    if args.save:
        with open(args.save, "xb") as f:
            f.write(data)
        env.say("Saved to " + str(args.save))
    found = edid.problems(data)
    if found:
        env.say("Problems: " + "; ".join(found))
        return REFUSED
    return OK


def cmd_backup(args, env: Env) -> int:
    with env.open_card() as transport:
        data = _read_current(env, transport)
    path = save_backup(data, args.backup_dir, "manual")
    env.say("Backup saved: {}\nState: {}".format(path, edid.state_text(data)))
    return OK


def cmd_decode(args, env: Env) -> int:
    data = Path(args.file).read_bytes()
    env.say("{} ({} bytes)".format(args.file, len(data)))
    env.say("State: " + edid.state_text(data))
    _print_edid(env, data)
    found = edid.problems(data)
    env.say("Safe to write: " + ("yes" if not found else "NO: " + "; ".join(found)))
    return OK if not found else REFUSED


# ---------------------------------------------------------------- write commands

def _plan_add(current: bytes) -> bytes:
    if edid.problems(current):
        raise Refused("The card's current EDID is not one this tool recognises ({}). If a write was "
                      "interrupted, unplug the USB cable for 5 seconds and try again; otherwise use "
                      "'restore' with a backup.".format("; ".join(edid.problems(current))))
    return edid.add_qhd60(current)


def _plan_remove(current: bytes) -> bytes:
    if edid.problems(current):
        raise Refused("The card's current EDID is not one this tool recognises; use 'restore' with a backup.")
    return edid.remove_qhd60(current)


def _load_restore_file(path: str) -> bytes:
    p = Path(path)
    if not p.is_file() or p.stat().st_size != 256:
        raise Refused("{} is not a 256-byte EDID file".format(path))
    data = p.read_bytes()
    found = edid.problems(data)
    if found:
        raise Refused("{} cannot be written safely: {}".format(path, "; ".join(found)))
    return data


def _write_flow(args, env: Env, label: str, plan: Callable[[bytes], bytes], what: str) -> int:
    with env.open_card() as transport:
        card = protocol.Card(transport, sleep=env.sleep)
        current = card.read_edid_stable()
        target = plan(current)
        if target == current:
            env.say("Nothing to do: the card already has this EDID ({}).".format(edid.state_text(current)))
            return OK
        found = edid.problems(target)
        if found:  # defence in depth; plans already check this
            raise Refused("The planned EDID failed validation: " + "; ".join(found))
        diff = edid.changed_offsets(current, target)
        env.say("Current: " + edid.state_text(current))
        env.say("Planned: " + edid.state_text(target))
        env.say("Bytes that change: {} of 256 (offsets {})".format(len(diff), _ranges(diff)))
        if args.dry_run:
            env.say("\nDry run: nothing was written and no files were created.")
            return OK
        backup = save_backup(current, args.backup_dir, "before-" + label)
        env.say("\nBackup of the current EDID saved and verified: {}".format(backup))
        env.say("\nAbout to {}. Before you continue:".format(what))
        env.say("  1. Unplug the HDMI cable from the Cam Link. Keep the USB cable connected.")
        env.say("  2. Do not unplug USB until the tool says it is done (about 2 seconds).")
        try:
            answer = env.input("Type {} to write to the card (anything else cancels): ".format(CONFIRM_WORD))
        except (EOFError, KeyboardInterrupt):
            answer = ""
        if answer.strip() != CONFIRM_WORD:
            env.say("Cancelled. Nothing was written.")
            return REFUSED
        env.say("Writing 32 chunks, each checked before the next one is sent...")
        try:
            with _defer_interrupts(env.say):
                card.write_edid(target)
        except protocol.WriteAborted as err:
            _say_aborted(env, err, backup)
            return WRITE_PROBLEM
        env.sleep(protocol.COMMIT_SETTLE_S)
        try:
            after = card.read_edid_stable()
        except _device_errors() as err:
            env.say("The write finished but the final read-back failed: {}".format(err))
            _say_check_steps(env, backup)
            return WRITE_PROBLEM
        if after != target:
            env.say("VERIFICATION FAILED: the card reports a different EDID than the one written "
                    "(offsets {}).".format(_ranges(edid.changed_offsets(after, target))))
            _say_check_steps(env, backup)
            return WRITE_PROBLEM
    env.say("Written and verified: a full read-back matches byte for byte.")
    result = _replug_check(args, env, target, backup)
    if result == OK:
        env.say("\nThen connect the HDMI cable again.")
        if label == "add":
            env.say("On a PS5: Settings > Screen and Video > Video Output > Resolution > 1440p.")
            env.say("To undo later:  python camlink-edid.py remove")
    return result


def _replug_check(args, env: Env, target: bytes, backup: Path) -> int:
    """Confirm the EDID survives a power cycle of the card, i.e. it is stored in flash."""
    if args.no_replug_check or env.wait_for_replug is None:
        env.say("\nTo confirm it is stored: unplug USB for 5 seconds, plug it back in and run 'status'.")
        return OK
    env.say("\nLast step: confirm the change is stored permanently.")
    env.say("Unplug the Cam Link USB cable now (Ctrl+C to skip this check)...")
    try:
        replugged = env.wait_for_replug(env.say)
    except KeyboardInterrupt:
        replugged = False
    if not replugged:
        env.say("Check skipped. Later: unplug USB for 5 seconds, plug it back in and run 'status'.")
        return OK
    try:
        with env.open_card() as transport:
            after = _read_current(env, transport)
    except _device_errors() as err:
        env.say("Could not read the card after reconnecting: {}\nRun 'status' later.".format(err))
        return OK
    if after != target:
        env.say("After reconnecting, the card reports: {}".format(edid.state_text(after)))
        env.say("This is not what was written. Your backup: {}".format(backup))
        env.say("Restore it with:  python camlink-edid.py restore \"{}\"".format(backup))
        return WRITE_PROBLEM
    env.say("Confirmed after reconnecting: " + edid.state_text(after))
    return OK


def _say_aborted(env: Env, err: protocol.WriteAborted, backup: Path) -> None:
    env.say("\nWRITE STOPPED: {}".format(err))
    if err.may_be_stored:
        env.say("The last chunk was involved, so the card may have stored the new EDID.")
    else:
        env.say("The tool stopped before the last chunk. On the analysed firmware the card stores the "
                "EDID only after the last chunk, so the stored EDID should be unchanged.")
    _say_check_steps(env, backup)


def _say_check_steps(env: Env, backup: Path) -> None:
    env.say("What to do now (do not retry the write repeatedly):")
    env.say("  1. Unplug the Cam Link USB cable for 5 seconds and plug it back in.")
    env.say("  2. Run:  python camlink-edid.py status")
    env.say("  3. If the state is not what you expect, restore your backup:")
    env.say("     python camlink-edid.py restore \"{}\"".format(backup))


def _ranges(offsets: List[int]) -> str:
    if not offsets:
        return "none"
    parts, start, prev = [], offsets[0], offsets[0]
    for o in offsets[1:] + [None]:
        if o is not None and o == prev + 1:
            prev = o
            continue
        parts.append(str(start) if start == prev else "{}-{}".format(start, prev))
        if o is not None:
            start = prev = o
    return ", ".join(parts)


def cmd_add(args, env: Env) -> int:
    return _write_flow(args, env, "add", _plan_add, "add the 2560x1440 @ 60 Hz mode")


def cmd_remove(args, env: Env) -> int:
    return _write_flow(args, env, "remove", _plan_remove, "remove the 2560x1440 @ 60 Hz mode")


def cmd_restore(args, env: Env) -> int:
    data = _load_restore_file(args.file)
    return _write_flow(args, env, "restore", lambda _current: data, "restore {}".format(args.file))


# ---------------------------------------------------------------- entry point

def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        prog="camlink-edid",
        description="Unofficial tool: add a 2560x1440 @ 60 Hz mode to the EDID of an Elgato "
                    "Cam Link 4K Rev.2 (USB 0FD9:007B). Not affiliated with Elgato/Corsair.")
    parser.add_argument("--version", action="version", version="camlink-edid " + __version__)
    sub = parser.add_subparsers(dest="command", metavar="command")

    def add(name, func, help_text, writes=False, backups=True):
        p = sub.add_parser(name, help=help_text, description=help_text)
        p.set_defaults(func=func)
        if backups:
            p.add_argument("--backup-dir", type=Path, default=DEFAULT_BACKUP_DIR,
                           help="where backups are kept (default: %(default)s)")
        if writes:
            p.add_argument("--dry-run", action="store_true",
                           help="read the card and show the plan without writing anything")
            p.add_argument("--no-replug-check", action="store_true",
                           help="skip the guided unplug/replug verification at the end")
        return p

    add("detect", cmd_detect, "list connected Cam Link devices and whether they are supported (no I/O)",
        backups=False)
    add("status", cmd_status, "read the card's EDID and show its state (read-only)").add_argument(
        "--save", metavar="FILE", help="also save the EDID to FILE (never overwrites)")
    add("backup", cmd_backup, "save a timestamped copy of the card's EDID (read-only)")
    add("decode", cmd_decode, "show the contents of an EDID file (offline)", backups=False).add_argument(
        "file", help="256-byte EDID file")
    add("add", cmd_add, "add the 2560x1440 @ 60 Hz mode to the card's EDID", writes=True)
    add("remove", cmd_remove, "remove the mode added by 'add' (exact inverse)", writes=True)
    add("restore", cmd_restore, "write a previously saved EDID file back to the card",
        writes=True).add_argument("file", help="backup file created by this tool")
    return parser


def main(argv=None, env: Optional[Env] = None) -> int:
    parser = build_parser()
    args = parser.parse_args(argv)
    if not getattr(args, "func", None):
        parser.print_help()
        return OK
    env = env or _default_env()
    try:
        return args.func(args, env)
    except (Refused, edid.EdidError, FileExistsError, FileNotFoundError) as err:
        env.say("Stopped, nothing was written: {}".format(err))
        return REFUSED
    except _device_errors() as err:
        env.say("Stopped, nothing was written: {}".format(err))
        return REFUSED
    except KeyboardInterrupt:
        env.say("Interrupted.")
        return REFUSED


if __name__ == "__main__":
    sys.exit(main())
