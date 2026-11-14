"""Taking the raw screenshot.

Primary path: the XDG Desktop Portal (works on Wayland and X11 under GNOME).
Fallback: whatever classic screenshot CLI is installed (for X11 sessions without a portal).
"""
from __future__ import annotations

import os
import shutil
import subprocess
import tempfile
import time

from gi.repository import Gio, GLib

PORTAL_BUS = "org.freedesktop.portal.Desktop"
PORTAL_PATH = "/org/freedesktop/portal/desktop"
SCREENSHOT_IFACE = "org.freedesktop.portal.Screenshot"


def _session_bus():
    return Gio.bus_get_sync(Gio.BusType.SESSION, None)


def register_host_app(app_id: str) -> bool:
    """Tell xdg-desktop-portal (>= 1.19) who we are, so the screenshot permission is remembered per app.

    Must run before any other portal call on this connection. Older portals lack the
    interface; that's fine, the call just fails.
    """
    try:
        _session_bus().call_sync(
            PORTAL_BUS, PORTAL_PATH, "org.freedesktop.host.portal.Registry", "Register",
            GLib.Variant("(sa{sv})", (app_id, {})), None, Gio.DBusCallFlags.NONE, 2000, None,
        )
        return True
    except GLib.Error:
        return False


def portal_available() -> bool:
    try:
        bus = _session_bus()
        res = bus.call_sync(
            "org.freedesktop.DBus", "/org/freedesktop/DBus", "org.freedesktop.DBus", "NameHasOwner",
            GLib.Variant("(s)", (PORTAL_BUS,)), None, Gio.DBusCallFlags.NONE, 1000, None,
        )
        if res.unpack()[0]:
            return True
        # not running yet but activatable?
        res = bus.call_sync(
            "org.freedesktop.DBus", "/org/freedesktop/DBus", "org.freedesktop.DBus", "ListActivatableNames",
            None, None, Gio.DBusCallFlags.NONE, 1000, None,
        )
        return PORTAL_BUS in res.unpack()[0]
    except GLib.Error:
        return False


def has_screenshot_permission(app_id: str):
    """True/False if the permission store knows the answer, None if never asked."""
    try:
        res = _session_bus().call_sync(
            "org.freedesktop.impl.portal.PermissionStore", "/org/freedesktop/impl/portal/PermissionStore",
            "org.freedesktop.impl.portal.PermissionStore", "Lookup",
            GLib.Variant("(ss)", ("screenshot", "screenshot")), None, Gio.DBusCallFlags.NONE, 1000, None,
        )
        perms = res.unpack()[0]
    except GLib.Error:
        return None
    for key in (app_id, ""):
        if key in perms:
            return "yes" in perms[key]
    return None


class PortalScreenshot:
    """One async Screenshot request. callback(path | None, error: str | None, cancelled: bool)."""

    _counter = 0

    def __init__(self, interactive: bool, callback, parent_window: str = ""):
        self.bus = _session_bus()
        self.callback = callback
        PortalScreenshot._counter += 1
        token = f"snipper_{os.getpid()}_{PortalScreenshot._counter}"
        sender = self.bus.get_unique_name()[1:].replace(".", "_")
        handle = f"/org/freedesktop/portal/desktop/request/{sender}/{token}"
        self._done = False
        self._sub = self.bus.signal_subscribe(
            PORTAL_BUS, "org.freedesktop.portal.Request", "Response", handle, None,
            Gio.DBusSignalFlags.NONE, self._on_response,
        )
        opts = {"handle_token": GLib.Variant("s", token), "interactive": GLib.Variant("b", interactive)}
        self.bus.call(
            PORTAL_BUS, PORTAL_PATH, SCREENSHOT_IFACE, "Screenshot",
            GLib.Variant("(sa{sv})", (parent_window, opts)), GLib.VariantType("(o)"),
            Gio.DBusCallFlags.NONE, -1, None, self._on_called,
        )
        if not interactive:
            # a non-interactive capture should be near instant; don't hang forever
            self._timeout = GLib.timeout_add_seconds(20, self._on_timeout)
        else:
            self._timeout = 0

    def _finish(self, path, error, cancelled=False):
        if self._done:
            return
        self._done = True
        if self._sub:
            self.bus.signal_unsubscribe(self._sub)
            self._sub = 0
        if self._timeout:
            GLib.source_remove(self._timeout)
            self._timeout = 0
        self.callback(path, error, cancelled)

    def _on_timeout(self):
        self._timeout = 0
        self._finish(None, "Portal screenshot timeout")
        return False

    def _on_called(self, bus, result):
        try:
            bus.call_finish(result)
        except GLib.Error as e:
            self._finish(None, e.message)

    def _on_response(self, _conn, _sender, _path, _iface, _signal, params):
        code, results = params.unpack()
        if code == 0 and results.get("uri"):
            self._finish(Gio.File.new_for_uri(results["uri"]).get_path(), None)
        elif code == 1:
            self._finish(None, None, cancelled=True)
        else:
            self._finish(None, "denied")


