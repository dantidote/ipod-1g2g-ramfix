"""Small native desktop utility; one main action per stage."""
import sys

from . import STOCK_FIRMWARE_REQUIREMENT


class InstallerView:
    def build_interface(self):
        tk, ttk, root = self.tk, self.ttk, self.root
        from tkinter import font
        self.scale = max(1.0, root.winfo_fpixels("1i") / 96)
        self.px = lambda n: round(n * self.scale)
        px = self.px
        self.face = "Helvetica Neue" if sys.platform == "darwin" else "Segoe UI"
        self.bg, self.ink, self.muted = "#f7f7f7", "#252525", "#666666"
        style = ttk.Style(root)
        preferred = "aqua" if sys.platform == "darwin" else "vista"
        if preferred in style.theme_names():
            style.theme_use(preferred)
        font.nametofont("TkDefaultFont").configure(family=self.face, size=10)
        font.nametofont("TkTextFont").configure(family=self.face, size=10)
        style.configure("TButton", font=(self.face, 10), padding=(px(12), px(5)))
        style.configure("TCombobox", font=(self.face, 10), padding=px(4))
        root.title("iPod RAM Fix")
        root.configure(background=self.bg)
        root.geometry("%dx%d" % (px(580), px(440)))
        root.minsize(px(540), px(440))
        root.columnconfigure(0, weight=1)
        root.rowconfigure(0, weight=1)
        page = tk.Frame(root, bg=self.bg, padx=px(30), pady=px(20))
        page.grid(row=0, column=0, sticky="nsew")
        page.columnconfigure(0, weight=1)
        self.label(page, "iPod RAM Fix", 17, True).grid(row=0, column=0, sticky="w")
        self.label(page, "For 8,000+ song libraries on 1st- and 2nd-generation iPods.\n"
                   "Fixes a memory leak in Apple's firmware that can freeze large libraries.", 10,
                   color=self.muted).grid(row=1, column=0, sticky="w", pady=(px(5), px(18)))
        self.label(page, "iPod", 10, True).grid(row=2, column=0, sticky="w", pady=(0, px(7)))
        device_row = tk.Frame(page, bg=self.bg)
        device_row.grid(row=3, column=0, sticky="ew")
        device_row.columnconfigure(0, weight=1)
        self.choice = ttk.Combobox(device_row, state="readonly", width=30)
        self.choice.grid(row=0, column=0, sticky="ew")
        self.choice.bind("<<ComboboxSelected>>", lambda event: self.changed())
        self.refresh_button = ttk.Button(device_row, text="Refresh", command=self.scan)
        self.refresh_button.grid(row=0, column=1, padx=(px(8), 0))
        self.compatibility = self.label(page, STOCK_FIRMWARE_REQUIREMENT +
                                        "\nWindows-formatted iPods only.", 9, color=self.muted)
        self.compatibility.grid(row=4, column=0, sticky="w", pady=(px(7), px(16)))
        self.status_heading = self.label(page, "Connect your iPod", 11, True)
        self.status_heading.grid(row=5, column=0, sticky="w")
        self.status = tk.StringVar(value="Connect with FireWire and close iTunes or Music. Then choose Find iPod.")
        self.status_label = tk.Label(page, textvariable=self.status, background=self.bg, foreground=self.muted,
                                    font=(self.face, 10), justify="left", anchor="nw", height=4)
        self.status_label.grid(row=6, column=0, sticky="ew", pady=(px(6), 0))
        page.bind("<Configure>", lambda e: self.status_label.configure(wraplength=max(px(200), e.width - px(60))))
        self.progress = ttk.Progressbar(page, mode="determinate")
        self.progress.grid(row=7, column=0, sticky="ew", pady=(px(7), 0))
        self.progress.grid_remove()
        page.rowconfigure(8, weight=1)

        footer = tk.Frame(root, bg="#eeeeee", padx=px(24), pady=px(14), highlightthickness=1,
                          highlightbackground="#dddddd")
        footer.grid(row=1, column=0, sticky="ew")
        footer.columnconfigure(1, weight=1)
        self.more = ttk.Menubutton(footer, text="More", direction="above")
        self.more.grid(row=0, column=0, sticky="w")
        self.more_menu = tk.Menu(self.more, tearoff=False)
        self.more.configure(menu=self.more_menu)
        self.more_menu.add_command(label="Restore backup…", command=self.restore)
        self.more_menu.add_command(label="Eject iPod", command=self.eject)
        self.more_menu.add_separator()
        self.more_menu.add_command(label="Help & licenses", command=self.about)
        self.label(footer, "v1 memory fix · Preview", 9, color=self.muted).grid(row=0, column=1, sticky="w", padx=px(10))
        actions = tk.Frame(footer, bg="#eeeeee")
        actions.grid(row=0, column=2, sticky="e")
        self.scan_button = ttk.Button(actions, text="Find iPod", command=self.scan)
        self.check_button = ttk.Button(actions, text="Check iPod", command=self.check)
        self.install_button = ttk.Button(actions, text="Back up and install", command=self.install)
        self.eject_button = ttk.Button(actions, text="Eject iPod", command=self.eject)
        # Recovery remains accessible even when compatibility checking fails.
        self.restore_button = ttk.Button(actions, text="Restore backup…", command=self.restore)
        self.primary_buttons = (self.scan_button, self.check_button, self.install_button,
                                self.eject_button, self.restore_button)
        for button in self.primary_buttons:
            button.grid(row=0, column=0, sticky="e")
            button.grid_remove()
        self.feedback_kind = "info"

    def label(self, parent, text, size=10, bold=False, color=None):
        return self.tk.Label(parent, text=text, background=parent.cget("background"),
                             foreground=color or self.ink, font=(self.face, size, "bold" if bold else "normal"),
                             anchor="w", justify="left", borderwidth=0)

    def feedback(self, title, message, kind="info"):
        self.feedback_kind = kind
        self.status_heading.configure(text=title, foreground="#ae2727" if kind == "error" else self.ink)
        self.status.set(message)

    def update_view(self, device):
        if not device and not self.choice.get():
            self.choice.set("No iPod connected")
        self.refresh_button.configure(state="disabled" if self.busy else "normal")
        self.more_menu.entryconfigure(0, state="normal" if device and not self.busy else "disabled")
        self.more_menu.entryconfigure(1, state="normal" if device and not self.busy else "disabled")
        self.more.configure(state="disabled" if self.busy else "normal")
        already = self.checked and self.checked["state"] in ("v1", "v2")
        if self.busy:
            chosen = {"scan": self.scan_button, "check": self.check_button, "install": self.install_button,
                      "restore": self.restore_button, "eject": self.eject_button}.get(self.action, self.scan_button)
            self.progress.grid()
        elif not device:
            chosen = self.scan_button
            self.progress.grid_remove()
        elif already or (self.feedback_kind == "success" and self.action in ("install", "restore")):
            chosen = self.eject_button
            self.progress.grid_remove()
        elif self.checked:
            chosen = self.install_button
            self.progress.grid_remove()
        else:
            chosen = self.check_button
            self.progress.grid_remove()
        self.primary_button = chosen
        for button in self.primary_buttons:
            button.grid_remove()
        chosen.grid()
