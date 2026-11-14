"""Interactive Cairo canvas: draws the document and turns pointer input into annotation edits."""
from __future__ import annotations

import math

import cairo
from gi.repository import Gdk, GObject, Gtk

from . import shapes as S

TOOLS = ("select", "rect", "ellipse", "line", "arrow", "text", "highlight", "blur", "step", "pen", "crop")
SELECTION_COLOR = (0.21, 0.52, 0.89)


class Style:
    def __init__(self, color, width, fill, font_size, bold):
        self.color = tuple(color)
        self.width = width
        self.fill = fill
        self.font_size = font_size
        self.bold = bold


class Canvas(Gtk.DrawingArea):
    __gsignals__ = {
        "changed": (GObject.SignalFlags.RUN_FIRST, None, ()),  # document changed (history)
        "selection-changed": (GObject.SignalFlags.RUN_FIRST, None, ()),
        "zoom-changed": (GObject.SignalFlags.RUN_FIRST, None, ()),
        "request-text": (GObject.SignalFlags.RUN_FIRST, None, (object, float, float)),  # shape|None, x, y (widget)
    }

    def __init__(self, doc, style: Style):
        super().__init__()
        self.doc = doc
        self.style = style
        self.tool = "rect"
        self.zoom = 1.0
        self.selected = None
        self.set_focusable(True)
        self.set_draw_func(self._draw)

        self._mode = None  # create | move | resize | crop | None
        self._handle = None
        self._last = None
        self._start_img = None
        self._pre_snap = None
        self._changed = False
        self._crop_rect = None
        self._pending_text = None  # (x, y) image coords where a new text goes

        drag = Gtk.GestureDrag(button=Gdk.BUTTON_PRIMARY)
        drag.connect("drag-begin", self._on_begin)
        drag.connect("drag-update", self._on_update)
        drag.connect("drag-end", self._on_end)
        self.add_controller(drag)
        self._drag = drag

        click = Gtk.GestureClick(button=Gdk.BUTTON_PRIMARY)
        click.connect("pressed", self._on_click)
        self.add_controller(click)

        motion = Gtk.EventControllerMotion()
        motion.connect("motion", self._on_motion)
        self.add_controller(motion)

        self._update_size()

    # coordinates ----------------------------------------------------------
    def to_image(self, x, y):
        cx, cy, _, _ = self.doc.crop
        return x / self.zoom + cx, y / self.zoom + cy

    def to_widget(self, ix, iy):
        cx, cy, _, _ = self.doc.crop
        return (ix - cx) * self.zoom, (iy - cy) * self.zoom

    def tolerance(self):
        return 6 / self.zoom

    def set_zoom(self, zoom):
        zoom = max(0.05, min(zoom, 16.0))
        if abs(zoom - self.zoom) > 1e-6:
            self.zoom = zoom
            self._update_size()
            self.emit("zoom-changed")

    def _update_size(self):
        self.set_size_request(max(1, int(self.doc.width * self.zoom)), max(1, int(self.doc.height * self.zoom)))
        self.queue_draw()

    def document_changed(self):
        """Call after undo/redo or any external change to the document."""
        if self.selected is not None and self.selected not in self.doc.shapes:
            self.selected = None
            self.emit("selection-changed")
        self._update_size()

    # tools / selection -----------------------------------------------------
    def set_tool(self, tool):
        self.tool = tool
        if tool in ("crop",):
            self.select(None)
        self._update_cursor(None)
        self.queue_draw()

    def select(self, shape):
        if shape is not self.selected:
            self.selected = shape
            self.emit("selection-changed")
        self.queue_draw()

    def delete_selected(self):
        if self.selected is None:
            return False
        self.doc.checkpoint()
        self.doc.shapes.remove(self.selected)
        self.selected = None
        self.emit("selection-changed")
        self.emit("changed")
        self.queue_draw()
        return True

    def nudge_selected(self, dx, dy):
        if self.selected is None:
            return False
        self.doc.checkpoint()
        self.selected.move(dx, dy)
        self.emit("changed")
        self.queue_draw()
        return True

    def apply_style_to_selection(self, attr):
        """Push one style attribute (color/width/fill/font_size/bold) onto the selected shape."""
        s = self.selected
        if s is None:
            return
        mapping = {"color": "color", "width": "width", "fill": "fill", "font_size": "size", "bold": "bold"}
        target = mapping[attr]
        if not hasattr(s, target):
            return
        value = getattr(self.style, attr)
        if target == "color":
            value = tuple(value)
        if getattr(s, target) == value:
            return
        self.doc.checkpoint()
        setattr(s, target, value)
        self.emit("changed")
        self.queue_draw()

    # text -----------------------------------------------------------------
    def commit_text(self, shape, text):
        """Called by the editor when the text popover is confirmed."""
        if shape is None:
            if not text.strip() or self._pending_text is None:
                return
            x, y = self._pending_text
            self.doc.checkpoint()
            st = self.style
            shape = S.TextShape(x, y, text, size=st.font_size, bold=st.bold, color=st.color)
            self.doc.shapes.append(shape)
            self.select(shape)
        else:
            if text == shape.text:
                return
            self.doc.checkpoint()
            if text.strip():
                shape.text = text
            else:
                self.doc.shapes.remove(shape)
                self.select(None)
        self._pending_text = None
        self.emit("changed")
        self.queue_draw()

    def _request_text(self, shape, ix, iy):
        if shape is None:
            self._pending_text = (ix, iy)
        wx, wy = self.to_widget(ix, iy)
        self.emit("request-text", shape, wx, wy)

    # shape factory --------------------------------------------------------
    def _new_shape(self, x, y):
        st = self.style
        kw = {"color": st.color, "width": st.width}
        t = self.tool
        if t == "rect":
            return S.RectShape(x, y, fill=st.fill, **kw)
        if t == "ellipse":
            return S.EllipseShape(x, y, fill=st.fill, **kw)
        if t == "line":
            return S.LineShape(x, y, **kw)
        if t == "arrow":
            return S.LineShape(x, y, arrow=True, **kw)
        if t == "highlight":
            return S.HighlightShape(x, y, **kw)
        if t == "blur":
            return S.BlurShape(x, y, **kw)
        if t == "pen":
            return S.PenShape(x, y, **kw)
        if t == "step":
            return S.StepShape(x, y, number=self.doc.next_step_number(), **kw)
        return None

    def _handle_at(self, x, y):
        s = self.selected
        if s is None or not s.resizable:
            return None
        r = 7 / self.zoom
        for name, (hx, hy) in s.handles().items():
            if abs(x - hx) <= r and abs(y - hy) <= r:
                return name
        return None

    # gestures -----------------------------------------------------------
    def _shift_held(self, gesture):
        state = gesture.get_current_event_state()
        return bool(state & Gdk.ModifierType.SHIFT_MASK)

    def _on_click(self, gesture, n_press, x, y):
        self.grab_focus()
        if n_press == 2 and self.tool != "text":
            ix, iy = self.to_image(x, y)
            hit = self.doc.shape_at(ix, iy, self.tolerance())
            if isinstance(hit, S.TextShape):
                self._drag.reset()
                self.select(hit)
                self._request_text(hit, hit.x, hit.y)

    def _on_begin(self, gesture, x, y):
        ix, iy = self.to_image(x, y)
        self._start_img = self._last = (ix, iy)
        self._pre_snap = self.doc.snapshot()
        self._changed = False
        self._mode = None
        tol = self.tolerance()

        if self.tool == "crop":
            self._mode = "crop"
            self._crop_rect = (ix, iy, ix, iy)
            return

        handle = self._handle_at(ix, iy)
        if handle:
            self._mode, self._handle = "resize", handle
            return
        if self.selected is not None and self.selected.hit(ix, iy, tol):
            self._mode = "move"
            return
        if self.tool in ("select", "text"):
            hit = self.doc.shape_at(ix, iy, tol)
            if self.tool == "text" and hit is not None and not isinstance(hit, S.TextShape):
                hit = None
            self.select(hit)
            self._mode = "move" if hit else ("text" if self.tool == "text" else None)
            return

        shape = self._new_shape(ix, iy)
        if shape is not None:
            self.doc.shapes.append(shape)
            self.selected = shape
            self._mode = "create"
            self._changed = True
            if self.tool == "step":
                self._mode = "create-step"
            self.queue_draw()

    def _on_update(self, gesture, dx, dy):
        ok, sx, sy = gesture.get_start_point()
        ix, iy = self.to_image(sx + dx, sy + dy)
        lx, ly = self._last
        constrain = self._shift_held(gesture)
        if self._mode == "crop":
            x0, y0, _, _ = self._crop_rect
            self._crop_rect = (x0, y0, ix, iy)
        elif self._mode == "create":
            self.selected.set_end(ix, iy, constrain)
        elif self._mode in ("move", "create-step"):
            if ix != lx or iy != ly:
                self.selected.move(ix - lx, iy - ly)
                self._changed = True
        elif self._mode == "resize":
            self.selected.drag_handle(self._handle, ix, iy, constrain)
            self._changed = True
        self._last = (ix, iy)
        self.queue_draw()

    def _on_end(self, gesture, dx, dy):
        mode, self._mode = self._mode, None
        moved = math.hypot(dx, dy) > 2
        if mode == "crop":
            x0, y0, x1, y1 = self._crop_rect
            self._crop_rect = None
            if self.doc.set_crop(min(x0, x1), min(y0, y1), abs(x1 - x0), abs(y1 - y0)):
                self._update_size()
                self.emit("changed")
            self.queue_draw()
            return
        if mode == "text" and not moved:
            self._request_text(None, *self._start_img)
            return
        if mode == "move" and self.tool == "text" and not moved and isinstance(self.selected, S.TextShape):
            self._request_text(self.selected, self.selected.x, self.selected.y)
            return
        if mode == "create":
            shape = self.selected
            if shape.is_degenerate():
                self.doc.shapes.remove(shape)
                self.selected = None
                # a simple click on an existing object selects it instead of drawing
                hit = self.doc.shape_at(*self._start_img, self.tolerance())
                self.select(hit)
                self.emit("selection-changed")
                return
            if isinstance(shape, S.BoxShape):
                shape.normalize()
        if mode and self._changed:
            self.doc.push_undo(self._pre_snap)
            self.emit("changed")
        self.emit("selection-changed")
        self.queue_draw()

    def _on_motion(self, ctrl, x, y):
        self._update_cursor(self.to_image(x, y))

    def _update_cursor(self, pos):
        name = "crosshair"
        if self.tool == "select":
            name = "default"
        elif self.tool == "text":
            name = "text"
        if pos is not None and self.tool != "crop":
            ix, iy = pos
            handle = self._handle_at(ix, iy)
            if handle:
                name = self.selected.handle_cursor(handle)
            elif self.selected is not None and self.selected.hit(ix, iy, self.tolerance()):
                name = "move"
            elif self.tool == "select" and self.doc.shape_at(ix, iy, self.tolerance()):
                name = "pointer"
        self.set_cursor(Gdk.Cursor.new_from_name(name, None))

    # drawing ------------------------------------------------------------
    def _draw(self, area, cr, width, height):
        cx, cy, cw, ch = self.doc.crop
        z = self.zoom
        cr.save()
        cr.scale(z, z)
        cr.translate(-cx, -cy)
        cr.rectangle(cx, cy, cw, ch)
        cr.clip()
        cr.set_source_surface(self.doc.base, 0, 0)
        if z < 1:
            cr.get_source().set_filter(cairo.FILTER_GOOD)
        elif z >= 2:
            cr.get_source().set_filter(cairo.FILTER_NEAREST)
        cr.paint()
        for s in self.doc.shapes:
            cr.new_path()
            s.draw(cr, self.doc)
        cr.restore()

        if self.selected is not None and self.selected in self.doc.shapes:
            self._draw_selection(cr, self.selected)
        if self._crop_rect:
            self._draw_crop(cr, width, height)

    def _draw_selection(self, cr, s):
        bx, by, bw, bh = s.bbox()
        pad = s.width / 2 + 3 / self.zoom if not isinstance(s, S.TextShape) else 2 / self.zoom
        x0, y0 = self.to_widget(bx - pad, by - pad)
        x1, y1 = self.to_widget(bx + bw + pad, by + bh + pad)
        cr.save()
        cr.set_line_width(1)
        if not isinstance(s, S.LineShape):
            cr.set_dash([4, 3])
            cr.set_source_rgb(*SELECTION_COLOR)
            cr.rectangle(int(x0) + 0.5, int(y0) + 0.5, int(x1 - x0), int(y1 - y0))
            cr.stroke()
            cr.set_dash([])
        if s.resizable:
            for hx, hy in s.handles().values():
                wx, wy = self.to_widget(hx, hy)
                cr.rectangle(int(wx) - 4.5, int(wy) - 4.5, 9, 9)
                cr.set_source_rgb(1, 1, 1)
                cr.fill_preserve()
                cr.set_source_rgb(*SELECTION_COLOR)
                cr.stroke()
        cr.restore()

    def _draw_crop(self, cr, width, height):
        x0, y0, x1, y1 = self._crop_rect
        ax, ay = self.to_widget(min(x0, x1), min(y0, y1))
        bx, by = self.to_widget(max(x0, x1), max(y0, y1))
        cr.save()
        cr.set_fill_rule(cairo.FILL_RULE_EVEN_ODD)
        cr.rectangle(0, 0, width, height)
        cr.rectangle(ax, ay, bx - ax, by - ay)
        cr.set_source_rgba(0, 0, 0, 0.5)
        cr.fill()
        cr.set_source_rgb(1, 1, 1)
        cr.set_line_width(1)
        cr.set_dash([5, 4])
        cr.rectangle(int(ax) + 0.5, int(ay) + 0.5, int(bx - ax), int(by - ay))
        cr.stroke()
        cr.restore()
