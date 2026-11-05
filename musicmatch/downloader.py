"""Builds yt-dlp commands, runs them in worker threads and reports progress."""
import os
import re
import shutil
import subprocess
import tempfile
import threading
import time
from collections import deque
from dataclasses import dataclass, field
from pathlib import Path
from typing import Callable, Optional

from .naming import file_base
from .paths import NO_WINDOW, ffmpeg_dir, ffmpeg_path, tool_env, ytdlp_path

_ILLEGAL = re.compile(r'[<>:"/\\|?*\x00-\x1f]')
_reserved = set()
_reserved_lock = threading.Lock()


@dataclass
class Job:
    id: int
    url: str
    title: str
    song: str = ""            # song title written to the tags and the file name
    artist: str = ""
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
    base = sanitize(file_base(job.song or job.title, job.artist))
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


def build_command(job: Job, name: str, work: Path) -> list:
    out_tmpl = str(work / name.replace("%", "%%")) + ".%(ext)s"
    cmd = [
        str(ytdlp_path()), "--no-playlist", "--no-warnings", "--newline", "--progress",
        "--windows-filenames", "--ffmpeg-location", str(ffmpeg_dir()),
        "--progress-template", "download:MMPROG %(progress._percent_str)s|%(progress._speed_str)s|%(progress._eta_str)s",
        "--progress-template", "postprocess:MMPP %(progress.postprocessor)s",
        "--print", "after_move:MMFILE %(filepath)s",
        "-o", out_tmpl,
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


Emit = Callable[[Job, str, object], None]

# All downloading and converting happens in a private folder on the local disk;
# only the finished file is copied into the output folder. That keeps half-made
# files out of the user's folder and avoids trouble with cloud-synced folders
# (Google Drive, OneDrive) that lock or lag on files while they are being written.
WORK_ROOT = Path(tempfile.gettempdir()) / "MusicMatch"


def purge_old_work(max_age_hours: float = 24):
    """Remove work folders left behind by a crash."""
    try:
        for d in WORK_ROOT.iterdir():
            if d.is_dir() and time.time() - d.stat().st_mtime > max_age_hours * 3600:
                shutil.rmtree(d, ignore_errors=True)
    except OSError:
        pass


def _ffmpeg(job: Job, args: list):
    """Run ffmpeg; returns (return code, last error line)."""
    cmd = [str(ffmpeg_path()), "-y", "-hide_banner", "-v", "error", *args]
    job.proc = subprocess.Popen(cmd, stdout=subprocess.DEVNULL, stderr=subprocess.PIPE, stdin=subprocess.DEVNULL,
                                text=True, encoding="utf-8", errors="replace", creationflags=NO_WINDOW)
    _, err = job.proc.communicate()
    lines = [l.strip() for l in (err or "").splitlines() if l.strip()]
    return job.proc.returncode, (lines[-1] if lines else "")


def _normalize_mp4(job: Job, emit: Emit) -> bool:
    src = Path(job.result_path)
    tmp = src.with_name(src.stem + ".norm.mp4")
    emit(job, "status", "@normalizing")
    rc, detail = _ffmpeg(job, ["-i", str(src), "-map", "0", "-c:v", "copy", "-c:a", "aac", "-b:a", "192k",
                               "-af", "loudnorm", "-movflags", "+faststart", str(tmp)])
    if job.cancelled:
        return False
    if rc != 0:
        raise RuntimeError(f"@norm_failed|{detail}")
    os.replace(tmp, src)
    return True


def _write_tags(job: Job, emit: Emit) -> bool:
    """Replace whatever tags yt-dlp wrote with clean ones, without re-encoding.

    MP3: ID3v2.3 (+ ID3v1), which car stereos read reliably. Cover art is kept.
    """
    src = Path(job.result_path)
    tmp = src.with_name(src.stem + ".tagged" + src.suffix)
    song = job.song or job.title
    emit(job, "status", "@tagging")
    args = ["-i", str(src), "-map", "0", "-c", "copy", "-map_metadata", "-1",
            "-metadata", f"title={song}", "-metadata", f"album={song}"]
    if job.artist:
        args += ["-metadata", f"artist={job.artist}", "-metadata", f"album_artist={job.artist}"]
    if src.suffix.lower() == ".mp3":
        args += ["-id3v2_version", "3", "-write_id3v1", "1",
                 "-metadata:s:v", "title=Album cover", "-metadata:s:v", "comment=Cover (front)"]
    else:
        args += ["-movflags", "+faststart"]
    rc, detail = _ffmpeg(job, args + [str(tmp)])
    if job.cancelled:
        return False
    if rc != 0:
        raise RuntimeError(f"@tags_failed|{detail}")
    os.replace(tmp, src)
    return True


def _retry(action, tries: int = 6, delay: float = 0.6):
    """Run `action`, retrying on OSError (cloud drives can briefly lock new files)."""
    for i in range(tries):
        try:
            return action()
        except OSError:
            if i == tries - 1:
                raise
            time.sleep(delay * (i + 1))


def _deliver(job: Job, emit: Emit, src: Path, name: str) -> Path:
    """Copy the finished file into the output folder and return its final path."""
    emit(job, "status", "@saving")
    final = Path(job.out_dir) / (name + src.suffix)
    part = final.with_name(final.name + ".mmpart")
    try:
        _retry(lambda: shutil.copyfile(src, part))
        _retry(lambda: os.replace(part, final))
    except OSError as e:
        try:
            part.unlink(missing_ok=True)
        except OSError:
            pass
        raise RuntimeError(f"@save_failed|{e.strerror or e}") from e
    return final


def run_job(job: Job, emit: Emit):
    name = None
    work = None
    try:
        os.makedirs(job.out_dir, exist_ok=True)
        WORK_ROOT.mkdir(parents=True, exist_ok=True)
        work = Path(tempfile.mkdtemp(prefix="job_", dir=WORK_ROOT))
        name = _unique_base(job)
        cmd = build_command(job, name, work)
    except ValueError:
        job.state = "error"
        emit(job, "error", "@invalid_trim")
        if work:
            shutil.rmtree(work, ignore_errors=True)
        return
    except Exception as e:
        job.state = "error"
        emit(job, "error", str(e))
        if work:
            shutil.rmtree(work, ignore_errors=True)
        return

    job.state = "running"
    emit(job, "status", "@starting")
    errors = []

    def cancelled():
        job.state = "cancelled"
        emit(job, "cancelled", None)

    try:
        job.proc = subprocess.Popen(
            cmd, stdout=subprocess.PIPE, stderr=subprocess.STDOUT, stdin=subprocess.DEVNULL,
            text=True, encoding="utf-8", errors="replace",
            creationflags=NO_WINDOW, env=tool_env(), cwd=str(work),
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
                speed = "" if (not speed or "Unknown" in speed) else speed
                eta = "" if (not eta or "Unknown" in eta) else eta
                emit(job, "progress", (value, f"@prog|{pct}|{speed}|{eta}"))
            elif line.startswith("MMPP "):
                emit(job, "progress", (100.0, "@converting"))
            elif line.startswith("MMFILE "):
                job.result_path = line[7:].strip()
            elif line.startswith("ERROR"):
                errors.append(line)
        rc = job.proc.wait()

        if job.cancelled:
            return cancelled()
        if rc != 0 or not job.result_path:
            msg = errors[-1] if errors else f"yt-dlp exited with code {rc}"
            job.state = "error"
            emit(job, "error", msg.replace("ERROR: ", "", 1))
            return
        if job.fmt == "mp4" and job.normalize and not _normalize_mp4(job, emit):
            return cancelled()
        if not _write_tags(job, emit):
            return cancelled()
        if job.cancelled:
            return cancelled()
        job.result_path = str(_deliver(job, emit, Path(job.result_path), name))
        job.state = "done"
        emit(job, "done", job.result_path)
    except Exception as e:  # noqa: BLE001
        if job.cancelled:
            cancelled()
        else:
            job.state = "error"
            emit(job, "error", str(e))
    finally:
        _release(job, name)
        shutil.rmtree(work, ignore_errors=True)


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
