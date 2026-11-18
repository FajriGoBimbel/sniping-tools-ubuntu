"""Full-screen overlay for picking a capture area on a frozen screenshot (one window per monitor)."""
from __future__ import annotations

import cairo
from gi.repository import Gdk, Gtk, Pango

from . import render as R
from .capture import monitor_regions

_DIM = R.rgba(0, 0, 0, 0.45)
_ACCENT = R.rgba(0.21, 0.52, 0.89, 1)
_GUIDE = R.rgba(1, 1, 1, 0.35)


class _MonitorOverlay(Gtk.Window):
    def __init__(self, selector, monitor, region):
        super().__init__()
        self.selector = selector
        self.region = region  # (x, y, w, h) inside the full screenshot, image pixels
        self.set_decorated(False)
        self.set_title("Snipper — pilih area")
        self.add_css_class("snipper-overlay")

        self.area = _OverlayView(self)
        self.area.set_hexpand(True)
        self.area.set_vexpand(True)
        self._texture = None  # this monitor's slice of the screenshot, uploaded to the GPU once
        self._layouts = {}
        self.area.set_cursor(Gdk.Cursor.new_from_name("crosshair", None))
        self.set_child(self.area)

        self.start = None  # image coords
        self.end = None
        self.pointer = None

        drag = Gtk.GestureDrag(button=Gdk.BUTTON_PRIMARY)
        drag.connect("drag-begin", self._on_begin)
        drag.connect("drag-update", self._on_update)
        drag.connect("drag-end", self._on_end)
        self.area.add_controller(drag)
        right = Gtk.GestureClick(button=Gdk.BUTTON_SECONDARY)
        right.connect("pressed", lambda *a: self.selector.cancel())
        self.area.add_controller(right)
        motion = Gtk.EventControllerMotion()
        motion.connect("motion", self._on_motion)
        self.area.add_controller(motion)
        keys = Gtk.EventControllerKey()
        keys.connect("key-pressed", self._on_key)
        self.add_controller(keys)
        self.connect("close-request", lambda *a: (self.selector.cancel(), False)[1])

        if monitor is not None:
            self.fullscreen_on_monitor(monitor)
        else:
            self.fullscreen()

    # coordinate helpers ---------------------------------------------------
    def _scale(self):
        w = max(1, self.area.get_width())
        h = max(1, self.area.get_height())
        return self.region[2] / w, self.region[3] / h

    def _to_image(self, x, y):
        sx, sy = self._scale()
        rx, ry, rw, rh = self.region
        return (min(max(rx + x * sx, rx), rx + rw), min(max(ry + y * sy, ry), ry + rh))

    def _selection(self):
        if not self.start or not self.end:
            return None
        x0, y0 = self.start
        x1, y1 = self.end
        x, y = round(min(x0, x1)), round(min(y0, y1))
        return x, y, round(max(x0, x1)) - x, round(max(y0, y1)) - y

    # events -------------------------------------------------------------
    def _on_begin(self, gesture, x, y):
        self.start = self.end = self._to_image(x, y)
        self.area.queue_draw()

    def _on_update(self, gesture, dx, dy):
        ok, sx, sy = gesture.get_start_point()
        self.end = self._to_image(sx + dx, sy + dy)
        self.pointer = (sx + dx, sy + dy)
        self.area.queue_draw()

    def _on_end(self, gesture, dx, dy):
        sel = self._selection()
        if sel and sel[2] >= 4 and sel[3] >= 4:
            self.selector.finish(sel)
        else:
            # a plain click captures this whole monitor
            self.selector.finish(self.region)

    def _on_motion(self, ctrl, x, y):
        self.pointer = (x, y)
        self.area.queue_draw()

    def _on_key(self, ctrl, keyval, keycode, state):
        if keyval == Gdk.KEY_Escape:
            self.selector.cancel()
            return True
        if keyval in (Gdk.KEY_Return, Gdk.KEY_KP_Enter, Gdk.KEY_space):
            sel = self._selection()
            self.selector.finish(sel if sel and sel[2] >= 4 and sel[3] >= 4 else self.region)
            return True
        return False

    # drawing ------------------------------------------------------------
    def _layout(self, key, text, size, bold):
        layout = self._layouts.get(key)
        if layout is None:
            layout = self.area.create_pango_layout(None)
            desc = Pango.FontDescription.from_string(f"Sans {'Bold ' if bold else ''}{size}")
            layout.set_font_description(desc)
            self._layouts[key] = layout
        if layout.get_text() != text:
            layout.set_text(text, -1)
        return layout

    def _snapshot(self, snapshot, width, height):
        """Everything here is GPU work: one cached texture plus a handful of colour nodes."""
        if width <= 0 or height <= 0:
            return
        rx, ry, rw, rh = self.region
        sx, sy = rw / width, rh / height
        if self._texture is None:
            from .document import crop_surface

            self._texture = R.texture_from_surface(crop_surface(self.selector.surface, rx, ry, rw, rh))
        R.append_texture(snapshot, self._texture, R.rect(0, 0, width, height), R.device_scale(self) / sx)

        sel = self._selection()
        hole = None
        if sel and sel[2] > 0 and sel[3] > 0:
            x, y, w, h = sel
            hole = ((x - rx) / sx, (y - ry) / sy, w / sx, h / sy)
        R.dim_outside(snapshot, _DIM, width, height, hole)

        if hole:
            vx, vy, vw, vh = hole
            R.outline(snapshot, _ACCENT, vx, vy, vw, vh, 1.5)
            self._label(snapshot, f"{sel[2]} × {sel[3]}", vx, vy + vh + 8, width, height, above_y=vy - 8)
        else:
            # crosshair guides help aim on a dimmed screen
            if self.pointer:
                px, py = self.pointer
                R.fill(snapshot, _GUIDE, 0, int(py), width, 1)
                R.fill(snapshot, _GUIDE, int(px), 0, 1, height)
            hint = self._layout("hint", "Drag untuk memilih area  ·  Klik = layar ini  ·  Esc = batal", 12, False)
            _ink, log = hint.get_pixel_extents()
            R.pill(snapshot, hint, (width - log.width - 12) / 2, 24)

    def _label(self, snapshot, text, x, y, width, height, above_y):
        layout = self._layout("label", text, 13, True)
        _ink, log = layout.get_pixel_extents()
        w, h = log.width + 12, log.height + 12
        if y + h > height:
            y = above_y - h
        x = min(max(0, x), width - w)
        y = min(max(0, y), height - h)
        R.pill(snapshot, layout, x, y)


class _OverlayView(Gtk.Widget):
    def __init__(self, owner):
        super().__init__()
        self.owner = owner

    def do_snapshot(self, snapshot):
        self.owner._snapshot(snapshot, self.get_width(), self.get_height())


class AreaSelector:
    """callback(cropped_surface | None)"""

    def __init__(self, app, surface: cairo.ImageSurface, callback):
        self.app = app
        self.surface = surface
        self.callback = callback
        self.done = False
        regions = monitor_regions(surface.get_width(), surface.get_height())
        if len(regions) <= 1:
            regions = [(regions[0][0] if regions else None, (0, 0, surface.get_width(), surface.get_height()))]
        self.windows = []
        for monitor, region in regions:
            win = _MonitorOverlay(self, monitor, region)
            win.set_application(app)
            self.windows.append(win)
            win.present()

    def _close_all(self):
        for w in self.windows:
            w.destroy()
        self.windows = []

    def finish(self, region):
        if self.done:
            return
        self.done = True
        self._close_all()
        from .document import crop_surface

        self.callback(crop_surface(self.surface, *region))

    def cancel(self):
        if self.done:
            return
        self.done = True
        self._close_all()
        self.callback(None)
