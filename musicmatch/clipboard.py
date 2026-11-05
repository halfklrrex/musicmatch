import re
from urllib.parse import urlparse

_URL = re.compile(r"https?://[^\s<>\"']+")
_HOSTS = ("youtube.com", "youtu.be", "youtube-nocookie.com")


def is_youtube_url(url: str) -> bool:
    try:
        host = (urlparse(url).hostname or "").lower()
    except ValueError:
        return False
    return any(host == h or host.endswith("." + h) for h in _HOSTS)


def extract_urls(text: str) -> list:
    """All distinct YouTube URLs in `text`, in order."""
    seen, out = set(), []
    for m in _URL.findall(text or ""):
        m = m.rstrip(".,);]")
        if is_youtube_url(m) and m not in seen:
            seen.add(m)
            out.append(m)
    return out
