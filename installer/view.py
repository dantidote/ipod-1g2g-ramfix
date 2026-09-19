"""A compact, early-iPod utility with a functional monochrome display."""
import sys

from . import VERSION


class InstallerView:
    BG = "#d8d9d5"
    INK = "#262922"
    MUTED = "#5c6057"
    LCD = "#bbc59d"
    LCD_INK = "#29351d"

    def build_interface(self):
        tk, ttk, root = self.tk, self.ttk, self.root
        self.font = "Lucida Grande" if sys.platform == "darwin" else "Tahoma"
        self.mono = "Monaco" if sys.platform == "darwin" else "Lucida Console"
        self.scale = max(1.0, root.winfo_fpixels("1i") / 96)
        px = lambda n: round(n * self.scale)
        root.title("iPod RAM Fix")
        root.geometry("%dx%d" % (px(780), px(510)))
        root.minsize(px(740), px(490))
        root.configure(background=self.BG)
        root.option_add("*Font", (self.font, 10))
        self.make_styles()
        root.columnconfigure(0, weight=1)
        root.rowconfigure(1, weight=1)

        # A faint satin finish lives behind real controls, never a screenshot.
        surface = tk.Canvas(root, background=self.BG, highlightthickness=0)
        surface.place(x=0, y=0, relwidth=1, relheight=1)
        def shade(event):
            surface.delete("grain")
            for y in range(0, event.height, 2):
                value = 224 - round(14 * y / max(1, event.height)) + (y % 6 == 0)
                color = "#%02x%02x%02x" % (value, value + 1, value - 2)
                surface.create_line(0, y, event.width, y, fill=color, tags="grain")
        surface.bind("<Configure>", shade)

        bezel = tk.Frame(root, bg="#92968a", relief="sunken", borderwidth=3)
        bezel.grid(row=0, column=0, sticky="ew", padx=px(20), pady=(px(20), px(17)))
        screen = tk.Frame(bezel, bg=self.LCD, padx=px(16), pady=px(13),
                          highlightthickness=1, highlightbackground="#6f795c")
        screen.pack(fill="both", expand=True)
        screen.columnconfigure(1, weight=1)
        icon = tk.Canvas(screen, bg=self.LCD, width=px(61), height=px(95), highlightthickness=0)
        icon.grid(row=0, column=0, rowspan=3, sticky="n", padx=(0, px(19)), pady=px(4))
        self.draw_ipod(icon)
        icon.scale("all", 0, 0, self.scale, self.scale)
        self.label(screen, "iPod RAM Fix", size=17, bold=True, mono=True, color=self.LCD_INK).grid(
            row=0, column=1, sticky="w", pady=(0, px(8)))
        self.status_heading = self.label(screen, "Connect your iPod", size=14, bold=True,
                                          mono=True, color=self.LCD_INK)
        self.status_heading.grid(row=1, column=1, sticky="w")
        self.status = tk.StringVar(value="Connect with FireWire, then find your device.")
        self.status_label = tk.Label(screen, textvariable=self.status, bg=self.LCD, fg=self.LCD_INK,
                                    font=(self.mono, 9), justify="left", anchor="nw", height=4)
        self.status_label.grid(row=2, column=1, sticky="ew", pady=(px(6), 0))
        screen.bind("<Configure>", lambda e: self.status_label.configure(wraplength=max(px(200), e.width - px(119))))
        tk.Frame(screen, bg="#87916b", height=1).grid(row=3, column=0, columnspan=2, sticky="ew", pady=(px(6), px(7)))
        self.display_detail = self.label(screen, "1st & 2nd generation / Apple software 1.5",
                                          size=8, mono=True, color=self.LCD_INK)
        self.display_detail.grid(row=4, column=0, columnspan=2, sticky="w")
        track = tk.Frame(screen, bg="#a7b38a", height=px(7))
        track.grid(row=5, column=0, columnspan=2, sticky="ew", pady=(px(8), 0))
        track.pack_propagate(False)
        self.progress = ttk.Progressbar(track, mode="determinate", style="LCD.Horizontal.TProgressbar")
        self.progress.pack(fill="both", expand=True)

        device = self.section(root, " Device ")
        device.grid(row=1, column=0, sticky="nsew", padx=px(20), pady=(0, px(13)))
        device.columnconfigure(0, weight=1)
        self.choice = ttk.Combobox(device, state="readonly", width=28)
        self.choice.grid(row=0, column=0, sticky="ew", padx=(0, px(12)), pady=(0, px(9)))
        self.choice.bind("<<ComboboxSelected>>", lambda event: self.changed())
        self.scan_button = ttk.Button(device, text="Find iPod", command=self.scan, style="Metal.TButton")
        self.scan_button.grid(row=0, column=1, sticky="ew", pady=(0, px(9)))
        check_row = tk.Frame(device, bg=self.BG)
        check_row.grid(row=1, column=0, columnspan=2, sticky="ew")
        self.check_button = ttk.Button(check_row, text="Check compatibility", command=self.check, style="Metal.TButton")
        self.check_button.pack(side="left")
        self.compatibility = self.label(check_row, "Not checked", size=9, color=self.MUTED)
        self.compatibility.pack(side="left", padx=px(12))

        bottom = tk.Frame(root, bg=self.BG)
        bottom.grid(row=2, column=0, sticky="ew", padx=px(20), pady=(0, px(13)))
        tk.Frame(bottom, bg="#a4a69e", height=1).pack(fill="x")
        tk.Frame(bottom, bg="#f6f6f3", height=1).pack(fill="x")
        self.label(bottom, "Memory leak fix · v1", size=9, color=self.MUTED).pack(anchor="w", pady=(px(10), 0))
        actions = tk.Frame(bottom, bg=self.BG)
        actions.pack(fill="x", pady=(px(9), px(10)))
        self.eject_button = ttk.Button(actions, text="Eject iPod", command=self.eject, style="Metal.TButton")
        self.eject_button.pack(side="left")
        self.restore_button = ttk.Button(actions, text="Restore backup…", command=self.restore, style="Metal.TButton")
        self.restore_button.pack(side="left", padx=px(10))
        self.install_button = ttk.Button(actions, text="Back up and install", command=self.install,
                                         style="Graphite.TButton")
        self.install_button.pack(side="right")
        footer = tk.Frame(bottom, bg=self.BG)
        footer.pack(fill="x")
        self.label(footer, "Preview  /  " + VERSION, size=8, color=self.MUTED).pack(side="left")
        ttk.Button(footer, text="Help & licenses", command=self.about, style="Quiet.TButton").pack(side="right")

    def label(self, parent, text, size=10, bold=False, color=None, mono=False):
        return self.tk.Label(parent, text=text, bg=parent.cget("background"), fg=color or self.INK,
                             font=(self.mono if mono else self.font, size, "bold" if bold else "normal"),
                             justify="left", anchor="w", borderwidth=0)

    def section(self, parent, text):
        return self.tk.LabelFrame(parent, text=text, bg=self.BG, fg=self.INK,
                                  font=(self.font, 10, "bold"), relief="groove", borderwidth=2,
                                  padx=round(12 * self.scale), pady=round(10 * self.scale))

    def make_styles(self):
        style = self.ttk.Style(self.root)
        style.theme_use("clam")
        style.configure(".", background=self.BG, foreground=self.INK, font=(self.font, 10))
        self._button_images = []
        for name, colors in (
            ("Metal", ("#fbfbf8", "#bfc1ba", "#868b80")),
            ("Graphite", ("#686d62", "#353b30", "#23291f")),
        ):
            normal = self.button_image(*colors)
            active = self.button_image("#eef2e5" if name == "Metal" else "#7b836f",
                                       "#c5ccb9" if name == "Metal" else "#434c37", "#69715e")
            pressed = self.button_image("#a8afa0" if name == "Metal" else "#303629",
                                        "#d4d9cb" if name == "Metal" else "#505a43", "#5c6452")
            disabled = self.button_image("#e4e5df", "#cdd0c6", "#a9ada0")
            self._button_images.extend((normal, active, pressed, disabled))
            style.element_create(name + ".button", "image", normal,
                                 ("disabled", disabled), ("pressed", pressed), ("active", active),
                                 border=4, sticky="nsew")
            style.layout(name + ".TButton", [(name + ".button", {
                "sticky": "nsew", "children": [("Button.focus", {
                    "sticky": "nsew", "children": [("Button.padding", {
                        "sticky": "nsew", "children": [("Button.label", {"sticky": "nsew"})]})]})]})])
            style.configure(name + ".TButton", font=(self.font, 10, "bold" if name == "Graphite" else "normal"),
                            padding=(round(17 * self.scale), round(7 * self.scale)),
                            foreground="#ffffff" if name == "Graphite" else self.INK,
                            focuscolor="#e6eadf" if name == "Graphite" else "#626957")
            style.map(name + ".TButton", foreground=[("disabled", "#777e6d")])
        style.configure("Quiet.TButton", background=self.BG, foreground=self.MUTED,
                        font=(self.font, 9), padding=(3, 2), borderwidth=0,
                        bordercolor=self.BG, lightcolor=self.BG, darkcolor=self.BG)
        style.map("Quiet.TButton", background=[("active", "#e6e8de")])
        style.configure("TCombobox", fieldbackground="#f1f3ea", background="#d4d8cb",
                        foreground=self.INK, bordercolor="#92998a", arrowcolor=self.INK,
                        padding=round(6 * self.scale), arrowsize=round(12 * self.scale))
        style.map("TCombobox", fieldbackground=[("readonly", "#f1f3ea"), ("disabled", "#dce0d3")],
                  foreground=[("disabled", "#777e6d"), ("readonly", self.INK)])
        style.configure("LCD.Horizontal.TProgressbar", background="#495938",
                        troughcolor="#a7b38a", bordercolor="#89976c", borderwidth=0,
                        lightcolor="#495938", darkcolor="#495938")

    def button_image(self, top, bottom, border):
        # Small nine-slice skins give native ttk buttons a tactile bevel.
        width, height = 24, 32
        image = self.tk.PhotoImage(master=self.root, width=width, height=height)
        a = tuple(int(top[i:i + 2], 16) for i in (1, 3, 5))
        b = tuple(int(bottom[i:i + 2], 16) for i in (1, 3, 5))
        for y in range(height):
            inset = 3 if y in (0, height - 1) else (1 if y in (1, height - 2) else 0)
            fill = "#%02x%02x%02x" % tuple(round(a[i] + (b[i] - a[i]) * y / (height - 1)) for i in range(3))
            image.put(border, to=(inset, y, width - inset, y + 1))
            if 0 < y < height - 1:
                image.put(fill, to=(inset + 1, y, width - inset - 1, y + 1))
        image.put(top, to=(3, 1, width - 3, 2))
        return image

    def draw_ipod(self, canvas):
        c = self.LCD_INK
        # The original player's silhouette, drawn as an LCD-sized line glyph.
        canvas.create_polygon(15, 2, 46, 2, 53, 9, 53, 84, 46, 91, 15, 91, 8, 84, 8, 9,
                              fill="", outline=c, width=3)
        canvas.create_rectangle(15, 12, 46, 38, fill=c, outline=c)
        canvas.create_oval(15, 47, 46, 78, fill=c, outline=c)
        canvas.create_oval(25, 57, 36, 68, fill=self.LCD, outline=self.LCD)

    def feedback(self, title, message, kind="info"):
        self.status_heading.configure(text=title, fg=self.LCD_INK)
        self.status.set(message)

    def update_view(self, device):
        if not device and not self.choice.get():
            self.choice.set("No iPod selected")
        if self.checked:
            state = self.checked["state"]
            self.compatibility.configure(text="Compatible firmware" if state == "original" else "Memory fix already installed")
            self.display_detail.configure(text="Firmware checked / backup required before writing" if state == "original"
                                          else "Memory fix present / no installation needed")
        else:
            self.compatibility.configure(text="Checking…" if self.busy and self.action == "check" else "Not checked")
            self.display_detail.configure(text="1st & 2nd generation / Apple software 1.5")
        already = self.checked and self.checked["state"] in ("v1", "v2")
        self.install_button.configure(text="Already up to date" if already else "Back up and install")
