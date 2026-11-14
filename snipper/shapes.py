"""Annotation objects. Every shape lives in image (pixel) coordinates and draws itself with Cairo.

Shapes are plain Python objects so the document can deep-copy them for unlimited undo/redo.
"""
from __future__ import annotations

import copy
import math

import cairo
import gi

gi.require_version("Pango", "1.0")
gi.require_version("PangoCairo", "1.0")
from gi.repository import Pango, PangoCairo  # noqa: E402

BOX_HANDLES = ("nw", "n", "ne", "e", "se", "s", "sw", "w")

_measure_surface = cairo.ImageSurface(cairo.FORMAT_ARGB32, 1, 1)


def _dist_to_segment(px, py, x1, y1, x2, y2):
    dx, dy = x2 - x1, y2 - y1
    if dx == 0 and dy == 0:
        return math.hypot(px - x1, py - y1)
    t = max(0.0, min(1.0, ((px - x1) * dx + (py - y1) * dy) / (dx * dx + dy * dy)))
    return math.hypot(px - (x1 + t * dx), py - (y1 + t * dy))


def constrain_angle(x1, y1, x2, y2):
    """Snap the vector (x1,y1)->(x2,y2) to multiples of 45 degrees."""
    dx, dy = x2 - x1, y2 - y1
    length = math.hypot(dx, dy)
    angle = round(math.atan2(dy, dx) / (math.pi / 4)) * (math.pi / 4)
    return x1 + length * math.cos(angle), y1 + length * math.sin(angle)


class Shape:
    kind = "shape"
    resizable = True

    def __init__(self, color=(0.88, 0.11, 0.14, 1.0), width=4.0):
        self.color = tuple(color)
        self.width = float(width)

    def __deepcopy__(self, memo):
        new = self.__class__.__new__(self.__class__)
        for k, v in self.__dict__.items():
            if not k.startswith("_"):  # skip caches
                new.__dict__[k] = copy.deepcopy(v, memo)
        return new

    def copy(self):
        return copy.deepcopy(self)

    # geometry -----------------------------------------------------------
    def bbox(self):
        raise NotImplementedError

    def hit(self, x, y, tol):
        bx, by, bw, bh = self.bbox()
        return bx - tol <= x <= bx + bw + tol and by - tol <= y <= by + bh + tol

    def move(self, dx, dy):
        raise NotImplementedError

    def handles(self):
        return {}

    def drag_handle(self, name, x, y, constrain=False):
        pass

    def set_end(self, x, y, constrain=False):
        pass

    def is_degenerate(self):
        _, _, w, h = self.bbox()
        return w < 3 and h < 3

    def handle_cursor(self, name):
        return {
            "nw": "nwse-resize", "se": "nwse-resize", "ne": "nesw-resize", "sw": "nesw-resize",
            "n": "ns-resize", "s": "ns-resize", "e": "ew-resize", "w": "ew-resize",
        }.get(name, "move")

    def draw(self, cr, doc):
        raise NotImplementedError


class BoxShape(Shape):
    """Anything defined by a rectangle: rectangle, ellipse, highlighter, blur."""

    def __init__(self, x1, y1, x2=None, y2=None, **kw):
        super().__init__(**kw)
        self.x1, self.y1 = float(x1), float(y1)
        self.x2 = float(x1 if x2 is None else x2)
        self.y2 = float(y1 if y2 is None else y2)

    def rect(self):
        x, y = min(self.x1, self.x2), min(self.y1, self.y2)
        return x, y, abs(self.x2 - self.x1), abs(self.y2 - self.y1)

    def bbox(self):
        return self.rect()

    def normalize(self):
        x, y, w, h = self.rect()
        self.x1, self.y1, self.x2, self.y2 = x, y, x + w, y + h

    def move(self, dx, dy):
        self.x1 += dx
        self.x2 += dx
        self.y1 += dy
        self.y2 += dy

    def set_end(self, x, y, constrain=False):
        if constrain:  # square / circle
            side = max(abs(x - self.x1), abs(y - self.y1))
            x = self.x1 + math.copysign(side, x - self.x1 or 1)
            y = self.y1 + math.copysign(side, y - self.y1 or 1)
        self.x2, self.y2 = x, y

    def handles(self):
        x, y, w, h = self.rect()
        cx, cy = x + w / 2, y + h / 2
        return {
            "nw": (x, y), "n": (cx, y), "ne": (x + w, y), "e": (x + w, cy),
            "se": (x + w, y + h), "s": (cx, y + h), "sw": (x, y + h), "w": (x, cy),
        }

    def drag_handle(self, name, x, y, constrain=False):
        self.normalize()
        if "w" in name:
            self.x1 = x
        if "e" in name:
            self.x2 = x
        if "n" in name:
            self.y1 = y
        if "s" in name:
            self.y2 = y


