import re
from urllib.parse import parse_qs, urlparse

_URL = re.compile(r"https?://[^\s<>\"']+")
_HOSTS = ("youtube.com", "youtu.be", "youtube-nocookie.com")
_ID = re.compile(r"^[A-Za-z0-9_-]{11}$")


def is_youtube_url(url: str) -> bool:
    try:
        host = (urlparse(url).hostname or "").lower()
    except ValueError:
        return False
    return any(host == h or host.endswith("." + h) for h in _HOSTS)


def video_url(url: str):
    """Canonical link to the single video a URL points at, or None.

    Playlist, mix, channel and search links have no single video, and any
    '&list=...' on a video link is dropped so only that one song is added.
    """
    try:
        p = urlparse(url)
    except ValueError:
        return None
    host = (p.hostname or "").lower()
    vid = None
    if host == "youtu.be" or host.endswith(".youtu.be"):
        vid = p.path.strip("/").split("/")[0]
    else:
        parts = [x for x in p.path.split("/") if x]
        if parts and parts[0] == "watch":
            vid = (parse_qs(p.query).get("v") or [""])[0]
        elif len(parts) >= 2 and parts[0] in ("shorts", "embed", "live", "v"):
            vid = parts[1]
    return f"https://www.youtube.com/watch?v={vid}" if vid and _ID.match(vid) else None


def scan(text: str):
    """(single-video links, number of YouTube links that are not a single video)"""
    seen, videos, skipped = set(), [], 0
    for m in _URL.findall(text or ""):
        m = m.rstrip(".,);]")
        if not is_youtube_url(m):
            continue
        v = video_url(m)
        if v is None:
            skipped += 1
        elif v not in seen:
            seen.add(v)
            videos.append(v)
    return videos, skipped


def extract_urls(text: str) -> list:
    """All distinct single-video YouTube links in `text`, in order."""
    return scan(text)[0]
