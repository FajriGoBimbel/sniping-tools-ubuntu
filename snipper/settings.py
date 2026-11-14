"""User preferences stored as JSON in ~/.config/snipper/settings.json."""
from __future__ import annotations

import json
import os
from datetime import datetime

from gi.repository import GLib

APP_ID = "com.wahanacreative.Snipper"
APP_NAME = "Snipper"
VERSION = "0.1.0"

CONFIG_DIR = os.path.join(GLib.get_user_config_dir(), "snipper")
CONFIG_FILE = os.path.join(CONFIG_DIR, "settings.json")


def default_save_dir():
    pics = GLib.get_user_special_dir(GLib.UserDirectory.DIRECTORY_PICTURES) or os.path.expanduser("~/Pictures")
    return os.path.join(pics, "Screenshots")


DEFAULTS = {
    "save_dir": None,  # None -> ~/Pictures/Screenshots
    "format": "png",  # png | jpg
    "jpg_quality": 92,
    "fullscreen_monitor": -1,  # -1 = all monitors, otherwise monitor index
    "default_delay": 0,
    "copy_after_capture": False,
    "close_after_save": False,
    "color": [0.88, 0.11, 0.14, 1.0],
    "width": 4,
    "font_size": 28,
    "bold": True,
    "fill": False,
    "shortcuts": {"area": "Print", "full": "<Shift>Print", "window": "<Alt>Print"},
}


class Settings:
    def __init__(self):
        self.data = json.loads(json.dumps(DEFAULTS))
        try:
            with open(CONFIG_FILE) as f:
                stored = json.load(f)
            for k, v in stored.items():
                if k in self.data:
                    self.data[k] = v
        except (OSError, ValueError):
            pass

    def __getitem__(self, key):
        return self.data[key]

    def __setitem__(self, key, value):
        self.data[key] = value
        self.save()

    def save(self):
        try:
            os.makedirs(CONFIG_DIR, exist_ok=True)
            tmp = CONFIG_FILE + ".tmp"
            with open(tmp, "w") as f:
                json.dump(self.data, f, indent=2)
            os.replace(tmp, CONFIG_FILE)
        except OSError:
            pass

    @property
    def save_dir(self):
        return os.path.expanduser(self.data["save_dir"] or default_save_dir())

    def new_filename(self, ext=None):
        ext = ext or self.data["format"]
        stamp = datetime.now().strftime("%Y-%m-%d_%H-%M-%S")
        base = os.path.join(self.save_dir, f"Screenshot_{stamp}")
        path = f"{base}.{ext}"
        n = 2
        while os.path.exists(path):
            path = f"{base}_{n}.{ext}"
            n += 1
        return path
