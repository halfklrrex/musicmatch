import customtkinter as ctk

from . import theme as t
from .metadata import fmt_duration

THUMB = (96, 54)


class QueueRow(ctk.CTkFrame):
    def __init__(self, master, job, duration, on_remove, on_retry, on_cancel, default_fmt="MP3"):
        super().__init__(master, corner_radius=14, fg_color=t.CARD, border_width=1, border_color=t.SEP)
        self.job = job
        self._on_remove, self._on_retry, self._on_cancel = on_remove, on_retry, on_cancel
        self.columnconfigure(1, weight=1)

        self.thumb = ctk.CTkLabel(self, text="", width=THUMB[0], height=THUMB[1],
                                  fg_color=t.TRACK, corner_radius=8)
        self.thumb.grid(row=0, column=0, rowspan=2, padx=(12, 12), pady=12)

        top = ctk.CTkFrame(self, fg_color="transparent")
        top.grid(row=0, column=1, sticky="ew", padx=(0, 12), pady=(12, 2))
        top.columnconfigure(0, weight=1)
        title = job.title if len(job.title) <= 70 else job.title[:67] + "…"
        t.label(top, title, 13, "semibold", anchor="w").grid(row=0, column=0, sticky="ew")
        t.label(top, fmt_duration(duration), 12, color=t.MUTED, width=50).grid(row=0, column=1, padx=6)
        self.fmt = t.segmented(top, ["MP3", "MP4"], width=104, height=28)
        self.fmt.set(default_fmt)
        self.fmt.grid(row=0, column=2, padx=6)
        self.btn_retry = t.tinted_button(top, "Retry", lambda: self._on_retry(self), width=64, height=26)
        self.btn_cancel = t.tinted_button(top, "Cancel", lambda: self._on_cancel(self), width=68,
                                          height=26, danger=True)
        self.btn_retry.grid(row=0, column=3, padx=2)
        self.btn_cancel.grid(row=0, column=4, padx=2)
        self.btn_retry.grid_remove()
        self.btn_cancel.grid_remove()
        t.circle_button(top, "✕", lambda: self._on_remove(self)).grid(row=0, column=5, padx=(4, 0))

        bot = ctk.CTkFrame(self, fg_color="transparent")
        bot.grid(row=1, column=1, sticky="ew", padx=(0, 12), pady=(2, 12))
        bot.columnconfigure(5, weight=1)
        t.label(bot, "Trim", 12, color=t.MUTED).grid(row=0, column=0)
        self.start = t.entry(bot, 62, 28, "0:00")
        self.start.grid(row=0, column=1, padx=6)
        t.label(bot, "to", 12, color=t.MUTED).grid(row=0, column=2)
        self.end = t.entry(bot, 62, 28, "end")
        self.end.grid(row=0, column=3, padx=6)
        self.norm = t.switch(bot, "Normalize")
        self.norm.grid(row=0, column=4, padx=(12, 12))
        self.bar = ctk.CTkProgressBar(bot, height=6, corner_radius=3, fg_color=t.TRACK,
                                      progress_color=t.ACCENT)
        self.bar.set(0)
        self.bar.grid(row=0, column=5, sticky="ew", padx=6)
        self.status = t.label(bot, "Ready", 12, color=t.MUTED, width=210, anchor="w")
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
        self.thumb.configure(image=img, fg_color="transparent")
        self.thumb.image = img

    def set_queued(self):
        self._lock(True)
        self.bar.set(0)
        self.bar.configure(progress_color=t.ACCENT)
        self.status.configure(text="Queued", text_color=t.MUTED)
        self.btn_retry.grid_remove()
        self.btn_cancel.grid()

    def set_progress(self, pct: float, text: str):
        self.bar.set(max(0.0, min(1.0, pct / 100)))
        self.status.configure(text=text, text_color=t.TEXT)
        self.btn_cancel.grid()

    def set_status(self, text: str):
        self.status.configure(text=text, text_color=t.TEXT)

    def set_done(self):
        self.bar.set(1)
        self.bar.configure(progress_color=t.GREEN)
        self.status.configure(text="Done ✓", text_color=t.GREEN_TEXT)
        self.btn_cancel.grid_remove()

    def set_error(self, msg: str):
        self._lock(False)
        self.bar.configure(progress_color=t.RED)
        self.status.configure(text=msg[:48] + ("…" if len(msg) > 48 else ""), text_color=t.RED_TEXT)
        self.btn_cancel.grid_remove()
        self.btn_retry.grid()

    def set_cancelled(self):
        self._lock(False)
        self.bar.set(0)
        self.status.configure(text="Cancelled", text_color=t.MUTED)
        self.btn_cancel.grid_remove()
        self.btn_retry.grid()
