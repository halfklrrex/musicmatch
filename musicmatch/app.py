import io
import itertools
import os
import queue
import subprocess
import threading
import urllib.request
from pathlib import Path
from tkinter import TclError, filedialog

import customtkinter as ctk
from PIL import Image

from . import history, metadata
from .clipboard import extract_urls
from .downloader import Job, Manager, parse_time, update_ytdlp
from . import theme as t
from .queue_row import QueueRow
from .settings import Settings

KBPS = ["128", "192", "320"]
HEIGHTS = ["Best", "1080", "720", "480", "360"]
PARALLEL = ["1", "2", "3", "4"]
GREY, GREEN, RED = t.MUTED, t.GREEN_TEXT, t.RED_TEXT


class App(ctk.CTk):
    def __init__(self):
        t.load_fonts()
        ctk.set_appearance_mode("light")
        super().__init__()
        self.title("MusicMatch")
        self.settings = Settings()
        self.geometry(self.settings["geometry"] or "1040x760")
        self.minsize(860, 520)

        self.ui_q = queue.Queue()
        self.manager = Manager(self._emit, int(self.settings["parallel"]))
        self.rows = []
        self.rows_by_job = {}
        self._ids = itertools.count(1)
        self._fetching = 0
        self._seen_clip = set()
        self._clip_new = []

        self._build()
        self.after(100, self._pump)
        self.bind("<FocusIn>", self._on_focus)
        self.protocol("WM_DELETE_WINDOW", self._close)

    # ------------------------------------------------------------ layout
    def _build(self):
        self.configure(fg_color=t.BG)
        self.columnconfigure(0, weight=1)
        self.rowconfigure(4, weight=1)

        head = ctk.CTkFrame(self, fg_color="transparent")
        head.grid(row=0, column=0, sticky="ew", padx=24, pady=(20, 0))
        t.label(head, "MusicMatch", 26, "semibold").grid(row=0, column=0, sticky="w")
        t.label(head, "Paste a YouTube link, get an MP3 or MP4.", 12, color=t.MUTED
                ).grid(row=1, column=0, sticky="w")

        self.banner = ctk.CTkFrame(self, fg_color=t.TINT, corner_radius=14)
        self.banner.columnconfigure(0, weight=1)
        self.banner_label = t.label(self.banner, "", 12, "medium", color=t.ACCENT, anchor="w")
        self.banner_label.grid(row=0, column=0, sticky="ew", padx=14, pady=10)
        t.primary_button(self.banner, "Add", self._banner_add, width=60, height=28).grid(row=0, column=1, padx=4)
        ctk.CTkButton(self.banner, text="Dismiss", width=70, height=28, corner_radius=14,
                      fg_color="transparent", hover_color=t.TINT_HOVER, text_color=t.ACCENT,
                      font=t.font(12, "medium"), command=self._banner_hide
                      ).grid(row=0, column=2, padx=(2, 10))

        bar = ctk.CTkFrame(self, fg_color="transparent")
        bar.grid(row=2, column=0, sticky="ew", padx=24, pady=(14, 8))
        bar.columnconfigure(0, weight=1)
        self.url_entry = t.entry(bar, 200, 40, "Paste YouTube video or playlist URL(s) here…", on_card=False)
        self.url_entry.configure(corner_radius=12)
        self.url_entry.grid(row=0, column=0, sticky="ew")
        self.url_entry.bind("<Return>", lambda e: self._add_from_entry())
        t.tinted_button(bar, "Paste", self._paste, width=76, height=40).grid(row=0, column=1, padx=8)
        t.primary_button(bar, "Add to queue", self._add_from_entry, width=130, height=40).grid(row=0, column=2)

        opts = ctk.CTkFrame(self, fg_color=t.CARD, corner_radius=14, border_width=1, border_color=t.SEP)
        opts.grid(row=3, column=0, sticky="ew", padx=24, pady=8)
        opts.columnconfigure(8, weight=1)
        t.label(opts, "New items", 12, color=t.MUTED).grid(row=0, column=0, padx=(14, 8), pady=12)
        self.def_fmt = t.segmented(opts, ["MP3", "MP4"], command=lambda v: self._set("fmt", v), width=110)
        self.def_fmt.set(self.settings["fmt"])
        self.def_fmt.grid(row=0, column=1)
        t.label(opts, "MP3 kbps", 12, color=t.MUTED).grid(row=0, column=2, padx=(16, 6))
        self.kbps = t.option_menu(opts, KBPS, lambda v: self._set("kbps", v), width=80)
        self.kbps.set(self.settings["kbps"])
        self.kbps.grid(row=0, column=3)
        t.label(opts, "MP4 max", 12, color=t.MUTED).grid(row=0, column=4, padx=(16, 6))
        self.height = t.option_menu(opts, HEIGHTS, lambda v: self._set("height", v), width=84)
        self.height.set(self.settings["height"])
        self.height.grid(row=0, column=5)
        t.label(opts, "Parallel", 12, color=t.MUTED).grid(row=0, column=6, padx=(16, 6))
        self.parallel = t.option_menu(opts, PARALLEL, self._set_parallel, width=64)
        self.parallel.set(self.settings["parallel"])
        self.parallel.grid(row=0, column=7)
        self.folder_label = t.label(opts, "", 11, color=t.MUTED, anchor="e")
        self.folder_label.grid(row=0, column=8, sticky="ew", padx=10)
        t.tinted_button(opts, "Browse…", self._browse, width=84, height=30).grid(row=0, column=9, padx=2)
        t.tinted_button(opts, "Open", self._open_folder, width=60, height=30).grid(row=0, column=10, padx=(2, 14))
        self._refresh_folder()

        self.list = ctk.CTkScrollableFrame(self, fg_color="transparent", scrollbar_button_color="#C7C7CC",
                                           scrollbar_button_hover_color="#AEAEB2")
        self.list.grid(row=4, column=0, sticky="nsew", padx=(18, 12), pady=4)
        self.list.columnconfigure(0, weight=1)
        self.empty = t.label(self.list, "Your queue is empty.\nPaste a link above to get started.", 13,
                             color=t.MUTED, justify="center")
        self.empty.grid(row=0, column=0, pady=70)

        foot = ctk.CTkFrame(self, fg_color="transparent")
        foot.grid(row=5, column=0, sticky="ew", padx=24, pady=(8, 18))
        foot.columnconfigure(4, weight=1)
        t.primary_button(foot, "Download all", self._download_all, width=140, height=38).grid(row=0, column=0)
        t.tinted_button(foot, "Clear finished", self._clear_finished, width=120, height=38
                        ).grid(row=0, column=1, padx=8)
        t.tinted_button(foot, "History", self._show_history, width=86, height=38).grid(row=0, column=2)
        self.btn_update = t.tinted_button(foot, "Update yt-dlp", self._update_ytdlp, width=120, height=38)
        self.btn_update.grid(row=0, column=3, padx=8)
        self.status = t.label(foot, "", 12, color=t.MUTED, anchor="e")
        self.status.grid(row=0, column=4, sticky="ew", padx=8)

    # ------------------------------------------------------------ plumbing
    def _emit(self, job, kind, data):
        """Called from worker threads."""
        self.ui_q.put((self._on_job_event, (job, kind, data)))

    def _pump(self):
        try:
            while True:
                fn, args = self.ui_q.get_nowait()
                try:
                    fn(*args)
                except TclError:
                    pass
        except queue.Empty:
            pass
        self.after(100, self._pump)

    def _set(self, key, value):
        self.settings[key] = value

    def _set_parallel(self, value):
        self.settings["parallel"] = value
        self.manager.set_limit(int(value))

    def _set_status(self, text, color=GREY):
        self.status.configure(text=text, text_color=color)

    def _refresh_status(self):
        active = sum(1 for r in self.rows if r.job.state in ("queued", "running"))
        parts = []
        if self._fetching:
            parts.append(f"Fetching info for {self._fetching} link(s)…")
        if active:
            parts.append(f"{active} downloading/queued")
        self._set_status("  •  ".join(parts))

    # ------------------------------------------------------------ folder
    def _refresh_folder(self):
        d = self.settings["out_dir"]
        home = str(Path.home())
        shown = "~" + d[len(home):] if d.lower().startswith(home.lower()) else d
        shown = shown if len(shown) < 50 else "…" + shown[-48:]
        self.folder_label.configure(text=shown)

    def _browse(self):
        d = filedialog.askdirectory(initialdir=self.settings["out_dir"], title="Choose output folder")
        if d:
            self.settings["out_dir"] = os.path.normpath(d)
            self._refresh_folder()

    def _open_folder(self):
        d = self.settings["out_dir"]
        os.makedirs(d, exist_ok=True)
        os.startfile(d)

    # ------------------------------------------------------------ adding
    def _paste(self):
        try:
            text = self.clipboard_get()
        except TclError:
            return
        self.url_entry.delete(0, "end")
        self.url_entry.insert(0, text.strip())
        self._add_from_entry()

    def _add_from_entry(self):
        text = self.url_entry.get()
        if not text.strip():
            return
        if self.add_urls(text):
            self.url_entry.delete(0, "end")

    def add_urls(self, text) -> bool:
        urls = extract_urls(text)
        if not urls:
            self._set_status("No YouTube links found in that text.", RED)
            return False
        for u in urls:
            self._seen_clip.add(u)
            self._fetching += 1
            threading.Thread(target=self._fetch, args=(u,), daemon=True).start()
        self._refresh_status()
        return True

    def _fetch(self, url):
        try:
            entries = metadata.fetch(url)
            self.ui_q.put((self._add_entries, (entries, None)))
        except Exception as e:  # noqa: BLE001
            fallback = [{"url": url, "title": url, "duration": None, "thumb": None}]
            self.ui_q.put((self._add_entries, (fallback, str(e))))

    def _add_entries(self, entries, error):
        self._fetching = max(0, self._fetching - 1)
        existing = {r.job.url for r in self.rows if r.job.state != "done"}
        for e in entries:
            if e["url"] in existing:
                continue
            self._add_row(e, error)
        self._refresh_status()

    def _add_row(self, e, error=None):
        self.empty.grid_remove()
        job = Job(next(self._ids), e["url"], e["title"])
        row = QueueRow(self.list, job, e.get("duration"), self._remove_row, self._retry_row,
                       self._cancel_row, default_fmt=self.settings["fmt"])
        row.grid(row=len(self.rows) + 1, column=0, sticky="ew", pady=4)
        self.rows.append(row)
        self.rows_by_job[job.id] = row
        if error:
            row.set_error(error.replace("ERROR: ", ""))
        if e.get("thumb"):
            threading.Thread(target=self._load_thumb, args=(row, e["thumb"]), daemon=True).start()

    def _load_thumb(self, row, url):
        try:
            req = urllib.request.Request(url, headers={"User-Agent": "Mozilla/5.0"})
            data = urllib.request.urlopen(req, timeout=15).read()
            img = t.rounded(Image.open(io.BytesIO(data)).convert("RGB").resize((192, 108)), 16)
            self.ui_q.put((row.set_thumb, (img,)))
        except Exception:  # noqa: BLE001
            pass

    # ------------------------------------------------------------ row actions
    def _start_row(self, row):
        job = row.job
        row.collect()
        try:
            parse_time(job.trim_start)
            parse_time(job.trim_end)
        except ValueError:
            row.set_error("Invalid trim time (use 1:30)")
            return
        job.kbps = self.settings["kbps"]
        job.height = self.settings["height"]
        job.out_dir = self.settings["out_dir"]
        row.set_queued()
        self.manager.submit(job)
        self._refresh_status()

    def _download_all(self):
        started = 0
        for row in list(self.rows):
            if row.job.state == "idle":
                self._start_row(row)
                started += 1
        if not started:
            self._set_status("Nothing new to download.")

    def _retry_row(self, row):
        self._start_row(row)

    def _cancel_row(self, row):
        self.manager.cancel(row.job)

    def _remove_row(self, row):
        if row.job.state in ("queued", "running"):
            self.manager.cancel(row.job)
        self.rows.remove(row)
        self.rows_by_job.pop(row.job.id, None)
        row.destroy()
        if not self.rows:
            self.empty.grid()
        self._refresh_status()

    def _clear_finished(self):
        for row in [r for r in self.rows if r.job.state == "done"]:
            self._remove_row(row)

    def _on_job_event(self, job, kind, data):
        row = self.rows_by_job.get(job.id)
        if row is None:
            return
        if kind == "progress":
            row.set_progress(*data)
        elif kind == "status":
            row.set_status(data)
        elif kind == "done":
            row.set_done()
            history.add(job.title, data, job.fmt.upper())
        elif kind == "error":
            row.set_error(data)
        elif kind == "cancelled":
            row.set_cancelled()
        self._refresh_status()

    # ------------------------------------------------------------ clipboard banner
    def _on_focus(self, event):
        if event.widget is not self:
            return
        try:
            text = self.clipboard_get()
        except TclError:
            return
        known = {r.job.url for r in self.rows}
        new = [u for u in extract_urls(text) if u not in self._seen_clip and u not in known]
        if not new:
            return
        self._clip_new = new
        self._seen_clip.update(new)
        extra = f" (+{len(new) - 1} more)" if len(new) > 1 else ""
        short = new[0] if len(new) == 0 or len(new[0]) < 60 else new[0][:57] + "…"
        self.banner_label.configure(text=f"YouTube link on clipboard: {short}{extra}")
        self.banner.grid(row=1, column=0, sticky="ew", padx=24, pady=(12, 0))

    def _banner_add(self):
        self.add_urls(" ".join(self._clip_new))
        self._banner_hide()

    def _banner_hide(self):
        self.banner.grid_remove()

    # ------------------------------------------------------------ history / update
    def _show_history(self):
        HistoryWindow(self)

    def _update_ytdlp(self):
        self.btn_update.configure(state="disabled")
        self._set_status("Updating yt-dlp…")

        def work():
            try:
                msg = update_ytdlp()
            except Exception as e:  # noqa: BLE001
                msg = f"Update failed: {e}"
            self.ui_q.put((self._update_done, (msg,)))

        threading.Thread(target=work, daemon=True).start()

    def _update_done(self, msg):
        self.btn_update.configure(state="normal")
        self._set_status(msg, GREEN)

    # ------------------------------------------------------------ shutdown
    def _close(self):
        self.settings["geometry"] = self.geometry()
        self.withdraw()
        self.manager.shutdown([r.job for r in self.rows])
        self.destroy()