class RectShape(BoxShape):
    kind = "rect"

    def __init__(self, *a, fill=False, **kw):
        super().__init__(*a, **kw)
        self.fill = fill

    def hit(self, x, y, tol):
        bx, by, bw, bh = self.rect()
        inside_outer = bx - tol <= x <= bx + bw + tol and by - tol <= y <= by + bh + tol
        if self.fill or not inside_outer:
            return inside_outer
        t = tol + self.width / 2
        inner = bx + t < x < bx + bw - t and by + t < y < by + bh - t
        return not inner

    def draw(self, cr, doc):
        x, y, w, h = self.rect()
        cr.save()
        cr.set_source_rgba(*self.color)
        cr.rectangle(x, y, w, h)
        if self.fill:
            cr.fill()
        else:
            cr.set_line_width(self.width)
            cr.set_line_join(cairo.LINE_JOIN_MITER)
            cr.stroke()
        cr.restore()


class EllipseShape(BoxShape):
    kind = "ellipse"

    def __init__(self, *a, fill=False, **kw):
        super().__init__(*a, **kw)
        self.fill = fill

    def hit(self, x, y, tol):
        bx, by, bw, bh = self.rect()
        rx, ry = max(bw / 2, 0.5), max(bh / 2, 0.5)
        cx, cy = bx + rx, by + ry
        d = math.hypot((x - cx) / rx, (y - cy) / ry)
        if self.fill:
            return d <= 1 + tol / min(rx, ry)
        return abs(d - 1) * min(rx, ry) <= tol + self.width / 2

    def _path(self, cr):
        x, y, w, h = self.rect()
        if w < 1 or h < 1:
            return False
        cr.new_path()
        cr.save()
        cr.translate(x + w / 2, y + h / 2)
        cr.scale(w / 2, h / 2)
        cr.arc(0, 0, 1, 0, 2 * math.pi)
        cr.restore()
        return True

    def draw(self, cr, doc):
        cr.save()
        if self._path(cr):
            cr.set_source_rgba(*self.color)
            if self.fill:
                cr.fill()
            else:
                cr.set_line_width(self.width)
                cr.stroke()
        cr.restore()


class HighlightShape(BoxShape):
    kind = "highlight"

    def __init__(self, *a, **kw):
        kw.setdefault("color", (0.96, 0.83, 0.18, 1.0))
        super().__init__(*a, **kw)

    def draw(self, cr, doc):
        x, y, w, h = self.rect()
        cr.save()
        cr.set_operator(cairo.OPERATOR_MULTIPLY)
        r, g, b, _ = self.color
        cr.set_source_rgba(r, g, b, 0.55)
        cr.rectangle(x, y, w, h)
        cr.fill()
        cr.restore()


class BlurShape(BoxShape):
    """Pixelates the underlying screenshot so sensitive data is unreadable."""

    kind = "blur"

    def block_size(self):
        return max(6, int(self.width * 3))

    def draw(self, cr, doc):
        x, y, w, h = (int(round(v)) for v in self.rect())
        if w < 1 or h < 1 or doc is None:
            return
        b = self.block_size()
        sw, sh = max(1, math.ceil(w / b)), max(1, math.ceil(h / b))
        key = (x, y, w, h, b)
        cached = getattr(self, "_cache", None)
        if cached and cached[0] == key:
            small = cached[1]
        else:
            small = cairo.ImageSurface(cairo.FORMAT_RGB24, sw, sh)
            c = cairo.Context(small)
            c.scale(sw / w, sh / h)
            c.set_source_surface(doc.base, -x, -y)
            c.get_source().set_filter(cairo.FILTER_GOOD)
            c.paint()
            self._cache = (key, small)
        cr.save()
        cr.rectangle(x, y, w, h)
        cr.clip()
        cr.translate(x, y)
        cr.scale(w / sw, h / sh)
        cr.set_source_surface(small, 0, 0)
        cr.get_source().set_filter(cairo.FILTER_NEAREST)
        cr.paint()
        cr.restore()


