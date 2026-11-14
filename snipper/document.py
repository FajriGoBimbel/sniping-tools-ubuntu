"""The editable screenshot: base image + annotation objects + crop, with unlimited undo/redo."""
from __future__ import annotations

import copy
import io

import cairo

from .shapes import StepShape


def surface_from_png_bytes(data: bytes) -> cairo.ImageSurface:
    return cairo.ImageSurface.create_from_png(io.BytesIO(data))


def load_image(path: str) -> cairo.ImageSurface:
    """Load any image GdkPixbuf understands into a Cairo surface."""
    if path.lower().endswith(".png"):
        try:
            return cairo.ImageSurface.create_from_png(path)
        except Exception:
            pass
    import gi

    gi.require_version("GdkPixbuf", "2.0")
    from gi.repository import GdkPixbuf

    pixbuf = GdkPixbuf.Pixbuf.new_from_file(path)
    ok, data = pixbuf.save_to_bufferv("png", [], [])
    return surface_from_png_bytes(data)


def crop_surface(src: cairo.ImageSurface, x: int, y: int, w: int, h: int) -> cairo.ImageSurface:
    out = cairo.ImageSurface(cairo.FORMAT_ARGB32, max(1, w), max(1, h))
    cr = cairo.Context(out)
    cr.set_source_surface(src, -x, -y)
    cr.paint()
    return out


class Document:
    def __init__(self, base: cairo.ImageSurface):
        self.base = base
        self.shapes = []
        self.crop = (0, 0, base.get_width(), base.get_height())
        self._undo = []
        self._redo = []
        self.dirty = False  # changed since last save/copy

    # history ------------------------------------------------------------
    def snapshot(self):
        return (copy.deepcopy(self.shapes), self.crop)

    def push_undo(self, snap):
        """Record `snap` (state *before* a change) as an undo step."""
        self._undo.append(snap)
        self._redo.clear()
        self.dirty = True

    def checkpoint(self):
        self.push_undo(self.snapshot())

    def _restore(self, snap):
        shapes, self.crop = snap
        self.shapes = copy.deepcopy(shapes)
        self.dirty = True

    def can_undo(self):
        return bool(self._undo)

    def can_redo(self):
        return bool(self._redo)

    def undo(self):
        if not self._undo:
            return False
        self._redo.append(self.snapshot())
        self._restore(self._undo.pop())
        return True

    def redo(self):
        if not self._redo:
            return False
        self._undo.append(self.snapshot())
        self._restore(self._redo.pop())
        return True

    # helpers ------------------------------------------------------------
    @property
    def width(self):
        return self.crop[2]

    @property
    def height(self):
        return self.crop[3]

    def next_step_number(self):
        nums = [s.number for s in self.shapes if isinstance(s, StepShape)]
        return max(nums, default=0) + 1

    def shape_at(self, x, y, tol):
        for s in reversed(self.shapes):
            if s.hit(x, y, tol):
                return s
        return None

    def set_crop(self, x, y, w, h):
        """Crop to a rectangle (image coords), clamped inside the current crop."""
        cx, cy, cw, ch = self.crop
        x0, y0 = max(cx, int(round(x))), max(cy, int(round(y)))
        x1, y1 = min(cx + cw, int(round(x + w))), min(cy + ch, int(round(y + h)))
        if x1 - x0 < 2 or y1 - y0 < 2:
            return False
        self.checkpoint()
        self.crop = (x0, y0, x1 - x0, y1 - y0)
        return True

    # output -------------------------------------------------------------
    def draw_content(self, cr):
        cr.set_source_surface(self.base, 0, 0)
        cr.paint()
        for s in self.shapes:
            cr.new_path()
            s.draw(cr, self)

    def render(self, opaque=False) -> cairo.ImageSurface:
        cx, cy, cw, ch = self.crop
        fmt = cairo.FORMAT_RGB24 if opaque else cairo.FORMAT_ARGB32
        out = cairo.ImageSurface(fmt, cw, ch)
        cr = cairo.Context(out)
        if opaque:
            cr.set_source_rgb(1, 1, 1)
            cr.paint()
        cr.translate(-cx, -cy)
        self.draw_content(cr)
        out.flush()
        return out

    def to_png_bytes(self, opaque=False) -> bytes:
        buf = io.BytesIO()
        self.render(opaque).write_to_png(buf)
        return buf.getvalue()

    def save(self, path: str, quality: int = 92):
        lower = path.lower()
        if lower.endswith((".jpg", ".jpeg")):
            import gi

            gi.require_version("GdkPixbuf", "2.0")
            from gi.repository import GdkPixbuf

            loader = GdkPixbuf.PixbufLoader.new_with_type("png")
            loader.write(self.to_png_bytes(opaque=True))
            loader.close()
            loader.get_pixbuf().savev(path, "jpeg", ["quality"], [str(quality)])
        else:
            self.render().write_to_png(path)
        self.dirty = False
