"""Look up title/duration/thumbnail for a URL; playlists expand to many entries."""
import json
import subprocess

from .paths import NO_WINDOW, tool_env, ytdlp_path


def _watch_url(video_id: str) -> str:
    return f"https://www.youtube.com/watch?v={video_id}"


def fetch(url: str) -> list:
    """Return a list of dicts: url, title, duration, channel, thumb."""
    proc = subprocess.run(
        [str(ytdlp_path()), "-J", "--flat-playlist", "--no-warnings", url],
        capture_output=True, text=True, encoding="utf-8", errors="replace",
        timeout=180, creationflags=NO_WINDOW, env=tool_env(), stdin=subprocess.DEVNULL,
    )
    if proc.returncode != 0:
        lines = [l for l in (proc.stderr or "").splitlines() if l.strip()]
        raise RuntimeError(lines[-1] if lines else "yt-dlp failed")
    data = json.loads(proc.stdout)

    def entry(d: dict, fallback_url: str) -> dict:
        vid = d.get("id")
        u = d.get("webpage_url") or d.get("url") or fallback_url
        if not str(u).startswith("http") and vid:
            u = _watch_url(vid)
        thumb = f"https://i.ytimg.com/vi/{vid}/mqdefault.jpg" if vid else d.get("thumbnail")
        return {
            "url": u,
            "title": d.get("title") or u,
            "duration": d.get("duration"),
            "channel": d.get("channel") or d.get("uploader") or "",
            "artist": d.get("artist") or "",
            "track": d.get("track") or "",
            "thumb": thumb,
        }

    if data.get("_type") == "playlist":
        return [entry(e, url) for e in data.get("entries") or [] if e]
    return [entry(data, url)]


def fmt_duration(seconds) -> str:
    if not seconds:
        return ""
    s = int(seconds)
    h, rem = divmod(s, 3600)
    m, s = divmod(rem, 60)
    return f"{h}:{m:02d}:{s:02d}" if h else f"{m}:{s:02d}"
