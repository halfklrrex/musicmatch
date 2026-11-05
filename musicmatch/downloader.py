"""Builds yt-dlp commands, runs them in worker threads and reports progress."""
import glob
import os
import re
import subprocess
import threading
from collections import deque
from dataclasses import dataclass, field
from pathlib import Path
from typing import Callable, Optional

from .paths import NO_WINDOW, ffmpeg_dir, ffmpeg_path, tool_env, ytdlp_path

_ILLEGAL = re.compile(r'[<>:"/\\|?*\x00-\x1f]')
_reserved = set()
_reserved_lock = threading.Lock()


@dataclass
class Job:
    id: int
    url: str
    title: str
    fmt: str = "mp3"          # "mp3" or "mp4"
    kbps: str = "320"
    height: str = "Best"
    trim_start: str = ""
    trim_end: str = ""
    normalize: bool = False
    out_dir: str = ""
    state: str = "idle"       # idle, queued, running, done, error, cancelled
    cancelled: bool = False
    result_path: str = ""
    proc: Optional[subprocess.Popen] = field(default=None, repr=False)


def parse_time(text: str) -> Optional[float]:
    """'1:30' -> 90.0, '' -> None. Raises ValueError on bad input."""
    text = (text or "").strip()
    if not text:
        return None
    parts = text.split(":")
    if len(parts) > 3:
        raise ValueError(text)
    total = 0.0
    for p in parts:
        total = total * 60 + float(p)
    if total < 0:
        raise ValueError(text)
    return total


def sanitize(title: str) -> str:
    name = _ILLEGAL.sub("_", title).strip().rstrip(". ")
    return (name[:150].rstrip(". ")) or "video"


def _unique_base(job: Job) -> str:
    base = sanitize(job.title)
    out = Path(job.out_dir)
    n = 0
    with _reserved_lock:
        while True:
            name = base if n == 0 else f"{base} ({n})"
            key = f"{out / name}.{job.fmt}".lower()
            if key not in _reserved and not (out / f"{name}.{job.fmt}").exists():
                _reserved.add(key)
                return name
            n += 1


def _release(job: Job, name: str):
    with _reserved_lock:
        _reserved.discard(f"{Path(job.out_dir) / name}.{job.fmt}".lower())


def build_command(job: Job, name: str) -> list:
    out_tmpl = str(Path(job.out_dir) / name.replace("%", "%%")) + ".%(ext)s"
    cmd = [
        str(ytdlp_path()), "--no-playlist", "--no-warnings", "--newline", "--progress",
        "--windows-filenames", "--ffmpeg-location", str(ffmpeg_dir()),
        "--progress-template", "download:MMPROG %(progress._percent_str)s|%(progress._speed_str)s|%(progress._eta_str)s",
        "--progress-template", "postprocess:MMPP %(progress.postprocessor)s",
        "--print", "after_move:MMFILE %(filepath)s",
        "-o", out_tmpl, "--embed-metadata",
    ]
    if job.fmt == "mp3":
        cmd += ["-f", "bestaudio/best", "-x", "--audio-format", "mp3",
                "--audio-quality", f"{job.kbps}K",
                "--embed-thumbnail", "--convert-thumbnails", "jpg"]
        if job.normalize:
            cmd += ["--postprocessor-args", "ExtractAudio:-af loudnorm"]
    else:
        h = None if job.height == "Best" else job.height
        flt = f"[height<={h}]" if h else ""
        cmd += ["-f", f"bv*{flt}[vcodec^=avc1]+ba[ext=m4a]/bv*{flt}+ba/b{flt}",
                "--merge-output-format", "mp4"]
    start, end = parse_time(job.trim_start), parse_time(job.trim_end)
    if start is not None or end is not None:
        s = job.trim_start.strip() or "0"
        e = job.trim_end.strip() or "inf"
        cmd += ["--download-sections", f"*{s}-{e}", "--force-keyframes-at-cuts"]
    cmd.append(job.url)
    return cmd


def kill_tree(proc: Optional[subprocess.Popen]):
    if proc and proc.poll() is None:
        subprocess.run(["taskkill", "/PID", str(proc.pid), "/T", "/F"],
                       capture_output=True, creationflags=NO_WINDOW)


def _cleanup(job: Job, name: str):
    """Remove partial/intermediate files for a failed or cancelled job."""
    pattern = os.path.join(glob.escape(job.out_dir), glob.escape(name) + ".*")
    for f in glob.glob(pattern):
        try:
            os.remove(f)
        except OSError:
            pass


Emit = Callable[[Job, str, object], None]


def _normalize_mp4(job: Job, emit: Emit) -> bool:
    src = Path(job.result_path)
    tmp = src.with_name(src.stem + ".norm.mp4")
    emit(job, "status", "Normalizing volume…")
    cmd = [str(ffmpeg_path()), "-y", "-i", str(src), "-map", "0", "-c:v", "copy",
           "-c:a", "aac", "-b:a", "192k", "-af", "loudnorm", "-movflags", "+faststart", str(tmp)]
    job.proc = subprocess.Popen(cmd, stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL,
                                stdin=subprocess.DEVNULL, creationflags=NO_WINDOW)
    rc = job.proc.wait()
    if job.cancelled:
        tmp.unlink(missing_ok=True)
        return False
    if rc != 0:
        tmp.unlink(missing_ok=True)
        raise RuntimeError("ffmpeg volume normalization failed")
    os.replace(tmp, src)
    return True


