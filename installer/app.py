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
from .view import InstallerView


def command():
    if getattr(sys, "frozen", False):
        return [sys.executable]
    return [sys.executable, str(Path(__file__).resolve().parents[1] / "install_ipod.py")]


def documentation():
    root = Path(sys._MEIPASS) / "docs" if getattr(sys, "frozen", False) else Path(__file__).resolve().parents[1]
    paths = [root / name for name in ("INSTALLER.md", "LICENSE", "NOTICE.md")]
    paths += sorted((root / "third_party_licenses").glob("*"))
    return {path.name: path.read_text(encoding="utf-8") for path in paths if path.is_file()}


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


class App(InstallerView):
    def __init__(self, root):
        import tkinter as tk
        from tkinter import ttk
        self.root, self.tk, self.ttk = root, tk, ttk
        self.devices, self.checked = [], None
        self.busy = False
        self.messages = queue.Queue()
        self.action = None
        root.protocol("WM_DELETE_WINDOW", self.close)
        self.build_interface()
        self.refresh_buttons()
        root.after(100, self.poll)

    def about(self):
        window = self.tk.Toplevel(self.root)
        window.title("iPod RAM Fix — help and licenses")
        window.geometry("820x650")
        docs = documentation()
        choices = self.ttk.Combobox(window, state="readonly", values=list(docs))
        choices.pack(fill="x", padx=16, pady=12)
        from tkinter.scrolledtext import ScrolledText
        body = ScrolledText(window, wrap="word", padx=12, pady=12)
        body.pack(fill="both", expand=True, padx=16, pady=(0, 16))
        def show(event=None):
            body.configure(state="normal")
            body.delete("1.0", "end")
            body.insert("1.0", docs.get(choices.get(), ""))
            body.configure(state="disabled")
        choices.bind("<<ComboboxSelected>>", show)
        if docs:
            choices.current(0)
            show()

    def selected(self):
        index = self.choice.current()
        return self.devices[index] if 0 <= index < len(self.devices) else None

    def changed(self):
        self.checked = None
        self.feedback("Check your iPod", "Choose Check iPod to verify the firmware before installing.")
        self.refresh_buttons()

    def refresh_buttons(self):
        device = self.selected()
        self.scan_button["state"] = "disabled" if self.busy else "normal"
        for button in (self.check_button, self.restore_button, self.eject_button):
            button["state"] = "normal" if device and not self.busy else "disabled"
        can_install = self.checked and self.checked["state"] == "original"
        self.install_button["state"] = "normal" if device and can_install and not self.busy else "disabled"
        self.choice["state"] = "disabled" if self.busy else "readonly"
        self.update_view(device)

    def start(self, request, callback, message):
        if self.busy:
            return
        self.busy = True
        self.action = request["action"]
        self.feedback(message, "Please keep the iPod connected. Checking and verification can take several minutes.", "busy")
        self.progress.configure(mode="indeterminate", value=0)
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
            self.progress.configure(mode="determinate", value=0)
            if error:
                from tkinter import messagebox
                self.checked = None
                if getattr(self, "last_backup", None):
                    error += "\nSelected backup folder: " + self.last_backup
                self.feedback("Operation stopped", error if len(error) <= 220 else error[:217] + "…", "error")
                messagebox.showerror("Operation stopped", error, parent=self.root)
            else:
                callback(result)
                self.progress.configure(mode="determinate", value=100)
            self.refresh_buttons()
        self.root.after(100, self.poll)

    def request(self, action):
        device = self.selected()
        request = {"action": action, "device_id": device["id"], "identity": device["identity"]}
        if action == "install":
            request["version"] = "v1"
        return request

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
                self.feedback("iPod found", "Choose Check iPod to verify the firmware before installing.", "success")
            else:
                self.feedback("No iPod found", "Check the FireWire cable and power. On Mac, FireWire requires macOS Sequoia 15 or earlier.")
        self.start({"action": "scan"}, done, "Looking for supported iPods.")

    def check(self):
        def done(result):
            self.checked = result
            if result["state"] == "original":
                self.feedback("Compatibility confirmed", "Ready to install the v1 memory leak fix. Choose Back up and install.", "success")
            else:
                self.feedback("Memory fix already installed", "No installation is needed. You can eject your iPod.", "success")
        self.start(self.request("check"), done, "Checking the installed firmware.")

    def install(self):
        from tkinter import filedialog, messagebox
        parent = filedialog.askdirectory(title="Save a firmware backup on your computer", parent=self.root)
        if not parent:
            return
        label = self.choice.get()
        if not messagebox.askokcancel("Install RAM fix?", "Install the v1 memory leak fix on:\n%s\n\n"
                "Your firmware will be backed up first. The music partition will not be written.\n"
                "Keep power and FireWire connected until verification finishes.\n\n"
                "This is experimental software. Continue?" % label, parent=self.root):
            return
        folder = Path(tempfile.mkdtemp(prefix="iPod-backup-" + time.strftime("%Y%m%d-") , dir=parent))
        request = self.request("install")
        request.update(backup_folder=str(folder),
                       checked_sha256=self.checked["prefix_sha256"])
        self.last_backup = str(folder)
        def done(result):
            self.checked = None
            self.feedback("Installation verified", result["message"] + "\nBackup: " + str(folder), "success")
        self.start(request, done, "Backing up and installing")

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
            self.feedback("Backup restored", result["message"], "success")
        self.start(request, done, "Restoring the saved firmware.")

    def eject(self):
        def done(result):
            self.devices, self.checked = [], None
            self.choice.set("")
            self.choice["values"] = []
            self.feedback("Safe to unplug", result["message"], "success")
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
        docs = documentation()
        if not all(name in docs for name in ("INSTALLER.md", "LICENSE", "Python-LICENSE.txt", "Tcl-license.terms")):
            raise RuntimeError("Bundled help or license notices are missing")
        result["bundled_documentation"] = "passed"
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
    if sys.platform == "win32":
        # Let Tk render at the display's resolution instead of bitmap stretching.
        ctypes.windll.shcore.SetProcessDpiAwareness(1)
    import tkinter as tk
    root = tk.Tk()
    app = App(root)
    if args.ui_smoke_test:
        root.update()
        result = {"ui": "passed", "device_access": False,
                  "install_disabled_without_check": str(app.install_button["state"]) == "disabled"}
        # Exercise the fixed v1 install request and write guards offline.
        app.devices = [{"id": "offline-ui-check", "identity": {"offline": True}}]
        app.choice["values"] = ["Offline UI check"]
        app.choice.current(0)
        app.refresh_buttons()
        if str(app.install_button["state"]) != "disabled":
            raise RuntimeError("An unchecked device enabled installation")
        app.checked = {"state": "original"}
        app.refresh_buttons()
        if app.request("install")["version"] != "v1" or str(app.install_button["state"]) != "normal":
            raise RuntimeError("The interface did not offer the v1 memory fix")
        for installed in ("v1", "v2"):
            app.checked = {"state": installed}
            app.refresh_buttons()
            if str(app.install_button["state"]) != "disabled":
                raise RuntimeError("The interface allowed an unnecessary install or downgrade")
        app.busy = True
        app.action = "install"
        app.refresh_buttons()
        controls = [app.scan_button, app.refresh_button, app.check_button, app.install_button,
                    app.restore_button, app.eject_button, app.choice, app.more]
        if any(str(widget["state"]) != "disabled" for widget in controls):
            raise RuntimeError("Device controls remained active during an operation")
        if any(app.more_menu.entrycget(i, "state") != "disabled" for i in (0, 1)):
            raise RuntimeError("Recovery or eject remained available during an operation")
        app.busy = False
        app.checked = None
        app.action = "install"
        app.feedback("Installation verified", "Offline UI check", "success")
        app.refresh_buttons()
        if app.primary_button is not app.eject_button:
            raise RuntimeError("Completed installation did not offer eject")
        app.feedback("Operation stopped", "Offline UI check", "error")
        app.refresh_buttons()
        if app.primary_button is not app.check_button or app.more_menu.entrycget(0, "state") != "normal":
            raise RuntimeError("Recovery was not available after a failed check")
        result["v1_only_and_busy_guards"] = "passed"
        root.destroy()
        if args.result:
            durable_new(args.result, json.dumps(result).encode())
        elif sys.stdout:
            print(json.dumps(result))
        return
    root.mainloop()
