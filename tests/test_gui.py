"""Drive the window against the simulated card. Skipped where no display is available."""
import tempfile
import time
import unittest
from pathlib import Path

from camlink_edid import edid, operations
from fakes import FakeCard, factory_like_edid

try:
    import tkinter as tk
    _root = tk.Tk()
    _root.destroy()
    HAVE_TK = True
except Exception:  # no display (e.g. Linux CI) or Tk missing
    HAVE_TK = False


@unittest.skipUnless(HAVE_TK, "Tk display not available")
class GuiTests(unittest.TestCase):
    def setUp(self):
        from camlink_edid import gui
        self.gui = gui
        self.base = factory_like_edid()
        self.added = edid.add_qhd60(self.base)
        self.tmp = tempfile.TemporaryDirectory()
        self.addCleanup(self.tmp.cleanup)
        self.backup_dir = Path(self.tmp.name) / "backups"
        self.root = tk.Tk()
        self.root.withdraw()
        self.addCleanup(self._destroy)

    def _destroy(self):
        try:
            self.root.destroy()
        except tk.TclError:
            pass

    def make_app(self, flash, usb=((0x0FD9, 0x007B),), replug=True):
        self.card = FakeCard(flash)

        def wait_for_replug(say, cancel=None):
            say("  Unplugged. Wait 5 seconds, then plug it back in.")
            self.card.replug()
            return True

        env = operations.Env(open_card=lambda: self.card, usb_ids=lambda: list(usb),
                             wait_for_replug=wait_for_replug if replug else None,
                             sleep=lambda s: None, say=lambda *a: None)
        self.app = self.gui.App(self.root, env, self.backup_dir)
        return self.app

    def pump(self, condition, timeout=5.0):
        end = time.monotonic() + timeout
        while time.monotonic() < end:
            self.root.update()
            if condition():
                return
            time.sleep(0.01)
        self.fail("condition not reached in time")

    def read(self):
        self.app.refresh()
        self.pump(lambda: not self.app.busy)

    def log(self):
        return self.app.log_text.get("1.0", "end")

    @staticmethod
    def visible(button):
        return button.winfo_manager() == "pack"

    def test_factory_card_offers_add_only(self):
        self.make_app(self.base)
        self.read()
        self.assertEqual(self.app.chip.cget("text"), "Not offered")
        self.assertTrue(self.visible(self.app.add_button))
        self.assertFalse(self.app.add_button.instate(["disabled"]))
        self.assertFalse(self.visible(self.app.remove_button))
        rows = [c for c in self.app.modes.winfo_children()]
        self.assertTrue(any("not offered" in w.cget("text") for r in rows for w in r.winfo_children()))

    def test_add_through_the_wizard(self):
        self.make_app(self.base)
        self.read()
        self.app.start_write("add")
        wizard = self.app.wizard
        wizard.start_write()  # must be ignored until both boxes are ticked
        self.assertEqual(wizard.phase, "check")
        self.assertTrue(wizard.write_button.instate(["disabled"]))
        wizard.hdmi.set(True)
        wizard.undo.set(True)
        wizard._update_write_button()
        self.assertFalse(wizard.write_button.instate(["disabled"]))
        wizard.write_button.invoke()
        self.pump(lambda: wizard.phase == "done")
        self.assertEqual(bytes(self.card.flash), self.added)
        self.assertEqual(len(list(self.backup_dir.glob("*.bin"))), 1)
        self.assertIn("Confirmed after reconnecting", self.log())
        wizard.close()
        self.pump(lambda: not self.app.busy and self.app.wizard is None)
        self.assertEqual(self.app.chip.cget("text"), "Offered")
        self.assertTrue(self.visible(self.app.remove_button))
        self.assertFalse(self.visible(self.app.add_button))
        self.assertFalse(self.app.remove_button.instate(["disabled"]))

    def test_rejected_write_shows_problem_and_keeps_flash(self):
        self.make_app(self.base)
        self.read()
        self.card.reject_write_at = 0
        wizard = self.app.open_wizard(operations.plan_add(self.app.current))
        wizard.hdmi.set(True)
        wizard.undo.set(True)
        wizard.start_write()
        self.pump(lambda: wizard.phase == "done")
        self.assertEqual(bytes(self.card.flash), self.base)
        self.assertIn("Write stopped", self.log())

    def test_card_changed_since_plan_writes_nothing(self):
        self.make_app(self.base)
        self.read()
        wizard = self.app.open_wizard(operations.plan_add(self.app.current))
        self.card.flash[:] = self.added
        self.card.replug()
        wizard.hdmi.set(True)
        wizard.undo.set(True)
        wizard.start_write()
        self.pump(lambda: wizard.phase == "done")
        self.assertEqual(self.card.write_frames, [])
        self.assertEqual(list(self.backup_dir.glob("*.bin")) if self.backup_dir.exists() else [], [])
        self.assertIn("Nothing was written", self.log())

    def test_window_cannot_close_during_write(self):
        self.make_app(self.base)
        self.read()
        wizard = self.app.open_wizard(operations.plan_add(self.app.current))
        wizard.phase = "writing"
        self.app.writing = True
        wizard.close()
        self.assertFalse(wizard.closed)
        self.app.on_close()
        self.assertTrue(self.root.winfo_exists())
        wizard.phase = "check"
        self.app.writing = False
        wizard.close()

    def test_remove_and_restore(self):
        self.make_app(self.added)
        self.read()
        self.assertEqual(self.app.chip.cget("text"), "Offered")
        backup = operations.save_backup(self.added, self.backup_dir, "manual")
        self.app.start_write("remove")
        w = self.app.wizard
        w.hdmi.set(True)
        w.undo.set(True)
        w.start_write()
        self.pump(lambda: w.phase == "done")
        self.assertEqual(bytes(self.card.flash), self.base)
        w.close()
        self.pump(lambda: self.app.wizard is None and not self.app.busy)
        self.app.start_restore(str(backup))
        w = self.app.wizard
        w.hdmi.set(True)
        w.undo.set(True)
        w.start_write()
        self.pump(lambda: w.phase == "done")
        self.assertEqual(bytes(self.card.flash), self.added)
        w.close()

    def test_unsupported_revision_is_explained(self):
        self.make_app(self.base, usb=((0x0FD9, 0x00F4),))
        self.read()
        self.assertIn("Rev.4", self.app.device_text.cget("text"))
        self.assertFalse(self.visible(self.app.add_button))
        self.assertFalse(self.app.modes_section.winfo_manager())
        self.assertEqual(self.card.frames, [])

    def test_invalid_restore_file_is_refused(self):
        self.make_app(self.base)
        self.read()
        bad = Path(self.tmp.name) / "bad.bin"
        bad.write_bytes(b"\x00" * 256)
        self.app.start_restore(str(bad))
        self.assertIsNone(self.app.wizard)
        self.assertIn("cannot be written safely", self.log())


if __name__ == "__main__":
    unittest.main()


class HelperTests(unittest.TestCase):
    """Pure helpers of the window; need tkinter importable but no display."""

    def setUp(self):
        try:
            from camlink_edid import gui
        except ImportError:  # tkinter missing entirely
            self.skipTest("tkinter not installed")
        self.gui = gui

    def test_short_path_keeps_short_and_shortens_long(self):
        self.assertEqual(self.gui.short_path(Path("C:/a/b")), str(Path("C:/a/b")))
        long = Path("C:/Users/someone/AppData/Local/Temp/" + "x" * 80 + "/camlink-edid-backups")
        text = self.gui.short_path(long)
        self.assertLessEqual(len(text), 58)
        self.assertIn("...", text)
        self.assertTrue(text.endswith("camlink-edid-backups"))

    def test_plain_state(self):
        base = factory_like_edid()
        self.assertIn("does not offer", self.gui.plain_state(base))
        self.assertIn("offers 2560", self.gui.plain_state(edid.add_qhd60(base)))
        self.assertIn("does not recognise", self.gui.plain_state(bytes(256)))
