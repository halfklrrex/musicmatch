import json
import time

from .paths import DATA_DIR

PATH = DATA_DIR / "history.json"
MAX = 500


def load() -> list:
    try:
        data = json.loads(PATH.read_text(encoding="utf-8"))
        return data if isinstance(data, list) else []
    except Exception:
        return []


def _save(items: list):
    try:
        DATA_DIR.mkdir(parents=True, exist_ok=True)
        PATH.write_text(json.dumps(items[:MAX], indent=2), encoding="utf-8")
    except Exception:
        pass


def add(title: str, path: str, fmt: str):
    items = load()
    items.insert(0, {
        "title": title,
        "path": path,
        "fmt": fmt,
        "date": time.strftime("%Y-%m-%d %H:%M"),
    })
    _save(items)


def clear():
    _save([])
