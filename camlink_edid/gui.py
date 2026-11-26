"""Graphical interface (Tkinter, part of Python's standard library).

A thin layer over operations.py: every check, backup and verification is the
same code the command line uses. Device work runs in a worker thread; results
come back to the window through a queue.
"""
from __future__ import annotations

import os
import queue
import sys
import threading
import time
from pathlib import Path
from typing import Callable, Dict, List, Optional, Tuple

import tkinter as tk
from tkinter import filedialog, ttk
from tkinter import font as tkfont

from . import PROJECT_URL, __version__, devices, edid, operations, protocol

INK = "#1C2430"
MUTED = "#5B6675"
BASE = "#F3F5F7"
PANEL = "#FFFFFF"
LINE = "#D5DBE1"
SIGNAL = "#0E7C86"
SIGNAL_DARK = "#0A5F66"
SIGNAL_SOFT = "#E1F1F2"
WARN = "#B25E00"
WARN_SOFT = "#FBEFE0"
DANGER = "#B42318"
DANGER_SOFT = "#FCE8E6"
QUIET_SOFT = "#E9ECEF"

QHD = (2560, 1440)


ICON = Path(__file__).with_name("assets") / "icon.ico"


def _dpi_aware() -> None:
    """Sharp text on scaled displays, and our own icon on the taskbar."""
    if sys.platform == "win32":
        try:
            import ctypes
            ctypes.windll.shcore.SetProcessDpiAwareness(1)
            ctypes.windll.shell32.SetCurrentProcessExplicitAppUserModelID("why-so-savvy.camlink-edid")
        except Exception:
            pass


class Theme:
    def __init__(self, root: tk.Tk):
        families = set(tkfont.families(root))

        def pick(*names):
            return next((n for n in names if n in families), "TkDefaultFont")

        display = pick("Bahnschrift SemiBold", "Bahnschrift", "Segoe UI Semibold", "Segoe UI")
        display_regular = pick("Bahnschrift", "Segoe UI")
        body = pick("Segoe UI", "Helvetica", "Arial")
        self.hero = tkfont.Font(root, family=display, size=24)
        self.heading = tkfont.Font(root, family=display, size=12)
        self.mode = tkfont.Font(root, family=display_regular, size=10)
        self.body = tkfont.Font(root, family=body, size=10)
        self.body_bold = tkfont.Font(root, family=body, size=10, weight="bold")
        self.small = tkfont.Font(root, family=body, size=9)
        self.scale = root.winfo_fpixels("1i") / 96.0

        style = ttk.Style(root)
        style.theme_use("clam")
        pad = (self.px(16), self.px(7))
        style.configure("TButton", font=self.body, padding=pad, background=PANEL, foreground=INK,
                        bordercolor=LINE, lightcolor=PANEL, darkcolor=PANEL, focuscolor=SIGNAL, relief="flat")
        style.map("TButton", background=[("disabled", BASE), ("pressed", QUIET_SOFT), ("active", "#EEF2F5")],
                  foreground=[("disabled", "#9AA4AF")])
        style.configure("Primary.TButton", background=SIGNAL, foreground="#FFFFFF", bordercolor=SIGNAL,
                        lightcolor=SIGNAL, darkcolor=SIGNAL, focuscolor="#FFFFFF", font=self.body_bold)
        style.map("Primary.TButton", background=[("disabled", "#A9CDD0"), ("pressed", SIGNAL_DARK),
                                                 ("active", SIGNAL_DARK)],
                  foreground=[("disabled", "#F4FAFA")], bordercolor=[("disabled", "#A9CDD0")])
        style.configure("Link.TButton", background=BASE, foreground=SIGNAL, bordercolor=BASE,
                        lightcolor=BASE, darkcolor=BASE, padding=(self.px(4), self.px(2)), font=self.body)
        style.map("Link.TButton", background=[("active", BASE), ("pressed", BASE)],
                  foreground=[("disabled", "#9AA4AF"), ("active", SIGNAL_DARK)])
        style.configure("PanelLink.TButton", background=PANEL, foreground=SIGNAL, bordercolor=PANEL,
                        lightcolor=PANEL, darkcolor=PANEL, padding=(0, self.px(2)), font=self.small)
        style.map("PanelLink.TButton", background=[("active", PANEL), ("pressed", PANEL)],
                  foreground=[("active", SIGNAL_DARK)])
        style.configure("TCheckbutton", background=PANEL, foreground=INK, font=self.body,
                        indicatorbackground=PANEL, indicatorforeground=SIGNAL, focuscolor=SIGNAL,
                        indicatorsize=self.px(15), indicatormargin=(0, 0, self.px(8), 0))
        style.map("TCheckbutton", background=[("active", PANEL)], indicatorbackground=[("pressed", SIGNAL_SOFT)])
        style.configure("Signal.Horizontal.TProgressbar", troughcolor=QUIET_SOFT, background=SIGNAL,
                        bordercolor=QUIET_SOFT, lightcolor=SIGNAL, darkcolor=SIGNAL,
                        thickness=self.px(8))

    def px(self, n: float) -> int:
        return int(round(n * self.scale))


