import io
import itertools
import os
import queue
import subprocess
import threading
import urllib.request
from tkinter import TclError, filedialog

import customtkinter as ctk
from PIL import Image

from . import history, metadata
from .clipboard import extract_urls
from .downloader import Job, Manager, parse_time, update_ytdlp
from .queue_row import GREEN, GREY, RED, QueueRow
from .settings import Settings

KBPS = ["128", "192", "320"]
HEIGHTS = ["Best", "1080", "720", "480", "360"]
PARALLEL = ["1", "2", "3", "4"]


class App(ctk.CTk):
    def __init__(self):
        ctk.set_appearance_mode("dark")
        ctk.set_default_color_theme("blue")
        super().__init__()
        self.title("MusicMatch")
        self.settings = Settings()
        self.geometry(self.settings["geometry"] or "1000x700")
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
        self.columnconfigure(0, weight=1)
        self.rowconfigure(3, weight=1)

        self.banner = ctk.CTkFrame(self, fg_color="#1f3a5f", corner_radius=8)
        self.banner.columnconfigure(0, weight=1)
        self.banner_label = ctk.CTkLabel(self.banner, text="", anchor="w")
        self.banner_label.grid(row=0, column=0, sticky="ew", padx=12, pady=8)
        ctk.CTkButton(self.banner, text="Add", width=60, command=self._banner_add).grid(row=0, column=1, padx=4)
        ctk.CTkButton(self.banner, text="Dismiss", width=70, fg_color="transparent", border_width=1,
                      command=self._banner_hide).grid(row=0, column=2, padx=(4, 10))

        bar = ctk.CTkFrame(self, fg_color="transparent")
        bar.grid(row=1, column=0, sticky="ew", padx=16, pady=(14, 6))
        bar.columnconfigure(0, weight=1)
        self.url_entry = ctk.CTkEntry(bar, height=38, placeholder_text="Paste YouTube video or playlist URL(s) here…")
        self.url_entry.grid(row=0, column=0, sticky="ew")
        self.url_entry.bind("<Return>", lambda e: self._add_from_entry())
        ctk.CTkButton(bar, text="Paste", width=70, height=38, fg_color="transparent", border_width=1,
                      command=self._paste).grid(row=0, column=1, padx=6)
        ctk.CTkButton(bar, text="Add to queue", width=120, height=38,
                      command=self._add_from_entry).grid(row=0, column=2)

        opts = ctk.CTkFrame(self)
        opts.grid(row=2, column=0, sticky="ew", padx=16, pady=6)
        opts.columnconfigure(8, weight=1)
        ctk.CTkLabel(opts, text="New items:").grid(row=0, column=0, padx=(12, 6), pady=10)
        self.def_fmt = ctk.CTkSegmentedButton(opts, values=["MP3", "MP4"], width=110,
                                              command=lambda v: self._set("fmt", v))
        self.def_fmt.set(self.settings["fmt"])
        self.def_fmt.grid(row=0, column=1)
        ctk.CTkLabel(opts, text="MP3 kbps").grid(row=0, column=2, padx=(16, 4))
        self.kbps = ctk.CTkOptionMenu(opts, values=KBPS, width=80, command=lambda v: self._set("kbps", v))
        self.kbps.set(self.settings["kbps"])
        self.kbps.grid(row=0, column=3)
        ctk.CTkLabel(opts, text="MP4 max").grid(row=0, column=4, padx=(16, 4))
        self.height = ctk.CTkOptionMenu(opts, values=HEIGHTS, width=80, command=lambda v: self._set("height", v))
        self.height.set(self.settings["height"])
        self.height.grid(row=0, column=5)
        ctk.CTkLabel(opts, text="Parallel").grid(row=0, column=6, padx=(16, 4))
        self.parallel = ctk.CTkOptionMenu(opts, values=PARALLEL, width=60, command=self._set_parallel)
        self.parallel.set(self.settings["parallel"])
        self.parallel.grid(row=0, column=7)
        self.folder_label = ctk.CTkLabel(opts, text="", anchor="e", text_color=GREY)
        self.folder_label.grid(row=0, column=8, sticky="ew", padx=10)
        ctk.CTkButton(opts, text="Browse…", width=80, command=self._browse).grid(row=0, column=9, padx=2)
        ctk.CTkButton(opts, text="Open", width=60, command=self._open_folder).grid(row=0, column=10, padx=(2, 12))
        self._refresh_folder()

        self.list = ctk.CTkScrollableFrame(self, label_text="")
        self.list.grid(row=3, column=0, sticky="nsew", padx=16, pady=6)
        self.list.columnconfigure(0, weight=1)
        self.empty = ctk.CTkLabel(self.list, text="Queue is empty.\nPaste a link above to get started.",
                                  text_color=GREY, justify="center")
        self.empty.grid(row=0, column=0, pady=60)

        foot = ctk.CTkFrame(self, fg_color="transparent")
        foot.grid(row=4, column=0, sticky="ew", padx=16, pady=(6, 14))
        foot.columnconfigure(4, weight=1)
        ctk.CTkButton(foot, text="Download all", width=130, height=36,
                      command=self._download_all).grid(row=0, column=0)
        ctk.CTkButton(foot, text="Clear finished", width=110, height=36, fg_color="transparent", border_width=1,
                      command=self._clear_finished).grid(row=0, column=1, padx=6)
        ctk.CTkButton(foot, text="History", width=80, height=36, fg_color="transparent", border_width=1,
                      command=self._show_history).grid(row=0, column=2)
        self.btn_update = ctk.CTkButton(foot, text="Update yt-dlp", width=110, height=36, fg_color="transparent",
                                        border_width=1, command=self._update_ytdlp)
        self.btn_update.grid(row=0, column=3, padx=6)
        self.status = ctk.CTkLabel(foot, text="", anchor="e", text_color=GREY)
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
        shown = d if len(d) < 60 else "…" + d[-58:]
        self.folder_label.configure(text=f"Save to: {shown}")

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
            img = Image.open(io.BytesIO(data)).convert("RGB").resize((96, 54))
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
        self.banner.grid(row=0, column=0, sticky="ew", padx=16, pady=(12, 0))

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
        self.columnconfigure(0, weight=1)
        self.rowconfigure(0, weight=1)
        self.body = ctk.CTkScrollableFrame(self)
        self.body.grid(row=0, column=0, sticky="nsew", padx=12, pady=12)
        self.body.columnconfigure(0, weight=1)
        ctk.CTkButton(self, text="Clear history", fg_color="transparent", border_width=1,
                      command=self._clear).grid(row=1, column=0, pady=(0, 12))
        self._fill()
        self.after(150, self.lift)

    def _fill(self):
        for w in self.body.winfo_children():
            w.destroy()
        items = history.load()
        if not items:
            ctk.CTkLabel(self.body, text="No downloads yet.", text_color=GREY).grid(pady=40)
            return
        for i, it in enumerate(items):
            f = ctk.CTkFrame(self.body)
            f.grid(row=i, column=0, sticky="ew", pady=3)
            f.columnconfigure(0, weight=1)
            title = it["title"] if len(it["title"]) < 60 else it["title"][:57] + "…"
            ctk.CTkLabel(f, text=title, anchor="w").grid(row=0, column=0, sticky="ew", padx=10, pady=(6, 0))
            ctk.CTkLabel(f, text=f'{it["fmt"]}  •  {it["date"]}', anchor="w", text_color=GREY
                         ).grid(row=1, column=0, sticky="ew", padx=10, pady=(0, 6))
            ctk.CTkButton(f, text="Open", width=60, command=lambda p=it["path"]: self._open(p)
                          ).grid(row=0, column=1, rowspan=2, padx=3)
            ctk.CTkButton(f, text="Show in folder", width=100, command=lambda p=it["path"]: self._show(p)
                          ).grid(row=0, column=2, rowspan=2, padx=(3, 10))

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
        ctk.CTkLabel(self, text="That file no longer exists.", text_color=RED).grid(row=2, column=0, pady=(0, 8))
        self.after(2500, lambda: [w.destroy() for w in self.grid_slaves(row=2)])

    def _clear(self):
        history.clear()
        self._fill()


def main():
    App().mainloop()