# ---------------------------------------------------------------------------
# CLI fallbacks (X11 sessions without a portal, other desktops)


def _tmp_png():
    d = GLib.get_user_runtime_dir() or tempfile.gettempdir()
    return os.path.join(d, f"snipper-{os.getpid()}-{int(time.time() * 1000)}.png")


def capture_with_tools(mode: str) -> str:
    """Capture with an installed CLI tool. mode: 'full' or 'window'. Returns the PNG path."""
    out = _tmp_png()
    if mode == "window":
        cmds = [
            ["gnome-screenshot", "-w", "-f", out],
            ["spectacle", "-b", "-n", "-a", "-o", out],
            ["scrot", "-u", "-o", out],
        ]
        if shutil.which("xdotool") and shutil.which("maim"):
            try:
                wid = subprocess.check_output(["xdotool", "getactivewindow"], text=True).strip()
                cmds.insert(1, ["maim", "-i", wid, out])
            except (OSError, subprocess.CalledProcessError):
                pass
    else:
        cmds = [
            ["gnome-screenshot", "-f", out],
            ["spectacle", "-b", "-n", "-f", "-o", out],
            ["grim", out],
            ["maim", out],
            ["scrot", "-o", out],
            ["import", "-window", "root", out],
        ]
    for cmd in cmds:
        if not shutil.which(cmd[0]):
            continue
        try:
            subprocess.run(cmd, check=True, timeout=20, stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)
        except (OSError, subprocess.SubprocessError):
            continue
        if os.path.exists(out) and os.path.getsize(out) > 0:
            return out
    raise RuntimeError(
        "Tidak bisa mengambil screenshot: XDG Desktop Portal tidak tersedia dan tidak ada "
        "alat fallback (gnome-screenshot, maim, scrot, grim, import)."
    )


# ---------------------------------------------------------------------------
# Monitor layout -> image regions


def monitor_regions(img_w: int, img_h: int):
    """Map each Gdk monitor to its rectangle inside a full-desktop screenshot.

    Returns a list of (Gdk.Monitor, (x, y, w, h)) in image pixels.
    """
    from gi.repository import Gdk

    display = Gdk.Display.get_default()
    model = display.get_monitors()
    monitors = [model.get_item(i) for i in range(model.get_n_items())]
    if not monitors:
        return []
    geos = [m.get_geometry() for m in monitors]
    bx = min(g.x for g in geos)
    by = min(g.y for g in geos)
    bw = max(g.x + g.width for g in geos) - bx
    bh = max(g.y + g.height for g in geos) - by
    sx, sy = img_w / bw, img_h / bh
    out = []
    for m, g in zip(monitors, geos):
        rx, ry = round((g.x - bx) * sx), round((g.y - by) * sy)
        rw, rh = round(g.width * sx), round(g.height * sy)
        rw, rh = min(rw, img_w - rx), min(rh, img_h - ry)
        out.append((m, (rx, ry, rw, rh)))
    return out
