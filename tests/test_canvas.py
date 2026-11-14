"""Drives the canvas interaction logic with fake gestures (needs a display: Wayland/X11)."""
import os
import sys

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

import gi  # noqa: E402

gi.require_version("Gdk", "4.0")

gi.require_version("Gtk", "4.0")
import cairo  # noqa: E402
from gi.repository import Gdk, Gtk  # noqa: E402

from snipper import shapes as S  # noqa: E402
from snipper.canvas import Canvas, Style  # noqa: E402
from snipper.document import Document  # noqa: E402


class FakeGesture:
    def __init__(self, x, y, shift=False):
        self.x, self.y, self.shift = x, y, shift

    def get_start_point(self):
        return True, self.x, self.y

    def get_current_event_state(self):
        return Gdk.ModifierType.SHIFT_MASK if self.shift else Gdk.ModifierType(0)


def drag(canvas, x0, y0, x1, y1, shift=False):
    g = FakeGesture(x0, y0, shift)
    canvas._on_begin(g, x0, y0)
    canvas._on_update(g, (x1 - x0) / 2, (y1 - y0) / 2)
    canvas._on_update(g, x1 - x0, y1 - y0)
    canvas._on_end(g, x1 - x0, y1 - y0)


def make():
    Gtk.init()
    doc = Document(cairo.ImageSurface(cairo.FORMAT_ARGB32, 400, 300))
    c = Canvas(doc, Style((1, 0, 0, 1), 4, False, 24, True))
    return doc, c


def test_flow():
    doc, c = make()
    c.set_tool("rect")
    drag(c, 10, 10, 110, 60)
    assert len(doc.shapes) == 1 and doc.shapes[0].rect() == (10, 10, 100, 50)
    assert c.selected is doc.shapes[0]
    # drag the selected rect by its border -> move
    drag(c, 30, 10, 50, 30)
    assert doc.shapes[0].rect() == (30, 30, 100, 50)
    # resize via SE handle
    drag(c, 130, 80, 200, 100)
    assert doc.shapes[0].rect() == (30, 30, 170, 70)
    # a click (no drag) does not create a shape
    drag(c, 300, 250, 300, 250)
    assert len(doc.shapes) == 1
    # arrow
    c.set_tool("arrow")
    drag(c, 250, 250, 350, 200)
    assert isinstance(doc.shapes[1], S.LineShape) and doc.shapes[1].arrow
    # steps auto-number
    c.set_tool("step")
    drag(c, 20, 250, 20, 250)
    drag(c, 60, 250, 60, 250)
    assert [s.number for s in doc.shapes if isinstance(s, S.StepShape)] == [1, 2]
    # style change applies to selection with undo
    c.style.color = (0, 0, 1, 1)
    c.apply_style_to_selection("color")
    assert doc.shapes[-1].color == (0, 0, 1, 1)
    # delete + undo everything back to empty
    c.delete_selected()
    assert len(doc.shapes) == 3
    n = 0
    while doc.undo():
        n += 1
    assert doc.shapes == [] and n >= 7
    # crop
    c.set_tool("crop")
    drag(c, 50, 50, 250, 150)
    assert doc.crop == (50, 50, 200, 100)
    # text: click creates pending text, commit adds it
    c.set_tool("text")
    got = []
    c.connect("request-text", lambda _c, shape, x, y: got.append(shape))
    drag(c, 20, 20, 20, 20)
    assert got == [None]
    c.commit_text(None, "Halo")
    t = doc.shapes[-1]
    assert isinstance(t, S.TextShape) and (t.x, t.y) == (70, 70)  # widget->image accounts for crop
    # zoom maps coordinates
    c.set_zoom(2.0)
    assert c.to_image(20, 20) == (60, 60)


if __name__ == "__main__":
    test_flow()
    print("ok test_flow")