class HistoryWindow(ctk.CTkToplevel):
    def __init__(self, master):
        super().__init__(master)
        self.title("Download history")
        self.geometry("720x480")
        self.transient(master)
        self.configure(fg_color=t.BG)
        self.columnconfigure(0, weight=1)
        self.rowconfigure(0, weight=1)
        self.body = ctk.CTkScrollableFrame(self, fg_color="transparent", scrollbar_button_color="#C7C7CC",
                                           scrollbar_button_hover_color="#AEAEB2")
        self.body.grid(row=0, column=0, sticky="nsew", padx=12, pady=12)
        self.body.columnconfigure(0, weight=1)
        t.tinted_button(self, "Clear history", self._clear, width=120, height=34
                        ).grid(row=1, column=0, pady=(0, 14))
        self._fill()
        self.after(150, self.lift)

    def _fill(self):
        for w in self.body.winfo_children():
            w.destroy()
        items = history.load()
        if not items:
            t.label(self.body, "No downloads yet.", 13, color=GREY).grid(pady=40)
            return
        for i, it in enumerate(items):
            f = ctk.CTkFrame(self.body, fg_color=t.CARD, corner_radius=14, border_width=1, border_color=t.SEP)
            f.grid(row=i, column=0, sticky="ew", pady=3)
            f.columnconfigure(0, weight=1)
            title = it["title"] if len(it["title"]) < 60 else it["title"][:57] + "…"
            t.label(f, title, 13, "medium", anchor="w").grid(row=0, column=0, sticky="ew", padx=14, pady=(10, 0))
            t.label(f, f'{it["fmt"]}  •  {it["date"]}', 11, color=GREY, anchor="w"
                    ).grid(row=1, column=0, sticky="ew", padx=14, pady=(0, 10))
            t.tinted_button(f, "Open", lambda p=it["path"]: self._open(p), width=64, height=30
                            ).grid(row=0, column=1, rowspan=2, padx=3)
            t.tinted_button(f, "Show in folder", lambda p=it["path"]: self._show(p), width=110, height=30
                            ).grid(row=0, column=2, rowspan=2, padx=(3, 12))

    def _open(self, path):
        if os.path.exists(path):
            os.startfile(path)
        else:
            self._missing()

    def _show(self, path):
        if os.path.exists(path):
            subprocess.Popen(["explorer", "/select,", os.path.normpath(path)])
        else:
            self._missing()

    def _missing(self):
        t.label(self, "That file no longer exists.", 12, color=RED).grid(row=2, column=0, pady=(0, 8))
        self.after(2500, lambda: [w.destroy() for w in self.grid_slaves(row=2)])

    def _clear(self):
        history.clear()
        self._fill()


def main():
    App().mainloop()