def _label(parent, text="", font=None, fg=INK, bg=PANEL, **kw) -> tk.Label:
    return tk.Label(parent, text=text, font=font, fg=fg, bg=bg, anchor="w", justify="left", **kw)


def short_path(path: Path, limit: int = 58) -> str:
    """Shorten long paths in the middle so they never stretch the window."""
    text = str(path)
    if len(text) <= limit:
        return text
    keep = limit - 3
    return text[:keep // 3] + "..." + text[-(keep - keep // 3):]


def plain_state(data: bytes) -> str:
    """The EDID state in words a user understands."""
    state = edid.classify(data)
    if state == edid.QHD60_PRESENT:
        return "The card offers 2560 × 1440 at 60 Hz"
    if state == edid.FACTORY_LAYOUT:
        return "The card does not offer 2560 × 1440 at 60 Hz"
    if not edid.problems(data):
        return "A custom EDID that this tool does not change"
    return "An EDID that this tool does not recognise"


class App:
    """The main window."""

    def __init__(self, root: tk.Tk, env: operations.Env, backup_dir: Path):
        self.root = root
        self.env = env
        self.backup_dir = Path(backup_dir)
        self.events: "queue.Queue[Tuple[Callable, tuple]]" = queue.Queue()
        self.busy = False
        self.writing = False
        self.current: Optional[bytes] = None
        self.wizard: Optional[WriteWizard] = None
        self.t = Theme(root)
        root.title("Cam Link EDID")
        if sys.platform == "win32" and ICON.is_file():
            try:
                root.iconbitmap(default=str(ICON))  # also used by the wizard and details windows
            except tk.TclError:
                pass
        root.configure(bg=BASE)
        root.resizable(False, False)
        root.protocol("WM_DELETE_WINDOW", self.on_close)
        root.report_callback_exception = self._on_callback_error
        self._pump_id: Optional[str] = None
        root.bind("<Destroy>", self._on_destroy, add="+")
        self._build()
        self._pump()

    # ------------------------------------------------------------ threading helpers
    def post(self, callback: Callable, *args) -> None:
        """Safe to call from any thread: run callback(*args) on the window's thread."""
        self.events.put((callback, args))

    def run_task(self, func: Callable, on_done: Callable, on_error: Callable) -> None:
        def work():
            try:
                result = func()
            except BaseException as err:  # reported in the window, never swallowed
                self.post(on_error, err)
            else:
                self.post(on_done, result)
        threading.Thread(target=work, name="camlink-edid-task").start()

    def _pump(self) -> None:
        try:
            while True:
                callback, args = self.events.get_nowait()
                callback(*args)
        except queue.Empty:
            pass
        try:
            self._pump_id = self.root.after(40, self._pump)
        except tk.TclError:  # the window was closed by one of the callbacks
            self._pump_id = None

    def _on_callback_error(self, exc_type, value, tb) -> None:
        """The .exe has no console, so unexpected errors are shown in the window instead of vanishing."""
        try:
            self.log("Unexpected error: {!r}. Please report it with this text.".format(value))
        except tk.TclError:
            pass

    def _on_destroy(self, event) -> None:
        if event.widget is self.root and self._pump_id is not None:
            try:
                self.root.after_cancel(self._pump_id)
            except tk.TclError:
                pass
            self._pump_id = None

    # ------------------------------------------------------------ layout
    def _build(self) -> None:
        t, px = self.t, self.t.px
        width = px(600)
        outer = tk.Frame(self.root, bg=BASE, padx=px(24), pady=px(16))
        outer.pack(fill="both", expand=True)

        top = tk.Frame(outer, bg=BASE)
        top.pack(fill="x")
        _label(top, "Cam Link EDID", t.heading, bg=BASE).pack(side="left")
        self.refresh_button = ttk.Button(top, text="Refresh", style="Link.TButton", command=self.refresh)
        self.refresh_button.pack(side="right")
        ttk.Button(top, text="Help", style="Link.TButton", command=self.open_help).pack(side="right",
                                                                                       padx=(0, px(10)))

        device = tk.Frame(outer, bg=BASE)
        device.pack(fill="x", pady=(px(2), px(12)))
        self.dot = tk.Canvas(device, width=px(10), height=px(10), bg=BASE, highlightthickness=0)
        self.dot.pack(side="left", padx=(0, px(8)))
        self.device_text = _label(device, "Looking for the Cam Link...", t.body, MUTED, BASE)
        self.device_text.pack(side="left")

        panel = tk.Frame(outer, bg=PANEL, highlightthickness=1, highlightbackground=LINE,
                         padx=px(22), pady=px(18))
        panel.pack(fill="x")
        hero_row = tk.Frame(panel, bg=PANEL)
        hero_row.pack(fill="x")
        self.hero = _label(hero_row, "2560 × 1440 at 60 Hz", t.hero, MUTED)
        self.hero.pack(side="left")
        self.chip = tk.Label(hero_row, text="", font=t.small, padx=px(9), pady=px(2), bg=QUIET_SOFT, fg=MUTED)
        self.chip.pack(side="left", padx=(px(14), 0), pady=(px(6), 0))
        self.hero_text = _label(panel, "", t.body, MUTED, wraplength=width - px(44))
        self.hero_text.pack(fill="x", pady=(px(4), px(14)))

        self.modes_section = tk.Frame(panel, bg=PANEL)
        tk.Frame(self.modes_section, bg=LINE, height=1).pack(fill="x")
        _label(self.modes_section, "Modes the card offers to the console", t.small, MUTED).pack(
            fill="x", pady=(px(12), px(6)))
        self.modes = tk.Frame(self.modes_section, bg=PANEL)
        self.modes.pack(fill="x")
        self.details_button = ttk.Button(self.modes_section, text="Show EDID details", style="PanelLink.TButton",
                                         command=self.show_details)
        self.details_button.pack(anchor="w", pady=(px(8), 0))

        self.actions = tk.Frame(outer, bg=BASE)
        self.actions.pack(fill="x", pady=(px(14), px(12)))
        self.add_button = ttk.Button(self.actions, text="Add 1440p60", style="Primary.TButton",
                                     command=lambda: self.start_write("add"))
        self.remove_button = ttk.Button(self.actions, text="Remove 1440p60",
                                        command=lambda: self.start_write("remove"))
        self.restore_button = ttk.Button(self.actions, text="Restore backup...", style="Link.TButton",
                                         command=self.start_restore)
        self.backup_button = ttk.Button(self.actions, text="Back up", style="Link.TButton", command=self.backup)

        _label(outer, "Activity", t.small, MUTED, BASE).pack(fill="x")
        self.log_text = tk.Text(outer, height=3, width=10, font=t.small, bg=PANEL, fg=INK, relief="flat",
                                highlightthickness=1, highlightbackground=LINE, wrap="word",
                                padx=px(10), pady=px(6), state="disabled")
        self.log_text.pack(fill="x", pady=(px(4), px(8)))

        foot = tk.Frame(outer, bg=BASE)
        foot.pack(fill="x")
        self.backup_text = _label(foot, "Backups are saved in {}".format(short_path(self.backup_dir)),
                                  t.small, MUTED, BASE)
        self.backup_text.pack(side="left")
        ttk.Button(foot, text="Open folder", style="Link.TButton", command=self.open_backups).pack(side="left")
        _label(outer, "camlink-edid {}. Unofficial; not affiliated with Elgato or Corsair.".format(__version__),
               t.small, "#8A94A0", BASE).pack(fill="x", pady=(px(4), 0))

        self._show_actions(add=False, remove=False, files=False)

    # ------------------------------------------------------------ small helpers
    def log(self, text: str) -> None:
        self.log_text.configure(state="normal")
        self.log_text.insert("end", "{}  {}\n".format(time.strftime("%H:%M:%S"), text))
        self.log_text.see("end")
        self.log_text.configure(state="disabled")

    def _set_dot(self, color: str) -> None:
        px = self.t.px
        self.dot.delete("all")
        self.dot.create_oval(1, 1, px(9), px(9), fill=color, outline=color)

    def _show_actions(self, add: bool, remove: bool, files: bool) -> None:
        """Show only the actions that make sense for the card's current state."""
        px = self.t.px
        for button in (self.add_button, self.remove_button, self.restore_button, self.backup_button):
            button.pack_forget()
        if add:
            self.add_button.pack(side="left", padx=(0, px(8)))
        if remove:
            self.remove_button.pack(side="left", padx=(0, px(8)))
        if files:
            self.restore_button.pack(side="right")
            self.backup_button.pack(side="right", padx=(0, px(6)))
        self._lock()

    def _lock(self) -> None:
        """Disable every action while the card is being read or written."""
        state = ["disabled"] if self.busy else ["!disabled"]
        for button in (self.add_button, self.remove_button, self.restore_button, self.backup_button,
                       self.refresh_button):
            button.state(state)

    def _show_modes_section(self, show: bool) -> None:
        if show and not self.modes_section.winfo_manager():
            self.modes_section.pack(fill="x")
        elif not show:
            self.modes_section.pack_forget()

    def _set_hero(self, title: str, chip: str, chip_colors: Tuple[str, str], text: str, title_color: str) -> None:
        self.hero.configure(text=title, fg=title_color)
        self.chip.configure(text=chip, bg=chip_colors[0], fg=chip_colors[1])
        if chip:
            self.chip.pack(side="left", padx=(self.t.px(14), 0), pady=(self.t.px(6), 0))
        else:
            self.chip.pack_forget()
        self.hero_text.configure(text=text)

    def _show_modes(self, data: Optional[bytes]) -> None:
        for child in self.modes.winfo_children():
            child.destroy()
        self._show_modes_section(bool(data))
        if not data:
            return
        groups: Dict[Tuple[int, int, bool], List[edid.Mode]] = {}
        for m in edid.offered_modes(data):
            groups.setdefault((m.width, m.height, m.interlaced), []).append(m)
        qhd_present = any(k[:2] == QHD and not k[2] for k in groups)
        rows = list(groups.items())
        if not qhd_present:
            rows.append(((QHD[0], QHD[1], False), []))
        rows.sort(key=lambda kv: (-kv[0][0] * kv[0][1], kv[0][2]))
        px = self.t.px
        for (w, h, interlaced), modes in rows:
            is_qhd = (w, h) == QHD and not interlaced
            bg = SIGNAL_SOFT if is_qhd and modes else PANEL
            row = tk.Frame(self.modes, bg=bg, padx=px(8), pady=px(1))
            row.pack(fill="x")
            fg = MUTED if is_qhd and not modes else INK
            _label(row, "{} × {}{}".format(w, h, "i" if interlaced else ""), self.t.mode, fg, bg,
                   width=12).pack(side="left")
            rates = ", ".join(str(m.refresh_hz) for m in modes) + " Hz" if modes else "not offered"
            _label(row, rates, self.t.body, fg if modes else MUTED, bg).pack(side="left")
            note = ""
            if is_qhd and modes:
                note = "added by this tool" if edid.classify(data) == edid.QHD60_PRESENT else ""
            elif any(m.preferred for m in modes):
                note = "preferred"
            if note:
                _label(row, note, self.t.small, SIGNAL if is_qhd else MUTED, bg).pack(side="right")

    def show_details(self) -> Optional[tk.Toplevel]:
        """Full EDID decode in its own window, so the main window keeps a fixed height."""
        if not self.current:
            return None
        px = self.t.px
        win = tk.Toplevel(self.root)
        win.title("EDID details")
        win.configure(bg=PANEL)
        win.transient(self.root)
        text = tk.Text(win, width=88, height=16, font=self.t.small, bg=PANEL, fg=INK, relief="flat",
                       wrap="word", padx=px(18), pady=px(14), borderwidth=0)
        text.insert("end", "\n".join(edid.describe(self.current)))
        text.configure(state="disabled")
        text.pack(fill="both", expand=True)
        bar = tk.Frame(win, bg=PANEL, padx=px(18), pady=px(12))
        bar.pack(fill="x")
        ttk.Button(bar, text="Close", command=win.destroy).pack(side="right")
        return win

    # ------------------------------------------------------------ reading the card
    def refresh(self) -> None:
        if self.busy:
            return
        self.busy = True
        self._lock()
        self._set_dot("#9AA4AF")
        self.device_text.configure(text="Reading the card...", fg=MUTED)
        env = self.env

        def task():
            found = [d for d in (devices.lookup(v, p) for v, p in env.usb_ids()) if d]
            supported = [d for d in found if d.support == devices.SUPPORTED]
            if len(supported) != 1:
                return found, None
            with env.open_card() as transport:
                return found, protocol.Card(transport, sleep=env.sleep).read_edid_stable()

        self.run_task(task, self._on_read, self._on_read_error)

    def _on_read(self, result) -> None:
        self.busy = False
        found, data = result
        self.current = data
        self._show_modes(data)
        supported = [d for d in found if d.support == devices.SUPPORTED]
        if data is None:
            self._show_no_device(found, supported)
            return
        self._set_dot(SIGNAL)
        self.device_text.configure(text="Cam Link 4K Rev.2 connected (USB 0FD9:007B)", fg=INK)
        state = edid.classify(data)
        title = "2560 × 1440 at 60 Hz"
        if state == edid.QHD60_PRESENT:
            self._set_hero(title, "Offered", (SIGNAL_SOFT, SIGNAL),
                           "The card offers this mode to the console. It is stored on the card, so it stays "
                           "after unplugging and on any PC.", SIGNAL)
            self._show_actions(add=False, remove=True, files=True)
            self.log("Read the card: 1440p60 is offered.")
        elif state == edid.FACTORY_LAYOUT:
            self._set_hero(title, "Not offered", (QUIET_SOFT, MUTED),
                           "The card does not offer this mode yet, so a PS5 will not let you choose 1440p. "
                           "Add it to the card's list of modes; you can remove it again at any time.", INK)
            self._show_actions(add=True, remove=False, files=True)
            self.log("Read the card: 1440p60 is not offered.")
        elif not edid.problems(data):
            self._set_hero("Custom EDID", "Unknown entry", (WARN_SOFT, WARN),
                           "The slot this tool uses already holds a different mode. To return to a known "
                           "state, restore a backup.", WARN)
            self._show_actions(add=False, remove=False, files=True)
            self.log("Read the card: the EDID has a custom entry this tool does not change.")
        else:
            self._set_hero("EDID not recognised", "Check needed", (DANGER_SOFT, DANGER),
                           "If a write was interrupted, unplug the USB cable for 5 seconds, plug it back "
                           "in and refresh. Otherwise restore a backup.", DANGER)
            self._show_actions(add=False, remove=False, files=True)
            self.log("Read the card: the EDID is not valid ({}).".format("; ".join(edid.problems(data))))

    def _show_no_device(self, found, supported) -> None:
        self._show_actions(False, False, False)
        if len(supported) > 1:
            self._set_dot(WARN)
            self.device_text.configure(text="Two supported Cam Links are connected", fg=WARN)
            self._set_hero("Connect one card", "", (PANEL, PANEL),
                           "Unplug every Cam Link except the one you want to change, then refresh.", INK)
            self.log("More than one supported Cam Link is connected.")
            return
        if not found:
            self._set_dot("#9AA4AF")
            self.device_text.configure(text="No Cam Link found", fg=MUTED)
            self._set_hero("Connect your Cam Link", "", (PANEL, PANEL),
                           "Plug the Cam Link 4K into a USB 3 port, close Camera Hub, then refresh.", INK)
            self.log("No Cam Link found.")
            return
        other = found[0]
        self._set_dot(WARN)
        self.device_text.configure(text="{} connected (USB {})".format(other.name, other.usb_id), fg=WARN)
        if other.support == devices.USB2_MODE:
            self._set_hero("Connect it to a USB 3 port", "", (PANEL, PANEL),
                           "The Cam Link is running in USB 2 mode, where this tool does not work. Plug it into "
                           "a USB 3 port (often blue) with the original cable, then refresh.", INK)
        elif other.support == devices.VENDOR_FEATURE:
            self._set_hero("Use Elgato's software", "", (PANEL, PANEL),
                           "Elgato's own software lists custom EDID support for the {}. "
                           "This tool does not change it.".format(other.name), INK)
        else:
            self._set_hero("This Cam Link is not supported", "", (PANEL, PANEL),
                           "This tool only works with the Cam Link 4K Rev.2 (USB 0FD9:007B). The {} is "
                           "different hardware, and how it stores its EDID is not known.".format(other.name), INK)
        self.log("Found {} (USB {}): not supported by this tool.".format(other.name, other.usb_id))

    def _on_read_error(self, err: BaseException) -> None:
        self.busy = False
        self.current = None
        self._show_modes(None)
        self._set_dot(DANGER)
        self.device_text.configure(text="Cam Link found, but it could not be read", fg=DANGER)
        self._set_hero("Can't read the card", "", (PANEL, PANEL), str(err), DANGER)
        self._show_actions(False, False, False)
        self.log("Read failed: {}".format(err))

    # ------------------------------------------------------------ actions
    def backup(self) -> None:
        if self.busy:
            return
        self.busy = True
        self._lock()
        env, directory = self.env, self.backup_dir

        def task():
            with env.open_card() as transport:
                data = protocol.Card(transport, sleep=env.sleep).read_edid_stable()
            return operations.save_backup(data, directory, "manual")

        def done(path):
            self.busy = False
            self.log("Backed up to {}".format(path))
            self.refresh()

        def failed(err):
            self.busy = False
            self.log("Backup failed: {}".format(err))
            self.refresh()

        self.run_task(task, done, failed)

    def open_help(self) -> None:
        import webbrowser
        webbrowser.open(PROJECT_URL + "#step-by-step")

    def open_backups(self) -> None:
        self.backup_dir.mkdir(parents=True, exist_ok=True)
        if sys.platform == "win32":
            os.startfile(str(self.backup_dir))  # noqa: S606 - opens Explorer on our own folder

    def start_write(self, label: str) -> None:
        if self.busy or self.current is None:
            return
        try:
            plan = operations.plan_add(self.current) if label == "add" else operations.plan_remove(self.current)
        except operations.Refused as err:
            self.log(str(err))
            return
        if plan.nothing_to_do:
            self.log("Nothing to do: the card already has this EDID.")
            return
        self.open_wizard(plan)

    def start_restore(self, path: Optional[str] = None) -> None:
        if self.busy or self.current is None:
            return
        if path is None:
            initial = str(self.backup_dir) if self.backup_dir.is_dir() else str(Path.home())
            path = filedialog.askopenfilename(parent=self.root, title="Restore backup", initialdir=initial,
                                              filetypes=[("EDID backup", "*.bin"), ("All files", "*.*")])
            if not path:
                return
        try:
            plan = operations.plan_restore(self.current, operations.load_restore_file(path))
        except operations.Refused as err:
            self.log(str(err))
            return
        if plan.nothing_to_do:
            self.log("Nothing to do: the card already has the EDID from {}.".format(Path(path).name))
            return
        self.open_wizard(plan)

    def open_wizard(self, plan: operations.Plan) -> "WriteWizard":
        self.busy = True
        self._lock()
        self.wizard = WriteWizard(self, plan)
        return self.wizard

    def wizard_closed(self, refresh: bool = True) -> None:
        self.wizard = None
        self.writing = False
        self.busy = False
        if refresh:
            self.refresh()

    def on_close(self) -> None:
        if self.writing:
            self.log("Writing in progress; the window closes when it is done.")
            return
        if self.wizard is not None:
            self.wizard.close()
        self.root.destroy()


class WriteWizard:
    """Check -> Write -> Confirm, for add, remove and restore."""

    STEPS = ("Check", "Write", "Confirm")

    def __init__(self, app: App, plan: operations.Plan):
        self.app = app
        self.plan = plan
        self.t = app.t
        self.phase = "check"
        self.closed = False
        self.backup: Optional[Path] = None
        self.cancel_replug = threading.Event()
        self.win = tk.Toplevel(app.root)
        self.win.title(plan.title)
        self.win.configure(bg=PANEL)
        self.win.resizable(False, False)
        self.win.transient(app.root)
        self.win.protocol("WM_DELETE_WINDOW", self.close)
        px = self.t.px
        self.frame = tk.Frame(self.win, bg=PANEL, padx=px(26), pady=px(22))
        self.frame.pack(fill="both", expand=True)
        self.steps = tk.Frame(self.frame, bg=PANEL)
        self.steps.pack(fill="x", pady=(0, px(16)))
        self.body = tk.Frame(self.frame, bg=PANEL)
        self.body.pack(fill="both", expand=True)
        self.buttons = tk.Frame(self.frame, bg=PANEL)
        self.buttons.pack(fill="x", pady=(px(20), 0))
        self.page_check()
        self.win.after(20, self._grab)

    def _grab(self) -> None:
        """Make the wizard modal once it is visible (grabbing earlier can fail in Tk)."""
        if self.closed:
            return
        try:
            self.win.grab_set()
            self.win.focus_set()
        except tk.TclError:
            self.win.after(50, self._grab)

    # ------------------------------------------------------------ shared page parts
    def _clear(self, step: int) -> None:
        for frame in (self.steps, self.body, self.buttons):
            for child in frame.winfo_children():
                child.destroy()
        px = self.t.px
        for n, name in enumerate(self.STEPS):
            done, now = n < step, n == step
            color = SIGNAL if (done or now) else "#9AA4AF"
            text = "{}  {}".format("✓" if done else n + 1, name)
            tk.Label(self.steps, text=text, font=self.t.body_bold if now else self.t.body, fg=color,
                     bg=PANEL).pack(side="left", padx=(0, px(18)))

    def _title(self, text: str, color: str = INK) -> None:
        _label(self.body, text, self.t.heading, color).pack(fill="x", pady=(0, self.t.px(8)))

    def _text(self, text: str, color: str = INK, font=None) -> tk.Label:
        lbl = _label(self.body, text, font or self.t.body, color, wraplength=self.t.px(470))
        lbl.pack(fill="x", pady=(0, self.t.px(8)))
        return lbl

    def _button(self, text: str, command: Callable, primary: bool = False, side: str = "right") -> ttk.Button:
        b = ttk.Button(self.buttons, text=text, command=command, style="Primary.TButton" if primary else "TButton")
        b.pack(side=side, padx=(self.t.px(8), 0) if side == "right" else (0, self.t.px(8)))
        return b

    # ------------------------------------------------------------ step 1: check
    def page_check(self) -> None:
        self._clear(0)
        plan = self.plan
        px = self.t.px
        self._title(plan.title)
        grid = tk.Frame(self.body, bg=PANEL)
        grid.pack(fill="x", pady=(0, px(10)))
        for row, (name, data) in enumerate((("Now", plan.current), ("After", plan.target))):
            _label(grid, name, self.t.body, MUTED).grid(row=row, column=0, sticky="w", padx=(0, px(18)), pady=px(2))
            _label(grid, plain_state(data), self.t.body_bold if row else self.t.body).grid(
                row=row, column=1, sticky="w", pady=px(2))
        where = "one unused slot and its checksum" if plan.label != "restore" else "the EDID"
        self._text("{} of 256 bytes change, in {}. Everything else stays as it is. A copy of the current "
                   "EDID is saved first, in {}".format(len(plan.changed), where, short_path(self.app.backup_dir)),
                   MUTED, self.t.small)
        self.hdmi = tk.BooleanVar(value=False)
        self.undo = tk.BooleanVar(value=False)
        box = tk.Frame(self.body, bg=PANEL)
        box.pack(fill="x", pady=(px(6), 0))
        ttk.Checkbutton(box, text="The HDMI cable is unplugged from the Cam Link (USB stays connected)",
                        variable=self.hdmi, command=self._update_write_button).pack(anchor="w", pady=px(2))
        ttk.Checkbutton(box, text="I know I can undo this later with Remove or Restore",
                        variable=self.undo, command=self._update_write_button).pack(anchor="w", pady=px(2))
        self.write_button = self._button("Write to card", self.start_write, primary=True)
        self._button("Cancel", self.close)
        self._update_write_button()

    def _update_write_button(self) -> None:
        ready = self.hdmi.get() and self.undo.get()
        self.write_button.state(["!disabled"] if ready else ["disabled"])

    # ------------------------------------------------------------ step 2: write
    def start_write(self) -> None:
        if self.phase != "check" or not (self.hdmi.get() and self.undo.get()):
            return
        self.phase = "writing"
        self.app.writing = True
        self.page_writing()
        plan, app = self.plan, self.app
        env, directory = app.env, app.backup_dir

        def task():
            with env.open_card() as transport:
                card = protocol.Card(transport, sleep=env.sleep)
                now = card.read_edid_stable()
                if now != plan.current:
                    raise operations.Refused("The card's EDID changed since this window opened. "
                                             "Close it and refresh.")
                backup = operations.save_backup(now, directory, "before-" + plan.label)
                app.post(self._on_backup, backup)
                operations.write_and_verify(card, plan, progress=lambda off: app.post(self._on_progress, off))
            return backup

        app.run_task(task, self._on_written, self._on_write_error)

    def page_writing(self) -> None:
        self._clear(1)
        self._title("Writing to the card")
        self._text("Keep the USB cable connected. This takes about a second.")
        self.progress = ttk.Progressbar(self.body, style="Signal.Horizontal.TProgressbar", maximum=32,
                                        mode="determinate", length=self.t.px(470))
        self.progress.pack(fill="x", pady=(self.t.px(6), self.t.px(6)))
        self.progress_text = self._text("Saving a backup of the current EDID...", MUTED, self.t.small)

    def _on_backup(self, path: Path) -> None:
        self.backup = path
        if not self.closed:
            self.progress_text.configure(text="Backup saved. Writing 32 chunks, each checked before the next.")

    def _on_progress(self, offset: int) -> None:
        if not self.closed:
            self.progress["value"] = offset // 8 + 1
            self.progress_text.configure(text="{} of 32 chunks written and checked".format(offset // 8 + 1))

    def _on_written(self, backup: Path) -> None:
        self.app.writing = False
        self.backup = backup
        self.app.log("{}: written and verified. Backup: {}".format(self.plan.title, backup))
        self.phase = "replug"
        self.page_replug()
        self.start_replug_check()

    def _on_write_error(self, err: BaseException) -> None:
        self.app.writing = False
        self.phase = "done"
        if isinstance(err, protocol.WriteAborted):
            self.app.log("Write stopped: {}".format(err))
            self.page_problem("Write stopped", operations.aborted_explanation(err), str(err), step=1)
        elif isinstance(err, operations.VerificationFailed):
            self.app.log("Check after writing failed: {}".format(err))
            self.page_problem("Check after writing failed",
                              "The write went through, but the card does not report the EDID that was written.",
                              str(err), step=1)
        elif isinstance(err, (operations.Refused,) + operations.device_errors()) and self.backup is None:
            self.app.log("Nothing was written: {}".format(err))
            self.page_nothing_written(err)
        else:
            self.app.log("Unexpected error: {!r}".format(err))
            self.page_problem("Unexpected error", "The tool hit an error it did not expect.", repr(err), step=1)

    # ------------------------------------------------------------ step 3: confirm
    def page_replug(self) -> None:
        self._clear(2)
        self._title("Written and checked. Now confirm it is stored.")
        px = self.t.px
        steps = tk.Frame(self.body, bg=PANEL)
        steps.pack(fill="x", pady=(0, px(8)))
        for n, text in enumerate(("Unplug the Cam Link's USB cable.", "Wait 5 seconds.",
                                  "Plug it back in."), 1):
            _label(steps, "{}.  {}".format(n, text), self.t.body).pack(fill="x", pady=px(1))
        self.replug_text = self._text("Waiting for you to unplug the USB cable...", SIGNAL, self.t.body_bold)
        self._button("Skip this check", self.skip_replug)

    def start_replug_check(self) -> None:
        app, env, target = self.app, self.app.env, self.plan.target
        if env.wait_for_replug is None:
            self._on_replug_done(None)
            return

        def task():
            if not env.wait_for_replug(lambda s: app.post(self._on_replug_status, s), cancel=self.cancel_replug):
                return None
            with env.open_card() as transport:
                return protocol.Card(transport, sleep=env.sleep).read_edid_stable()

        app.run_task(task, self._on_replug_done, self._on_replug_error)

    def _on_replug_status(self, text: str) -> None:
        if not self.closed and self.phase == "replug":
            self.replug_text.configure(text=text.strip())

    def skip_replug(self) -> None:
        self.cancel_replug.set()
        if not self.closed:
            self.replug_text.configure(text="Skipping...")

    def _on_replug_done(self, after: Optional[bytes]) -> None:
        if self.closed:
            self.app.wizard_closed()
            return
        self.phase = "done"
        if after is None:
            self.app.log("Replug check skipped.")
            self.page_done(confirmed=False)
        elif after == self.plan.target:
            self.app.log("Confirmed after reconnecting: {}".format(edid.state_text(after)))
            self.page_done(confirmed=True)
        else:
            self.app.log("After reconnecting the card reports: {}".format(edid.state_text(after)))
            self.page_problem("Not stored as expected",
                              "After reconnecting, the card reports something other than what was written: "
                              "{}.".format(plain_state(after).lower()), "SHA-256 " + edid.sha256(after), step=2)

    def _on_replug_error(self, err: BaseException) -> None:
        if self.closed:
            self.app.wizard_closed()
            return
        self.phase = "done"
        self.app.log("Could not read the card after reconnecting: {}".format(err))
        self.page_done(confirmed=False, note="The card could not be read after reconnecting ({}). "
                                             "Refresh in a moment to check it.".format(err))

    # ------------------------------------------------------------ results
    def page_done(self, confirmed: bool, note: str = "") -> None:
        self._clear(3)
        done_titles = {"add": "1440p60 added", "remove": "1440p60 removed", "restore": "Backup restored"}
        self._title(done_titles[self.plan.label], SIGNAL)
        if confirmed:
            self._text("The card still reports the new EDID after reconnecting, so it is stored.")
        else:
            self._text(note or "Not confirmed yet. Later, unplug the USB cable for 5 seconds, plug it back in "
                               "and press Refresh.")
        self._text("Connect the HDMI cable again.")
        if self.plan.label == "add":
            self._text("On a PS5: Settings > Screen and Video > Video Output > Resolution > 1440p. "
                       "In your capture app, choose 2560 × 1440 at 60 fps.")
        self._button("Close", self.close, primary=True)

    def page_problem(self, title: str, plain: str, detail: str, step: int) -> None:
        self._clear(step)
        px = self.t.px
        self._title(title, DANGER)
        self._text(plain)
        if self.backup:
            _label(self.body, "What to do now (do not retry the write repeatedly):", self.t.body_bold).pack(
                fill="x", pady=(px(4), px(4)))
            for n, line in enumerate(("Unplug the Cam Link's USB cable for 5 seconds and plug it back in.",
                                      "Close this window and check the state in the main window.",
                                      "If it is not what you expect, choose Restore backup... and pick "
                                      "{}".format(self.backup.name)), 1):
                _label(self.body, "{}.  {}".format(n, line), self.t.body, wraplength=px(470)).pack(
                    fill="x", pady=px(1))
        self._text("Details: " + detail, MUTED, self.t.small).pack_configure(pady=(px(10), 0))
        self._button("Close", self.close, primary=True)
        if self.backup:
            self._button("Open backups folder", self.app.open_backups)

    def page_nothing_written(self, err: BaseException) -> None:
        self._clear(0)
        self._title("Nothing was written", WARN)
        self._text(str(err))
        self._button("Close", self.close, primary=True)

    def close(self) -> None:
        if self.phase == "writing":
            return  # never interrupt a write; it finishes in about a second
        if self.closed:
            return
        replug_running = self.phase == "replug"
        self.closed = True
        self.cancel_replug.set()
        try:
            self.win.grab_release()
            self.win.destroy()
        except tk.TclError:
            pass
        # A running replug check calls wizard_closed() itself once it has stopped.
        if not replug_running:
            self.app.wizard_closed()


def main(backup_dir: Optional[Path] = None, env: Optional[operations.Env] = None) -> int:
    _dpi_aware()
    try:
        root = tk.Tk()
    except tk.TclError as err:
        print("Cannot open a window: {}. Use the command line instead: python camlink-edid.py --help".format(err))
        return 1
    app = App(root, env or operations.default_env(), backup_dir or operations.DEFAULT_BACKUP_DIR)
    root.after(200, app.refresh)
    root.mainloop()
    return 0


if __name__ == "__main__":
    sys.exit(main())
