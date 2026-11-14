"""Headless tests for shapes, rendering, crop and undo/redo. Run: python3 -m pytest tests  (or python3 tests/test_document.py)"""
import os
import sys
import tempfile

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

import cairo  # noqa: E402

from snipper import shapes as S  # noqa: E402
from snipper.document import Document, load_image  # noqa: E402


def make_base(w=200, h=120):
    surf = cairo.ImageSurface(cairo.FORMAT_ARGB32, w, h)
    cr = cairo.Context(surf)
    cr.set_source_rgb(1, 1, 1)
    cr.paint()
    # stripes so pixelation has something to average
    for x in range(0, w, 4):
        cr.set_source_rgb(0, 0, 0)
        cr.rectangle(x, 0, 2, h)
        cr.fill()
    return surf


def pixel(surf, x, y):
    surf.flush()
    data = surf.get_data()
    off = y * surf.get_stride() + x * 4
    b, g, r, a = data[off], data[off + 1], data[off + 2], data[off + 3]
    return r, g, b, a


def test_rect_renders_and_hits():
    doc = Document(make_base())
    r = S.RectShape(10, 10, 60, 50, color=(1, 0, 0, 1), width=4)
    doc.shapes.append(r)
    out = doc.render()
    assert pixel(out, 10, 30)[:3] == (255, 0, 0)
    assert r.hit(10, 30, 2)
    assert not r.hit(35, 30, 2)  # inside an outline rect is not a hit
    r.fill = True
    assert r.hit(35, 30, 2)


def test_undo_redo_unlimited():
    doc = Document(make_base())
    for i in range(50):
        doc.checkpoint()
        doc.shapes.append(S.LineShape(0, i, 100, i, arrow=True))
    assert len(doc.shapes) == 50
    for _ in range(50):
        assert doc.undo()
    assert doc.shapes == [] and not doc.undo()
    for _ in range(50):
        assert doc.redo()
    assert len(doc.shapes) == 50
    assert doc.shapes[0].arrow


def test_undo_restores_moved_shape():
    doc = Document(make_base())
    doc.checkpoint()
    s = S.RectShape(10, 10, 20, 20)
    doc.shapes.append(s)
    doc.checkpoint()
    doc.shapes[0].move(5, 5)
    assert doc.shapes[0].x1 == 15
    doc.undo()
    assert doc.shapes[0].x1 == 10


def test_crop_is_non_destructive_and_undoable():
    doc = Document(make_base(200, 120))
    doc.shapes.append(S.RectShape(50, 50, 80, 80, fill=True, color=(0, 0, 1, 1)))
    assert doc.set_crop(40, 40, 100, 60)
    out = doc.render()
    assert (out.get_width(), out.get_height()) == (100, 60)
    assert pixel(out, 15, 15)[:3] == (0, 0, 255)  # shape kept its image position
    assert doc.set_crop(0, 0, 1000, 1000)  # clamps inside current crop
    assert doc.crop == (40, 40, 100, 60)
    doc.undo()
    doc.undo()
    assert doc.crop == (0, 0, 200, 120)


def test_blur_pixelates():
    doc = Document(make_base())
    doc.shapes.append(S.BlurShape(0, 0, 60, 60, width=4))
    out = doc.render()
    # stripes (0/255 alternating every 2px) become a uniform gray inside the block
    vals = {pixel(out, x, 5)[0] for x in range(0, 10)}
    assert len(vals) == 1 and 40 < vals.pop() < 220
    # outside is untouched
    assert pixel(out, 100, 5)[0] in (0, 255)


def test_steps_number_sequentially():
    doc = Document(make_base())
    for _ in range(3):
        doc.shapes.append(S.StepShape(20, 20, number=doc.next_step_number()))
    assert [s.number for s in doc.shapes] == [1, 2, 3]


def test_text_and_all_shapes_render():
    doc = Document(make_base())
    pen = S.PenShape(5, 5)
    for i in range(10):
        pen.add_point(5 + i * 3, 5 + i * 2)
    doc.shapes += [
        S.TextShape(10, 10, "Halo\nDunia", size=20, bold=True),
        S.EllipseShape(5, 5, 50, 40),
        S.HighlightShape(0, 0, 100, 20),
        S.LineShape(0, 0, 100, 100),
        S.LineShape(0, 100, 100, 0, arrow=True),
        pen,
    ]
    _x, _y, w, h = doc.shapes[0].bbox()
    assert w > 20 and h > 30  # two lines of text
    doc.render()


def test_handles_resize_box():
    r = S.RectShape(10, 10, 50, 50)
    r.drag_handle("se", 80, 90)
    assert r.rect() == (10, 10, 70, 80)
    r.drag_handle("nw", 0, 0)
    assert r.rect() == (0, 0, 80, 90)


def test_constrain():
    r = S.RectShape(0, 0)
    r.set_end(30, 10, constrain=True)
    assert r.rect()[2] == r.rect()[3] == 30
    ln = S.LineShape(0, 0)
    ln.set_end(100, 10, constrain=True)
    assert abs(ln.y2) < 1e-9


def test_save_png_and_jpg_roundtrip():
    doc = Document(make_base())
    doc.shapes.append(S.RectShape(10, 10, 60, 50, color=(1, 0, 0, 1)))
    with tempfile.TemporaryDirectory() as d:
        for ext in ("png", "jpg"):
            p = os.path.join(d, f"out.{ext}")
            doc.save(p)
            img = load_image(p)
            assert (img.get_width(), img.get_height()) == (200, 120)
    assert not doc.dirty


if __name__ == "__main__":
    for name, fn in list(globals().items()):
        if name.startswith("test_"):
            fn()
            print("ok", name)
