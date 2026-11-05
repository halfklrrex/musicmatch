import os
import sys
import threading

import webview

from .api import Api
from .paths import DATA_DIR, WEBUI
from .settings import Settings


def _set_icon(window):
    """Use the Twin Arch icon for the window/taskbar (best effort, off the UI thread)."""
    def work():
        try:
            import clr  # noqa: F401  (pythonnet)
            from System import Action
            from System.Drawing import Icon
            icon = Icon(str(WEBUI / "icon.ico"))
            window.native.Invoke(Action(lambda: setattr(window.native, "Icon", icon)))
        except Exception:
            pass
    threading.Thread(target=work, daemon=True).start()


def _ensure_streams():
    """A windowed exe has no stdout/stderr; the local web server needs them."""
    if not getattr(sys, "frozen", False) and sys.stdout is not None and sys.stderr is not None:
        return
    try:
        DATA_DIR.mkdir(parents=True, exist_ok=True)
        log = open(DATA_DIR / "musicmatch.log", "w", encoding="utf-8", buffering=1)
    except OSError:
        log = open(os.devnull, "w")
    sys.stdout = sys.stderr = log


def main():
    _ensure_streams()
    if os.environ.get("MM_DEBUG"):
        import faulthandler
        faulthandler.dump_traceback_later(10, file=sys.stderr)
    settings = Settings()
    api = Api(settings)
    try:
        w, h = (int(v) for v in str(settings["size"]).split("x"))
    except (ValueError, TypeError):
        w, h = 1120, 780
    window = webview.create_window(
        "MusicMatch", url=str(WEBUI / "index.html"), js_api=api,
        width=max(w, 900), height=max(h, 620), min_size=(900, 620),
        background_color="#F5F5F7",
    )
    api._bind(window)
    window.events.closing += api._on_closing
    window.events.loaded += lambda: _set_icon(window)
    webview.start(debug=bool(os.environ.get("MM_DEBUG")), gui="edgechromium")