def run_job(job: Job, emit: Emit):
    name = None
    try:
        os.makedirs(job.out_dir, exist_ok=True)
        name = _unique_base(job)
        cmd = build_command(job, name)
    except ValueError:
        job.state = "error"
        emit(job, "error", "Invalid trim time (use e.g. 1:30 or 0:01:30)")
        return
    except Exception as e:
        job.state = "error"
        emit(job, "error", str(e))
        return

    job.state = "running"
    emit(job, "status", "Starting…")
    errors = []
    try:
        job.proc = subprocess.Popen(
            cmd, stdout=subprocess.PIPE, stderr=subprocess.STDOUT, stdin=subprocess.DEVNULL,
            text=True, encoding="utf-8", errors="replace",
            creationflags=NO_WINDOW, env=tool_env(), cwd=job.out_dir,
        )
        if job.cancelled:
            kill_tree(job.proc)
        for raw in job.proc.stdout:
            line = raw.strip()
            if line.startswith("MMPROG "):
                pct, speed, eta = (line[7:].split("|") + ["", ""])[:3]
                pct, speed, eta = pct.strip(), speed.strip(), eta.strip()
                try:
                    value = float(pct.rstrip("%"))
                except ValueError:
                    continue
                bits = [pct]
                if speed and "Unknown" not in speed:
                    bits.append(speed)
                if eta and "Unknown" not in eta:
                    bits.append(f"ETA {eta}")
                emit(job, "progress", (value, "  •  ".join(bits)))
            elif line.startswith("MMPP "):
                emit(job, "progress", (100.0, "Converting…"))
            elif line.startswith("MMFILE "):
                job.result_path = line[7:].strip()
            elif line.startswith("ERROR"):
                errors.append(line)
        rc = job.proc.wait()

        if job.cancelled:
            _cleanup(job, name)
            job.state = "cancelled"
            emit(job, "cancelled", None)
            return
        if rc != 0 or not job.result_path:
            msg = errors[-1] if errors else f"yt-dlp exited with code {rc}"
            _cleanup(job, name)
            job.state = "error"
            emit(job, "error", msg.replace("ERROR: ", "", 1))
            return
        if job.fmt == "mp4" and job.normalize:
            if not _normalize_mp4(job, emit):
                _cleanup(job, name)
                job.state = "cancelled"
                emit(job, "cancelled", None)
                return
        job.state = "done"
        emit(job, "done", job.result_path)
    except Exception as e:  # noqa: BLE001
        if job.cancelled:
            _cleanup(job, name)
            job.state = "cancelled"
            emit(job, "cancelled", None)
        else:
            job.state = "error"
            emit(job, "error", str(e))
    finally:
        _release(job, name)


class Manager:
    """Runs jobs with a configurable number in parallel."""

    def __init__(self, emit: Emit, limit: int = 2):
        self.emit = emit
        self.limit = limit
        self._lock = threading.Lock()
        self._pending = deque()
        self._running = 0
        self._threads = set()

    def set_limit(self, n: int):
        with self._lock:
            self.limit = max(1, n)
            self._pump()

    def submit(self, job: Job):
        with self._lock:
            job.state = "queued"
            job.cancelled = False
            job.result_path = ""
            self._pending.append(job)
            self._pump()

    def _pump(self):  # call with lock held
        while self._running < self.limit and self._pending:
            job = self._pending.popleft()
            self._running += 1
            t = threading.Thread(target=self._work, args=(job,), daemon=True)
            self._threads.add(t)
            t.start()

    def _work(self, job: Job):
        try:
            run_job(job, self.emit)
        finally:
            with self._lock:
                self._running -= 1
                self._threads.discard(threading.current_thread())
                self._pump()

    def cancel(self, job: Job):
        with self._lock:
            if job in self._pending:
                self._pending.remove(job)
                job.state = "cancelled"
                self.emit(job, "cancelled", None)
                return
        if job.state == "running":
            job.cancelled = True
            kill_tree(job.proc)

    def cancel_all(self):
        with self._lock:
            queued = list(self._pending)
            self._pending.clear()
        for job in queued:
            job.state = "cancelled"
            self.emit(job, "cancelled", None)

    def shutdown(self, jobs, timeout: float = 3.0):
        """Kill active jobs and give workers a moment to clean up partial files."""
        self.cancel_all()
        for job in jobs:
            if job.state == "running":
                job.cancelled = True
                kill_tree(job.proc)
        for t in list(self._threads):
            t.join(timeout)


def update_ytdlp() -> str:
    proc = subprocess.run(
        [str(ytdlp_path()), "-U"], capture_output=True, text=True, encoding="utf-8",
        errors="replace", timeout=180, creationflags=NO_WINDOW, env=tool_env(),
        stdin=subprocess.DEVNULL,
    )
    lines = [l.strip() for l in (proc.stdout + proc.stderr).splitlines() if l.strip()]
    return lines[-1] if lines else "No output from yt-dlp"
