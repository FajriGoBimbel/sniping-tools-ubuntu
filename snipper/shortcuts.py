"""Global shortcuts via GNOME custom keybindings (works on Ubuntu 22.04/24.04, Wayland and X11).

GNOME Shell binds Print / Shift+Print / Alt+Print to its own screenshot UI, so installing our
bindings moves the shell's ones out of the way (and remembers them, so removal restores them).
"""
from __future__ import annotations

import json
import os

from gi.repository import Gio, Gtk

from .settings import CONFIG_DIR

MEDIA_KEYS = "org.gnome.settings-daemon.plugins.media-keys"
CUSTOM_SCHEMA = "org.gnome.settings-daemon.plugins.media-keys.custom-keybinding"
CUSTOM_BASE = "/org/gnome/settings-daemon/plugins/media-keys/custom-keybindings/"
SHELL_KEYS = "org.gnome.shell.keybindings"
SHELL_SCREENSHOT_KEYS = ("show-screenshot-ui", "screenshot", "screenshot-window")
BACKUP_FILE = os.path.join(CONFIG_DIR, "gnome-shortcuts-backup.json")

ACTIONS = {
    "area": ("Snipper: capture area", "--area"),
    "full": ("Snipper: capture layar penuh", "--full"),
    "window": ("Snipper: capture jendela", "--window"),
}


def _schema(name):
    src = Gio.SettingsSchemaSource.get_default()
    return src.lookup(name, True) if src else None


def supported() -> bool:
    return _schema(MEDIA_KEYS) is not None and _schema(CUSTOM_SCHEMA) is not None


def valid_accel(accel: str) -> bool:
    if not accel:
        return True
    res = Gtk.accelerator_parse(accel)
    key = res[1] if len(res) == 3 else res[0]  # GTK4: (ok, key, mods)
    return bool(key)


def _path(action):
    return f"{CUSTOM_BASE}snipper-{action}/"


def installed() -> bool:
    if not supported():
        return False
    paths = Gio.Settings.new(MEDIA_KEYS).get_strv("custom-keybindings")
    return any(p == _path(a) for p in paths for a in ACTIONS)


def install(command: str, accels: dict) -> None:
    """command: shell command that launches Snipper; accels: {'area': 'Print', ...}."""
    if not supported():
        raise RuntimeError("Pengaturan shortcut GNOME tidak ditemukan di sistem ini.")
    wanted = {a for a, acc in accels.items() if acc}

    # free the keys from GNOME Shell's built-in screenshot UI (backup once)
    if _schema(SHELL_KEYS):
        shell = Gio.Settings.new(SHELL_KEYS)
        keys = [k for k in SHELL_SCREENSHOT_KEYS if shell.props.settings_schema.has_key(k)]
        if not os.path.exists(BACKUP_FILE):
            os.makedirs(CONFIG_DIR, exist_ok=True)
            with open(BACKUP_FILE, "w") as f:
                json.dump({k: list(shell.get_strv(k)) for k in keys}, f)
        taken = set(accels.values())
        for k in keys:
            remaining = [b for b in shell.get_strv(k) if b not in taken]
            shell.set_strv(k, remaining)

    media = Gio.Settings.new(MEDIA_KEYS)
    paths = [p for p in media.get_strv("custom-keybindings") if not p.startswith(f"{CUSTOM_BASE}snipper-")]
    for action, (name, flag) in ACTIONS.items():
        if action not in wanted:
            continue
        s = Gio.Settings.new_with_path(CUSTOM_SCHEMA, _path(action))
        s.set_string("name", name)
        s.set_string("command", f"{command} {flag}")
        s.set_string("binding", accels[action])
        paths.append(_path(action))
    media.set_strv("custom-keybindings", paths)
    Gio.Settings.sync()


def remove() -> None:
    if not supported():
        return
    media = Gio.Settings.new(MEDIA_KEYS)
    media.set_strv(
        "custom-keybindings",
        [p for p in media.get_strv("custom-keybindings") if not p.startswith(f"{CUSTOM_BASE}snipper-")],
    )
    for action in ACTIONS:
        s = Gio.Settings.new_with_path(CUSTOM_SCHEMA, _path(action))
        for key in ("name", "command", "binding"):
            s.reset(key)
    if os.path.exists(BACKUP_FILE) and _schema(SHELL_KEYS):
        shell = Gio.Settings.new(SHELL_KEYS)
        try:
            with open(BACKUP_FILE) as f:
                backup = json.load(f)
            for k, v in backup.items():
                shell.set_strv(k, v)
        except (OSError, ValueError):
            pass
        os.remove(BACKUP_FILE)
    Gio.Settings.sync()
