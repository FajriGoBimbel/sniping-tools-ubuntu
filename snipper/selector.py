"""Full-screen overlay for picking a capture area on a frozen screenshot (one window per monitor)."""
from __future__ import annotations

import cairo
from gi.repository import Gdk, Gtk, Pango, PangoCairo

from .capture import monitor_regions


class _MonitorOverlay(Gtk.Window):
    def __init__(self, selector, monitor, region):
        super().__init__()
        self.selector = selector
        self.region = region  # (x, y, w, h) inside the full screenshot, image pixels
        self.set_decorated(False)
        self.set_title("Snipper — pilih area")
        self.add_css_class("snipper-overlay")

        self.area = Gtk.DrawingArea()
        self.area.set_draw_func(self._draw)
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
    def _draw(self, area, cr, width, height):
        rx, ry, rw, rh = self.region
        sx, sy = rw / max(1, width), rh / max(1, height)
        cr.save()
        cr.scale(1 / sx, 1 / sy)
        cr.translate(-rx, -ry)
        cr.set_source_surface(self.selector.surface, 0, 0)
        cr.paint()
        cr.restore()

        sel = self._selection()
        # dim everything except the selection
        cr.set_source_rgba(0, 0, 0, 0.45)
        cr.set_fill_rule(cairo.FILL_RULE_EVEN_ODD)
        cr.rectangle(0, 0, width, height)
        if sel:
            x, y, w, h = sel
            vx, vy, vw, vh = (x - rx) / sx, (y - ry) / sy, w / sx, h / sy
            cr.rectangle(vx, vy, vw, vh)
        cr.fill()

        if sel and sel[2] > 0 and sel[3] > 0:
            cr.set_source_rgba(0.21, 0.52, 0.89, 1)
            cr.set_line_width(1.5)
            cr.rectangle(vx + 0.5, vy + 0.5, vw - 1, vh - 1)
            cr.stroke()
            self._label(cr, f"{w} × {h}", vx, vy + vh + 8, width, height, above_y=vy - 8)
        else:
            # crosshair guides help aim on a dimmed screen
            if self.pointer:
                px, py = self.pointer
                cr.set_source_rgba(1, 1, 1, 0.35)
                cr.set_line_width(1)
                cr.move_to(0, int(py) + 0.5)
                cr.line_to(width, int(py) + 0.5)
                cr.move_to(int(px) + 0.5, 0)
                cr.line_to(int(px) + 0.5, height)
                cr.stroke()
            self._hint(cr, width)

    def _text_layout(self, cr, text, size=13, bold=True):
        layout = PangoCairo.create_layout(cr)
        desc = Pango.FontDescription.from_string(f"Sans {'Bold ' if bold else ''}{size}")
        layout.set_font_description(desc)
        layout.set_text(text, -1)
        return layout

    def _pill(self, cr, layout, x, y):
        _ink, log = layout.get_pixel_extents()
        pad = 6
        w, h = log.width + 2 * pad, log.height + 2 * pad
        r = 6
        cr.new_sub_path()
        cr.arc(x + w - r, y + r, r, -1.5708, 0)
        cr.arc(x + w - r, y + h - r, r, 0, 1.5708)
        cr.arc(x + r, y + h - r, r, 1.5708, 3.1416)
        cr.arc(x + r, y + r, r, 3.1416, 4.7124)
        cr.close_path()
        cr.set_source_rgba(0.1, 0.1, 0.12, 0.85)
        cr.fill()
        cr.move_to(x + pad, y + pad)
        cr.set_source_rgb(1, 1, 1)
        PangoCairo.show_layout(cr, layout)
        return w, h

    def _label(self, cr, text, x, y, width, height, above_y):
        layout = self._text_layout(cr, text)
        _ink, log = layout.get_pixel_extents()
        w, h = log.width + 12, log.height + 12
        if y + h > height:
            y = above_y - h
        x = min(max(0, x), width - w)
        y = min(max(0, y), height - h)
        self._pill(cr, layout, x, y)

    def _hint(self, cr, width):
        layout = self._text_layout(
            cr, "Drag untuk memilih area  ·  Klik = layar ini  ·  Esc = batal", size=12, bold=False
        )
        _ink, log = layout.get_pixel_extents()
        self._pill(cr, layout, (width - log.width - 12) / 2, 24)


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
