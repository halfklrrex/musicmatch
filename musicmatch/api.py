"""Bridge between the web UI (JS) and the download engine.

Every public method of `Api` is callable from JavaScript as
`pywebview.api.<name>(...)`. Anything not meant for JS is underscore-prefixed
(pywebview skips those). Events flow back with `window.mm.onEvent({...})`.
"""
import ctypes
import itertools
import json
import os
import subprocess
import threading
from pathlib import Path

import webview

from . import history, metadata
from .clipboard import extract_urls
from .naming import file_base, guess
from .downloader import Job, Manager, parse_time, update_ytdlp

VERSION = "2.1.0"


def read_clipboard() -> str:
    """Unicode text on the Windows clipboard ('' if none)."""
    u32, k32 = ctypes.windll.user32, ctypes.windll.kernel32
    u32.GetClipboardData.restype = ctypes.c_void_p
    k32.GlobalLock.restype = ctypes.c_void_p
    k32.GlobalLock.argtypes = [ctypes.c_void_p]
    k32.GlobalUnlock.argtypes = [ctypes.c_void_p]
    if not u32.OpenClipboard(None):
        return ""
    try:
        handle = u32.GetClipboardData(13)  # CF_UNICODETEXT
        if not handle:
            return ""
        ptr = k32.GlobalLock(handle)
        if not ptr:
            return ""
        try:
            return ctypes.wstring_at(ptr)
        finally:
            k32.GlobalUnlock(handle)
    finally:
        u32.CloseClipboard()


def display_dir(path: str) -> str:
    home = str(Path.home())
    return "~" + path[len(home):] if path.lower().startswith(home.lower()) else path


