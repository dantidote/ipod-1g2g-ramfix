"""The installer's presentation. Device access stays in the worker."""
import sys

from . import VERSION


class InstallerView:
    BG = "#f1f3f6"
    INK = "#182637"
    MUTED = "#596879"
    BLUE = "#245edb"
    LINE = "#dce2ea"

    def build_interface(self):
        tk, ttk, root = self.tk, self.ttk, self.root
        family = "Helvetica Neue" if sys.platform == "darwin" else "Segoe UI"
        self.font = family
        self.scale = max(1.0, root.winfo_fpixels("1i") / 96)
        px = lambda value: round(value * self.scale)
        root.title("iPod RAM Fix")
        root.configure(background=self.BG)
        root.geometry("%dx%d" % (px(940), px(740)))
        root.minsize(px(860), px(700))
        root.option_add("*Font", (family, 10))
        style = ttk.Style(root)
        style.theme_use("clam")
        style.configure("TButton", font=(family, 10), padding=(12, 6),
                        background="#ffffff", foreground=self.INK,
                        bordercolor=self.LINE, lightcolor="#ffffff", darkcolor="#ffffff")
        style.map("TButton", background=[("active", "#edf2fa"), ("disabled", "#f4f5f7")],
                  foreground=[("disabled", "#8c97a5")])
        style.configure("Primary.TButton", font=(family, 11, "bold"), padding=(18, 9),
                        background=self.BLUE, foreground="white", bordercolor=self.BLUE,
                        lightcolor=self.BLUE, darkcolor=self.BLUE)
        style.map("Primary.TButton", background=[("disabled", "#dce5f6"), ("active", "#194cb9")],
                  foreground=[("disabled", "#778ba9"), ("!disabled", "white")],
                  bordercolor=[("disabled", "#dce5f6")])
        style.configure("Link.TButton", background=self.BG, borderwidth=0,
                        bordercolor=self.BG, lightcolor=self.BG, darkcolor=self.BG,
                        padding=(8, 6), foreground=self.MUTED)
        style.configure("TCombobox", padding=7, fieldbackground="white", background="#edf2fa",
                        bordercolor=self.LINE, arrowsize=13)
        style.map("TCombobox", fieldbackground=[("readonly", "white"), ("disabled", "#f4f5f7")],
                  foreground=[("readonly", self.INK), ("disabled", "#8c97a5")])
        style.configure("Patch.TRadiobutton", background="white", foreground=self.INK,
                        font=(family, 11, "bold"), padding=(0, 3))
        style.map("Patch.TRadiobutton", background=[("active", "white")],
                  foreground=[("disabled", "#8c97a5")])
        style.configure("Fix.Horizontal.TProgressbar", background=self.BLUE,
                        troughcolor="#e7ecf3", borderwidth=0, thickness=4)
        root.columnconfigure(0, weight=1)
        root.rowconfigure(1, weight=1)

        header = tk.Frame(root, bg=self.BG)
        header.grid(row=0, column=0, sticky="ew", padx=26, pady=(20, 17))
        self.label(header, "iPod RAM Fix", size=17, bold=True).pack(side="left")
        self.label(header, "PREVIEW  /  " + VERSION, size=9, color=self.MUTED).pack(side="right")

        body = tk.Frame(root, bg=self.BG)
        body.grid(row=1, column=0, sticky="nsew", padx=26)
        body.columnconfigure(1, weight=1)
        body.rowconfigure(0, weight=1)
        sidebar = tk.Frame(body, bg="#e7edf4", width=px(222))
        sidebar.grid(row=0, column=0, sticky="ns", padx=(0, 22))
        sidebar.pack_propagate(False)
        drawing = tk.Canvas(sidebar, width=px(218), height=px(220), bg="#e7edf4", highlightthickness=0)
        drawing.pack(pady=(14, 0))
        self.draw_ipod(drawing)
        drawing.scale("all", 0, 0, .84, .84)
        drawing.move("all", 17, 0)
        drawing.scale("all", 0, 0, self.scale, self.scale)
        self.label(sidebar, "More music.\nSame iPod.", size=20, bold=True).pack(anchor="w", padx=22)
        self.label(sidebar, "Give your library more room\nto grow with the RAM fix.",
                   color=self.MUTED, size=10).pack(anchor="w", padx=22, pady=(8, 14))
        self.label(sidebar, "MADE FOR", size=8, bold=True, color=self.MUTED).pack(anchor="w", padx=22)
        self.label(sidebar, "1st & 2nd generation\nApple software 1.5\nWindows-formatted iPods",
                   size=10).pack(anchor="w", padx=22, pady=(6, 10))

        content = tk.Frame(body, bg=self.BG)
        content.grid(row=0, column=1, sticky="nsew")
        content.columnconfigure(0, weight=1)
        steps = tk.Frame(content, bg=self.BG)
        steps.grid(row=0, column=0, sticky="ew", pady=(0, 12))
        self.steps = []
        for i, title in enumerate(("CONNECT", "CHECK", "INSTALL")):
            steps.columnconfigure(i, weight=1)
            item = self.label(steps, "%02d  %s" % (i + 1, title), size=9, bold=True)
            item.grid(row=0, column=i, sticky="w")
            self.steps.append(item)

        connection = self.card(content)
        connection.grid(row=1, column=0, sticky="ew")
        connection.columnconfigure(0, weight=1)
        self.label(connection, "YOUR IPOD", size=8, bold=True, color=self.MUTED).grid(
            row=0, column=0, sticky="w")
        self.device_title = self.label(connection, "Connect with FireWire", size=15, bold=True)
        self.device_title.grid(row=1, column=0, sticky="w", pady=(3, 6))
        self.scan_button = ttk.Button(connection, text="Find my iPod", command=self.scan)
        self.scan_button.grid(row=0, column=1, rowspan=2, padx=(12, 0))
        self.choice = ttk.Combobox(connection, state="readonly", width=25)
        self.choice.grid(row=2, column=0, columnspan=2, sticky="ew", pady=(4, 10))
        self.choice.bind("<<ComboboxSelected>>", lambda event: self.changed())
        self.check_button = ttk.Button(connection, text="Check compatibility", command=self.check)
        self.check_button.grid(row=3, column=0, sticky="w")
        self.compatibility = self.label(connection, "Not checked", size=9, color=self.MUTED)
        self.compatibility.grid(row=3, column=1, sticky="e", padx=(10, 0))

        patches = self.card(content)
        patches.grid(row=2, column=0, sticky="ew", pady=(12, 0))
        patches.columnconfigure(0, weight=1)
        self.label(patches, "CHOOSE YOUR PATCH", size=8, bold=True, color=self.MUTED).grid(
            row=0, column=0, sticky="w", pady=(0, 7))
        self.version = tk.StringVar(value="v1")
        self.patch_buttons = []
        options = (("v1", "Memory fix", "RECOMMENDED", "Fixes the library memory leak. Published v1 patch."),
                   ("v2", "Memory fix + larger buffers", "EXPERIMENTAL", "Adds v2 changes. Faster startup is not guaranteed."))
        for i, (value, title, badge, detail) in enumerate(options):
            line = tk.Frame(patches, bg="white")
            line.grid(row=1 + i * 2, column=0, sticky="ew", pady=(5 if i else 0, 0))
            button = ttk.Radiobutton(line, text=title, value=value, variable=self.version,
                                     style="Patch.TRadiobutton", command=self.refresh_buttons)
            button.pack(side="left")
            self.patch_buttons.append(button)
            self.label(line, badge, size=7, bold=True,
                       color="#416649" if i == 0 else "#87662a").pack(side="right", padx=(8, 0))
            self.label(patches, detail, size=9, color=self.MUTED).grid(
                row=2 + i * 2, column=0, sticky="w", padx=(23, 0), pady=(0, 7))
        content.rowconfigure(3, weight=1)
        action = tk.Frame(content, bg=self.BG)
        action.grid(row=4, column=0, sticky="ew", pady=(14, 0))
        self.install_button = ttk.Button(action, text="Back up and install", style="Primary.TButton",
                                         command=self.install)
        self.install_button.pack(fill="x")
        self.label(action, "Your firmware is backed up and every write is verified.", size=9,
                   color=self.MUTED).pack(pady=(7, 0))

        footer = tk.Frame(root, bg=self.BG)
        footer.grid(row=2, column=0, sticky="ew", padx=26, pady=(18, 16))
        footer.columnconfigure(0, weight=1)
        status_panel = self.card(footer, padding=12)
        status_panel.grid(row=0, column=0, sticky="ew")
        self.status_heading = self.label(status_panel, "Ready when you are", size=11, bold=True)
        self.status_heading.pack(anchor="w")
        self.status = tk.StringVar(value="Connect with FireWire and close iTunes or Music, then choose Find my iPod.")
        self.status_label = tk.Label(status_panel, textvariable=self.status, bg="white", fg=self.MUTED,
                                    font=(family, 9), anchor="w", justify="left", wraplength=820)
        self.status_label.pack(fill="x", pady=(3, 8))
        status_panel.bind("<Configure>", lambda event: self.status_label.configure(wraplength=max(200, event.width - 28)))
        progress_track = tk.Frame(status_panel, bg="#e7ecf3", height=4)
        progress_track.pack(fill="x")
        progress_track.pack_propagate(False)
        self.progress = ttk.Progressbar(progress_track, mode="determinate", style="Fix.Horizontal.TProgressbar")
        self.progress.pack(fill="both", expand=True)
        links = tk.Frame(footer, bg=self.BG)
        links.grid(row=1, column=0, sticky="ew", pady=(7, 0))
        self.restore_button = ttk.Button(links, text="Restore backup…", command=self.restore, style="Link.TButton")
        self.restore_button.pack(side="left")
        self.eject_button = ttk.Button(links, text="Eject iPod", command=self.eject, style="Link.TButton")
        self.eject_button.pack(side="left", padx=(8, 0))
        ttk.Button(links, text="Help & licenses", command=self.about, style="Link.TButton").pack(side="right")

    def label(self, parent, text, size=10, bold=False, color=None):
        return self.tk.Label(parent, text=text, bg=parent.cget("background"), fg=color or self.INK,
                             font=(self.font, size, "bold" if bold else "normal"),
                             justify="left", anchor="w", borderwidth=0)

    def card(self, parent, padding=14):
        return self.tk.Frame(parent, bg="white", padx=padding, pady=padding,
                             highlightthickness=1, highlightbackground=self.LINE)

    def draw_ipod(self, canvas):
        # Vector artwork keeps the app sharp without shipping image dependencies.
        def rounded(x1, y1, x2, y2, radius, fill, outline):
            points = [x1 + radius, y1, x2 - radius, y1, x2, y1, x2, y1 + radius,
                      x2, y2 - radius, x2, y2, x2 - radius, y2, x1 + radius, y2,
                      x1, y2, x1, y2 - radius, x1, y1 + radius, x1, y1]
            canvas.create_polygon(points, smooth=True, splinesteps=24, fill=fill, outline=outline, width=1)
        rounded(49, 15, 181, 253, 17, "#d6dee8", "#d6dee8")
        rounded(43, 9, 175, 247, 17, "#fbfcfe", "#c7d1dd")
        rounded(55, 29, 163, 115, 6, "#8c9a86", "#9eab98")
        canvas.create_rectangle(60, 34, 158, 110, fill="#c5d2b2", outline="")
        canvas.create_text(109, 46, text="iPod", font=(self.font, 10, "bold"), fill="#354932")
        canvas.create_line(63, 56, 154, 56, fill="#778b65")
        canvas.create_rectangle(63, 62, 155, 79, fill="#536c46", outline="")
        canvas.create_text(68, 70, text="Music", anchor="w", font=(self.font, 9, "bold"), fill="#eff7de")
        canvas.create_text(151, 70, text=">", anchor="e", font=(self.font, 10), fill="#eff7de")
        canvas.create_text(68, 91, text="Settings", anchor="w", font=(self.font, 9), fill="#354932")
        canvas.create_oval(63, 140, 155, 232, fill="#eef1f5", outline="#d9e0e8")
        canvas.create_oval(82, 159, 136, 213, fill="#fcfdff", outline="#d9e0e8")
        canvas.create_text(109, 132, text="MENU", font=(self.font, 7, "bold"), fill="#8b97a7")
        canvas.create_text(54, 184, text="‹", font=(self.font, 15, "bold"), fill="#8b97a7")
        canvas.create_text(165, 184, text="›", font=(self.font, 15, "bold"), fill="#8b97a7")
        canvas.create_text(109, 239, text="▶ Ⅱ", font=(self.font, 7), fill="#8b97a7")

    def feedback(self, title, message, kind="info"):
        colors = {"info": self.INK, "busy": self.BLUE, "success": "#2f6b49", "error": "#a83c35"}
        self.status_heading.configure(text=title, fg=colors[kind])
        self.status.set(message)

    def update_view(self, device):
        active = 0 if not device else (1 if not self.checked else 2)
        for i, label in enumerate(self.steps):
            label.configure(fg=self.BLUE if i == active else ("#477558" if i < active else "#8994a3"))
        self.device_title.configure(text="Your iPod is connected" if device else "Connect with FireWire")
        if self.checked:
            state = self.checked["state"]
            label = "Compatible" if state == "original" else state.upper() + " installed"
            self.compatibility.configure(text=label, fg="#2f6b49")
        else:
            self.compatibility.configure(text="Checking…" if self.busy and self.action == "check" else "Not checked",
                                         fg=self.MUTED)
        target = self.version.get()
        already = self.checked and (self.checked["state"] == target or
                                    self.checked["state"] == "v2" and target == "v1")
        self.install_button.configure(text="Already up to date" if already else "Back up and install")
