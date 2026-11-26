"""Command line interface. The logic lives in operations.py, shared with the window.

Exit codes:
  0  success (or nothing to do)
  1  refused or failed BEFORE anything was written: the card is unchanged
  2  a problem happened during or after a write: follow the printed steps
"""
from __future__ import annotations

import argparse
import contextlib
import signal
import sys
import threading
from pathlib import Path
from typing import Callable, Optional

from . import __version__, devices, edid, operations, protocol
from .operations import DEFAULT_BACKUP_DIR, Env, Refused, save_backup  # noqa: F401  (re-exported)

OK, REFUSED, WRITE_PROBLEM = 0, 1, 2
CONFIRM_WORD = "WRITE"
_ranges = operations.ranges


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


def _print_edid(env: Env, data: bytes) -> None:
    for line in edid.describe(data):
        env.say("  " + line)


def _read_current(env: Env, transport) -> bytes:
    return protocol.Card(transport, sleep=env.sleep).read_edid_stable()


# ---------------------------------------------------------------- read-only commands

def cmd_detect(args, env: Env) -> int:
    found = [devices.lookup(vid, pid) for vid, pid in env.usb_ids()]
    found = [f for f in found if f is not None]
    if not found:
        env.say("No Elgato Cam Link device found on USB.")
        return REFUSED
    for info in found:
        env.say("{}  {}  -> {}".format(info.usb_id, info.name, info.note))
    supported = [f for f in found if f.support == devices.SUPPORTED]
    if len(supported) == 1:
        env.say("\nNext: python camlink-edid.py status   (read-only)")
        return OK
    if len(supported) > 1:
        env.say("\nMore than one supported card is connected. Connect only the one you want to change.")
    return REFUSED


def cmd_status(args, env: Env) -> int:
    with env.open_card() as transport:
        data = _read_current(env, transport)
    env.say("Cam Link 4K Rev.2 (USB 0FD9:007B): EDID read twice, both reads identical.")
    env.say("State: " + edid.state_text(data))
    for name in operations.matching_backups(data, args.backup_dir):
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

def _write_flow(args, env: Env, make_plan: Callable[[bytes], operations.Plan]) -> int:
    with env.open_card() as transport:
        card = protocol.Card(transport, sleep=env.sleep)
        plan = make_plan(card.read_edid_stable())
        if plan.nothing_to_do:
            env.say("Nothing to do: the card already has this EDID ({}).".format(edid.state_text(plan.current)))
            return OK
        env.say("Current: " + edid.state_text(plan.current))
        env.say("Planned: " + edid.state_text(plan.target))
        env.say("Bytes that change: {} of 256 (offsets {})".format(len(plan.changed), _ranges(plan.changed)))
        if args.dry_run:
            env.say("\nDry run: nothing was written and no files were created.")
            return OK
        backup = save_backup(plan.current, args.backup_dir, "before-" + plan.label)
        env.say("\nBackup of the current EDID saved and verified: {}".format(backup))
        env.say("\nReady to write ({}). Before you continue:".format(plan.title))
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
                operations.write_and_verify(card, plan)
        except protocol.WriteAborted as err:
            env.say("\nWRITE STOPPED: {}".format(err))
            env.say(operations.aborted_explanation(err))
            _say_recovery(env, backup)
            return WRITE_PROBLEM
        except operations.VerificationFailed as err:
            env.say("\nVERIFICATION FAILED: {}".format(err))
            _say_recovery(env, backup)
            return WRITE_PROBLEM
    env.say("Written and verified: a full read-back matches byte for byte.")
    result = _replug_check(args, env, plan.target, backup)
    if result == OK:
        env.say("\nThen connect the HDMI cable again.")
        if plan.label == "add":
            env.say("On a PS5: Settings > Screen and Video > Video Output > Resolution > 1440p.")
            env.say("To undo later:  python camlink-edid.py remove")
    return result


def _say_recovery(env: Env, backup: Path) -> None:
    for line in operations.recovery_steps(backup):
        env.say(line)
    env.say('   python camlink-edid.py restore "{}"'.format(backup))


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
    except operations.device_errors() as err:
        env.say("Could not read the card after reconnecting: {}\nRun 'status' later.".format(err))
        return OK
    if after != target:
        env.say("After reconnecting, the card reports: {}".format(edid.state_text(after)))
        env.say("This is not what was written. Your backup: {}".format(backup))
        env.say('Restore it with:  python camlink-edid.py restore "{}"'.format(backup))
        return WRITE_PROBLEM
    env.say("Confirmed after reconnecting: " + edid.state_text(after))
    return OK


def cmd_add(args, env: Env) -> int:
    return _write_flow(args, env, operations.plan_add)


def cmd_remove(args, env: Env) -> int:
    return _write_flow(args, env, operations.plan_remove)


def cmd_restore(args, env: Env) -> int:
    data = operations.load_restore_file(args.file)
    return _write_flow(args, env, lambda current: operations.plan_restore(current, data))


def cmd_gui(args, env: Env) -> int:
    from . import gui
    return gui.main(backup_dir=args.backup_dir)


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

    add("gui", cmd_gui, "open the graphical interface")
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
    env = env or operations.default_env()
    try:
        return args.func(args, env)
    except (Refused, edid.EdidError, FileExistsError, FileNotFoundError) as err:
        env.say("Stopped, nothing was written: {}".format(err))
        return REFUSED
    except operations.device_errors() as err:
        env.say("Stopped, nothing was written: {}".format(err))
        return REFUSED
    except KeyboardInterrupt:
        env.say("Interrupted.")
        return REFUSED


if __name__ == "__main__":
    sys.exit(main())
