import customtkinter as ctk

from .metadata import fmt_duration

THUMB = (96, 54)
RED, GREEN, GREY = "#ff6b6b", "#4cc38a", "#9aa0a6"


class QueueRow(ctk.CTkFrame):
    def __init__(self, master, job, duration, on_remove, on_retry, on_cancel, default_fmt="MP3"):
        super().__init__(master, corner_radius=8)
        self.job = job
        self._on_remove, self._on_retry, self._on_cancel = on_remove, on_retry, on_cancel
        self.columnconfigure(1, weight=1)

        self.thumb = ctk.CTkLabel(self, text="", width=THUMB[0], height=THUMB[1],
                                  fg_color=("gray80", "gray20"), corner_radius=6)
        self.thumb.grid(row=0, column=0, rowspan=2, padx=10, pady=10)

        top = ctk.CTkFrame(self, fg_color="transparent")
        top.grid(row=0, column=1, sticky="ew", padx=(0, 10), pady=(10, 2))
        top.columnconfigure(0, weight=1)
        title = job.title if len(job.title) <= 80 else job.title[:77] + "…"
        ctk.CTkLabel(top, text=title, anchor="w", font=ctk.CTkFont(weight="bold")
                     ).grid(row=0, column=0, sticky="ew")
        ctk.CTkLabel(top, text=fmt_duration(duration), text_color=GREY, width=50
                     ).grid(row=0, column=1, padx=6)
        self.fmt = ctk.CTkSegmentedButton(top, values=["MP3", "MP4"], width=110)
        self.fmt.set(default_fmt)
        self.fmt.grid(row=0, column=2, padx=6)
        self.btn_retry = ctk.CTkButton(top, text="Retry", width=60, command=lambda: self._on_retry(self))
        self.btn_cancel = ctk.CTkButton(top, text="Cancel", width=60, fg_color="#7a4a1f",
                                        hover_color="#9a5e28", command=lambda: self._on_cancel(self))
        self.btn_retry.grid(row=0, column=3, padx=2)
        self.btn_cancel.grid(row=0, column=4, padx=2)
        self.btn_retry.grid_remove()
        self.btn_cancel.grid_remove()
        ctk.CTkButton(top, text="✕", width=30, fg_color="transparent", border_width=1,
                      text_color=("gray20", "gray80"), command=lambda: self._on_remove(self)
                      ).grid(row=0, column=5, padx=(2, 0))

        bot = ctk.CTkFrame(self, fg_color="transparent")
        bot.grid(row=1, column=1, sticky="ew", padx=(0, 10), pady=(2, 10))
        bot.columnconfigure(5, weight=1)
        ctk.CTkLabel(bot, text="Trim", text_color=GREY).grid(row=0, column=0)
        self.start = ctk.CTkEntry(bot, width=64, placeholder_text="0:00")
        self.start.grid(row=0, column=1, padx=4)
        ctk.CTkLabel(bot, text="to", text_color=GREY).grid(row=0, column=2)
        self.end = ctk.CTkEntry(bot, width=64, placeholder_text="end")
        self.end.grid(row=0, column=3, padx=4)
        self.norm = ctk.CTkCheckBox(bot, text="Normalize", width=20, checkbox_width=18, checkbox_height=18)
        self.norm.grid(row=0, column=4, padx=(10, 10))
        self.bar = ctk.CTkProgressBar(bot)
        self.bar.set(0)
        self.bar.grid(row=0, column=5, sticky="ew", padx=6)
        self.status = ctk.CTkLabel(bot, text="Ready", text_color=GREY, width=210, anchor="w")
        self.status.grid(row=0, column=6)

    # ---- data in/out -------------------------------------------------
    def collect(self):
        """Copy the per-row options into the job."""
        j = self.job
        j.fmt = self.fmt.get().lower()
        j.trim_start = self.start.get().strip()
        j.trim_end = self.end.get().strip()
        j.normalize = bool(self.norm.get())

    def _lock(self, locked: bool):
        state = "disabled" if locked else "normal"
        for w in (self.fmt, self.start, self.end, self.norm):
            w.configure(state=state)

    # ---- state display (main thread only) ----------------------------
    def set_thumb(self, pil_image):
        if not self.winfo_exists():
            return
        img = ctk.CTkImage(light_image=pil_image, dark_image=pil_image, size=THUMB)
        self.thumb.configure(image=img)
        self.thumb.image = img

    def set_queued(self):
        self._lock(True)
        self.bar.set(0)
        self.bar.configure(progress_color=ctk.ThemeManager.theme["CTkProgressBar"]["progress_color"])
        self.status.configure(text="Queued", text_color=GREY)
        self.btn_retry.grid_remove()
        self.btn_cancel.grid()

    def set_progress(self, pct: float, text: str):
        self.bar.set(max(0.0, min(1.0, pct / 100)))
        self.status.configure(text=text, text_color=("gray10", "gray90"))
        self.btn_cancel.grid()

    def set_status(self, text: str):
        self.status.configure(text=text, text_color=("gray10", "gray90"))

    def set_done(self):
        self.bar.set(1)
        self.bar.configure(progress_color=GREEN)
        self.status.configure(text="Done ✓", text_color=GREEN)
        self.btn_cancel.grid_remove()

    def set_error(self, msg: str):
        self._lock(False)
        self.bar.configure(progress_color=RED)
        self.status.configure(text=msg[:60] + ("…" if len(msg) > 60 else ""), text_color=RED)
        self.btn_cancel.grid_remove()
        self.btn_retry.grid()

    def set_cancelled(self):
        self._lock(False)
        self.bar.set(0)
        self.status.configure(text="Cancelled", text_color=GREY)
        self.btn_cancel.grid_remove()
        self.btn_retry.grid()
