"""Locations of bundled tools and per-user data."""
import os
import shutil
import subprocess
import sys
from pathlib import Path

APP = "MusicMatch"
NO_WINDOW = getattr(subprocess, "CREATE_NO_WINDOW", 0)


def _bundle_bin() -> Path:
    if getattr(sys, "frozen", False):
        return Path(getattr(sys, "_MEIPASS", Path(sys.executable).parent)) / "bin"
    return Path(__file__).resolve().parent.parent / "bin"


BUNDLED_BIN = _bundle_bin()
ASSETS = (
    Path(getattr(sys, "_MEIPASS", ".")) / "musicmatch" / "assets"
    if getattr(sys, "frozen", False)
    else Path(__file__).resolve().parent / "assets"
)
DATA_DIR = Path(os.environ.get("APPDATA", str(Path.home()))) / APP
LOCAL_BIN = Path(os.environ.get("LOCALAPPDATA", str(Path.home()))) / APP / "bin"


def ytdlp_path() -> Path:
    """yt-dlp lives in a writable per-user folder so `yt-dlp -U` can replace it."""
    LOCAL_BIN.mkdir(parents=True, exist_ok=True)
    local = LOCAL_BIN / "yt-dlp.exe"
    bundled = BUNDLED_BIN / "yt-dlp.exe"
    if not local.exists() and bundled.exists():
        shutil.copy2(bundled, local)
    return local if local.exists() else bundled


def ffmpeg_dir() -> Path:
    return BUNDLED_BIN


def ffmpeg_path() -> Path:
    return BUNDLED_BIN / "ffmpeg.exe"


def tool_env() -> dict:
    env = os.environ.copy()
    # Bundled dir first so yt-dlp finds deno (JS runtime) and ffmpeg.
    env["PATH"] = str(BUNDLED_BIN) + os.pathsep + env.get("PATH", "")
    env["PYTHONIOENCODING"] = "utf-8"
    env["PYTHONUTF8"] = "1"
    return env