class Api:
    def __init__(self, settings):
        self._settings = settings
        self._window = None
        self._jobs = {}
        self._ids = itertools.count(1)
        self._seen = set()
        self._fetching = 0
        self._lock = threading.Lock()
        self._history_lock = threading.Lock()
        self._manager = Manager(self._on_job, int(settings["parallel"]))

    # ---------------------------------------------------------- plumbing
    def _bind(self, window):
        self._window = window

    def _push(self, event: dict):
        if self._window is None:
            return
        try:
            self._window.evaluate_js("window.mm && window.mm.onEvent(%s)" % json.dumps(event))
        except Exception:  # window closing
            pass

    def _on_job(self, job, kind, data):
        if kind == "done":
            with self._history_lock:
                history.add(file_base(job.song or job.title, job.artist), data, job.fmt.upper())
        self._push({"t": "job", "id": job.id, "kind": kind, "data": data})

    def _on_closing(self):
        try:
            self._settings["size"] = f"{self._window.width}x{self._window.height}"
        except Exception:
            pass
        self._manager.shutdown(list(self._jobs.values()))

    # ---------------------------------------------------------- state
    def init(self):
        s = self._settings
        return {
            "version": VERSION,
            "fmt": str(s["fmt"]).lower(), "kbps": s["kbps"], "height": s["height"], "parallel": s["parallel"],
            "folder": display_dir(s["out_dir"]),
        }

    def set_setting(self, key, value):
        if key not in ("fmt", "kbps", "height", "parallel"):
            return False
        self._settings[key] = str(value).upper() if key == "fmt" else str(value)
        if key == "parallel":
            self._manager.set_limit(int(value))
        return True

    def browse_folder(self):
        dialog = getattr(webview, "FileDialog", None)
        kind = dialog.FOLDER if dialog else webview.FOLDER_DIALOG
        res = self._window.create_file_dialog(kind, directory=self._settings["out_dir"])
        if res:
            path = os.path.normpath(res[0] if isinstance(res, (list, tuple)) else res)
            self._settings["out_dir"] = path
            return display_dir(path)
        return None

    def open_folder(self):
        d = self._settings["out_dir"]
        os.makedirs(d, exist_ok=True)
        os.startfile(d)

    # ---------------------------------------------------------- adding links
    def add_urls(self, text):
        urls = extract_urls(text)
        tickets = []
        for u in urls:
            self._seen.add(u)
            ticket = next(self._ids)
            tickets.append(ticket)
            with self._lock:
                self._fetching += 1
        for u, ticket in zip(urls, tickets):
            threading.Thread(target=self._fetch, args=(u, ticket), daemon=True).start()
        return {"added": len(urls), "tickets": tickets}

    def _fetch(self, url, ticket):
        error = None
        try:
            entries = metadata.fetch(url)
        except Exception as e:  # noqa: BLE001
            entries = [{"url": url, "title": url, "duration": None, "thumb": None}]
            error = str(e).replace("ERROR: ", "")
        rows = []
        with self._lock:
            self._fetching = max(0, self._fetching - 1)
            n = self._fetching
            known = {j.url for j in self._jobs.values() if j.state != "done"}
            for e in entries:
                if e["url"] in known:
                    continue
                known.add(e["url"])
                artist, song = guess(e["title"], e.get("channel", ""), e.get("artist", ""), e.get("track", ""))
                job = Job(next(self._ids), e["url"], e["title"], song=song, artist=artist)
                self._jobs[job.id] = job
                rows.append({"id": job.id, "title": job.title, "url": job.url, "song": song, "artist": artist,
                             "duration": e.get("duration"), "thumb": e.get("thumb"), "error": error})
        self._push({"t": "rows", "ticket": ticket, "rows": rows, "n": n})

    def clipboard_text(self):
        return read_clipboard()

    def clipboard_urls(self):
        """YouTube links on the clipboard that were not offered or added before."""
        known = {j.url for j in self._jobs.values()}
        new = [u for u in extract_urls(read_clipboard()) if u not in self._seen and u not in known]
        self._seen.update(new)
        return new

    # ---------------------------------------------------------- downloads
    def start(self, items):
        """items: [{id, fmt, trim_start, trim_end, normalize}]"""
        for it in items:
            job = self._jobs.get(it.get("id"))
            if not job or job.state in ("queued", "running", "done"):
                continue
            job.fmt = "mp4" if it.get("fmt") == "mp4" else "mp3"
            job.trim_start = str(it.get("trim_start") or "").strip()
            job.trim_end = str(it.get("trim_end") or "").strip()
            job.normalize = bool(it.get("normalize"))
            job.song = str(it.get("song") or "").strip() or job.title
            job.artist = str(it.get("artist") or "").strip()
            try:
                parse_time(job.trim_start)
                parse_time(job.trim_end)
            except ValueError:
                job.state = "error"
                self._push({"t": "job", "id": job.id, "kind": "error",
                            "data": "Invalid trim time (use 1:30)"})
                continue
            job.kbps = self._settings["kbps"]
            job.height = self._settings["height"]
            job.out_dir = self._settings["out_dir"]
            self._manager.submit(job)
            self._push({"t": "job", "id": job.id, "kind": "queued", "data": None})

    def cancel(self, job_id):
        job = self._jobs.get(job_id)
        if job:
            self._manager.cancel(job)

    def remove(self, job_id):
        job = self._jobs.pop(job_id, None)
        if job and job.state in ("queued", "running"):
            self._manager.cancel(job)

    # ---------------------------------------------------------- files & history
    def history(self):
        items = history.load()
        for it in items:
            it["exists"] = os.path.exists(it.get("path", ""))
        return items

    def history_clear(self):
        with self._history_lock:
            history.clear()

    def open_path(self, path):
        if path and os.path.exists(path):
            os.startfile(path)
            return True
        return False

    def show_in_folder(self, path):
        if path and os.path.exists(path):
            subprocess.Popen(["explorer", "/select,", os.path.normpath(path)])
            return True
        return False

    # ---------------------------------------------------------- yt-dlp update
    def update_ytdlp(self):
        def work():
            try:
                msg = update_ytdlp()
                self._push({"t": "updated", "msg": msg, "ok": True})
            except Exception as e:  # noqa: BLE001
                self._push({"t": "updated", "msg": f"Update failed: {e}", "ok": False})
        threading.Thread(target=work, daemon=True).start()
