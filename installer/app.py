"""Desktop interface and narrowly scoped elevated worker entry point."""
import argparse
import ctypes
import json
import os
from pathlib import Path
import queue
import shlex
import subprocess
import sys
import tempfile
import threading
import time
import traceback

from . import VERSION
from .core import durable_new


def command():
    if getattr(sys, "frozen", False):
        return [sys.executable]
    return [sys.executable, str(Path(__file__).resolve().parents[1] / "install_ipod.py")]


def worker(path):
    from .service import execute
    folder = Path(path).resolve().parent
    request = json.loads(Path(path).read_text(encoding="utf-8"))
    events = []
    def event(message):
        events.append(message)
    try:
        result = {"ok": True, "result": execute(request, event)}
    except Exception as error:
        result = {"ok": False, "error": str(error), "details": traceback.format_exc()}
    result["events"] = events
    durable_new(folder / "response.json", (json.dumps(result, indent=2) + "\n").encode())


def perform(request):
    with tempfile.TemporaryDirectory(prefix="ipod-ramfix-") as temporary:
        folder = Path(temporary)
        job = folder / "request.json"
        durable_new(job, json.dumps(request).encode())
        args = command() + ["--worker", str(job)]
        if sys.platform == "darwin" and os.geteuid() != 0 and request["action"] != "scan":
            # Pass the complete shell command as an argv item, never interpolate
            # file paths into AppleScript source. shlex protects shell arguments.
            script = "on run argv\n do shell script (item 1 of argv) with administrator privileges\nend run"
            args = ["/usr/bin/osascript", "-e", script, shlex.join(args)]
        options = {"creationflags": subprocess.CREATE_NO_WINDOW} if os.name == "nt" else {}
        # No timeout: never kill a worker that may be writing or rolling back.
        result = subprocess.run(args, capture_output=True, **options)
        response = folder / "response.json"
        if not response.exists():
            raise RuntimeError((result.stderr or result.stdout).decode("utf-8", "replace").strip()
                               or "The operation did not finish. If writing had started, keep your backup and use Restore backup.")
        data = json.loads(response.read_text())
        if not data["ok"]:
            raise RuntimeError(data["error"])
        return data["result"]


