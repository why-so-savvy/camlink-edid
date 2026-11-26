import json
import signal
import tempfile
import unittest
from pathlib import Path

from camlink_edid import cli, edid
from fakes import FakeCard, factory_like_edid


class Harness:
    """Runs CLI commands against a simulated card, with scripted answers."""

    def __init__(self, flash: bytes, answer: str = "WRITE", replug: bool = True):
        self.card = FakeCard(flash)
        self.answer = answer
        self.output = []
        self.tmp = tempfile.TemporaryDirectory()
        self.backup_dir = Path(self.tmp.name) / "backups"
        self.env = cli.Env(
            open_card=lambda: self.card,
            usb_ids=lambda: [],
            wait_for_replug=(self._replug if replug else None),
            input=self._input,
            sleep=lambda s: None,
            say=lambda text="": self.output.append(str(text)),
        )

    def _input(self, prompt):
        self.output.append(prompt)
        if isinstance(self.answer, BaseException):
            raise self.answer
        return self.answer

    def _replug(self, say):
        self.card.replug()
        return True

    def run(self, *argv):
        return cli.main(list(argv) + (["--backup-dir", str(self.backup_dir)]
                                      if argv[0] in ("status", "backup", "add", "remove", "restore") else []),
                        env=self.env)

    @property
    def text(self):
        return "\n".join(self.output)

    def backups(self):
        return sorted(self.backup_dir.glob("*.bin")) if self.backup_dir.exists() else []

    def close(self):
        self.tmp.cleanup()


class CliTests(unittest.TestCase):
    def setUp(self):
        self.base = factory_like_edid()
        self.added = edid.add_qhd60(self.base)

    def harness(self, flash=None, **kw):
        h = Harness(self.base if flash is None else flash, **kw)
        self.addCleanup(h.close)
        return h

    def test_status_is_read_only(self):
        h = self.harness()
        self.assertEqual(h.run("status"), cli.OK)
        self.assertEqual(h.card.write_frames, [])
        self.assertIn("no 1440p mode", h.text)

    def test_add_success_creates_verified_backup_and_survives_replug(self):
        h = self.harness()
        self.assertEqual(h.run("add"), cli.OK)
        self.assertEqual(bytes(h.card.flash), self.added)
        backups = h.backups()
        self.assertEqual(len(backups), 1)
        self.assertEqual(backups[0].read_bytes(), self.base)
        meta = json.loads(backups[0].with_suffix(".json").read_text(encoding="utf-8"))
        self.assertEqual(meta["sha256"], edid.sha256(self.base))
        self.assertIn("Confirmed after reconnecting", h.text)
        self.assertIn("1440p", h.text)

    def test_dry_run_writes_nothing_and_creates_no_files(self):
        h = self.harness()
        self.assertEqual(h.run("add", "--dry-run"), cli.OK)
        self.assertEqual(h.card.write_frames, [])
        self.assertEqual(h.backups(), [])

    def test_anything_but_the_confirm_word_cancels(self):
        for answer in ("", "yes", "write", "WRITE NOW", EOFError(), KeyboardInterrupt()):
            h = self.harness(answer=answer)
            self.assertEqual(h.run("add"), cli.REFUSED, answer)
            self.assertEqual(h.card.write_frames, [])
            self.assertEqual(bytes(h.card.flash), self.base)

    def test_nothing_to_do_when_already_added(self):
        h = self.harness(flash=self.added)
        self.assertEqual(h.run("add"), cli.OK)
        self.assertEqual(h.card.write_frames, [])
        self.assertIn("Nothing to do", h.text)

    def test_refuses_unrecognised_card_edid(self):
        broken = bytearray(self.base)
        broken[127] ^= 1
        h = self.harness(flash=bytes(broken))
        self.assertEqual(h.run("add"), cli.REFUSED)
        self.assertEqual(h.card.write_frames, [])

    def test_rejected_write_reports_problem_and_keeps_flash(self):
        h = self.harness()
        h.card.reject_write_at = 0
        self.assertEqual(h.run("add"), cli.WRITE_PROBLEM)
        self.assertEqual(bytes(h.card.flash), self.base)
        self.assertIn("WRITE STOPPED", h.text)
        self.assertIn("restore", h.text)

    def test_final_readback_mismatch_is_reported(self):
        h = self.harness()
        h.card.after_commit_flip = 200
        self.assertEqual(h.run("add"), cli.WRITE_PROBLEM)
        self.assertIn("VERIFICATION FAILED", h.text)

    def test_not_stored_after_replug_is_reported(self):
        h = self.harness()
        h.card.flash_fails = True
        self.assertEqual(h.run("add"), cli.WRITE_PROBLEM)
        self.assertIn("not what was written", h.text)

    def test_remove_restores_the_original_bytes(self):
        h = self.harness(flash=self.added)
        self.assertEqual(h.run("remove"), cli.OK)
        self.assertEqual(bytes(h.card.flash), self.base)

    def test_restore_from_backup(self):
        h = self.harness()
        self.assertEqual(h.run("add"), cli.OK)
        backup = h.backups()[0]
        self.assertEqual(h.run("restore", str(backup)), cli.OK)
        self.assertEqual(bytes(h.card.flash), self.base)

    def test_restore_refuses_invalid_file_without_touching_the_card(self):
        h = self.harness()
        bad = Path(h.tmp.name) / "bad.bin"
        data = bytearray(self.base)
        data[200] ^= 1
        bad.write_bytes(bytes(data))
        self.assertEqual(h.run("restore", str(bad)), cli.REFUSED)
        self.assertEqual(h.card.frames, [])

    def test_restore_works_even_if_the_card_edid_is_broken(self):
        broken = bytearray(self.base)
        broken[127] ^= 1
        h = self.harness(flash=bytes(broken))
        good = Path(h.tmp.name) / "good.bin"
        good.write_bytes(self.base)
        self.assertEqual(h.run("restore", str(good)), cli.OK)
        self.assertEqual(bytes(h.card.flash), self.base)

    def test_backups_are_never_overwritten(self):
        h = self.harness()
        for _ in range(3):
            self.assertEqual(h.run("backup"), cli.OK)
        self.assertEqual(len(h.backups()), 3)

    def test_skipped_replug_check_still_succeeds(self):
        h = self.harness(replug=False)
        self.assertEqual(h.run("add"), cli.OK)
        self.assertIn("run 'status'", h.text)

    def test_detect_reports_unsupported_revision(self):
        h = self.harness()
        h.env.usb_ids = lambda: [(0x0FD9, 0x00F4)]
        self.assertEqual(h.run("detect"), cli.REFUSED)
        self.assertIn("Rev.4", h.text)
        h.env.usb_ids = lambda: [(0x0FD9, 0x007B)]
        self.assertEqual(h.run("detect"), cli.OK)

    def test_ctrl_c_is_postponed_during_the_write(self):
        said = []
        with cli._defer_interrupts(said.append):
            signal.raise_signal(signal.SIGINT)
        self.assertTrue(said)

    def test_offset_ranges(self):
        self.assertEqual(cli._ranges([72, 73, 74, 127]), "72-74, 127")
        self.assertEqual(cli._ranges([]), "none")


if __name__ == "__main__":
    unittest.main()
