"""Interactive Cairo canvas: draws the document and turns pointer input into annotation edits."""
from __future__ import annotations

import math

import cairo
from gi.repository import Gdk, GObject, Gtk

from . import render as R
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


class Canvas(Gtk.Widget):
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

        # Rendering cache: the screenshot plus every settled annotation is flattened once into a
        # GPU texture. While a shape is being drawn/moved, only shapes[_split:] are drawn live.
        self._split = None
        self._layer = None  # (cairo surface, texture) of the crop region, image pixels
        self._cursor_name = None

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

    def invalidate(self):
        """Annotations or crop changed: rebuild the flattened layer on the next frame."""
        self._layer = None
        self.queue_draw()

    def document_changed(self):
        """Call after undo/redo or any external change to the document."""
        self.invalidate()
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
        self.invalidate()
        return True

    def nudge_selected(self, dx, dy):
        if self.selected is None:
            return False
        self.doc.checkpoint()
        self.selected.move(dx, dy)
        self.emit("changed")
        self.invalidate()
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
        self.invalidate()

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
        self.invalidate()

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
            self._begin_live(self.doc.shapes.index(self.selected))
            return
        if self.selected is not None and self.selected.hit(ix, iy, tol):
            self._mode = "move"
            self._begin_live(self.doc.shapes.index(self.selected))
            return
        if self.tool in ("select", "text"):
            hit = self.doc.shape_at(ix, iy, tol)
            if self.tool == "text" and hit is not None and not isinstance(hit, S.TextShape):
                hit = None
            self.select(hit)
            self._mode = "move" if hit else ("text" if self.tool == "text" else None)
            if hit is not None:
                self._begin_live(self.doc.shapes.index(hit))
            return

        shape = self._new_shape(ix, iy)
        if shape is not None:
            self.doc.shapes.append(shape)
            self.selected = shape
            self._mode = "create"
            self._changed = True
            if self.tool == "step":
                self._mode = "create-step"
            self._begin_live(len(self.doc.shapes) - 1)

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

    def _begin_live(self, index):
        """From now until the drag ends, shapes[index:] are drawn live on top of the cached layer."""
        if self._split != index:
            self._split = index
            self.invalidate()

    def _end_live(self):
        if self._split is not None:
            self._split = None
            self.invalidate()

    def _on_end(self, gesture, dx, dy):
        mode, self._mode = self._mode, None
        self._end_live()
        moved = math.hypot(dx, dy) > 2
        if mode == "crop":
            x0, y0, x1, y1 = self._crop_rect
            self._crop_rect = None
            if self.doc.set_crop(min(x0, x1), min(y0, y1), abs(x1 - x0), abs(y1 - y0)):
                self.invalidate()
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
        if name != self._cursor_name:
            self._cursor_name = name
            self.set_cursor(Gdk.Cursor.new_from_name(name, None))

    # drawing ------------------------------------------------------------
    def _ensure_layer(self):
        """Flatten base image + settled shapes (crop region, 1:1 image pixels) into a texture."""
        if self._layer is not None:
            return self._layer
        cx, cy, cw, ch = self.doc.crop
        surf = cairo.ImageSurface(cairo.FORMAT_ARGB32, max(1, cw), max(1, ch))
        cr = cairo.Context(surf)
        cr.translate(-cx, -cy)
        cr.set_source_surface(self.doc.base, 0, 0)
        cr.paint()
        settled = self.doc.shapes if self._split is None else self.doc.shapes[: self._split]
        for s in settled:
            cr.new_path()
            s.draw(cr, self.doc)
        self._layer = (surf, R.texture_from_surface(surf))
        return self._layer

    @staticmethod
    def _shape_extent(s):
        bx, by, bw, bh = s.bbox()
        pad = max(12.0, s.width * 4)  # stroke, round caps, arrow heads, step badges
        return bx - pad, by - pad, bx + bw + pad, by + bh + pad

    def do_snapshot(self, snapshot):
        width, height = self.get_width(), self.get_height()
        if width <= 0 or height <= 0:
            return
        cx, cy, cw, ch = self.doc.crop
        z = self.zoom
        layer_surf, texture = self._ensure_layer()
        R.append_texture(snapshot, texture, R.rect(0, 0, cw * z, ch * z), z * R.device_scale(self))

        if self._split is not None and self._split < len(self.doc.shapes):
            self._snapshot_live(snapshot, layer_surf, self.doc.shapes[self._split:])

        if self.selected is not None and self.selected in self.doc.shapes:
            self._draw_selection(snapshot, self.selected)
        if self._crop_rect:
            self._draw_crop(snapshot, width, height)

    def _snapshot_live(self, snapshot, layer_surf, live):
        """Rasterize only the area the moving shape(s) cover, not the whole canvas."""
        cx, cy, cw, ch = self.doc.crop
        x0 = y0 = math.inf
        x1 = y1 = -math.inf
        for s in live:
            a, b, c, d = self._shape_extent(s)
            x0, y0, x1, y1 = min(x0, a), min(y0, b), max(x1, c), max(y1, d)
        x0, y0 = max(x0, cx), max(y0, cy)
        x1, y1 = min(x1, cx + cw), min(y1, cy + ch)
        if x1 <= x0 or y1 <= y0:
            return
        wx0, wy0 = self.to_widget(x0, y0)
        wx1, wy1 = self.to_widget(x1, y1)
        wx0, wy0 = math.floor(wx0), math.floor(wy0)
        wx1, wy1 = math.ceil(wx1), math.ceil(wy1)
        cr = snapshot.append_cairo(R.rect(wx0, wy0, wx1 - wx0, wy1 - wy0))
        z = self.zoom
        cr.scale(z, z)
        cr.translate(-cx, -cy)
        cr.rectangle(cx, cy, cw, ch)
        cr.clip()
        if any(isinstance(s, S.HighlightShape) for s in live):
            # multiply blending needs the real pixels underneath
            cr.set_source_surface(layer_surf, cx, cy)
            if z >= 2:
                cr.get_source().set_filter(cairo.FILTER_NEAREST)
            cr.paint()
        for s in live:
            cr.new_path()
            s.draw(cr, self.doc)

    def _draw_selection(self, snapshot, s):
        bx, by, bw, bh = s.bbox()
        pad = s.width / 2 + 3 / self.zoom if not isinstance(s, S.TextShape) else 2 / self.zoom
        x0, y0 = self.to_widget(bx - pad, by - pad)
        x1, y1 = self.to_widget(bx + bw + pad, by + bh + pad)
        if not isinstance(s, S.LineShape):
            R.dashed_outline(snapshot, SELECTION_COLOR, x0, y0, x1 - x0, y1 - y0)
        if s.resizable:
            for hx, hy in s.handles().values():
                wx, wy = self.to_widget(hx, hy)
                R.fill(snapshot, _SEL_RGBA, int(wx) - 5, int(wy) - 5, 10, 10)
                R.fill(snapshot, _WHITE, int(wx) - 4, int(wy) - 4, 8, 8)

    def _draw_crop(self, snapshot, width, height):
        x0, y0, x1, y1 = self._crop_rect
        ax, ay = self.to_widget(min(x0, x1), min(y0, y1))
        bx, by = self.to_widget(max(x0, x1), max(y0, y1))
        R.dim_outside(snapshot, _CROP_DIM, width, height, (ax, ay, bx - ax, by - ay))
        R.dashed_outline(snapshot, (1, 1, 1), ax, ay, bx - ax, by - ay, dash=(5, 4))


_SEL_RGBA = R.rgba(*SELECTION_COLOR)
_WHITE = R.rgba(1, 1, 1, 1)
_CROP_DIM = R.rgba(0, 0, 0, 0.5)