class App:
    def __init__(self, root):
        import tkinter as tk
        from tkinter import ttk
        self.root, self.tk, self.ttk = root, tk, ttk
        self.devices, self.checked = [], None
        self.busy = False
        self.messages = queue.Queue()
        root.title("iPod RAM Fix — preview")
        root.minsize(700, 580)
        root.geometry("760x620")
        root.protocol("WM_DELETE_WINDOW", self.close)
        panel = ttk.Frame(root, padding=24)
        panel.pack(fill="both", expand=True)
        ttk.Label(panel, text="Give your iPod room for its library", font=("", 19, "bold")).pack(anchor="w")
        ttk.Label(panel, text="Experimental installer • " + VERSION, padding=(0, 8)).pack(anchor="w")
        ttk.Label(panel, text="First- and second-generation FireWire iPods running Apple software 1.5.\n"
                  "This preview supports Windows-formatted iPods on both Windows and Mac.\n"
                  "Close iTunes and other iPod apps. Keep a separate copy of your music.",
                  wraplength=680, justify="left").pack(anchor="w", pady=(0, 18))
        self.scan_button = ttk.Button(panel, text="1. Find my iPod", command=self.scan)
        self.scan_button.pack(anchor="w")
        self.choice = ttk.Combobox(panel, state="readonly")
        self.choice.pack(fill="x", pady=10)
        self.choice.bind("<<ComboboxSelected>>", lambda event: self.changed())
        self.check_button = ttk.Button(panel, text="2. Check compatibility", command=self.check)
        self.check_button.pack(anchor="w")
        self.version = ttk.Combobox(panel, state="readonly", values=(
            "Memory leak fix (v1 — published patch)", "Memory fix + larger buffers (v2 — experimental)"))
        self.version.current(0)
        self.version.pack(fill="x", pady=10)
        self.version.bind("<<ComboboxSelected>>", lambda event: self.refresh_buttons())
        self.install_button = ttk.Button(panel, text="3. Back up and install", command=self.install)
        self.install_button.pack(anchor="w")
        ttk.Separator(panel).pack(fill="x", pady=18)
        row = ttk.Frame(panel)
        row.pack(fill="x")
        self.restore_button = ttk.Button(row, text="Restore backup…", command=self.restore)
        self.restore_button.pack(side="left")
        self.eject_button = ttk.Button(row, text="Eject iPod", command=self.eject)
        self.eject_button.pack(side="left", padx=12)
        self.progress = ttk.Progressbar(panel, mode="indeterminate")
        self.progress.pack(fill="x", pady=(18, 10))
        self.status = tk.StringVar(value="Connect your iPod with FireWire, then choose Find my iPod.")
        ttk.Label(panel, textvariable=self.status, wraplength=680, justify="left").pack(anchor="w")
        ttk.Label(panel, text="No firmware downloads. Your backup stays on your computer.\n"
                  "The new installer is a preview; its Mac device-writing path needs a hardware trial.",
                  wraplength=680, justify="left").pack(anchor="w", side="bottom", pady=(14, 0))
        self.refresh_buttons()
        root.after(100, self.poll)

    def selected(self):
        index = self.choice.current()
        return self.devices[index] if 0 <= index < len(self.devices) else None

    def changed(self):
        self.checked = None
        self.status.set("Choose Check compatibility before installing.")
        self.refresh_buttons()

    def refresh_buttons(self):
        device = self.selected()
        self.scan_button["state"] = "disabled" if self.busy else "normal"
        for button in (self.check_button, self.restore_button, self.eject_button):
            button["state"] = "normal" if device and not self.busy else "disabled"
        target = ("v1", "v2")[max(0, self.version.current())]
        can_install = self.checked and self.checked["state"] != target and not (
            self.checked["state"] == "v2" and target == "v1")
        self.install_button["state"] = "normal" if device and can_install and not self.busy else "disabled"
        for choice in (self.choice, self.version):
            choice["state"] = "disabled" if self.busy else "readonly"

    def start(self, request, callback, message):
        if self.busy:
            return
        self.busy = True
        self.status.set(message + " Please keep the iPod connected.")
        self.refresh_buttons()
        self.progress.start(12)
        def work():
            try:
                self.messages.put((callback, perform(request), None))
            except Exception as error:
                self.messages.put((callback, None, str(error)))
        threading.Thread(target=work, daemon=False).start()

    def poll(self):
        try:
            callback, result, error = self.messages.get_nowait()
        except queue.Empty:
            pass
        else:
            self.busy = False
            self.progress.stop()
            if error:
                from tkinter import messagebox
                self.checked = None
                if getattr(self, "last_backup", None):
                    error += "\nSelected backup folder: " + self.last_backup
                self.status.set(error)
                messagebox.showerror("Operation stopped", error, parent=self.root)
            else:
                callback(result)
            self.refresh_buttons()
        self.root.after(100, self.poll)

    def request(self, action):
        device = self.selected()
        return {"action": action, "device_id": device["id"], "identity": device["identity"]}

    def scan(self):
        self.checked = None
        def done(result):
            self.devices = result["devices"]
            self.choice["values"] = ["%s · %.1f GB · ID …%s" % (
                d["identity"]["model"], d["identity"]["size"] / 1e9,
                d["identity"]["hardware_id"][-6:]) for d in self.devices]
            self.choice.set("")
            if self.devices:
                self.choice.current(0)
                self.status.set("iPod found. Check compatibility next.")
            else:
                self.status.set("No supported FireWire iPod found. Check the cable, power and FireWire support. "
                                "Card readers, USB-only iPods and internal disks are not eligible.")
        self.start({"action": "scan"}, done, "Looking for supported iPods.")

    def check(self):
        def done(result):
            self.checked = result
            self.status.set(result["message"] + ". Choose a patch, then Back up and install.")
        self.start(self.request("check"), done, "Checking the installed firmware.")

    def install(self):
        from tkinter import filedialog, messagebox
        parent = filedialog.askdirectory(title="Save a firmware backup on your computer", parent=self.root)
        if not parent:
            return
        version = ("v1", "v2")[self.version.current()]
        device = self.selected()
        label = self.choice.get()
        if not messagebox.askokcancel("Install RAM fix?", "Install %s on:\n%s\n\n"
                "Your firmware will be backed up first. The music partition will not be written.\n"
                "Keep power and FireWire connected until verification finishes.\n\n"
                "This is experimental software. Continue?" % (version, label), parent=self.root):
            return
        folder = Path(tempfile.mkdtemp(prefix="iPod-backup-" + time.strftime("%Y%m%d-") , dir=parent))
        request = self.request("install")
        request.update(backup_folder=str(folder), version=version,
                       checked_sha256=self.checked["prefix_sha256"])
        self.last_backup = str(folder)
        def done(result):
            self.checked = None
            self.status.set(result["message"] + "\nBackup: " + str(folder))
        self.start(request, done, "Backing up and installing. Backup folder: " + str(folder) + ".")

    def restore(self):
        from tkinter import filedialog, messagebox
        manifest = filedialog.askopenfilename(title="Select this iPod's backup.json", parent=self.root,
                                               filetypes=[("Firmware backup", "backup.json")])
        if not manifest:
            return
        if not messagebox.askokcancel("Restore firmware?", "Restore the saved firmware to:\n" +
                self.choice.get() + "\n\nThe backup must belong to this iPod. "
                "It returns to the version saved before that installation.", parent=self.root):
            return
        request = self.request("restore")
        request["backup_folder"] = str(Path(manifest).parent)
        def done(result):
            self.checked = None
            self.status.set(result["message"])
        self.start(request, done, "Restoring the saved firmware.")

    def eject(self):
        def done(result):
            self.devices, self.checked = [], None
            self.choice.set("")
            self.choice["values"] = []
            self.status.set(result["message"])
        self.start(self.request("eject"), done, "Ejecting the iPod.")

    def close(self):
        if self.busy:
            from tkinter import messagebox
            messagebox.showinfo("Operation in progress", "Wait for the operation to finish before closing.",
                                parent=self.root)
        else:
            self.root.destroy()


