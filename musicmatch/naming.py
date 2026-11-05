"""Work out a clean song title and artist from a YouTube video title.

"Breaking Benjamin - Failure (Official Lyric Video)" -> ("Breaking Benjamin", "Failure")
These guesses are shown in the UI so they can be corrected before downloading.
"""
import re

# words that mark a bracketed or trailing phrase as video clutter, not part of the song name
_NOISE = re.compile(
    r"\b(official|lyric|lyrics|lyrical|video|audio|visuali[sz]er|hd|hq|4k|8k|1080p|720p|mv|m/v|"
    r"music|full song|explicit|clean|remaster(?:ed)?|with lyrics|vevo|topic|out now|premiere|"
    r"animated|clip|clipe|oficial|letra|subtitulado|sub\.? ?(?:espa[nñ]ol|esp))\b",
    re.I)
# words that mean the phrase is part of the song's identity: keep it
_KEEP = re.compile(r"\b(feat|ft|featuring|remix|live|acoustic|cover|version|edit|mix|instrumental|demo|unplugged)\b", re.I)
_GROUP = re.compile(r"\s*[\(\[\{]([^\)\]\}]*)[\)\]\}]")
_SEPARATORS = re.compile(r"\s+[-–—|]\s+|\s*[–—]\s*")
_QUOTES = "\"'“”‘’`«»"


def _is_clutter(text: str) -> bool:
    return bool(_NOISE.search(text)) and not _KEEP.search(text)


def _strip_groups(text: str) -> str:
    return _GROUP.sub(lambda m: "" if _is_clutter(m.group(1)) else m.group(0), text).strip()


def _clean_channel(name: str) -> str:
    name = re.sub(r"\s*-\s*Topic$", "", name or "", flags=re.I)
    name = re.sub(r"\s*(VEVO|Official|Music|Records|Channel)$", "", name, flags=re.I)
    return name.strip()


def _tidy(text: str) -> str:
    text = re.sub(r"\s+", " ", text).strip(" -–—|:,._")
    return text.strip(_QUOTES).strip()


def guess(video_title: str, channel: str = "", artist: str = "", track: str = ""):
    """Return (artist, song). Either may be '' when it cannot be determined."""
    # YouTube Music style uploads carry real tags; trust them.
    if artist and track:
        return _tidy(artist), _tidy(track)

    title = _strip_groups(video_title or "")
    parts = [p for p in _SEPARATORS.split(title) if p.strip()]
    if len(parts) >= 2:
        first, rest = parts[0], [p for p in parts[1:] if not _is_clutter(p)]
        if rest:
            return _tidy(artist or first), _tidy(" - ".join(rest))
    song = _tidy(parts[0] if parts else title)
    return _tidy(artist or _clean_channel(channel)), _tidy(track or song)


def file_base(song: str, artist: str) -> str:
    """'Failure - Breaking Benjamin' (or just the song when the artist is unknown)."""
    return f"{song} - {artist}" if artist else song