class LineShape(Shape):
    kind = "line"

    def __init__(self, x1, y1, x2=None, y2=None, arrow=False, **kw):
        super().__init__(**kw)
        self.x1, self.y1 = float(x1), float(y1)
        self.x2 = float(x1 if x2 is None else x2)
        self.y2 = float(y1 if y2 is None else y2)
        self.arrow = arrow
        if arrow:
            self.kind = "arrow"

    def bbox(self):
        x, y = min(self.x1, self.x2), min(self.y1, self.y2)
        return x, y, abs(self.x2 - self.x1), abs(self.y2 - self.y1)

    def is_degenerate(self):
        return math.hypot(self.x2 - self.x1, self.y2 - self.y1) < 4

    def hit(self, x, y, tol):
        return _dist_to_segment(x, y, self.x1, self.y1, self.x2, self.y2) <= tol + self.width / 2

    def move(self, dx, dy):
        self.x1 += dx
        self.x2 += dx
        self.y1 += dy
        self.y2 += dy

    def set_end(self, x, y, constrain=False):
        if constrain:
            x, y = constrain_angle(self.x1, self.y1, x, y)
        self.x2, self.y2 = x, y

    def handles(self):
        return {"p1": (self.x1, self.y1), "p2": (self.x2, self.y2)}

    def handle_cursor(self, name):
        return "move"

    def drag_handle(self, name, x, y, constrain=False):
        if name == "p1":
            if constrain:
                x, y = constrain_angle(self.x2, self.y2, x, y)
            self.x1, self.y1 = x, y
        else:
            self.set_end(x, y, constrain)

    def head_length(self):
        return max(12.0, self.width * 4.0)

    def draw(self, cr, doc):
        x1, y1, x2, y2 = self.x1, self.y1, self.x2, self.y2
        length = math.hypot(x2 - x1, y2 - y1)
        cr.save()
        cr.set_source_rgba(*self.color)
        cr.set_line_width(self.width)
        cr.set_line_cap(cairo.LINE_CAP_ROUND)
        if self.arrow and length > 0:
            head = min(self.head_length(), length)
            angle = math.atan2(y2 - y1, x2 - x1)
            spread = math.radians(26)
            # stop the shaft inside the head so the round cap doesn't poke out of the tip
            sx = x2 - math.cos(angle) * head * 0.8
            sy = y2 - math.sin(angle) * head * 0.8
            cr.move_to(x1, y1)
            cr.line_to(sx, sy)
            cr.stroke()
            cr.move_to(x2, y2)
            cr.line_to(x2 - head * math.cos(angle - spread), y2 - head * math.sin(angle - spread))
            cr.line_to(x2 - head * math.cos(angle + spread), y2 - head * math.sin(angle + spread))
            cr.close_path()
            cr.fill()
        else:
            cr.move_to(x1, y1)
            cr.line_to(x2, y2)
            cr.stroke()
        cr.restore()


class PenShape(Shape):
    kind = "pen"
    resizable = False

    def __init__(self, x, y, **kw):
        super().__init__(**kw)
        self.points = [(float(x), float(y))]

    def add_point(self, x, y):
        lx, ly = self.points[-1]
        if math.hypot(x - lx, y - ly) >= 1.0:
            self.points.append((float(x), float(y)))

    def set_end(self, x, y, constrain=False):
        self.add_point(x, y)

    def bbox(self):
        xs = [p[0] for p in self.points]
        ys = [p[1] for p in self.points]
        return min(xs), min(ys), max(xs) - min(xs), max(ys) - min(ys)

    def is_degenerate(self):
        return len(self.points) < 2

    def hit(self, x, y, tol):
        t = tol + self.width / 2
        pts = self.points
        if len(pts) == 1:
            return math.hypot(x - pts[0][0], y - pts[0][1]) <= t
        return any(_dist_to_segment(x, y, *pts[i], *pts[i + 1]) <= t for i in range(len(pts) - 1))

    def move(self, dx, dy):
        self.points = [(px + dx, py + dy) for px, py in self.points]

    def draw(self, cr, doc):
        if len(self.points) < 2:
            return
        cr.save()
        cr.set_source_rgba(*self.color)
        cr.set_line_width(self.width)
        cr.set_line_cap(cairo.LINE_CAP_ROUND)
        cr.set_line_join(cairo.LINE_JOIN_ROUND)
        cr.move_to(*self.points[0])
        for p in self.points[1:]:
            cr.line_to(*p)
        cr.stroke()
        cr.restore()


