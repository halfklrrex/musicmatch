import json
from pathlib import Path

from .paths import DATA_DIR

DEFAULTS = {
    "out_dir": str(Path.home() / "Downloads" / "MusicMatch"),
    "fmt": "MP3",
    "kbps": "320",
    "height": "Best",
    "parallel": "2",
    "size": "1120x780",
    "lang": "",
}


class Settings:
    def __init__(self):
        self.path = DATA_DIR / "settings.json"
        self.data = dict(DEFAULTS)
        try:
            self.data.update(json.loads(self.path.read_text(encoding="utf-8")))
        except Exception:
            pass

    def __getitem__(self, key):
        return self.data.get(key, DEFAULTS.get(key))

    def __setitem__(self, key, value):
        self.data[key] = value
        self.save()

    def save(self):
        try:
            DATA_DIR.mkdir(parents=True, exist_ok=True)
            self.path.write_text(json.dumps(self.data, indent=2), encoding="utf-8")
        except Exception:
            pass