def main():
    parser = argparse.ArgumentParser(description="iPod RAM Fix desktop installer")
    parser.add_argument("--worker", type=Path, help=argparse.SUPPRESS)
    parser.add_argument("--self-test", action="store_true", help="Offline import check; no device access")
    parser.add_argument("--ui-smoke-test", action="store_true", help="Open/close the interface without device access")
    parser.add_argument("--result", type=Path)
    args = parser.parse_args()
    if args.worker:
        worker(args.worker)
        return
    if args.self_test:
        from . import core, devices, service
        result = {"version": VERSION, "platform": sys.platform, "imports": "passed", "device_access": False}
        if args.result:
            durable_new(args.result, json.dumps(result).encode())
        elif sys.stdout:
            print(json.dumps(result))
        return
    if not args.ui_smoke_test and sys.platform == "win32" and not ctypes.windll.shell32.IsUserAnAdmin():
        code = ctypes.windll.shell32.ShellExecuteW(None, "runas", command()[0],
                    subprocess.list2cmdline(command()[1:]), None, 1)
        if code <= 32:
            raise RuntimeError("Administrator access is required to inspect the iPod. No firmware changed.")
        return
    import tkinter as tk
    root = tk.Tk()
    app = App(root)
    if args.ui_smoke_test:
        root.update()
        result = {"ui": "passed", "device_access": False,
                  "install_disabled_without_check": str(app.install_button["state"]) == "disabled"}
        root.destroy()
        if args.result:
            durable_new(args.result, json.dumps(result).encode())
        elif sys.stdout:
            print(json.dumps(result))
        return
    root.mainloop()