class TextShape(Shape):
    kind = "text"
    resizable = False

    def __init__(self, x, y, text="", size=24, bold=False, **kw):
        super().__init__(**kw)
        self.x, self.y = float(x), float(y)
        self.text = text
        self.size = float(size)
        self.bold = bold

    def _layout(self, cr):
        layout = PangoCairo.create_layout(cr)
        desc = Pango.FontDescription.from_string("Sans")
        desc.set_absolute_size(self.size * Pango.SCALE)
        desc.set_weight(Pango.Weight.BOLD if self.bold else Pango.Weight.NORMAL)
        layout.set_font_description(desc)
        layout.set_text(self.text or " ", -1)
        return layout

    def bbox(self):
        layout = self._layout(cairo.Context(_measure_surface))
        _ink, logical = layout.get_pixel_extents()
        return self.x, self.y, max(logical.width, 4), max(logical.height, 4)

    def is_degenerate(self):
        return not self.text.strip()

    def move(self, dx, dy):
        self.x += dx
        self.y += dy

    def draw(self, cr, doc):
        if not self.text:
            return
        cr.save()
        cr.new_path()
        layout = self._layout(cr)
        # thin contrasting halo keeps text readable on any background
        r, g, b, a = self.color
        lum = 0.299 * r + 0.587 * g + 0.114 * b
        cr.move_to(self.x, self.y)
        PangoCairo.layout_path(cr, layout)
        cr.set_source_rgba(*((0, 0, 0, 0.55 * a) if lum > 0.6 else (1, 1, 1, 0.75 * a)))
        cr.set_line_width(max(2.0, self.size / 10))
        cr.set_line_join(cairo.LINE_JOIN_ROUND)
        cr.stroke()
        cr.move_to(self.x, self.y)
        cr.set_source_rgba(*self.color)
        PangoCairo.show_layout(cr, layout)
        cr.restore()


class StepShape(Shape):
    """Numbered marker (1, 2, 3...) for step-by-step guides."""

    kind = "step"
    resizable = False

    def __init__(self, x, y, number=1, **kw):
        super().__init__(**kw)
        self.x, self.y = float(x), float(y)
        self.number = int(number)

    def radius(self):
        return 10 + self.width * 2.5

    def bbox(self):
        r = self.radius()
        return self.x - r, self.y - r, 2 * r, 2 * r

    def is_degenerate(self):
        return False

    def hit(self, x, y, tol):
        return math.hypot(x - self.x, y - self.y) <= self.radius() + tol

    def move(self, dx, dy):
        self.x += dx
        self.y += dy

    def set_end(self, x, y, constrain=False):
        self.x, self.y = x, y

    def draw(self, cr, doc):
        r = self.radius()
        cr.save()
        cr.new_path()
        cr.arc(self.x, self.y, r, 0, 2 * math.pi)
        cr.set_source_rgba(*self.color)
        cr.fill_preserve()
        cr.set_source_rgba(1, 1, 1, 0.9)
        cr.set_line_width(max(1.5, r / 9))
        cr.stroke()
        layout = PangoCairo.create_layout(cr)
        desc = Pango.FontDescription.from_string("Sans Bold")
        desc.set_absolute_size(r * 1.1 * Pango.SCALE)
        layout.set_font_description(desc)
        layout.set_text(str(self.number), -1)
        _ink, logical = layout.get_pixel_extents()
        cr.move_to(self.x - logical.width / 2, self.y - logical.height / 2)
        rr, gg, bb, _ = self.color
        dark_text = 0.299 * rr + 0.587 * gg + 0.114 * bb > 0.6
        cr.set_source_rgb(*((0, 0, 0) if dark_text else (1, 1, 1)))
        PangoCairo.show_layout(cr, layout)
        cr.restore()
